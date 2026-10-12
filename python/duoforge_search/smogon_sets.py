"""The closed-sheet set prior: whole sets of the team registry, reweighted by Smogon's usage statistics (decision 0081,
#385 step 3).

    python -m duoforge_search.smogon_sets --stats DIR [--fetch] [--check]

Source: the team registry (data/teams: published pastes) for whole sets, and Smogon's usage statistics
(https://www.smogon.com/stats), the chaos JSON of Reg M-C (Bo1 and Bo3) of smogon_spreads (the same pinned files, month
and cutoffs), for how often each part of a set is played. With thanks to Smogon and its statistics maintainers. The raw
files stay outside the repository (smogon_spreads.load checks their pins); only the derived table TABLE_PATH is
committed, with this credit in its header. --check rebuilds the table and fails unless it is the committed one byte for
byte.

A set is (item, ability, nature, moves) under the engine's names; the species is the one an open sheet names (a Mega
forme's base species, with the stone). Derivation, every case counted in the table's "derivation":
- Registry sets: every member of every registry team, once per team in which it appears. A name the engine does not know,
  or a set its setup refuses, is dropped and counted (refused). A set holding the stone of its species' Mega forme is in
  that forme's bucket; any other set is in the base species' bucket.
- Smogon marginals, per bucket: the Smogon entry of the bucket's name (a Mega forme has its own) at the highest cutoff
  whose two formats together weigh at least smogon_spreads.MIN_WEIGHT (the spread table's rule), both formats summed:
  the item, the ability, the nature (from the spreads) and each move's share of sets (a set has four move slots). A Mega
  entry's ability is the Mega's own, not the sheet's: no ability marginal for a Mega bucket (counted).
- Raking: the bucket's support (its registry sets) is reweighted from its registry counts toward the marginals by
  iterative proportional fitting, RAKE_SWEEPS sweeps of the item, ability and nature partitions and of each move's
  in/out partition. A target blends Smogon with the registry (PRIOR_WEIGHT sets' worth of the registry's own share), so
  a part Smogon never saw keeps a small weight instead of none. Smogon's mass on parts no support set has is counted
  (uncovered), and so is the largest gap between a target and the raked share (residual).
- Thin buckets: fewer than MIN_SETS distinct registry sets, or support that leaves more than UNCOVERED_MAX of Smogon's
  item, ability or move mass uncovered (counted apart). SYNTH_SETS sets are drawn from the bucket's marginals (a
  deterministic word per draw), joined to its registry sets, and raked with them. Consistency rules, each counted: four
  distinct moves; a Choice item's holder carries no move of CHOICE_EXCLUDED (Protect, Detect); a Mega bucket's set holds
  its stone and takes its ability from the base species' Smogon entry, else from the engine's legal abilities; the
  engine's setup accepts the set (else it is drawn again, up to SYNTH_ATTEMPTS times per set).
- A forme Smogon counts under its dex sibling's name (Toxtricity-Low-Key under "Toxtricity") and the table lacks takes
  the sibling's sets its own setup accepts (counted: species.from_dex_sibling).
- A species is its buckets mixed by their Smogon weights (a bucket Smogon does not name keeps its registry share: a
  species Smogon does not name is the registry's alone, counted). Its MAX_SETS heaviest sets become RESOLUTION whole
  draws by largest remainders; a set below one draw is dropped (counted).
"""
import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import smogon_spreads as ss

TABLE_PATH = Path(__file__).resolve().parents[2] / "data" / "belief" / f"smogon-sets-regmc-{ss.MONTH}.json"
TABLE_SHA256 = "42f24df8b61495d0234b929de96c0ea4e2f4e3d8b3237e90a1416e615c5208c0"
REGISTRY = Path(__file__).resolve().parents[2] / "data" / "teams"
MIN_SETS = 4
UNCOVERED_MAX = 0.25  # a bucket whose support leaves more of Smogon's item, ability or move mass uncovered is thin too
SYNTH_SETS = 32
SYNTH_ATTEMPTS = 16
PRIOR_WEIGHT = 20.0
RAKE_SWEEPS = 30
MAX_SETS = 128
RESOLUTION = 10000
CHOICE_ITEMS = ("choiceband", "choicescarf", "choicespecs")
CHOICE_EXCLUDED = ("protect", "detect")
EPSILON = 1e-9


def _id(name):
    return "".join(c for c in name.lower() if c.isalnum())


def _word(*parts):
    """A deterministic 64-bit word of its parts (SHA-256), as the set belief's words."""
    text = "|".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little")


def _pick(word, weights):
    """The index floor(word * total / 2^64) points at in the cumulative weights (whole-number weights)."""
    total = sum(weights)
    x = (word * total) >> 64
    for i, w in enumerate(weights):
        if x < w:
            return i
        x -= w
    raise ValueError("no weight to pick from")


class Names:
    """The engine's names of a POOL context: canonical(table, name) -> its row's name, or None for a name it lacks."""

    def __init__(self, ctx):
        self.ctx = ctx
        self._cache = {}

    def canonical(self, table, name):
        import duoforge
        from duoforge import data
        key = (table, _id(name))
        if key not in self._cache:
            try:
                row = data.find(self.ctx, table, key[1])
                self._cache[key] = data.name(self.ctx, table, row)
            except duoforge.DuoforgeError as err:
                if err.status_name != "DUOFORGE_E_INVALID_ARGUMENT":
                    raise
                self._cache[key] = None
        return self._cache[key]

    def species(self, name):
        """(the sheet's species name, the bucket name) of a species or forme name, or None: a Mega forme's sheet names
        its base species with the stone."""
        from duoforge import data
        canonical = self.canonical(data.TABLE_SPECIES, name)
        if canonical is None:
            return None
        info = data.forme_info(self.ctx, data.find(self.ctx, data.TABLE_SPECIES, canonical))
        if int(info["is_mega"]):
            return data.name(self.ctx, data.TABLE_SPECIES, int(info["base_species"])), canonical
        return canonical, canonical

    def megas(self, species):
        """[(stone, Mega forme)] of a species (engine names)."""
        from duoforge import data
        sid = data.find(self.ctx, data.TABLE_SPECIES, species)
        out = []
        for k in range(data.mega_count(self.ctx, sid)):
            mega = data.mega_at(self.ctx, sid, k)
            out.append((data.name(self.ctx, data.TABLE_ITEM, int(mega["stone"])),
                        data.name(self.ctx, data.TABLE_SPECIES, int(mega["mega_species"]))))
        return out

    def mega_bucket(self, species, item):
        """The Mega forme's name a set of `species` holding `item` (engine names) is in, or None."""
        return next((forme for stone, forme in self.megas(species) if item and stone == item), None)

    def dex(self, species):
        from duoforge import data
        return int(data.forme_info(self.ctx, data.find(self.ctx, data.TABLE_SPECIES, species))["dex_num"])

    def setup_formes(self):
        """The names of every species of the context a member may be (setup-legal: a base forme, not a Mega)."""
        from duoforge import data
        out = []
        for sid in range(data.count(self.ctx, data.TABLE_SPECIES)):
            if int(data.forme_info(self.ctx, sid)["setup_legal"]):
                out.append(data.name(self.ctx, data.TABLE_SPECIES, sid))
        return out

    def legal_abilities(self, species):
        from duoforge import data
        info = data.forme_info(self.ctx, data.find(self.ctx, data.TABLE_SPECIES, species))
        return [data.name(self.ctx, data.TABLE_ABILITY, int(a)) for a in info["abilities"][:int(info["ability_count"])]]


def legal(live_data, species, s):
    """Whether the engine's setup accepts set s = (item, ability, nature, moves) of species (duoforge_live.data's
    setup_issue under a gender the species may have)."""
    from duoforge_live import teams
    from duoforge_live.data import trace_to_c
    rule = live_data.tables["GENDER_RULE"][live_data.forme(species)]
    gender = {trace_to_c.GENDER["F"]: "F", trace_to_c.GENDERLESS: ""}.get(rule, "M")
    item, ability, nature, moves = s
    text = teams.to_text([{"species": species, "item": item, "ability": ability, "nature": nature, "moves": list(moves),
                           "evs": [0] * 6, "gender": gender, "level": 50}])
    try:
        member = live_data.team(text)[0]
    except (KeyError, ValueError, trace_to_c.ConversionError):
        return False
    return live_data.setup_issue(member) is None


def registry_sets(root, names, live_data):
    """({species: {bucket: Counter({set: teams})}}, counts) of every registry team: a set once per team that has it."""
    from duoforge import data
    from duoforge_replay.prior import parse_paste
    index = json.loads((Path(root) / "index.json").read_text(encoding="utf-8"))
    out = defaultdict(lambda: defaultdict(Counter))
    counts = Counter()
    for entry in index["teams"]:
        seen = set()
        for species, item, ability, nature, moves, _ in parse_paste((Path(root) / f"{entry['id']}.txt").read_text(
                encoding="utf-8")):
            counts["registry.members"] += 1
            named = names.species(species)
            parts = [names.canonical(data.TABLE_ITEM, item) if item else "",
                     names.canonical(data.TABLE_ABILITY, ability), names.canonical(data.TABLE_NATURE, nature)]
            move_names = [names.canonical(data.TABLE_MOVE, m) for m in moves]
            if named is None or None in parts or None in move_names or (named[0] != named[1]):
                counts["registry.refused.name"] += 1
                continue
            s = (parts[0], parts[1], parts[2], tuple(sorted(move_names)))
            if not legal(live_data, named[0], s):
                counts["registry.refused.setup"] += 1
                continue
            if (named[0], s) in seen:
                continue
            seen.add((named[0], s))
            bucket = names.mega_bucket(named[0], s[0]) or named[0]
            out[named[0]][bucket][s] += 1
        counts["registry.teams"] += 1
    return out, counts


def marginals(sources, names):
    """({bucket: {"cutoff", "weight", "species", "item", "ability", "nature", "move"}}, counts): each Smogon name's
    marginals at its cutoff (smogon_spreads' rule), keyed by the engine's name of the forme; a name the engine does not
    know is counted (outside_context)."""
    from duoforge import data
    by_cutoff, counts = {}, Counter()
    for (fmt, cutoff), stats in sources.items():
        if fmt not in ss.FORMATS or cutoff not in ss.CUTOFFS:
            raise ValueError(f"an unknown source {fmt}-{cutoff}")
        for raw_name, entry in stats["data"].items():
            named = names.species(raw_name)
            if named is None:
                counts["smogon.outside_context"] += 1
                continue
            m = by_cutoff.setdefault(cutoff, {}).setdefault(named[1], {
                "species": named[0], "weight": 0.0, "item": Counter(), "ability": Counter(), "nature": Counter(),
                "move": Counter()})
            weight = float(sum(entry["Abilities"].values()))
            m["weight"] += weight
            for kind, table, key in (("item", data.TABLE_ITEM, "Items"), ("ability", data.TABLE_ABILITY, "Abilities")):
                for name, w in entry[key].items():
                    if kind == "item" and name == "nothing":
                        m[kind][""] += float(w)
                        continue
                    canonical = names.canonical(table, name)
                    if canonical is None:
                        counts[f"smogon.unknown_{kind}"] += 1
                        continue
                    m[kind][canonical] += float(w)
            for text, w in entry["Spreads"].items():
                nature = names.canonical(data.TABLE_NATURE, text.partition(":")[0])
                if nature is None:
                    counts["smogon.unknown_nature"] += 1
                    continue
                m["nature"][nature] += float(w)
            for name, w in entry["Moves"].items():
                if name == "":
                    continue  # an empty slot: no move
                canonical = names.canonical(data.TABLE_MOVE, name)
                if canonical is None:
                    counts["smogon.unknown_move"] += 1
                    continue
                m["move"][canonical] += float(w)
    chosen = {}
    for bucket in sorted({b for per in by_cutoff.values() for b in per}):
        present = [c for c in ss.CUTOFFS if c in by_cutoff and by_cutoff[c].get(bucket, {}).get("weight", 0) > 0]
        if not present:
            counts["smogon.weightless"] += 1
            continue
        heavy = [c for c in present if by_cutoff[c][bucket]["weight"] >= ss.MIN_WEIGHT]
        cutoff = heavy[0] if heavy else present[-1]
        m = dict(by_cutoff[cutoff][bucket])
        m["cutoff"] = cutoff
        chosen[bucket] = m
    return chosen, counts


def _shares(counter):
    total = sum(counter.values())
    return {k: v / total for k, v in counter.items()} if total > 0 else {}


def targets(marginal, support, counts, mega):
    """The raking targets of a bucket: for item, ability (not for a Mega bucket), nature, each category of the support
    blended (PRIOR_WEIGHT) with the support's own share; for each support move its share of sets, blended. Also the
    Smogon mass the support does not cover, per kind."""
    total = sum(counts)
    own = {kind: Counter() for kind in ("item", "ability", "nature", "move")}
    for s, c in zip(support, counts):
        for kind, value in zip(("item", "ability", "nature"), s[:3]):
            own[kind][value] += c / total
        for move in s[3]:
            own["move"][move] += c / total
    w = marginal["weight"]
    out, uncovered = {}, {}
    for kind in ("item", "ability", "nature"):
        if kind == "ability" and mega:
            continue
        smogon = _shares(marginal[kind])
        uncovered[kind] = sum(p for k, p in smogon.items() if k not in own[kind])
        covered = sum(p for k, p in smogon.items() if k in own[kind])
        out[kind] = {k: (w * (smogon.get(k, 0.0) / covered if covered > 0 else 0.0) + PRIOR_WEIGHT * own[kind][k])
                     / (w + PRIOR_WEIGHT) for k in own[kind]}
    slots = sum(marginal["move"].values())
    if slots > 0:
        sets = slots / 4.0
        smogon = {k: min(1.0, v / sets) for k, v in marginal["move"].items()}
        uncovered["move"] = sum(v for k, v in marginal["move"].items() if k not in own["move"]) / slots
    else:
        smogon = {}
        uncovered["move"] = 0.0
    out["move"] = {k: (w * smogon.get(k, 0.0) + PRIOR_WEIGHT * own["move"][k]) / (w + PRIOR_WEIGHT) for k in own["move"]}
    return out, uncovered


def rake(support, counts, goal):
    """The raked weights (summing to 1) of the support sets from their counts toward the goal shares (targets)."""
    total = float(sum(counts))
    w = [c / total for c in counts]
    for _ in range(RAKE_SWEEPS):
        for kind, column in (("item", 0), ("ability", 1), ("nature", 2)):
            if kind not in goal:
                continue
            current = Counter()
            for s, x in zip(support, w):
                current[s[column]] += x
            w = [x * goal[kind][s[column]] / current[s[column]] if current[s[column]] > EPSILON else x
                 for s, x in zip(support, w)]
        for move, t in sorted(goal["move"].items()):
            t = min(max(t, EPSILON), 1.0 - EPSILON)
            inside = sum(x for s, x in zip(support, w) if move in s[3])
            if inside <= EPSILON or inside >= 1.0 - EPSILON:
                continue
            w = [x * (t / inside if move in s[3] else (1.0 - t) / (1.0 - inside)) for s, x in zip(support, w)]
    total = sum(w)
    return [x / total for x in w]


def residual(support, weights, goal):
    """The largest gap between a goal share and the raked share."""
    gap = 0.0
    for kind, column in (("item", 0), ("ability", 1), ("nature", 2)):
        if kind not in goal:
            continue
        current = Counter()
        for s, x in zip(support, weights):
            current[s[column]] += x
        gap = max([gap] + [abs(current[k] - t) for k, t in goal[kind].items()])
    for move, t in goal["move"].items():
        gap = max(gap, abs(sum(x for s, x in zip(support, weights) if move in s[3]) - t))
    return gap


def synthesize(bucket, marginal, base_marginal, names, live_data, species, mega_stone):
    """SYNTH_SETS sets drawn from a bucket's marginals under the consistency rules (module docstring), and the counts."""
    counts = Counter()
    items = sorted(marginal["item"].items())
    natures = sorted(marginal["nature"].items())
    moves = sorted(marginal["move"].items())
    if mega_stone is not None:
        abilities = sorted((base_marginal or {}).get("ability", {}).items())
        if not abilities:
            abilities = [(a, 1.0) for a in names.legal_abilities(species)]
            counts["synth.ability_from_engine"] += 1
        else:
            counts["synth.ability_from_base"] += 1
    else:
        abilities = sorted(marginal["ability"].items())
    if not natures or len(moves) < 4 or not abilities or (mega_stone is None and not items):
        counts["synth.refused.marginals"] += 1  # too little the engine knows to draw a whole set from (Ditto: one move)
        return [], counts

    def scaled(pairs):
        return [max(1, int(round(w * 1000))) for _, w in pairs]
    out = []
    for k in range(SYNTH_SETS):
        for attempt in range(SYNTH_ATTEMPTS):
            word = lambda part: _word("smogon-sets", bucket, k, attempt, part)  # noqa: E731
            item = mega_stone if mega_stone is not None else items[_pick(word("item"), scaled(items))][0]
            ability = abilities[_pick(word("ability"), scaled(abilities))][0]
            nature = natures[_pick(word("nature"), scaled(natures))][0]
            pool = [(m, w) for m, w in moves if not (_id(item) in CHOICE_ITEMS and m in CHOICE_EXCLUDED)]
            chosen = []
            for slot in range(4):
                if not pool:
                    break
                i = _pick(word(f"move{slot}"), scaled(pool))
                chosen.append(pool.pop(i)[0])
            if len(chosen) < 4:
                counts["synth.redrawn.moves"] += 1
                continue
            s = (item, ability, nature, tuple(sorted(chosen)))
            if not legal(live_data, species, s):
                counts["synth.redrawn.setup"] += 1
                continue
            out.append(s)
            break
        else:
            counts["synth.refused.setup"] += 1
    return out, counts


def build(sources, live_data, names, registry_root=REGISTRY):
    """The derived table (a dict) of the pinned sources and the registry."""
    sets, counts = registry_sets(registry_root, names, live_data)
    chosen, mcounts = marginals(sources, names)
    counts.update(mcounts)
    species_buckets = defaultdict(set)
    for bucket, m in chosen.items():
        species_buckets[m["species"]].add(bucket)
    for species, buckets in sets.items():
        species_buckets[species].update(buckets)
    uncovered_sum, residual_max = Counter(), 0.0
    table = {}
    for species in sorted(species_buckets):
        mixture = {}
        for bucket in sorted(species_buckets[species]):
            support_counts = sets.get(species, {}).get(bucket, Counter())
            marginal = chosen.get(bucket)
            mega = bucket != species
            if marginal is None:
                if not support_counts:
                    continue
                counts["buckets.registry_only"] += 1
                support = sorted(support_counts)
                weights = rake(support, [support_counts[s] for s in support], {"move": {}})
                share = float(sum(support_counts.values()))
                mixture[bucket] = (share, support, weights, None)
                continue
            support = sorted(support_counts)
            base_counts = [support_counts[s] for s in support]
            thin = len(support) < MIN_SETS
            if not thin:
                _, uncovered = targets(marginal, support, base_counts, mega)
                thin = max(uncovered.get(k, 0.0) for k in ("item", "ability", "move")) > UNCOVERED_MAX
                if thin:
                    counts["buckets.synthesized.uncovered"] += 1
            if thin:
                stone = next((st for st, forme in names.megas(species) if forme == bucket), None) if mega else None
                drawn, scounts = synthesize(bucket, marginal, chosen.get(species), names, live_data, species, stone)
                counts.update(scounts)
                counts["buckets.synthesized"] += 1
                extra = [s for s in drawn if s not in support_counts]
                support = sorted(set(support) | set(extra))
                base_counts = [support_counts.get(s, 0) + drawn.count(s) for s in support]
                if not support:
                    counts["buckets.empty"] += 1
                    continue
            else:
                counts["buckets.raked"] += 1
            goal, uncovered = targets(marginal, support, base_counts, mega)
            if mega:
                counts["buckets.mega_no_ability"] += 1
            weights = rake(support, base_counts, goal)
            residual_max = max(residual_max, residual(support, weights, goal))
            for kind, v in uncovered.items():
                uncovered_sum[kind] += v * marginal["weight"]
            mixture[bucket] = (marginal["weight"], support, weights, marginal["cutoff"])
        if not mixture:
            continue
        if all(m[3] is None for m in mixture.values()):
            counts["species.registry_only"] += 1
        total = sum(m[0] for m in mixture.values())
        probs = Counter()
        for share, support, weights, _ in mixture.values():
            for s, x in zip(support, weights):
                probs[s] += share / total * x
        table[species] = _quantize(probs, counts)
        table[species]["cutoffs"] = {b: m[3] for b, m in sorted(mixture.items()) if m[3] is not None}
    _dex_siblings(table, names, live_data, counts)
    weight_all = sum(m["weight"] for m in chosen.values())
    derivation = {"min_sets": MIN_SETS, "uncovered_max": UNCOVERED_MAX, "synth_sets": SYNTH_SETS, "prior_weight": PRIOR_WEIGHT, "rake_sweeps": RAKE_SWEEPS,
                  "max_sets": MAX_SETS, "resolution": RESOLUTION, "choice_excluded": list(CHOICE_EXCLUDED),
                  "residual_max": round(residual_max, 4),
                  "uncovered_share": {k: round(v / weight_all, 4) for k, v in sorted(uncovered_sum.items())} if weight_all else {},
                  "species": len(table), **{k: v for k, v in sorted(counts.items())}}
    battles = {f"{fmt}-{cutoff}": int(stats["info"]["number of battles"]) for (fmt, cutoff), stats in sorted(sources.items())}
    registry_sha = hashlib.sha256((Path(registry_root) / "index.json").read_bytes()).hexdigest()
    return {"source": {"credit": ss.CREDIT, "url": ss.URL, "month": ss.MONTH, "formats": list(ss.FORMATS),
                       "cutoffs": list(ss.CUTOFFS), "fetched": ss.FETCHED, "files": dict(ss.SOURCES), "battles": battles,
                       "registry_index_sha256": registry_sha},
            "derivation": derivation, "species": table}


def _dex_siblings(table, names, live_data, counts):
    """Formes Smogon counts under a sibling's name (Toxtricity-Low-Key under "Toxtricity", Squawkabilly-White under
    "Squawkabilly"): every setup-legal species the table lacks takes the sets of the table's species with its dex number
    that its own setup accepts, with their draws (counted: species.from_dex_sibling)."""
    by_dex = defaultdict(list)
    for species in table:
        by_dex[names.dex(species)].append(species)
    for forme in names.setup_formes():
        siblings = sorted(by_dex.get(names.dex(forme), ())) if forme not in table else []
        probs = Counter()
        for sibling in siblings:
            for item, ability, nature, moves, n in table[sibling]["sets"]:
                s = (item, ability, nature, tuple(moves))
                if legal(live_data, forme, s):
                    probs[s] += n
        if probs:
            table[forme] = _quantize(probs, counts)
            table[forme]["cutoffs"] = {}
            table[forme]["from"] = siblings
            counts["species.from_dex_sibling"] += 1


def _quantize(probs, counts):
    """A species' MAX_SETS heaviest sets as RESOLUTION whole draws by largest remainders, heaviest first."""
    items = sorted(probs.items(), key=lambda kv: (-kv[1], kv[0]))
    counts["sets.beyond_max_sets"] += max(0, len(items) - MAX_SETS)
    items = items[:MAX_SETS]
    total = sum(p for _, p in items)
    exact = [RESOLUTION * p / total for _, p in items]
    draws = [int(math.floor(x)) for x in exact]
    for i in sorted(range(len(items)), key=lambda i: (-(exact[i] - draws[i]), i))[:RESOLUTION - sum(draws)]:
        draws[i] += 1
    counts["sets.below_resolution"] += sum(1 for n in draws if not n)
    return {"sets": [[s[0], s[1], s[2], list(s[3]), n] for (s, _), n in zip(items, draws) if n]}


def render(table):
    """The one text of a derived table: a species per line (compact, diffable)."""
    lines = ["{", f' "source": {json.dumps(table["source"], sort_keys=True)},',
             f' "derivation": {json.dumps(table["derivation"], sort_keys=True)},', ' "species": {']
    names = sorted(table["species"])
    for i, name in enumerate(names):
        tail = "," if i + 1 < len(names) else ""
        lines.append(f"  {json.dumps(name)}: {json.dumps(table['species'][name], separators=(',', ':'), sort_keys=True)}{tail}")
    lines += [" }", "}", ""]
    return "\n".join(lines)


def load_table(path=TABLE_PATH, sha256=None):
    """The committed derived table; with sha256, its file must have that digest (else ValueError)."""
    raw = Path(path).read_bytes()
    if sha256 is not None and hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError(f"{path} is not the pinned set table ({sha256[:12]})")
    return json.loads(raw)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.smogon_sets", description=__doc__.split("\n")[0])
    p.add_argument("--stats", required=True, help="the cache of the raw Smogon stats (outside the repository)")
    p.add_argument("--fetch", action="store_true", help="download a missing pinned file once")
    p.add_argument("--check", action="store_true", help="fail unless the committed table is this build")
    p.add_argument("--out", default=str(TABLE_PATH))
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.stats)
    except ValueError:
        raise SystemExit(f"--stats {args.stats} is inside the repository: the raw stats are never committed") from None
    if args.fetch:
        ss.fetch(args.stats)
    from duoforge_live import data as live
    live_data = live.load(kind="pool")
    text = render(build(ss.load(args.stats), live_data, Names(live_data.context())))
    if args.check:
        with open(args.out, encoding="utf-8") as f:
            if f.read() != text:
                raise SystemExit(f"{args.out} is not the table these stats give: regenerate it")
        print(f"{args.out}: matches")
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{args.out}: {hashlib.sha256(text.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
