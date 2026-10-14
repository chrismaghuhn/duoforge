"""The preview oracle (issue #458): what the team preview costs in one matchup, before an opening book is built.

    python -m duoforge_search.preview_oracle --checkpoint MAIN --foe-net FOE --ours OURS --foe FOE_TEAM --out DIR
        [--side ours|foe] [--arms all | today,LEADS|BENCH,...] [--foe-lead SPECIES,SPECIES] [--our-arm LEADS|BENCH]
        [--our-mix ARM:P,...] [--foe-mix ARM:P,...] [--pairs 32] [--seed SEED] [--workers 8] [--max-steps 1000]
    python -m duoforge_search.preview_oracle summary DIR
    python -m duoforge_search.preview_oracle matrix DIR... --out FILE [--previous FILE]

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

A mix ("ARM:P,ARM:P,...", P a decimal or a fraction like 1/3, positive and summing to exactly 1) plays one of its arms
per game, picked by a word of the game's decision key under a tag of its own (mix_pick): the pick does not depend on the
arm, so every arm of a run plays the same picks (common random numbers), and it is apart from the foe's drawn preview.
--our-mix (foe side only, instead of --our-arm) mixes our preview over "today" and combinations; --foe-mix (ours side
only, instead of --foe-lead) mixes the foe's over "drawn" (its team-head draw) and combinations. A mixed arm is refused
unless every game picked, each pick played, and each arm of the mix was picked about as often as its probability says
(check_mix); the summary refuses arms whose picks differ.

`matrix` reads foe-side runs of one measurement (each DIR one of our previews: --our-arm, or today without it; the same
seed, pairs, commit, library and foe arms in every DIR) into the matrix of our mean scores, our previews by the foe's
arms, and writes its exact equilibrium (zero_sum.solve: our mix, the foe's mix and the value) to FILE; with --previous
(an earlier matrix FILE), also the double-oracle gap of that file's mixes on this matrix (zero_sum.gap).

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
OUR_MIX_TAG = 0x4D49584F55520000  # "MIXOUR": the pick word of our mixed preview, apart from DRAW_TAG
FOE_MIX_TAG = 0x4D4958464F450000  # "MIXFOE": the pick word of the foe's mixed preview
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
    from . import belief
    return belief.draw_index(probabilities, int(_uniform(key, seed, DRAW_TAG) * 2.0 ** 53) << 11)


def _uniform(key, seed, tag):
    """A uniform in [0, 1) of a decision key under seed and tag (seeds.play_uniforms)."""
    from . import seeds
    return float(seeds.play_uniforms(np.uint64((int(seed) + tag) & 0xFFFFFFFFFFFFFFFF),
                                     np.array([key], np.uint64))[0])


def parse_mix(text, side):
    """[(arm, Fraction)] of a mix "ARM:P,ARM:P,..." over the arms of the side whose preview it mixes (ours: today and
    combinations; foe: drawn and combinations), each arm once, sorted by name, every P positive and their sum exactly
    1. ValueError otherwise."""
    from fractions import Fraction
    if side not in SIDES:
        raise ValueError(f"the side is one of {SIDES} (got {side!r})")
    reference = TODAY if side == "ours" else DRAWN
    out = {}
    for part in (x.strip() for x in text.split(",")):
        if not part:
            continue
        name, colon, prob = part.rpartition(":")
        name = name.strip()
        if not colon or not name:
            raise ValueError(f"a mix is ARM:P,ARM:P,... like '23|04:1/2,today:1/2' (got {part!r})")
        if name in (TODAY, DRAWN) and name != reference:
            raise ValueError(f"{name!r} is no arm of the {side} side's mix (its reference arm is {reference!r})")
        if name != reference:
            parse_arm(name)
        if name in out:
            raise ValueError(f"the mix names {name!r} twice")
        try:
            p = Fraction(prob.strip())
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"the mix's probability of {name!r} is no number ({prob!r})") from None
        if p <= 0:
            raise ValueError(f"the mix's probability of {name!r} is not positive ({p})")
        out[name] = p
    if not out:
        raise ValueError("the mix names no arm")
    if sum(out.values()) != 1:
        raise ValueError(f"the mix's probabilities sum to {sum(out.values())}, not 1")
    return sorted(out.items())


def mix_text(mix):
    """The canonical text of a parsed mix: "ARM:P,..." by name, each P an exact fraction."""
    return ",".join(f"{name}:{p}" for name, p in mix)


def mix_pick(mix, key, seed, tag):
    """The arm of a mix [(arm, Fraction)] that a decision with this key plays: a uniform of the key under tag against
    the mix's cumulative probabilities, compared exactly."""
    from fractions import Fraction
    u, total = Fraction(_uniform(key, seed, tag)), 0
    for name, p in mix:
        total += p
        if u < total:
            return name
    raise RuntimeError(f"the mix's probabilities sum to {total}, not 1")


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
            probs = head_probabilities(s, self.heads, (obs, slots, pairs), e, p)
            r["own_choice"] = r["choice"]
            if self.keep is not None:
                probs = probs * self.keep
            actions[d] = r["choice"] = draw_choice(probs, int(keys[d]), self.seed)
            self.drawn[e] = r["choice"]
        return actions, records


def head_probabilities(search, heads, encoded, env, seat):
    """The search's team-head probabilities for (env, seat) from roots.query_encoded's arrays; heads keeps the first
    per seat, and every later one must equal it (RuntimeError)."""
    obs, slots, pairs = encoded
    _, logp, _ = search._policy(obs[env:env + 1, seat], slots[env:env + 1, seat], pairs[env:env + 1, seat])
    probs = np.exp(np.asarray(logp[0], np.float64))
    first = heads.setdefault(seat, probs)
    if not np.allclose(first, probs, rtol=0, atol=1e-6):
        raise RuntimeError(f"the foe's team head differs between games of seat {seat} (env {env})")
    return probs


class MixedPreview:
    """A Timed search whose team-preview decisions play an arm of a mix [(arm, Fraction)], picked per decision by
    mix_pick under tag: a combination plays its TEAM_TABLE row, today the search's own choice, drawn a draw from the
    search's own team head (draw_choice, the same draw as DrawnPreview's in that game). Every other decision is the
    search's. picked maps each game (env) to its arm, played to its played row."""

    def __init__(self, timed, search, seed, mix, tag):
        self.timed, self.search, self.seed, self.mix, self.tag = timed, search, int(seed), list(mix), int(tag)
        self.picked, self.played, self.heads = {}, {}, {}

    def clear(self):
        self.timed.clear()
        self.picked, self.played = {}, {}

    def decide(self, roots, envs, seats, keys, last_step):
        actions, records = self.timed.decide(roots, envs, seats, keys, last_step)
        encoded = None
        for d, r in enumerate(records):
            if r["boundary"] != "TEAM_SELECTION":
                continue
            e, p = int(envs[d]), int(seats[d])
            if r["kind"] != "team":
                raise RuntimeError(f"a raw preview decided {r['kind']!r} at team preview (env {e})")
            r["own_choice"] = r["choice"]
            name = mix_pick(self.mix, int(keys[d]), self.seed, self.tag)
            if name == DRAWN:
                if encoded is None:
                    encoded = roots.query_encoded(self.search.encoder, self.search.ext_supported)
                choice = draw_choice(head_probabilities(self.search, self.heads, encoded, e, p), int(keys[d]),
                                     self.seed)
            elif name == TODAY:
                choice = r["choice"]
            else:
                choice = team_index(name)
            actions[d] = r["choice"] = int(choice)
            self.picked[e], self.played[e] = name, int(choice)
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


def check_mix(arm, preview, decisions, games, who="our"):
    """{arm of the mix: games picked} of a MixedPreview; SystemExit unless it picked in each of the games, each
    team-preview decision in decisions played its game's pick (a combination its row up to side and bench order, today
    the own choice, drawn the recorded draw), and each arm of the mix was picked within 4 standard deviations (plus one
    game) of its expected count. A combination's play is checked against its pick independently; today's and drawn's
    against what MixedPreview recorded (the own choice, its draw)."""
    picked = preview.picked
    if sorted(picked) != list(range(games)):
        raise SystemExit(f"arm {arm}: {who} mix picked no preview in {games - len(set(picked) & set(range(games)))} "
                         f"game(s)")
    for r in decisions:
        if r["boundary"] != "TEAM_SELECTION":
            continue
        e = int(r["env"])
        name = picked[e]
        ok = (r["choice"] == r["own_choice"] if name == TODAY else
              r["choice"] == preview.played[e] if name == DRAWN else arm_of(r["choice"]) == name)
        if not ok:
            raise SystemExit(f"arm {arm}: {who} mix picked {name} in game {e}, but it played {arm_of(r['choice'])}")
    counts = {}
    for name in picked.values():
        counts[name] = counts.get(name, 0) + 1
    stray = sorted(set(counts) - {name for name, _ in preview.mix})
    if stray:
        raise SystemExit(f"arm {arm}: {who} mix picked {stray}, which it does not hold")
    for name, p in preview.mix:
        expected = games * p
        bound = 4 * float(expected * (1 - p)) ** 0.5 + 1
        if abs(counts.get(name, 0) - expected) > bound:
            raise SystemExit(f"arm {arm}: {who} mix picked {name} in {counts.get(name, 0)} of {games} games, expected "
                             f"{float(expected):.1f} (bound {bound:.1f})")
    return {name: counts.get(name, 0) for name, _ in preview.mix}


def foe_previews(preview, decisions):
    """env -> the foe's played team row: a DrawnPreview's draws or a MixedPreview's played rows, else the foe's team
    records' choices."""
    if isinstance(preview, DrawnPreview):
        return dict(preview.drawn)
    if isinstance(preview, MixedPreview):
        return dict(preview.played)
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
    foe's lead. The foe side (the arms fix the foe's preview; ours is today's, or --our-arm's, in every arm): the
    reference is drawn, the ranking is the foe's best answers first (our lowest scores), and the exploitability is our
    score against drawn minus our score against the best answer. Scores are always ours."""
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
    elif conditions.get("our_arm") is not None:
        wrong = sorted(n for n, e in arms.items() if played_set(e) != {conditions["our_arm"]})
        if wrong:
            raise SystemExit(f"arms {wrong}: our preview did not play --our-arm {conditions['our_arm']}")
    for key, flag in (("our_picked", "our_mix"), ("foe_picked", "foe_mix")):
        if conditions.get(flag) is not None and len({json.dumps(e.get(key)) for e in arms.values()}) != 1:
            raise SystemExit(f"the arms' {key.replace('_', ' ')} previews of --{flag.replace('_', '-')} differ: the arms "
                             f"are not paired")
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
            "our_mix": conditions.get("our_mix"),
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
    """Our played preview per seat of an arm file: its our_played (a combination, or under --our-mix the sorted list of
    those played), else (an arm file from before --our-arm, when ours always played its own) its own_choice."""
    return entry.get("our_played", entry["own_choice"])


def played_set(entry):
    """The set of combinations our preview played in an arm file, over its seats (our_played's lists flattened)."""
    out = set()
    for v in our_played(entry).values():
        out.update(v if isinstance(v, list) else [v])
    return out


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


def _arm_entry(arm, records, ours_decisions, foe_decisions, foe_drawn, seconds, our_picked=None, foe_picked=None):
    """An arm file's record. our_played is one combination per seat, or the sorted list of them when ours varied
    (under --our-mix); our_picked and foe_picked are a mix's picks per game (None without one)."""
    from . import arena
    own, played = {}, {}
    for r in ours_decisions:
        if r["boundary"] == "TEAM_SELECTION":
            own[str(r["seat"])] = arm_of(r["own_choice"])
            played.setdefault(str(r["seat"]), set()).add(arm_of(r["choice"]))
    played = {seat: sorted(v)[0] if len(v) == 1 else sorted(v) for seat, v in played.items()}
    return {"arm": arm, "scores": [float(x) for x in arena.scores(records)],
            "unfinished": int(records["unfinished"].sum()), "unresolved": int(records["unresolved"].sum()),
            "foe_drawn": foe_drawn, "own_choice": own, "our_played": played,
            "our_picked": our_picked, "foe_picked": foe_picked,
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


MATRIX_KEYS = ("tool", "seed", "pairs", "games", "max_steps", "step", "side", "foe_preview", "ours_sha256_prefix",
               "foe_sha256_prefix", "registry", "left_out", "species", "commit", "dirty", "library", "encoders",
               "sha256_prefix", "table_sha256")


def build_matrix(dirs):
    """(rows, columns, scores, conditions) of foe-side runs of one measurement: each DIR one of our previews (its
    --our-arm, or today), the rows sorted (today first, then by name) and the foe's arms as columns (drawn first, then
    by name), so the order of the DIRs does not matter; scores[i][j] is our exact mean score (Fraction) of row i
    against column j. SystemExit unless every DIR is a foe-side run without --our-mix, the rows are distinct, the DIRs
    agree in MATRIX_KEYS and in their arms, every arm file names the measurement's commit and dirty state and holds
    one score per game, a row's arms played one preview of ours (its --our-arm, if set), and each arm's foe previews
    are the same in every DIR (paired)."""
    from fractions import Fraction
    if not dirs:
        raise SystemExit("matrix needs at least one run directory")
    rows, runs = [], []
    for d in dirs:
        conditions = ladder._load_json(os.path.join(d, "conditions.json"))
        if conditions.get("side", "ours") != "foe":
            raise SystemExit(f"{d}: a matrix row is a foe-side run (this is the {conditions.get('side', 'ours')} side)")
        if conditions.get("our_mix") is not None:
            raise SystemExit(f"{d}: a matrix row is one preview of ours, not the mix {conditions['our_mix']}")
        arm_dir = os.path.join(d, "arms")
        arms = {}
        for name in sorted(os.listdir(arm_dir)):
            if name.endswith(".json"):
                entry = ladder._load_json(os.path.join(arm_dir, name))
                arms[entry["arm"]] = entry
        rows.append(conditions.get("our_arm") or TODAY)
        runs.append((d, conditions, arms))
    if len(set(rows)) != len(rows):
        raise SystemExit(f"matrix rows repeat: {rows}")
    order = sorted(range(len(rows)), key=lambda i: (rows[i] != TODAY, rows[i]))
    rows, runs = [rows[i] for i in order], [runs[i] for i in order]
    first_dir, first, first_arms = runs[0]
    for d, conditions, arms in runs:
        changed = [k for k in MATRIX_KEYS if conditions.get(k) != first.get(k)]
        if changed:
            raise SystemExit(f"{d} and {first_dir} are not one measurement (they differ in {changed})")
        if sorted(arms) != sorted(first_arms):
            raise SystemExit(f"{d} and {first_dir} played other foe arms ({sorted(arms)} / {sorted(first_arms)})")
        for name, entry in arms.items():
            if entry.get("commit") != first.get("commit"):
                raise SystemExit(f"{d}: arm {name} names commit {entry.get('commit')}, not {first.get('commit')}")
            if entry.get("dirty") != first.get("dirty"):
                raise SystemExit(f"{d}: arm {name} names dirty {entry.get('dirty')}, not {first.get('dirty')}")
            if len(entry["scores"]) != first.get("games"):
                raise SystemExit(f"{d}: arm {name} holds {len(entry['scores'])} scores, not {first.get('games')}")
            if entry["foe_drawn"] != first_arms[name]["foe_drawn"]:
                raise SystemExit(f"{d} and {first_dir}: arm {name}'s foe previews differ: not paired")
        if len({json.dumps(our_played(e), sort_keys=True) for e in arms.values()}) > 1:
            raise SystemExit(f"{d}: the arms' our previews differ: the arms are not paired")
        if conditions.get("our_arm") is not None:
            wrong = sorted(n for n, e in arms.items() if played_set(e) != {conditions["our_arm"]})
            if wrong:
                raise SystemExit(f"{d}: arms {wrong}: our preview did not play --our-arm {conditions['our_arm']}")
    if not first_arms:
        raise SystemExit(f"{first_dir} holds no finished arm")
    columns = sorted(first_arms, key=lambda n: (n != DRAWN, n))
    scores = [[sum(Fraction(x) for x in arms[c]["scores"]) / len(arms[c]["scores"]) for c in columns]
              for _, _, arms in runs]
    return rows, columns, scores, {k: first.get(k) for k in MATRIX_KEYS}


def _mix_of(names, weights):
    """{name: Fraction} of a mix's support (positive weights) in the given order."""
    return {name: w for name, w in zip(names, weights) if w > 0}


def _check_previous(old, rows, columns, scores, conditions):
    """SystemExit unless an earlier matrix file old is of this measurement (its conditions) and this matrix extends
    it: its rows and columns are among these, with the same exact cells."""
    if json.loads(json.dumps(_finite(old.get("conditions")))) != json.loads(json.dumps(_finite(conditions))):
        changed = sorted(k for k in MATRIX_KEYS if (old.get("conditions") or {}).get(k) != conditions.get(k))
        raise SystemExit(f"--previous is of another measurement (it differs in {changed})")
    missing = sorted(set(old["rows"]) - set(rows)) + sorted(set(old["columns"]) - set(columns))
    if missing:
        raise SystemExit(f"--previous: this matrix lacks its rows or columns {missing}")
    for i, row in enumerate(old["rows"]):
        for j, column in enumerate(old["columns"]):
            if str(scores[rows.index(row)][columns.index(column)]) != old["scores_exact"][i][j]:
                raise SystemExit(f"--previous: cell ({row}, {column}) is {old['scores_exact'][i][j]} there, "
                                 f"{scores[rows.index(row)][columns.index(column)]} here")


def _extend(mix, names, who):
    """The weights of a stored mix {name: "P"} over names; SystemExit if it holds a name that names lacks."""
    from fractions import Fraction
    missing = sorted(set(mix) - set(names))
    if missing:
        raise SystemExit(f"--previous: {who} mix holds {missing}, which this matrix lacks")
    return [Fraction(mix.get(name, 0)) for name in names]


def main_matrix(argv):
    from . import zero_sum
    p = argparse.ArgumentParser(prog="python -m duoforge_search.preview_oracle matrix")
    p.add_argument("dirs", nargs="+", help="foe-side runs of one measurement, one per preview of ours")
    p.add_argument("--out", required=True, help="the output file, outside the repository")
    p.add_argument("--previous", help="an earlier matrix file: the gap of its mixes on this matrix")
    args = p.parse_args(argv)
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)
    except ValueError:
        raise SystemExit(f"--out {args.out} is inside the repository (AGENTS.md)") from None
    rows, columns, scores, conditions = build_matrix(args.dirs)
    x, y, value = zero_sum.solve(scores)
    ours, foes = _mix_of(rows, x), _mix_of(columns, y)
    out = {"conditions": conditions, "rows": rows, "columns": columns,
           "scores_points": [[100.0 * float(v) for v in row] for row in scores],
           "scores_exact": [[str(v) for v in row] for row in scores],
           "value_points": 100.0 * float(value), "value_exact": str(value),
           "our_mix": {k: str(v) for k, v in ours.items()}, "foe_mix": {k: str(v) for k, v in foes.items()},
           "our_mix_text": mix_text(sorted(ours.items())), "foe_mix_text": mix_text(sorted(foes.items()))}
    if args.previous:
        old = ladder._load_json(args.previous)
        _check_previous(old, rows, columns, scores, conditions)
        g = zero_sum.gap(scores, _extend(old["our_mix"], rows, "our"), _extend(old["foe_mix"], columns, "the foe's"))
        out["previous"] = {"file": os.path.basename(args.previous), "our_mix": old["our_mix"],
                           "foe_mix": old["foe_mix"], **{k + "_points": 100.0 * float(v) for k, v in g.items()},
                           **{k + "_exact": str(v) for k, v in g.items()}}
    with open(args.out + ".tmp", "w", encoding="utf-8") as f:
        json.dump(_finite(out), f, indent=1, allow_nan=False)
    os.replace(args.out + ".tmp", args.out)
    print(json.dumps({k: out[k] for k in ("value_points", "our_mix", "foe_mix", "previous") if k in out}, indent=1))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["summary"]:
        return main_summary(argv[1:])
    if argv[:1] == ["matrix"]:
        return main_matrix(argv[1:])
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
    p.add_argument("--our-mix", metavar="ARM:P,...",
                   help="play our preview mixed over today and combinations, picked per game (foe side only)")
    p.add_argument("--foe-mix", metavar="ARM:P,...",
                   help="play the foe's preview mixed over drawn and combinations, picked per game (ours side only)")
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
        if args.our_arm in (TODAY, DRAWN):
            raise SystemExit(f"--our-arm takes a combination LEADS|BENCH like '23|04', not {args.our_arm!r}")
        try:
            parse_arm(args.our_arm)
        except ValueError as err:
            raise SystemExit(f"--our-arm: {err}") from None
    our_mix = foe_mix = None
    if args.our_mix is not None:
        if args.side != "foe":
            raise SystemExit("--our-mix mixes our preview on the foe side; on the ours side the arms fix it")
        if args.our_arm is not None:
            raise SystemExit("--our-mix and --our-arm both set our preview: give one")
        try:
            our_mix = parse_mix(args.our_mix, "ours")
        except ValueError as err:
            raise SystemExit(f"--our-mix: {err}") from None
    if args.foe_mix is not None:
        if args.side != "ours":
            raise SystemExit("--foe-mix mixes the foe's preview on the ours side; on the foe side the arms fix it")
        if args.foe_lead is not None:
            raise SystemExit("--foe-mix and --foe-lead both set the foe's preview: give one")
        try:
            foe_mix = parse_mix(args.foe_mix, "foe")
        except ValueError as err:
            raise SystemExit(f"--foe-mix: {err}") from None
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
            "foe_preview": ("fixed per arm; in the arm drawn, drawn from the foe search's raw team head (draw_choice)"
                            if args.side == "foe" else "drawn from the foe search's raw team head (draw_choice)"
                            if foe_mix is None else "mixed by --foe-mix, picked per game (mix_pick)"),
            "foe_lead": None if args.foe_lead is None else sorted(x.strip() for x in args.foe_lead.split(",")),
            "our_arm": args.our_arm,
            "our_mix": mix_text(our_mix) if our_mix else None, "foe_mix": mix_text(foe_mix) if foe_mix else None,
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
                if our_mix is not None:
                    our_preview = MixedPreview(foe_arena.Timed(ours_search), ours_search, args.seed, our_mix,
                                               OUR_MIX_TAG)
                else:
                    our_preview = ForcedPreview(foe_arena.Timed(ours_search), team_index(ours_arm) if forced else None)
                learner = arena.SearchPlayer(our_preview, "ours", args.seed)
                if args.side == "foe" and arm != DRAWN:
                    foe_preview = ForcedPreview(foe_arena.Timed(foe_search), team_index(arm))
                elif foe_mix is not None:
                    foe_preview = MixedPreview(foe_arena.Timed(foe_search), foe_search, args.seed, foe_mix,
                                               FOE_MIX_TAG)
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
                picks = {}
                if args.side == "ours":
                    check_played(arm, ours_decisions)
                    if foe_mix is not None:
                        picks["foe"] = check_mix(arm, foe_preview, foe_decisions, n, "the foe's")
                else:
                    check_played(arm, foe_decisions, "the foe's")
                    check_constant_own(arm, ours_decisions)
                    if args.our_arm is not None:
                        check_played(arm, ours_decisions, combination=args.our_arm)
                    if our_mix is not None:
                        picks["ours"] = check_mix(arm, our_preview, ours_decisions, n)
                entry = _arm_entry(arm, records, ours_decisions, foe_decisions, [int(played[e]) for e in range(n)],
                                   seconds,
                                   our_picked=[our_preview.picked[e] for e in range(n)] if our_mix else None,
                                   foe_picked=[foe_preview.picked[e] for e in range(n)] if foe_mix else None)
                entry["commit"], entry["dirty"] = commit, dirty
                if picks:
                    entry["mix_counts"] = picks
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
