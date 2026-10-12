"""The live belief's spreads from Smogon's usage statistics (owner 2026-10-12).

    python -m duoforge_search.smogon_spreads --stats DIR [--fetch] [--check]

Source: Smogon's usage statistics (https://www.smogon.com/stats), the "chaos" JSON of Reg M-C (Bo1 and Bo3) for MONTH at
the rating cutoffs CUTOFFS. With thanks to Smogon and its statistics maintainers. The raw files stay outside the
repository (a cache, DIR, pinned by SOURCES' SHA-256); only the derived table data/belief/ (TABLE_PATH) is committed,
with this credit in its header (owner 2026-10-12: derived tables may be committed with credits). --fetch downloads a
missing file once; --check regenerates the table from DIR and fails unless it is the committed one byte for byte.

Derivation:
- every spread "Nature:HP/Atk/Def/SpA/SpD/Spe" (stat points) is checked: at most 32 per stat and 66 in all; another
  spread is dropped and counted (invalid), a malformed one raises;
- a Mega forme's spreads join its base species (an open team sheet names the base species with its stone);
- per species, the highest cutoff whose two formats together weigh at least MIN_WEIGHT (Smogon's rating-weighted
  count) gives the spreads of that cutoff, both formats summed; a species too light at every cutoff takes the lowest
  cutoff's; the cutoff of every species is counted (origin);
- its MAX_SPREADS heaviest spreads are kept (the rest counted), their weights become RESOLUTION whole draws (largest
  remainders); a spread below one draw is dropped and counted.
SpreadTable rows (rows): one row per draw, team -1 (no team to leave out), item -1 (a spread states no item: the belief
draws by species and nature, levels 2 and 3).
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from .errors import SearchError

MONTH = "2026-09"
URL = f"https://www.smogon.com/stats/{MONTH}/chaos/"
FORMATS = ("gen9championsvgc2026regmc", "gen9championsvgc2026regmcbo3")
CUTOFFS = (1760, 1630, 1500, 0)
SOURCES = {
    "gen9championsvgc2026regmc-0.json": "0486ba6cc0d4b220ea959aa981260ab6feab4f4a8b8297886580968cf10cd5f3",
    "gen9championsvgc2026regmc-1500.json": "cce52663ff63878ebb0fb696ef2b1e6218ff563438c79323fb0a8d12736d8cec",
    "gen9championsvgc2026regmc-1630.json": "9c1daf8f3258b124db4b06f94fcee49e6e2308c0db9f2520896139c45791e73b",
    "gen9championsvgc2026regmc-1760.json": "923a9744a1210a9957313ee505e0735e5f0437746bd4e6e030f8b6f9113ed000",
    "gen9championsvgc2026regmcbo3-0.json": "6483d6ca2c1769ea89a8726ce5f3810cbe484cad98a2ac9abc31c26e5def36c5",
    "gen9championsvgc2026regmcbo3-1500.json": "58b6c584452f1f48abb92d407e14851d157f719248cb6bfd752bab0d542be0ad",
    "gen9championsvgc2026regmcbo3-1630.json": "aacadb753fecca51bd175c49dff9ec96dec020c18aaa3904d956a5323cd51a84",
    "gen9championsvgc2026regmcbo3-1760.json": "f944e2de85ee262f20caa75b6a7b500dc8cfe6347264c142c16c1b0829813ee7",
}
FETCHED = "2026-10-12"
CREDIT = ("Derived from Smogon's usage statistics (https://www.smogon.com/stats), with thanks to Smogon and its "
          "statistics maintainers.")
MIN_WEIGHT = 20.0
RESOLUTION = 1000
MAX_SPREADS = 32  # per species, the heaviest (a compact table: the tail of single spreads holds little weight)
MAX_STAT, MAX_TOTAL = 32, 66
TABLE_PATH = Path(__file__).resolve().parents[2] / "data" / "belief" / f"smogon-spreads-regmc-{MONTH}.json"
TABLE_SHA256 = "f20bf4cbbac2a9e763702111c34875c276058d08becdf26fa5ff4c282204f369"


def parse_spread(text):
    """(nature, stat points) of a spread "Nature:a/b/c/d/e/f", or None for stat points past MAX_STAT or MAX_TOTAL;
    ValueError for a malformed one."""
    nature, sep, rest = text.partition(":")
    parts = rest.split("/")
    if not sep or len(parts) != 6 or not all(p.isdigit() for p in parts):
        raise ValueError(f"malformed spread {text!r}")
    sp = tuple(int(p) for p in parts)
    if max(sp) > MAX_STAT or sum(sp) > MAX_TOTAL:
        return None
    return nature, sp


def _base(name):
    return name.split("-Mega")[0]


def species_spreads(sources):
    """({species: (cutoff, {(nature, stat points): weight})}, counts) of the chaos JSONs sources[(format, cutoff)]."""
    counts = Counter()
    by_cutoff = {}
    for (fmt, cutoff), stats in sources.items():
        if fmt not in FORMATS or cutoff not in CUTOFFS:
            raise ValueError(f"an unknown source {fmt}-{cutoff}")
        merged = by_cutoff.setdefault(cutoff, {})
        for name, entry in stats["data"].items():
            spreads = merged.setdefault(_base(name), Counter())
            for text, weight in entry["Spreads"].items():
                spread = parse_spread(text)
                if spread is None:
                    counts["invalid"] += 1
                    continue
                spreads[spread] += float(weight)
    megas = {name for stats in sources.values() for name in stats["data"] if _base(name) != name}
    counts["mega_merged"] = len(megas)
    chosen = {}
    for name in sorted({n for merged in by_cutoff.values() for n in merged}):
        present = [c for c in CUTOFFS if c in by_cutoff and sum(by_cutoff[c].get(name, {}).values()) > 0]
        heavy = [c for c in present if sum(by_cutoff[c][name].values()) >= MIN_WEIGHT]
        cutoff = heavy[0] if heavy else present[-1]
        chosen[name] = (cutoff, dict(by_cutoff[cutoff][name]))
    origin = Counter(str(cutoff) for cutoff, _ in chosen.values())
    out = {"invalid": counts["invalid"], "mega_merged": counts["mega_merged"],
           "origin": {str(c): origin[str(c)] for c in CUTOFFS if origin[str(c)]}}
    return chosen, out


def quantize(chosen):
    """({species: {"cutoff", "spreads": [[nature, "a/b/c/d/e/f", draws], ...]}}, {"below_resolution",
    "beyond_max_spreads"}): each species' MAX_SPREADS heaviest spreads as RESOLUTION whole draws by largest
    remainders, heaviest first."""
    derived, dropped = {}, {"below_resolution": 0, "beyond_max_spreads": 0}
    for name, (cutoff, weights) in chosen.items():
        items = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
        dropped["beyond_max_spreads"] += max(0, len(items) - MAX_SPREADS)
        items = items[:MAX_SPREADS]
        total = sum(w for _, w in items)
        exact = [RESOLUTION * w / total for _, w in items]
        draws = [int(x) for x in exact]
        for i in sorted(range(len(items)), key=lambda i: (-(exact[i] - draws[i]), i))[:RESOLUTION - sum(draws)]:
            draws[i] += 1
        spreads = [[nature, "/".join(map(str, sp)), n] for ((nature, sp), _), n in zip(items, draws) if n]
        dropped["below_resolution"] += sum(1 for n in draws if not n)
        derived[name] = {"cutoff": cutoff, "spreads": spreads}
    return derived, dropped


def rows(ctx, derived):
    """The SpreadTable columns (team, species, nature, item, stat points) of a derived table's species under the
    context, one row per draw, and the counts of species taken and outside the context's tables."""
    from duoforge import data
    import duoforge
    cols, counts = ([], [], [], [], []), Counter()
    for name, entry in derived.items():
        try:
            species = data.find(ctx, data.TABLE_SPECIES, data.to_id(name))
            natures = {n: data.find(ctx, data.TABLE_NATURE, data.to_id(n)) for n in {s[0] for s in entry["spreads"]}}
        except duoforge.DuoforgeError as err:
            if err.status_name != "DUOFORGE_E_INVALID_ARGUMENT":
                raise
            counts["outside_context"] += 1
            continue
        counts["species"] += 1
        for nature, text, draws in entry["spreads"]:
            sp = tuple(int(p) for p in text.split("/"))
            for _ in range(draws):
                for col, value in zip(cols, (-1, species, natures[nature], -1, sp)):
                    col.append(value)
    return cols, dict(counts)


def load(stats_dir):
    """{(format, cutoff): chaos JSON} of the pinned SOURCES in stats_dir; SearchError for a missing or other file."""
    out = {}
    for name, sha in SOURCES.items():
        path = Path(stats_dir) / name
        if not path.exists():
            raise SearchError(f"Smogon stats file {name} is missing from {stats_dir} (--fetch downloads it)")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise SearchError(f"Smogon stats file {name} is not the pinned one ({sha[:12]})")
        fmt, cutoff = name[:-len(".json")].rsplit("-", 1)
        out[(fmt, int(cutoff))] = json.loads(raw)
    return out


def fetch(stats_dir):
    """Downloads the SOURCES missing from stats_dir once (then load checks the pins)."""
    os.makedirs(stats_dir, exist_ok=True)
    for name in SOURCES:
        path = Path(stats_dir) / name
        if not path.exists():
            with urllib.request.urlopen(URL + name, timeout=120) as r:
                path.write_bytes(r.read())


def build(sources):
    """The derived table (a dict) of the pinned sources."""
    chosen, counts = species_spreads(sources)
    derived, dropped = quantize(chosen)
    battles = {f"{fmt}-{cutoff}": int(stats["info"]["number of battles"]) for (fmt, cutoff), stats in sorted(sources.items())}
    return {"source": {"credit": CREDIT, "url": URL, "month": MONTH, "formats": list(FORMATS), "cutoffs": list(CUTOFFS),
                       "fetched": FETCHED, "files": dict(SOURCES), "battles": battles},
            "derivation": {"min_weight": MIN_WEIGHT, "resolution": RESOLUTION, "max_spreads": MAX_SPREADS,
                           "max_stat": MAX_STAT, "max_total": MAX_TOTAL, **counts, **dropped, "species": len(derived)},
            "species": derived}


def render(table):
    """The one text of a derived table: a species per line (compact, diffable)."""
    head = {k: v for k, v in table.items() if k != "species"}
    lines = ["{", f' "source": {json.dumps(head["source"], sort_keys=True)},',
             f' "derivation": {json.dumps(head["derivation"], sort_keys=True)},', ' "species": {']
    names = sorted(table["species"])
    for i, name in enumerate(names):
        tail = "," if i + 1 < len(names) else ""
        lines.append(f"  {json.dumps(name)}: {json.dumps(table['species'][name], separators=(',', ':'))}{tail}")
    lines += [" }", "}", ""]
    return "\n".join(lines)


def load_table(path=TABLE_PATH):
    """The committed derived table."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.smogon_spreads", description=__doc__.split("\n")[0])
    p.add_argument("--stats", required=True, help="the cache of the raw Smogon stats (outside the repository)")
    p.add_argument("--fetch", action="store_true", help="download a missing pinned file once")
    p.add_argument("--check", action="store_true", help="fail unless the committed table is this build")
    p.add_argument("--out", default=str(TABLE_PATH))
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.fetch:
        fetch(args.stats)
    text = render(build(load(args.stats)))
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
