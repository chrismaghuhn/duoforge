"""The VGC sets of Smogon's Champions dex as facts (issue #458): set names, items, abilities, moves, stat points, natures.

    python -m duoforge_search.smogon_dex --cache DIR [--fetch SLUGS] [--check] [--out PATH]

Source: Smogon's dex (https://www.smogon.com/dex/champions/), one page per species; each page embeds its sets as JSON
(dexSettings, the "dump-pokemon" call). The pages stay in a cache outside the repository (DIR, one SLUG.html each,
--fetch downloads the slugs of a file, one request every FETCH_SECONDS). Kept are the sets of the FORMATS, of the
species and of its formes (Megas): name, species, format, items, abilities, moves (per slot, its alternatives), stat
points (Champions' 0..32 per stat) and natures. The analysis text (descriptions, overviews, comments) is never read
into the table: it is Smogon's writing, and only facts are committed, with credits (owner, #458).
--check reproduces the committed table (TABLE_PATH) byte for byte from the cache.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

TABLE_PATH = Path(__file__).resolve().parents[2] / "data/book/smogon-dex-vgc-2026-10.json"
URL = "https://www.smogon.com/dex/champions/pokemon/{}/"
FORMATS = ("VGC26 Regulation M-A", "VGC26 Regulation M-B")
STATS = ("hp", "atk", "def", "spa", "spd", "spe")
FETCH_SECONDS = 3.0
CREDIT = ("Derived from Smogon's Champions dex (https://www.smogon.com/dex/champions/), with thanks to Smogon and its "
          "VGC analysis writers. Facts only (set names, items, abilities, moves, stat points, natures); the analyses "
          "themselves are not copied.")
_SETTINGS = re.compile(r"dexSettings = (\{.*?\})\s*</script>", re.S)


def page_sets(text, slug):
    """The kept sets of one cached page, in the page's order: the species' own strategies, then each forme's."""
    m = _SETTINGS.search(text)
    if m is None:
        raise ValueError(f"{slug}: no dexSettings on the page")
    calls = json.loads(m.group(1))["injectRpcs"]
    dumps = [value for key, value in calls if json.loads(key)[0] == "dump-pokemon"]
    if len(dumps) != 1:
        raise ValueError(f"{slug}: {len(dumps)} dump-pokemon calls on the page, expected 1")
    dump = dumps[0]
    groups = [(None, dump.get("strategies", []))]
    groups += [(f["formeName"], f.get("strategies", [])) for f in dump.get("formeStrategies") or []]
    out = []
    for forme, strategies in groups:
        for strategy in strategies:
            if strategy["format"] not in FORMATS:
                continue
            for ms in strategy["movesets"]:
                out.append({"slug": slug, "forme": forme, "species": ms["pokemon"], "format": strategy["format"],
                            "name": ms["name"], "items": list(ms["items"]), "abilities": list(ms["abilities"]),
                            "moves": [[x["move"] for x in slot] for slot in ms["moveslots"]],
                            "natures": list(ms["natures"]),
                            "stat_points": [[int(c[s]) for s in STATS] for c in ms["evconfigs"]]})
    return out


def build(cache):
    """The table of every SLUG.html in the cache, slugs sorted: {"source", "credits", "slugs", "sets"}."""
    slugs = sorted(p.stem for p in Path(cache).glob("*.html"))
    if not slugs:
        raise SystemExit(f"{cache} holds no cached page (--fetch SLUGS downloads them)")
    sets = []
    for slug in slugs:
        sets += page_sets((Path(cache) / f"{slug}.html").read_text(encoding="utf-8"), slug)
    return {"source": {"url": "https://www.smogon.com/dex/champions/", "formats": list(FORMATS)},
            "credits": CREDIT, "slugs": slugs, "sets": sets}


def render(table):
    """The committed text: one set per line, so a refresh's diff names the sets that changed."""
    head = {k: v for k, v in table.items() if k != "sets"}
    lines = [json.dumps(s, ensure_ascii=False, separators=(",", ":")) for s in table["sets"]]
    body = json.dumps(head, ensure_ascii=False, indent=1)[:-2]
    return body + ',\n "sets": [\n  ' + ",\n  ".join(lines) + "\n ]\n}\n"


def fetch(cache, slugs_file):
    """Downloads the page of every slug in slugs_file (one per line) that the cache lacks, FETCH_SECONDS apart."""
    os.makedirs(cache, exist_ok=True)
    with open(slugs_file, encoding="utf-8") as f:
        slugs = [line.strip() for line in f if line.strip()]
    for slug in slugs:
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            raise SystemExit(f"{slugs_file}: {slug!r} is no dex slug")
        path = Path(cache) / f"{slug}.html"
        if path.exists() and path.stat().st_size:
            continue
        request = urllib.request.Request(URL.format(slug), headers={"User-Agent": "duoforge-research"})
        with urllib.request.urlopen(request, timeout=30) as response:
            path.write_bytes(response.read())
        time.sleep(FETCH_SECONDS)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.smogon_dex", description=__doc__.split("\n")[0])
    p.add_argument("--cache", required=True, help="the cached pages (outside the repository)")
    p.add_argument("--fetch", metavar="SLUGS", help="download the pages of these slugs (one per line) first")
    p.add_argument("--check", action="store_true", help="the committed table must be what the cache gives")
    p.add_argument("--out", default=str(TABLE_PATH))
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.cache)
    except ValueError:
        raise SystemExit(f"--cache {args.cache} is inside the repository: the pages are never committed") from None
    if args.fetch:
        fetch(args.cache, args.fetch)
    text = render(build(args.cache))
    if args.check:
        with open(args.out, encoding="utf-8") as f:
            if f.read() != text:
                raise SystemExit(f"{args.out} is not the table this cache gives: regenerate it")
        print(f"{args.out}: reproduced")
        return 0
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{args.out}: {text.count(chr(10))} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
