"""The preview oracle (issue #458): what the team preview costs in one matchup, before an opening book is built.

    python -m duoforge_search.preview_oracle --checkpoint MAIN --foe-net FOE --ours OURS --foe FOE_TEAM --out DIR
        [--side ours|foe] [--arms all | today,LEADS|BENCH,...] [--foe-lead SPECIES,SPECIES] [--our-arm LEADS|BENCH]
        [--pairs 32] [--seed SEED] [--workers 8] [--max-steps 1000]
    python -m duoforge_search.preview_oracle summary DIR

Our team OURS (a registry paste or a packed team) meets the foe team FOE_TEAM in --pairs game pairs (ladder.matchup_rows:
pair k is game k with ours on seat 0, then on seat 1). Both seats are piloted by ladder step 0 (the live search
until 2026-10-14, mix with lambda 0.5; MAIN searches, FOE is the foe model of the searched worlds), each with the other team's registry rows left out of its
spread table. An arm fixes our team preview:

- "today": our search's own choice, the main network's raw top-1 (live play);
- "LEADS|BENCH", e.g. "24|01": the four members brought (indices into OURS, 0 to 5), the two leads before the bar and
  the bench after it, each ascending. 15 bring-4 sets times 6 lead pairs are the 90 combinations ("all" plays each of
  them and "today"). A lead's side (left or right) and the bench order are fixed by the ascending order.

The foe's preview is drawn from the foe search's own team head (the main network's, as it plays raw at preview) by a
word of the game's decision key (draw_choice): the same draw in every arm, so the arms differ in our preview only.
--foe-lead fixes the foe's two leads (by species; the draw keeps only the team head's rows that lead with them, so its
bench still comes from the head): the case of an opponent who always leads so (#458, the sun lead). Each
arm plays the same suite rows on the same batch seed (common random numbers): a game of two arms is the same game up to
our preview. A SearchError stops the run; the summary refuses arms whose foe draws differ ("not paired").

--side foe turns the oracle around (the preview exploitability of #458): our preview is today's in every arm, and an
arm fixes the foe's preview instead ("LEADS|BENCH" indexes FOE_TEAM). Its reference arm "drawn" draws the foe's
preview from its team head as above; the summary ranks the foe's best answers first and reports the exploitability,
our score against drawn minus our score against the best answer, and refuses arms whose our previews differ.
--our-arm LEADS|BENCH (foe side only) plays our preview fixed to that combination instead of today's, in every arm
(drawn included): the exploitability of a candidate preview, e.g. a book entry. Every arm is refused unless our
preview played it in every game.

Each finished arm is written to DIR/arms/ARM.json (per-game scores, the foe's drawn choice per game, the decision
digests and fallback shares) and a rerun skips it when its conditions match; `summary` (also run at the end) writes
DIR/oracle.json: per arm its score with a pair-bootstrap interval, the paired difference to "today" in points, the
spread of the combinations (range, standard deviation, and the part of it left after the games' noise) and the foe's
preview distribution. Everything stays outside the repository: the teams' files are named by hash prefix only.
"""
import argparse
import hashlib
import itertools
import json
import os
import sys
import time

import numpy as np

from . import foe_arena, ladder

SEED = 0x2026101300000458
DRAW_TAG = 0x5052455649455700  # "PREVIEW": the foe preview's draw word, apart from the search's own words
STEP = "0"  # ladder step 0 on both seats (ladder.STEP0); its team preview is the raw top-1, so forcing it replaces
# nothing searched
ROSTER, BROUGHT = 6, 4
TODAY = "today"
DRAWN = "drawn"  # the foe side's reference arm: the foe's preview drawn from its team head, as on the ours side
SIDES = ("ours", "foe")


def combos():
    """The 90 arm names "LEADS|BENCH" in order: bring-4 sets lexicographically, then their lead pairs."""
    out = []
    for brought in itertools.combinations(range(ROSTER), BROUGHT):
        for leads in itertools.combinations(brought, 2):
            bench = [m for m in brought if m not in leads]
            out.append(f"{leads[0]}{leads[1]}|{bench[0]}{bench[1]}")
    return out


def parse_arm(name):
    """(leads, bench) of an arm name "LEADS|BENCH": two ascending members each, six distinct indices below 6 in all
    four. ValueError otherwise; "today" has no tuple (ValueError)."""
    leads, bar, bench = name.partition("|")
    if not bar or len(leads) != 2 or len(bench) != 2 or not (leads + bench).isdigit():
        raise ValueError(f"an arm is 'today' or LEADS|BENCH like '24|01' (got {name!r})")
    lead, rest = [int(c) for c in leads], [int(c) for c in bench]
    members = lead + rest
    if max(members) >= ROSTER or len(set(members)) != BROUGHT or lead != sorted(lead) or rest != sorted(rest):
        raise ValueError(f"arm {name!r}: four distinct members below {ROSTER}, leads and bench each ascending")
    return tuple(lead), tuple(rest)


def team_index(name):
    """The TEAM_TABLE row (the team head's action) of an arm name: leads first, then the bench."""
    from duoforge_learn.selfplay import TEAM_TABLE
    leads, bench = parse_arm(name)
    hit = np.flatnonzero((TEAM_TABLE == np.array(leads + bench, TEAM_TABLE.dtype)).all(axis=1))
    return int(hit[0])


def arm_of(choice):
    """The arm name of a TEAM_TABLE row: its leads and bench each sorted (side and bench order dropped)."""
    from duoforge_learn.selfplay import TEAM_TABLE
    row = [int(x) for x in TEAM_TABLE[int(choice)]]
    leads, bench = sorted(row[:2]), sorted(row[2:])
    return f"{leads[0]}{leads[1]}|{bench[0]}{bench[1]}"


def arms_of(text, side="ours"):
    """The arm list of --arms for the side whose preview the arms fix: "all" (the reference arm, then the 90
    combinations) or a comma list, each arm at most once. The ours side's reference is "today", the foe side's
    "drawn"."""
    if side not in SIDES:
        raise ValueError(f"the side is one of {SIDES} (got {side!r})")
    reference = TODAY if side == "ours" else DRAWN
    if text == "all":
        return [reference] + combos()
    out = [x.strip() for x in text.split(",") if x.strip()]
    if not out:
        raise ValueError("--arms names no arm")
    for name in out:
        if name in (TODAY, DRAWN) and name != reference:
            raise ValueError(f"{name!r} is no arm of the {side} side (its reference arm is {reference!r})")
        if name != reference:
            parse_arm(name)
    if len(set(out)) != len(out):
        raise ValueError(f"--arms names an arm twice ({text!r})")
    return out


def draw_choice(probabilities, key, seed):
    """The team head's draw of one decision: u from the decision key (seeds.play_uniforms under DRAW_TAG) against the
    cumulative probabilities, as the search's own draws play (belief.draw_index)."""
    from . import belief, seeds
    u = float(seeds.play_uniforms(np.uint64((int(seed) + DRAW_TAG) & 0xFFFFFFFFFFFFFFFF),
                                  np.array([key], np.uint64))[0])
    return belief.draw_index(probabilities, int(u * 2.0 ** 53) << 11)


class ForcedPreview:
    """A Timed search whose team-preview decisions play one fixed TEAM_TABLE row (choice), or its own when choice is
    None; every other decision is the search's. A team record keeps the search's own choice as own_choice."""

    def __init__(self, timed, choice):
        self.timed, self.choice = timed, choice

    def clear(self):
        self.timed.clear()

    def decide(self, roots, envs, seats, keys, last_step):
        actions, records = self.timed.decide(roots, envs, seats, keys, last_step)
        for d, r in enumerate(records):
            if r["boundary"] != "TEAM_SELECTION":
                continue
            if r["kind"] != "team":
                raise RuntimeError(f"a raw preview decided {r['kind']!r} at team preview (env {r['env']})")
            r["own_choice"] = r["choice"]
            if self.choice is not None:
                actions[d] = r["choice"] = int(self.choice)
        return actions, records


class DrawnPreview:
    """A Timed search whose team-preview decisions are drawn from its own team head (draw_choice); every other decision
    is the search's. drawn maps each game (env) to its drawn row; heads keeps the team head's probabilities per seat
    (the first seen, and every later one must equal it: the preview's view of a matchup does not change)."""

    def __init__(self, timed, search, seed, keep=None):
        self.timed, self.search, self.seed, self.keep = timed, search, int(seed), keep
        self.drawn, self.heads = {}, {}

    def clear(self):
        self.timed.clear()
        self.drawn = {}

    def decide(self, roots, envs, seats, keys, last_step):
        actions, records = self.timed.decide(roots, envs, seats, keys, last_step)
        team = [d for d, r in enumerate(records) if r["boundary"] == "TEAM_SELECTION"]
        if not team:
            return actions, records
        s = self.search
        obs, slots, pairs = roots.query_encoded(s.encoder, s.ext_supported)
        for d in team:
            r, e, p = records[d], int(envs[d]), int(seats[d])
            if r["kind"] != "team":
                raise RuntimeError(f"a raw preview decided {r['kind']!r} at team preview (env {e})")
            _, logp, _ = s._policy(obs[e:e + 1, p], slots[e:e + 1, p], pairs[e:e + 1, p])
            probs = np.exp(np.asarray(logp[0], np.float64))
            first = self.heads.setdefault(p, probs)
            if not np.allclose(first, probs, rtol=0, atol=1e-6):
                raise RuntimeError(f"the foe's team head differs between games of seat {p} (env {e})")
            r["own_choice"] = r["choice"]
            if self.keep is not None:
                probs = probs * self.keep
            actions[d] = r["choice"] = draw_choice(probs, int(keys[d]), self.seed)
            self.drawn[e] = r["choice"]
        return actions, records


def lead_mask(species, text):
    """The TEAM_TABLE rows (bool) that lead with the two members named in text ("Charizard,Venusaur", either order) of
    a team with these species; SystemExit naming a species the team lacks or a pair that is no two members."""
    from duoforge import data
    from duoforge_learn.selfplay import TEAM_TABLE
    ids = [data.to_id(x) for x in species]
    names = [x.strip() for x in text.split(",") if x.strip()]
    if len(names) != 2:
        raise SystemExit(f"--foe-lead names two species (got {text!r})")
    members = []
    for name in names:
        if data.to_id(name) not in ids:
            raise SystemExit(f"--foe-lead: the foe team has no {name!r} (its species: {', '.join(species)})")
        members.append(ids.index(data.to_id(name)))
    if members[0] == members[1]:
        raise SystemExit(f"--foe-lead names one member twice ({text!r})")
    return (np.sort(TEAM_TABLE[:, :2], axis=1) == np.array(sorted(members), TEAM_TABLE.dtype)).all(axis=1)


def fallback_causes(decisions):
    """{cause: count} of the decisions that played raw (foe_arena.FALLBACK_KINDS): each record's causes, else its
    reason, else its kind."""
    out = {}
    for r in decisions:
        if r["kind"] in foe_arena.FALLBACK_KINDS:
            for cause in r.get("causes") or [r.get("reason") or r["kind"]]:
                out[str(cause)] = out.get(str(cause), 0) + 1
    return dict(sorted(out.items()))


def paired_difference(a, b, resamples=2000, seed=SEED):
    """The mean of a - b over paired games (rows 2k and 2k + 1 one pair) in points (x 100), with its 95 % interval by
    the bootstrap over the pairs (ladder's draw)."""
    a, b = np.asarray(a, np.float64).reshape(-1), np.asarray(b, np.float64).reshape(-1)
    if a.shape != b.shape or a.size == 0 or a.size % 2:
        raise ValueError(f"paired scores need the same two rows per pair (got {a.size} and {b.size})")
    per_pair = (a - b).reshape(-1, 2).mean(axis=1)
    low, high = ladder._pair_bootstrap(per_pair, resamples, seed)
    return {"pairs": int(per_pair.size), "points": 100.0 * float(per_pair.mean()), "95": [100.0 * low, 100.0 * high]}


def spread(scores):
    """How far the combinations lie apart, from their per-game scores (arm -> array, the same pairs each): the range
    and standard deviation of their means in points, the mean noise of a mean (its standard error over the pairs, in
    points) and the true spread left after it: sqrt(max(0, var(means) - mean(se^2))), a random-effects estimate
    (predeclared, #458).

    The arms play the same games (common random numbers), so their noises are positively correlated and that estimate
    subtracts too much: it is a lower bound. true_sd_paired_points subtracts only the noise of the arms' differences,
    (tr S - 1'S1/K) / (K - 1) with S the covariance of the K arms' means, i.e. the variance of each arm's per-pair
    score around the pair's mean over all arms (added after the runs, reported beside the predeclared one)."""
    names = sorted(scores)
    if len(names) < 2:
        raise ValueError("a spread needs at least two combinations")
    per_pair = np.stack([np.asarray(scores[name], np.float64).reshape(-1, 2).mean(axis=1) for name in names], axis=1)
    pairs, k = per_pair.shape
    means = per_pair.mean(axis=0)
    se2 = per_pair.var(axis=0, ddof=1) / pairs if pairs > 1 else np.zeros(k)
    var = float(means.var(ddof=1))
    around = per_pair - per_pair.mean(axis=1, keepdims=True)
    paired_noise = float(around.var(axis=0, ddof=1).sum()) / pairs / (k - 1) if pairs > 1 else 0.0
    return {"combinations": len(names), "range_points": 100.0 * float(means.max() - means.min()),
            "sd_points": 100.0 * var ** 0.5, "noise_points": 100.0 * float(se2.mean()) ** 0.5,
            "true_sd_points": 100.0 * max(0.0, var - float(se2.mean())) ** 0.5,
            "paired_noise_points": 100.0 * paired_noise ** 0.5,
            "true_sd_paired_points": 100.0 * max(0.0, var - paired_noise) ** 0.5}


def resume_changes(old, conditions):
    """The condition keys in which a run's existing conditions.json (old) records another measurement than this run's
    conditions: every key but commit, dirty, cpu and workers (the commit is recorded per arm, and the arms' digests show
    whether it played alike). A conditions.json without a side is the ours side's (written before the foe side)."""
    old = {"side": "ours", **old}
    keys = [k for k in conditions if k not in ("commit", "dirty", "cpu", "workers")]
    return [k for k in keys if old.get(k) != json.loads(json.dumps(_finite(conditions[k])))]


def check_drawn(arm, drawn, games):
    """SystemExit unless the foe drew a preview in each of the games (drawn: env -> row)."""
    if sorted(drawn) != list(range(games)):
        raise SystemExit(f"arm {arm}: the foe drew no preview in {games - len(set(drawn) & set(range(games)))} "
                         f"game(s)")


def check_played(arm, decisions, who="our", combination=None):
    """SystemExit unless every team-preview decision in decisions played the combination (by default the arm's; the
    reference arms today and drawn play their own)."""
    combination = arm if combination is None else combination
    if combination in (TODAY, DRAWN):
        return
    played = {arm_of(r["choice"]) for r in decisions if r["boundary"] == "TEAM_SELECTION"}
    if played != {combination}:
        raise SystemExit(f"arm {arm}: {who} preview played {sorted(played)}, not {combination}")


def check_constant_own(arm, decisions):
    """SystemExit unless our own preview (each team record's own_choice, side and bench order dropped) is one
    combination per seat over all the arm's games: on the foe side, the arms are paired only if ours is the same."""
    own = {}
    for r in decisions:
        if r["boundary"] == "TEAM_SELECTION":
            own.setdefault(int(r["seat"]), set()).add(arm_of(r["own_choice"]))
    varied = {seat: sorted(v) for seat, v in sorted(own.items()) if len(v) > 1}
    if varied:
        raise SystemExit(f"arm {arm}: our own preview differs between games ({varied})")


def foe_previews(preview, decisions):
    """env -> the foe's played team row: a DrawnPreview's draws, else the foe's team records' choices."""
    if isinstance(preview, DrawnPreview):
        return dict(preview.drawn)
    return {int(r["env"]): r["choice"] for r in decisions if r["boundary"] == "TEAM_SELECTION"}


def _names(members, arm):
    if arm in (TODAY, DRAWN):
        return None
    leads, bench = parse_arm(arm)
    return {"leads": [members[m] for m in leads], "bench": [members[m] for m in bench]}


def summarize(out_dir):
    """oracle.json from DIR/conditions.json and DIR/arms/*.json: per arm its score, interval and difference to the
    reference arm, the ranking, the spread of the combinations, the marginals per bring set and per lead pair, and the
    foe's preview distribution. Returns the dict (also written).

    The ours side (the arms fix our preview; the foe's is drawn alike in every arm): the reference is today, the
    ranking is ours (best first), the loss is today against the best combination, and the scores are split by the
    foe's lead. The foe side (the arms fix the foe's preview; ours is today's in every arm): the reference is drawn,
    the ranking is the foe's best answers first (our lowest scores), and the exploitability is our score against drawn
    minus our score against the best answer. Scores are always ours."""
    conditions = ladder._load_json(os.path.join(out_dir, "conditions.json"))
    arm_dir = os.path.join(out_dir, "arms")
    arms = {}
    for name in sorted(os.listdir(arm_dir)):
        if name.endswith(".json"):
            entry = ladder._load_json(os.path.join(arm_dir, name))
            arms[entry["arm"]] = entry
    if not arms:
        raise SystemExit(f"{arm_dir} holds no finished arm")
    side = conditions.get("side", "ours")
    if side == "ours":
        if len({tuple(e["foe_drawn"]) for e in arms.values()}) != 1:
            raise SystemExit("the arms' foe previews differ: the arms are not paired")
    elif len({json.dumps(our_played(e), sort_keys=True) for e in arms.values()}) != 1:
        raise SystemExit("the arms' our previews differ: the arms are not paired")
    ours, foe = conditions["species"]["ours"], conditions["species"]["foe"]
    fixed = ours if side == "ours" else foe  # the team whose preview the arms fix
    reference_name = TODAY if side == "ours" else DRAWN
    scores = {name: np.asarray(e["scores"], np.float64) for name, e in arms.items()}
    reference = scores.get(reference_name)
    per_arm = {}
    for name, e in arms.items():
        per_arm[name] = {**({"members": _names(fixed, name)} if name != reference_name
                            else {"own_choice": e["own_choice"], "our_played": our_played(e)}),
                         "score": ladder.pair_interval(scores[name]),
                         "unfinished": e["unfinished"], "unresolved": e["unresolved"],
                         "fallback_share": e["fallback_share"], "fallback_causes": e.get("fallback_causes")}
        if reference is not None and name != reference_name:
            per_arm[name]["vs_" + reference_name] = paired_difference(scores[name], reference)
    combo_scores = {name: s for name, s in scores.items() if name != reference_name}
    sign = -1.0 if side == "ours" else 1.0  # ours: our best first; foe: the foe's best answers (our lowest) first
    ranking = sorted(combo_scores, key=lambda n: (sign * combo_scores[n].mean(), n))
    out = {"conditions": conditions, "arms": per_arm, "ranking": ranking}
    if len(combo_scores) >= 2:
        out["spread"] = spread(combo_scores)
    if side == "foe" and reference is not None and ranking:
        best = ranking[0]
        out["exploitability"] = {
            "best_answer": best, "our_preview": our_played(arms[DRAWN]), "our_arm": conditions.get("our_arm"),
            "points": paired_difference(reference, combo_scores[best]),
            "note": "the foe's best answer of the combinations played here, selected on these games: biased toward the "
                    "foe by the selection. In a confirmation run, the screen's best answer's vs_drawn is the number "
                    "not selected on these games"}
    today = reference if side == "ours" else None
    if today is not None and ranking:
        best = ranking[0]
        own = arms[TODAY]["own_choice"]
        out["loss"] = {"best": best, "today": own, "today_combination": sorted(set(own.values())),
                       "points": paired_difference(combo_scores[best], today),
                       "note": "the best of the combinations played here, selected on these games: biased upward by "
                               "the selection; a confirmation run on fresh seeds measures it without that bias"}
    marg = {"bring": {}, "leads": {}}
    for name, s in combo_scores.items():
        leads, bench = parse_arm(name)
        bring = "".join(str(m) for m in sorted(leads + bench))
        marg["bring"].setdefault(bring, []).append(s.mean())
        marg["leads"].setdefault("".join(map(str, leads)), []).append(s.mean())
    out["marginals"] = {kind: {key: {"members": [fixed[int(c)] for c in key], "combinations": len(v),
                                     "mean": float(np.mean(v)), "max": float(np.max(v)), "min": float(np.min(v))}
                               for key, v in sorted(table.items())} for kind, table in marg.items()}
    if side == "foe":  # the foe's drawn previews are the reference arm's
        foe_drawn = arms[DRAWN]["foe_drawn"] if DRAWN in arms else []
    else:
        foe_drawn = next(iter(arms.values()))["foe_drawn"]
    leads, brings = {}, {}
    for choice in foe_drawn:
        leads_, bench = parse_arm(arm_of(choice))
        lead_key = " + ".join(foe[m] for m in leads_)
        bring_key = " + ".join(foe[m] for m in sorted(leads_ + bench))
        leads[lead_key] = leads.get(lead_key, 0) + 1
        brings[bring_key] = brings.get(bring_key, 0) + 1
    out["foe_preview"] = {"games": len(foe_drawn), "leads": dict(sorted(leads.items(), key=lambda kv: -kv[1])),
                          "brought": dict(sorted(brings.items(), key=lambda kv: -kv[1]))}
    if side == "ours":  # on the foe side, each arm is one foe lead
        by_lead = {}
        for name, s in scores.items():
            rows = {}
            for g, choice in enumerate(foe_drawn):
                leads_, _ = parse_arm(arm_of(choice))
                rows.setdefault(" + ".join(foe[m] for m in leads_), []).append(s[g])
            by_lead[name] = {k: {"games": len(v), "score": float(np.mean(v))} for k, v in rows.items()}
        out["by_foe_lead"] = by_lead
    with open(os.path.join(out_dir, "oracle.json"), "w", encoding="utf-8") as f:
        json.dump(_finite(out), f, indent=1, allow_nan=False)
    return out


def our_played(entry):
    """Our played preview per seat of an arm file: its our_played, else (an arm file from before --our-arm, when ours
    always played its own) its own_choice."""
    return entry.get("our_played", entry["own_choice"])


def _finite(obj):
    from . import arena
    return arena._finite(obj)


def registry_id(path):
    """The registry id (data/teams/index.json) whose file has this file's bytes (teams.text_sha256), else None."""
    from duoforge import teams
    from duoforge_live.data import ROOT
    with open(path, "rb") as f:
        digest = teams.text_sha256(f.read())
    index = json.loads((ROOT / "data/teams/index.json").read_text(encoding="utf-8"))
    hits = [t["id"] for t in index["teams"] if t["sha256"] == digest]
    return hits[0] if hits else None


def _arm_entry(arm, records, ours_decisions, foe_decisions, foe_drawn, seconds):
    from . import arena
    own, played = {}, {}
    for r in ours_decisions:
        if r["boundary"] == "TEAM_SELECTION":
            own[str(r["seat"])] = arm_of(r["own_choice"])
            played[str(r["seat"])] = arm_of(r["choice"])
    return {"arm": arm, "scores": [float(x) for x in arena.scores(records)],
            "unfinished": int(records["unfinished"].sum()), "unresolved": int(records["unresolved"].sum()),
            "foe_drawn": foe_drawn, "own_choice": own, "our_played": played,
            "fallback_share": {"ours": foe_arena.fallback_share(ours_decisions),
                               "foe": foe_arena.fallback_share(foe_decisions)},
            "fallback_causes": {"ours": fallback_causes(ours_decisions), "foe": fallback_causes(foe_decisions)},
            "decisions_sha256": {"ours": ladder.decisions_digest(ours_decisions),
                                 "foe": ladder.decisions_digest(foe_decisions)},
            "decisions": {"ours": len(ours_decisions), "foe": len(foe_decisions)},
            "wall_seconds": ladder.wall_seconds(ours_decisions + foe_decisions), "seconds": seconds}


def main_summary(argv):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.preview_oracle summary")
    p.add_argument("out")
    args = p.parse_args(argv)
    out = summarize(args.out)
    print(json.dumps(_finite({k: out[k] for k in ("loss", "exploitability", "spread", "foe_preview") if k in out}),
                     indent=1))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["summary"]:
        return main_summary(argv[1:])
    p = argparse.ArgumentParser(prog="python -m duoforge_search.preview_oracle", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True, help="the main network (BC6): both seats search with it")
    p.add_argument("--foe-net", required=True, help="the foe model in both seats' searched worlds (BC6)")
    p.add_argument("--ours", required=True, help="our team: a registry paste or a packed team")
    p.add_argument("--foe", required=True, help="the foe team: a paste or a packed team, with its stat points")
    p.add_argument("--out", required=True, help="the output directory, outside the repository")
    p.add_argument("--side", choices=SIDES, default="ours",
                   help="whose preview the arms fix: ours (the foe's is drawn) or the foe's (ours is today's)")
    p.add_argument("--arms", default="all",
                   help="'all' (the side's reference arm, today or drawn, and the 90 combinations) or a comma list")
    p.add_argument("--foe-lead", metavar="SPECIES,SPECIES",
                   help="fix the foe's two leads; its bench is drawn from its team head given them (ours side only)")
    p.add_argument("--our-arm", metavar="LEADS|BENCH",
                   help="play our preview fixed to this combination in every arm instead of today's (foe side only)")
    p.add_argument("--pairs", type=int, default=32)
    p.add_argument("--seed", type=lambda text: int(text, 0), default=SEED)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-steps", type=int, default=1000)
    args = p.parse_args(argv)

    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)
    except ValueError:
        raise SystemExit(f"--out {args.out} is inside the repository (AGENTS.md)") from None
    if args.side == "foe" and args.foe_lead is not None:
        raise SystemExit("--foe-lead fixes the foe's leads on the ours side; on the foe side the arms fix them")
    if args.our_arm is not None:
        if args.side != "foe":
            raise SystemExit("--our-arm fixes our preview on the foe side; on the ours side the arms fix it")
        try:
            parse_arm(args.our_arm)
        except ValueError as err:
            raise SystemExit(f"--our-arm: {err}") from None
    try:
        arms = arms_of(args.arms, args.side)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    if args.pairs < 1:
        raise SystemExit("--pairs must be positive")
    matchup = ladder.matchup_teams(args.ours, args.foe)  # members without stat points are refused, never filled
    ours_id, foe_id = registry_id(args.ours), registry_id(args.foe)
    foe_species = [m["species"] for m in matchup["foe"]["members"]]
    keep = None if args.foe_lead is None else lead_mask(foe_species, args.foe_lead)

    from . import arena
    paths = {"main": args.checkpoint, "foe": args.foe_net}
    digests = {role: arena._sha256(path) for role, path in paths.items()}
    commit, dirty = ladder._checkout()

    import duoforge
    from duoforge import _layout
    from duoforge_learn import checkpoint as ck, evaluate
    from . import honest

    C = _layout.CONSTANTS
    settings = ladder.step_settings(STEP)
    if settings.get("preview_mode", "raw") != "raw":
        raise SystemExit(f"step {STEP}'s preview is not raw: forcing it would replace a searched preview")

    def load(path):
        params, config = ck.load_trained(path)
        return {"model": ck.trained_model(config, params), "params": params, "encoder": ck.encoder_of(config),
                "ext": ck.ext_supported_of(config)}

    main_net, foe_net = load(args.checkpoint), load(args.foe_net)
    foe_tuple = (foe_net["model"], foe_net["params"], foe_net["encoder"], foe_net["ext"])
    arm_dir = os.path.join(args.out, "arms")
    os.makedirs(arm_dir, exist_ok=True)

    with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
        pool = ladder.matchup_pool(ctx, matchup)
        rows = ladder.matchup_rows(args.pairs)
        table, source_ids, table_info = honest.live_spread_table(ctx)
        n = rows.shape[0]
        conditions = {
            "tool": "preview_oracle", "seed": hex(args.seed), "pairs": args.pairs, "games": int(n),
            "max_steps": args.max_steps, "step": {"name": STEP, "settings": settings},
            "side": args.side,
            "foe_preview": ("drawn from the foe search's raw team head (draw_choice)" if args.side == "ours" else
                            "fixed per arm; in the arm drawn, drawn from the foe search's raw team head (draw_choice)"),
            "foe_lead": None if args.foe_lead is None else sorted(x.strip() for x in args.foe_lead.split(",")),
            "our_arm": args.our_arm,
            "ours_sha256_prefix": matchup["ours"]["sha256"][:12], "foe_sha256_prefix": matchup["foe"]["sha256"][:12],
            "registry": {"ours": ours_id, "foe": foe_id},
            "left_out": {"ours_search": source_ids.get(foe_id), "foe_search": source_ids.get(ours_id)},
            "species": {label: [m["species"] for m in matchup[label]["members"]] for label in ladder.MATCHUP_LABELS},
            "commit": commit, "dirty": dirty, "library": duoforge.version(), "cpu": arena.cpu_model(),
            "encoders": {"main": main_net["encoder"], "foe": foe_net["encoder"]},
            "sha256_prefix": {role: digest[:12] for role, digest in digests.items()},
            "table_sha256": table_info["sha256"], "workers": args.workers}
        path = os.path.join(args.out, "conditions.json")
        if os.path.exists(path):  # a rerun resumes only the same measurement
            changed = resume_changes(ladder._load_json(path), conditions)
            if changed:
                raise SystemExit(f"{path} records another measurement (differs in {changed}): use a new --out")
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_finite(conditions), f, indent=1, allow_nan=False)

        def searcher(left_out):
            options = dict(settings, table=table, exclude_teams=[left_out] * n, workers=args.workers,
                           foe_net=foe_tuple)
            return honest.Honest(ctx, main_net["model"], main_net["params"], main_net["encoder"], main_net["ext"],
                                 **options)

        class SearchingOpponent(evaluate.Player):
            """play_suite takes an evaluate.Player as its opponent: the searching player is wrapped (ladder's)."""

            def __init__(self, player):
                super().__init__(None, None, None, player.name)
                self.player = player

            def indices(self, batch, choices, step=None, seats=None, last_step=None):
                return self.player.indices(batch, choices, step=step, seats=seats, last_step=last_step)

        with searcher(source_ids.get(foe_id)) as ours_search, searcher(source_ids.get(ours_id)) as foe_search:
            for arm in arms:
                target = os.path.join(arm_dir, (arm if arm in (TODAY, DRAWN) else arm.replace("|", "-")) + ".json")
                if os.path.exists(target):
                    print(f"{arm}: done before, skipped", flush=True)
                    continue
                ours_search.clear()
                foe_search.clear()
                ours_arm = arm if args.side == "ours" else args.our_arm  # None or today: our own preview
                forced = ours_arm is not None and ours_arm != TODAY
                learner = arena.SearchPlayer(ForcedPreview(foe_arena.Timed(ours_search),
                                                           team_index(ours_arm) if forced else None), "ours", args.seed)
                if args.side == "foe" and arm != DRAWN:
                    foe_preview = ForcedPreview(foe_arena.Timed(foe_search), team_index(arm))
                else:
                    foe_preview = DrawnPreview(foe_arena.Timed(foe_search), foe_search, args.seed, keep)
                opponent = SearchingOpponent(arena.SearchPlayer(foe_preview, "foe", args.seed))
                started = time.perf_counter()
                records = evaluate.play_suite(ctx, pool, rows, learner, opponent, args.workers, args.seed,
                                              max_steps=args.max_steps)
                seconds = time.perf_counter() - started
                ours_decisions = [r for row in sorted(learner.records) for r in learner.records[row]]
                foe_decisions = [r for row in sorted(opponent.player.records) for r in opponent.player.records[row]]
                played = foe_previews(foe_preview, foe_decisions)
                check_drawn(arm, played, n)
                entry = _arm_entry(arm, records, ours_decisions, foe_decisions, [int(played[e]) for e in range(n)],
                                   seconds)
                entry["commit"] = commit
                if args.side == "ours":
                    check_played(arm, ours_decisions)
                else:
                    check_played(arm, foe_decisions, "the foe's")
                    if args.our_arm is None:
                        check_constant_own(arm, ours_decisions)
                    else:
                        check_played(arm, ours_decisions, combination=args.our_arm)
                with open(target + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(_finite(entry), f, indent=1, allow_nan=False)
                os.replace(target + ".tmp", target)
                print(f"{arm}: score {np.mean(entry['scores']):.3f} over {n} games, {seconds:.0f} s", flush=True)
    out = summarize(args.out)
    print(json.dumps(_finite({k: out[k] for k in ("loss", "exploitability", "spread", "foe_preview") if k in out}),
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
