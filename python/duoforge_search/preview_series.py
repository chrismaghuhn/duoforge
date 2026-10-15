"""A predeclared series of the preview oracle (issue #458), run as one program: the mixed team preview's double oracle
and its final measurement, exactly as docs/benchmarks/2026-10-14-preview-mixed/README.md (commit f6b924a4) fixes them.

    python -m duoforge_search.preview_series --plan preview-mixed-2026-10-14 --checkpoint MAIN --foe-net FOE
        --ours OURS --foe FOE_TEAM --out DIR [--workers 8] [--max-steps 1000] [--parallel 3] [--cpus-per-process 16]
        [--deadline-seconds S] [--resume]

Each block of the series is one or more runs of `python -m duoforge_search.preview_oracle` (its own process, its own
log under DIR/logs/). Up to --parallel processes run side by side, process i pinned with taskset to CPUs
i * --cpus-per-process and up (the AWS box: 3 processes of 16 CPUs, 8 workers each; locally --parallel 1 and no pin).
The arms a block still lacks are split over the processes, each into a part directory of its own, and merged into the
run's directory afterwards (the parts' conditions must be the run's, the worker count included); the run's summary is
then made from the merged arms. Without --resume, DIR must not exist.

--resume continues a series in DIR (HauptSession, 2026-10-15: after a spot interruption, from the state the box keeps in
the private bucket) without drawing anything anew: the seeds are the plan's, and every arm file already in a run's
directory stays and is not played again (part directories of an interrupted block are dropped and their arms played
again, on the same seeds). The series is then run from its start; its decisions follow from the same arm files, so a
resumed series ends exactly as an uninterrupted one. DIR/round.txt names the last round finished (written after each
round and at the end): the box saves the state when it changes.

The first block is the check "alone against beside" (HauptSession, 2026-10-15): the cell (today, drawn) is played
alone, then again beside two other cells of the first row; every field of the two arm files but the timing ones must be
equal, or the series stops (exit 3, equality.json names the fields). The alone run's arm is the cell.

Then the plan (PLANS) runs: the start matrix, up to four double-oracle rounds (the foe's best answer to our mix and our
best answer to the foe's mix, by screens; new cells at the plan's cell pairs on its cell seed; the gap of the previous
mixes on the filled matrix), the stop rule (gap below 3 points, nothing new, or the last round), and the final
measurement (a screen of the final mix, the confirmation of drawn and its 5 best answers, the controls today and
23|04) with the predeclared comparisons, paired, and the book reading. DIR/series.json records every block, its
seconds and each round's seconds, the mixes, gaps and the stop reason, and the final numbers; DIR/matrix/ holds the
matrix files. --deadline-seconds stops the series before a batch of processes that could end after it, judged by the
longest batch so far (refused: deadline), so that a box's watchdog never cuts it off unrecorded. Exit 0 when the series is done, 3 when the check failed, 4 when a
run failed, the series or one of the oracle's own checks refused, or anything else went wrong (series.json names the
reason; an error of another kind is named by its type only, since its text could name a member of a team).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from fractions import Fraction

from . import preview_oracle as oracle

TODAY, DRAWN = oracle.TODAY, oracle.DRAWN
TIMING = ("seconds", "wall_seconds")  # the arm file's fields that may differ between equal runs

PLANS = {
    # docs/benchmarks/2026-10-14-preview-mixed/README.md at f6b924a4 (#504)
    "preview-mixed-2026-10-14": {
        "cell_seed": 0x2026101300000464, "cell_pairs": 64,
        "screen_seed": 0x2026101300000465, "screen_pairs": 32,  # round r: foe +2(r-1), ours +2(r-1)+1
        "rounds": 4, "gap_stop": Fraction(3, 100),
        "start_rows": [TODAY, "23|04"], "start_columns": [DRAWN, "15|23", "12|35"],
        "final_screen_seed": 0x202610130000046D, "final_seed": 0x202610130000046E, "final_pairs": 256,
        "answers": 5,
        "workers": 8, "max_steps": 1000, "ours": "A",  # 8 workers per process; Team A (registry id); 1000 steps
        "controls": [(TODAY, [DRAWN, "15|23"]), ("23|04", [DRAWN, "12|35"])],
        "thresholds": {"worst": -5.0, "gain": 0.0, "exploitable": 5.0, "little": 3.0},
    },
}
EQUALITY_EXIT, FAILED_EXIT = 3, 4


class SeriesError(RuntimeError):
    """A refusal of the series, named (reason) for series.json."""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def slug(arm):
    return arm.replace("|", "-")


def arm_file(run_dir, arm):
    return os.path.join(run_dir, "arms", slug(arm) + ".json")


def done_arms(run_dir):
    arm_dir = os.path.join(run_dir, "arms")
    if not os.path.isdir(arm_dir):
        return set()
    return {oracle.ladder._load_json(os.path.join(arm_dir, n))["arm"] for n in os.listdir(arm_dir) if n.endswith(".json")}


def split(arms, parts):
    """The arms in at most `parts` groups, round robin, each group in the given order."""
    groups = [arms[i::parts] for i in range(min(parts, len(arms)))]
    return [g for g in groups if g]


def _start(cmd, log_path, env):
    """Start one process (its output to log_path); returns the Popen. Tests replace this."""
    log = open(log_path, "w", encoding="utf-8")
    try:
        return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
    finally:
        log.close()


class Series:
    def __init__(self, args, plan):
        self.args, self.plan = args, plan
        self.out = args.out
        self.record = {"plan": args.plan, "workers": args.workers, "parallel": args.parallel,
                       "cpus_per_process": args.cpus_per_process, "status": "running", "blocks": [], "rounds": []}
        self.counter = 0
        self.started = time.monotonic()
        if args.resume:  # the earlier launches' record stays, and their logs keep their numbers
            old = oracle.ladder._load_json(os.path.join(self.out, "series.json"))
            self.record["launches"] = old.get("launches", []) + [{k: old.get(k) for k in (
                "status", "reason", "message", "blocks", "rounds", "equality")}]
            self.counter = len(os.listdir(os.path.join(self.out, "logs")))
        self.longest = 0.0  # the longest batch so far: a batch starts only if one as long would end before the deadline

    # ----------------------------------------------------------------------------------------------- the runs
    def base(self):
        a = self.args
        return ["--checkpoint", a.checkpoint, "--foe-net", a.foe_net, "--ours", a.ours, "--foe", a.foe,
                "--workers", str(a.workers), "--max-steps", str(a.max_steps)]

    def command(self, out, args, slot):
        cmd = [sys.executable, "-u", "-m", "duoforge_search.preview_oracle", *self.base(), "--out", out, *args]
        cpp = self.args.cpus_per_process
        if cpp:
            cmd = ["taskset", "-c", f"{slot * cpp}-{(slot + 1) * cpp - 1}", *cmd]
        return cmd

    def run_jobs(self, name, jobs):
        """jobs: [(out, args)], at most --parallel at once, each on a slot of its own; a failing one stops the series."""
        if len(jobs) > self.args.parallel:
            raise SeriesError("internal", f"block {name}: {len(jobs)} jobs for {self.args.parallel} processes")
        deadline = self.args.deadline_seconds
        if deadline and time.monotonic() - self.started + self.longest > deadline:
            raise SeriesError("deadline", f"block {name} could end after the deadline ({deadline} s; the longest batch so far "
                                          f"took {self.longest:.0f} s)")
        started = time.perf_counter()
        procs = []
        for slot, (out, args) in enumerate(jobs):
            self.counter += 1
            log = os.path.join(self.out, "logs", f"{self.counter:04d}-{name}-{slot}.log")
            procs.append((out, _start(self.command(out, args, slot), log, os.environ.copy())))
        codes = [p.wait() for _, p in procs]
        seconds = time.perf_counter() - started
        self.longest = max(self.longest, seconds)
        self.record["blocks"].append({"block": name, "processes": len(jobs), "seconds": seconds,
                                      "exit": codes})
        self.save()
        failed = [out for (out, _), c in zip(procs, codes) if c != 0]
        if failed:
            raise SeriesError("oracle_failed", f"block {name}: {len(failed)} run(s) failed: {failed}")
        return seconds

    def check_conditions(self, run_dir, conditions):
        """That a part's or run's conditions are this series': the plan's workers, a clean checkout, the plan's team."""
        if conditions.get("workers") != self.args.workers:
            raise SeriesError("workers", f"{run_dir}: workers {conditions.get('workers')}, not {self.args.workers}")
        if conditions.get("dirty") is not False:
            raise SeriesError("dirty", f"{run_dir}: dirty {conditions.get('dirty')}")
        if (conditions.get("registry") or {}).get("ours") != self.plan["ours"]:
            raise SeriesError("ours", f"{run_dir}: our team is not the plan's registry team {self.plan['ours']}")

    def merge(self, run_dir, part):
        """The part's arms into the run's directory; its conditions must be the run's (worker count included)."""
        new = oracle.ladder._load_json(os.path.join(part, "conditions.json"))
        self.check_conditions(part, new)
        path = os.path.join(run_dir, "conditions.json")
        os.makedirs(os.path.join(run_dir, "arms"), exist_ok=True)
        if os.path.exists(path):
            old = oracle.ladder._load_json(path)
            changed = oracle.resume_changes(old, new) + [k for k in ("workers", "commit", "dirty") if old.get(k) != new.get(k)]
            if changed:
                raise SeriesError("parts_differ", f"{part}: conditions differ from {run_dir} in {changed}")
        else:
            shutil.copyfile(os.path.join(part, "conditions.json"), path)
        for name in sorted(os.listdir(os.path.join(part, "arms"))):
            if not name.endswith(".json"):
                continue
            target = os.path.join(run_dir, "arms", name)
            if os.path.exists(target):
                raise SeriesError("parts_differ", f"{part}: arm file {name} is in {run_dir} already")
            shutil.copyfile(os.path.join(part, "arms", name), target)
        shutil.rmtree(part)

    def play(self, name, runs):
        """runs: [(run_dir, args, arms)]: every arm a run lacks, split over the processes, then merged; each run's
        summary from its merged arms. Returns the block's seconds."""
        jobs, parts = [], []  # a process plays one run's arms: each run's lacking arms in up to --parallel groups
        for run_dir, args, arms in runs:
            missing = [a for a in arms if a not in done_arms(run_dir)]
            for group in split(missing, self.args.parallel):
                self.counter += 1
                part = os.path.join(run_dir + ".parts", f"{self.counter:04d}")
                jobs.append((part, [*args, "--arms", ",".join(group)]))
                parts.append((run_dir, part))
        if not jobs:  # nothing to play (a resumed series): the summaries are made again from the arms
            for run_dir, _, _ in runs:
                oracle.summarize(run_dir)
            return 0.0
        seconds = 0.0
        for i in range(0, len(jobs), self.args.parallel):  # at most --parallel processes at once
            seconds += self.run_jobs(name, jobs[i:i + self.args.parallel])
        for run_dir, part in parts:
            self.merge(run_dir, part)
        for run_dir, _, _ in runs:
            if os.path.isdir(run_dir + ".parts") and not os.listdir(run_dir + ".parts"):
                os.rmdir(run_dir + ".parts")
            oracle.summarize(run_dir)
            self.check_conditions(run_dir, oracle.ladder._load_json(os.path.join(run_dir, "conditions.json")))
        return seconds

    # ----------------------------------------------------------------------------------------------- the plan
    def run_dir(self, name):
        return os.path.join(self.out, "runs", name)

    def row_dir(self, row):
        return self.run_dir(f"row-{slug(row)}")

    def row_args(self, row):
        p = self.plan
        return ["--side", "foe", *([] if row == TODAY else ["--our-arm", row]), "--seed", hex(p["cell_seed"]),
                "--pairs", str(p["cell_pairs"])]

    def equality(self):
        """The check alone against beside: the cell (today, drawn) alone, then beside the first row's two other
        cells. Raises SeriesError (written to equality.json) when the two arm files differ beyond timing."""
        p = self.plan
        alone, beside = self.run_dir("equality-alone"), self.run_dir("equality-beside")
        args = self.row_args(TODAY)
        self.play("equality-alone", [(alone, args, [DRAWN])])
        others = [c for c in p["start_columns"] if c != DRAWN][:max(0, self.args.parallel - 1)]
        self.play("equality-beside", [(beside, args, [DRAWN])] + [(self.row_dir(TODAY), args, [c]) for c in others])
        a, b = (oracle.ladder._load_json(arm_file(d, DRAWN)) for d in (alone, beside))
        differs = sorted(k for k in set(a) | set(b) if k not in TIMING and a.get(k) != b.get(k))
        result = {"cell": [TODAY, DRAWN], "beside": others, "processes": 1 + len(others), "equal": not differs,
                  "differs": differs}
        with open(os.path.join(self.out, "equality.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
        self.record["equality"] = result
        if differs:
            raise SeriesError("beside_differs", f"the cell alone and beside differ in {differs}")
        # the alone run's arm is the cell (its conditions are the row's)
        self.merge_copy(alone, self.row_dir(TODAY), DRAWN)

    def merge_copy(self, source, run_dir, arm):
        new = oracle.ladder._load_json(os.path.join(source, "conditions.json"))
        self.check_conditions(source, new)
        path = os.path.join(run_dir, "conditions.json")
        os.makedirs(os.path.join(run_dir, "arms"), exist_ok=True)
        if os.path.exists(path):
            old = oracle.ladder._load_json(path)
            changed = oracle.resume_changes(old, new) + [k for k in ("workers", "commit", "dirty") if old.get(k) != new.get(k)]
            if changed:
                raise SeriesError("parts_differ", f"{source}: conditions differ from {run_dir} in {changed}")
        else:
            shutil.copyfile(os.path.join(source, "conditions.json"), path)
        shutil.copyfile(arm_file(source, arm), arm_file(run_dir, arm))
        oracle.summarize(run_dir)

    def fill(self, name, rows, columns):
        return self.play(name, [(self.row_dir(r), self.row_args(r), columns) for r in rows])

    def matrix(self, rows, columns, name, previous=None):
        os.makedirs(os.path.join(self.out, "matrix"), exist_ok=True)
        path = os.path.join(self.out, "matrix", f"{name}.json")
        argv = ["matrix", *[self.row_dir(r) for r in rows], "--out", path, "--columns", ",".join(columns)]
        if previous:
            argv += ["--previous", os.path.join(self.out, "matrix", f"{previous}.json")]
        with open(os.devnull, "w") as quiet:
            stdout, sys.stdout = sys.stdout, quiet
            try:
                oracle.main(argv)
            finally:
                sys.stdout = stdout
        m = oracle.ladder._load_json(path)
        if m["conditions"].get("workers") != self.args.workers:
            raise SeriesError("workers", f"matrix {name}: workers {m['conditions'].get('workers')}")
        return m

    def screen(self, name, side, flag, mix, seed):
        p = self.plan
        run_dir = self.run_dir(name)
        arms = oracle.arms_of("all", side)
        seconds = self.play(name, [(run_dir, ["--side", side, flag, mix, "--seed", hex(seed),
                                              "--pairs", str(p["screen_pairs"])], arms)])
        o = oracle.ladder._load_json(os.path.join(run_dir, "oracle.json"))
        key = "our_mix" if flag == "--our-mix" else "foe_mix"
        c = o["conditions"]
        if c["side"] != side or c.get(key) != oracle.mix_text(oracle.parse_mix(mix, "ours" if flag == "--our-mix"
                                                                             else "foe")) \
                or c["seed"] != hex(seed) or c["pairs"] != p["screen_pairs"] or len(o["ranking"]) != 90:
            raise SeriesError("screen", f"screen {name} is not the screen asked for")
        return o, seconds

    def run(self):
        p = self.plan
        self.equality()
        rows, columns = list(p["start_rows"]), list(p["start_columns"])
        started = time.perf_counter()
        self.fill("cells-start", rows, columns)
        m, name, why = self.matrix(rows, columns, "m0"), "m0", None
        self.record["rounds"].append({"round": 0, "seconds": time.perf_counter() - started, "rows": list(rows),
                                      "columns": list(columns), "value_points": m["value_points"],
                                      "our_mix": m["our_mix_text"], "foe_mix": m["foe_mix_text"]})
        self.save()
        self.mark("0")
        for r in range(1, p["rounds"] + 1):
            started = time.perf_counter()
            seed_foe, seed_ours = p["screen_seed"] + 2 * (r - 1), p["screen_seed"] + 2 * (r - 1) + 1
            foe, _ = self.screen(f"r{r}-foe", "foe", "--our-mix", m["our_mix_text"], seed_foe)
            ours, _ = self.screen(f"r{r}-ours", "ours", "--foe-mix", m["foe_mix_text"], seed_ours)
            answer, best = foe["ranking"][0], ours["ranking"][0]
            entry = {"round": r, "screen_seeds": [hex(seed_foe), hex(seed_ours)], "foe_answer": answer,
                     "our_answer": best}
            targets, new = [], []
            if answer not in columns:  # a new column: every row plays it
                columns.append(answer)
                targets, new = list(rows), [answer]
            if best not in rows:  # a new row plays every column
                rows.append(best)
                targets.append(best)
                new.append(best)
            if not targets:
                why = f"round {r}: the screens found nothing beyond the matrix"
                entry.update(seconds=time.perf_counter() - started, new=[])
                self.record["rounds"].append(entry)
                break
            self.fill(f"cells-r{r}", targets, columns)
            m, name = self.matrix(rows, columns, f"m{r}", previous=name), f"m{r}"
            gap = Fraction(m["previous"]["gap_exact"])
            entry.update(seconds=time.perf_counter() - started, new=new,
                         rows=list(rows), columns=list(columns), gap_points=m["previous"]["gap_points"],
                         value_points=m["value_points"], our_mix=m["our_mix_text"], foe_mix=m["foe_mix_text"])
            self.record["rounds"].append(entry)
            self.save()
            self.mark(str(r))
            if gap < p["gap_stop"]:
                why = f"round {r}: gap {m['previous']['gap_points']:.2f} points, below {float(p['gap_stop']) * 100:g}"
                break
        else:
            why = f"round {p['rounds']}: the last round"
        mix = m["our_mix_text"]
        self.record.update(stop=why, final_matrix=name, final_mix=mix)
        self.save()
        self.final(mix)

    def final(self, mix):
        p = self.plan
        started = time.perf_counter()
        screen, _ = self.screen("final-screen", "foe", "--our-mix", mix, p["final_screen_seed"])
        top = screen["ranking"][:p["answers"]]
        confirm = self.run_dir("final-confirm")
        args = ["--side", "foe", "--our-mix", mix, "--seed", hex(p["final_seed"]), "--pairs", str(p["final_pairs"])]
        runs = [(confirm, args, [DRAWN] + top)]
        for row, arms in p["controls"]:
            runs.append((self.run_dir(f"final-{slug(row)}"),
                         ["--side", "foe", *([] if row == TODAY else ["--our-arm", row]), "--seed", hex(p["final_seed"]),
                          "--pairs", str(p["final_pairs"])], arms))
        self.play("final", runs)
        self.record["final"] = {"answers": top, "seconds": time.perf_counter() - started, **self.compare(top)}
        self.record["status"] = "done"
        self.save()
        self.mark("done")

    def compare(self, top):
        """The predeclared numbers (README "What is reported"), paired over the final seed's game pairs, after the
        pairing check: the three drawn arms have identical foe draws, the runs the same seed, pairs, commit, dirty
        state, library and workers."""
        p = self.plan
        dirs = {"mix": self.run_dir("final-confirm"), TODAY: self.run_dir(f"final-{slug(TODAY)}"),
                "23|04": self.run_dir("final-23-04")}
        conditions = {k: oracle.ladder._load_json(os.path.join(d, "conditions.json")) for k, d in dirs.items()}
        keys = ("seed", "pairs", "games", "commit", "dirty", "library", "workers", "step", "registry",
                "ours_sha256_prefix", "foe_sha256_prefix", "sha256_prefix", "table_sha256", "max_steps")
        for k in keys:
            values = {name: c.get(k) for name, c in conditions.items()}
            if len({json.dumps(v, sort_keys=True) for v in values.values()}) != 1:
                raise SeriesError("pairing", f"the final runs differ in {k}: {values}")
        arm = lambda d, a: oracle.ladder._load_json(arm_file(d, a))  # noqa: E731
        drawn = {name: arm(d, DRAWN) for name, d in dirs.items()}
        if len({json.dumps(e["foe_drawn"]) for e in drawn.values()}) != 1:
            raise SeriesError("pairing", "the final drawn arms' foe draws differ")
        for name, d in dirs.items():
            for n in os.listdir(os.path.join(d, "arms")):
                e = oracle.ladder._load_json(os.path.join(d, "arms", n))
                if e.get("commit") != conditions["mix"]["commit"] or e.get("dirty") != conditions["mix"]["dirty"]:
                    raise SeriesError("pairing", f"{d}/{n}: another commit or dirty state")
        import numpy as np
        score = lambda d, a: np.asarray(arm(d, a)["scores"], np.float64)  # noqa: E731
        mix_drawn, mix_best = score(dirs["mix"], DRAWN), score(dirs["mix"], top[0])
        (today_row, today_arms), (cand_row, cand_arms) = p["controls"]
        t_drawn, t_answer = score(dirs[TODAY], DRAWN), score(dirs[TODAY], today_arms[1])
        c_drawn, c_answer = score(dirs[cand_row], DRAWN), score(dirs[cand_row], cand_arms[1])
        pd = oracle.paired_difference
        th = p["thresholds"]

        def verdict(d, threshold):
            lo, hi = d["95"]
            if lo > threshold:
                return "holds"
            return "fails: wholly below the threshold" if hi < threshold else "fails: reaches below the threshold"

        exploit = pd(mix_drawn, mix_best)
        lo, hi = exploit["95"]
        confirmed = {a: pd(mix_drawn, score(dirs["mix"], a)) for a in top}
        worst, gain = pd(mix_best, t_answer), pd(mix_drawn, t_drawn)
        best_confirmed = max(confirmed, key=lambda a: (confirmed[a]["points"], a))
        flags = {}  # README: an arm whose raw-fallback share is more than 2 points above its seat's median, by run
        for name, d in dirs.items():
            o = oracle.ladder._load_json(os.path.join(d, "oracle.json"))
            for seat in ("ours", "foe"):
                shares = {a: 100.0 * e["fallback_share"][seat] for a, e in o["arms"].items()}
                median = float(np.median(list(shares.values())))
                named = {a: {"share_points": v, "causes": (o["arms"][a].get("fallback_causes") or {}).get(seat)}
                         for a, v in shares.items() if v > median + 2}
                flags[f"{name}.{seat}"] = {"median_points": median, "max_points": max(shares.values()), "named": named}
        return {
            "pairing": "passed",
            "exploitability": {"answer": top[0], **exploit,
                               "reading": "exploitable" if lo > th["exploitable"] else "little to gain"
                               if hi < th["little"] else "no conclusion"},
            "confirmed_answers": confirmed,
            "best_confirmed": {"answer": best_confirmed, **confirmed[best_confirmed],
                               "note": "selected on stage-2 games, biased upward"},
            "fallbacks": flags,
            "scores": {"mix_drawn": float(mix_drawn.mean()), "mix_best": float(mix_best.mean()),
                       "today_drawn": float(t_drawn.mean()), "today_answer": float(t_answer.mean()),
                       "candidate_drawn": float(c_drawn.mean()), "candidate_answer": float(c_answer.mean())},
            "worst_case": {**worst, "condition": f"lower bound > {th['worst']:g}", "result": verdict(worst, th["worst"])},
            "gain": {**gain, "condition": f"lower bound > {th['gain']:g}", "result": verdict(gain, th["gain"])},
            "book_candidate": worst["95"][0] > th["worst"] and gain["95"][0] > th["gain"],
            "beside_without_reading": {
                "worst_case_vs_candidate": pd(mix_best, c_answer), "gain_vs_candidate": pd(mix_drawn, c_drawn),
                "exploitability_minus_today": pd(mix_drawn - mix_best, t_drawn - t_answer),
                "exploitability_minus_candidate": pd(mix_drawn - mix_best, c_drawn - c_answer)},
        }

    def mark(self, text):
        """DIR/round.txt: the last round finished ("0" the start matrix, "done" the end); the box saves the state when
        it changes."""
        path = os.path.join(self.out, "round.txt")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(text + "\n")
        os.replace(path + ".tmp", path)

    def save(self):
        path = os.path.join(self.out, "series.json")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(oracle._finite(self.record), f, indent=1, allow_nan=False)
        os.replace(path + ".tmp", path)


def check_resume(args):
    """SystemExit unless --out holds a series of this plan, worker count and process count that is not done; then its
    part directories (of an interrupted block, never merged) are dropped."""
    path = os.path.join(args.out, "series.json")
    if not os.path.isfile(path):
        raise SystemExit(f"--resume: {args.out} holds no series.json")
    old = oracle.ladder._load_json(path)
    for key in ("plan", "workers", "parallel", "cpus_per_process"):
        if old.get(key) != getattr(args, key):
            raise SystemExit(f"--resume: the series in {args.out} has {key}={old.get(key)!r}, not {getattr(args, key)!r}")
    if old.get("status") == "done":
        raise SystemExit(f"--resume: the series in {args.out} is done")
    os.makedirs(os.path.join(args.out, "logs"), exist_ok=True)
    runs = os.path.join(args.out, "runs")
    for name in sorted(os.listdir(runs)) if os.path.isdir(runs) else []:
        if name.endswith(".parts"):
            shutil.rmtree(os.path.join(runs, name))


def parser():
    p = argparse.ArgumentParser(prog="python -m duoforge_search.preview_series", description=__doc__.split("\n")[0])
    p.add_argument("--plan", required=True, choices=sorted(PLANS))
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--foe-net", required=True)
    p.add_argument("--ours", required=True)
    p.add_argument("--foe", required=True)
    p.add_argument("--out", required=True, help="the series' directory, outside the repository; must not exist "
                                                "unless --resume")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-steps", type=int, default=1000)
    p.add_argument("--parallel", type=int, default=1, help="processes side by side (the AWS box: 3)")
    p.add_argument("--cpus-per-process", type=int, default=0, help="pin process i to CPUs i*N.. with taskset (0: none)")
    p.add_argument("--deadline-seconds", type=int, default=0,
                   help="refuse a batch that could end this long after the series began (0: none)")
    p.add_argument("--resume", action="store_true", help="continue the series in --out (nothing is drawn anew)")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)
    except ValueError:
        raise SystemExit(f"--out {args.out} is inside the repository (AGENTS.md)") from None
    if not args.resume and os.path.exists(args.out):
        raise SystemExit(f"--out {args.out} exists: give --resume to continue the series there")
    if not 1 <= args.parallel <= 3:
        raise SystemExit("--parallel is 1 to 3 (HauptSession: three processes on the AWS box)")
    plan = PLANS[args.plan]
    if args.workers != plan["workers"] or args.max_steps != plan["max_steps"]:
        raise SystemExit(f"plan {args.plan} fixes --workers {plan['workers']} and --max-steps {plan['max_steps']}")
    if args.cpus_per_process < 0 or args.deadline_seconds < 0:
        raise SystemExit("--cpus-per-process and --deadline-seconds are not negative")
    if args.resume:
        check_resume(args)
    else:
        os.makedirs(os.path.join(args.out, "logs"))
    series = Series(args, PLANS[args.plan])
    series.save()
    try:
        series.run()
    except SeriesError as err:
        series.record.update(status="refused", reason=err.reason, message=str(err))
        series.save()
        print(f"preview_series: refused ({err.reason}): {err}", file=sys.stderr)
        return EQUALITY_EXIT if err.reason == "beside_differs" else FAILED_EXIT
    except SystemExit as err:  # a refusal of the oracle's own checks (summary, matrix): its text is the oracle's
        series.record.update(status="refused", reason="oracle_refused", message=str(err.code))
        series.save()
        print(f"preview_series: refused (oracle_refused): {err.code}", file=sys.stderr)
        return FAILED_EXIT
    except Exception as err:  # noqa: BLE001 -- recorded by type only: its text could name a member of a team
        series.record.update(status="failed", reason="error", message=type(err).__name__)
        series.save()
        print(f"preview_series: failed ({type(err).__name__})", file=sys.stderr)
        return FAILED_EXIT
    print(json.dumps({k: series.record.get(k) for k in ("status", "stop", "final_mix")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
