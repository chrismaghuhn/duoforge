"""Restructure step 11: split the entries of decision 0015 into docs/mechanics/<area>/<id>-<slug>.md.

    git show <sha>:docs/decisions/0015-content-expansion-pool.md > OLD.md
    git show <sha>:docs/support/README.md > OLD_README.md
    python3 tools/restructure/split_0015.py OLD.md OLD_README.md <repo root>

Pure move: every entry keeps its text byte for byte (its first line still starts with "<id>. "); a mechanic file is a
fixed header (anchor, heading, Area / Step / Tests lines), the entry text, and the entry's support README lines under
"## Support". Decision 0015 keeps everything that is not an entry, in its order, and gets the redirect table (section
4.3) where the entries were. split_0015_check.py proves both directions. One-off: new entries are written as mechanic
files directly (docs/mechanics/TEMPLATE.md).
"""
import re
import sys
from pathlib import Path

ENTRY = re.compile(r"^(5[a-z]{1,2})\. \*\*")
END = re.compile(r"^(#|[0-9]+\. |Lane A batch 8 \(integrator H32)")
TEST = re.compile(r"\bduoforge\.[a-z_]+\.[a-z0-9_]+\b")
STEP = re.compile(r"^(G[0-9]+[a-z]?(?:-[A-Z](?:/[A-Z])?)?|[ACIK][0-9]+[a-z]?)\b")
DUP_5DL = "5dl-556"  # the Illusion entry of issue 556; K4 Gravity keeps 5dl (HS, 2026-10-23)

AREA = {
    "field": "5d 5i 5l 5ab 5aj 5bf 5dl",
    "forms": "5j 5n 5p 5q 5y 5ag 5ak 5am 5bc 5bj 5bh 5cb 5aq 5be 5dl-556 5dm 5du 5dw 5dd",
    "items": "5ao 5cw 5dk",
    "abilities": "5g 5bb 5s 5z 5ah 5ba 5bk 5bp 5br 5bl 5bm 5bo 5bt 5bs 5bq 5bn 5bv 5bi 5bg 5bd 5dq 5dy 5di",
    "flow": "5o 5cj 5df 5dg 5do 5dt",
    "mechanics": "5x 5cv",
    "moves": "5a 5b 5c 5e 5f 5h 5k 5m 5r 5t 5u 5v 5w 5aa 5ac 5ad 5ae 5af 5ai 5al 5an 5ap 5ar 5as 5at 5au 5aw 5az 5ax "
             "5av 5ca 5cc 5ay 5cd 5ce 5cf 5ch 5cs 5ct 5cy 5cg 5cu 5co 5cp 5cx 5db 5da 5dc 5de 5dh 5dj 5dn 5dp 5dr "
             "5ds 5dv 5dx",
}
AREA_OF = {i: a for a, ids in AREA.items() for i in ids.split()}

# The support README lines (1-based line numbers of the README at the split's base) that one entry owns.
SUPPORT = {41: "5bc", 43: "5as", 44: "5bb", 45: "5bi", 46: "5bm", 47: "5ao", 48: "5bh", 49: "5br", 50: "5bf",
           51: "5aw", 52: "5an", 55: "5bd", 57: "5al", 58: "5be", 61: "5ba", 62: "5bg", 63: "5bj", 64: "5bk",
           66: "5bp", 68: "5bo", 70: "5bl", 72: "5bt", 73: "5bs", 75: "5bq", 77: "5bn", 79: "5al", 81: "5av",
           83: "5at"}
DUPLICATE_README_LINES = {79}  # the exact copy of line 57 (G48)

# Ids cited in the repository that never got an entry in 0015: where their record is.
NO_ENTRY = {
    "5ck": "G82 Healing Wish: [decision 0045](0045-healing-wish.md)",
    "5cl": "turn-history moves: [decision 0046](0046-turn-history-moves.md)",
    "5cm": "G84 Leech Seed and Curse: [decision 0047](0047-leech-seed-curse.md)",
    "5cn": "G86 power moves: [decision 0048](0048-power-moves.md)",
    "5cq": "batch 6 Charge Beam and Wild Charge: the comments of `src/data/support_manifest.c` and "
           "`tests/data/test_pool_tables.c`",
    "5cr": "C3 multi-hit moves: `docs/research/expansion/champions-100.md`",
    "5cz": "G96 Psychic Terrain: [decision 0065](0065-psychic-terrain.md)",
}


def id_key(i):
    base = i.split("-")[0]
    return (len(base), base, i)


SLUG = {"5az": "haze-after-you-quash", "5co": "cheap-moves-c1", "5cp": "cheap-moves-c2", "5ct": "cheap-moves-c4",
        "5cy": "surf-endeavor", "5dr": "a0-data-only-marks-parts-2-3", "5ds": "a0-data-only-marks-parts-1-4",
        "5dy": "a2a-fourteen-abilities", "5au": "trymove-order-audit", "5aw": "outrage-lockedmove",
        "5ao": "muscle-band-wise-glasses-bright-powder"}


def slug(i, title):
    if i in SLUG:
        return SLUG[i]
    t = re.sub(r"\s*\(.*", "", STEP.sub("", title)).lstrip(" ,:")
    words = re.findall(r"[a-z0-9]+", t.lower().replace("'", ""))
    drop = {"the", "a", "an", "and", "of", "s"}
    words = [w for w in words if w not in drop][:5]
    return "-".join(words) or "entry"


def registered(root):
    """CTest names registered by name in the CMake files, and the C test file basename -> its CTest name."""
    names, by_file = set(), {}
    for f in list(root.glob("tests/**/*.cmake")) + list(root.glob("tools/**/*.cmake")) + \
            list(root.glob("tests/CMakeLists.txt")) + list(root.glob("tools/**/CMakeLists.txt")):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"NAME\s+(duoforge\.[A-Za-z0-9_.]+)(?:\s+SOURCES\s+([^\s)]+))?", text):
            names.add(m.group(1))
            if m.group(2):
                by_file[Path(m.group(2)).name] = m.group(1)
    return names, by_file


def split(old, readme, root):
    lines = old.splitlines(keepends=True)
    rd = readme.splitlines(keepends=True)
    names, by_file = registered(root)
    entries, keep, cur = [], [], None
    for n, line in enumerate(lines):
        m = ENTRY.match(line)
        if m:
            cur = {"id": m.group(1), "line": n + 1, "text": [line]}
            entries.append(cur)
            keep.append(("ENTRY", cur))
        elif cur is not None and not END.match(line):
            cur["text"].append(line)
        else:
            cur = None
            keep.append(line)
    seen = set()
    for e in entries:
        if e["id"] == "5dl" and "issue 556" in e["text"][0]:
            e["id"] = DUP_5DL
        assert e["id"] not in seen, e["id"]
        seen.add(e["id"])
        # trailing blank lines stay in 0015's flow, not in the entry
        while e["text"] and not e["text"][-1].strip():
            keep_blank = e["text"].pop()
            e.setdefault("trail", []).insert(0, keep_blank)
        e["title"] = re.match(r"^5[a-z]+\. \*\*(.*?)\*\*", e["text"][0]).group(1)
        e["area"] = AREA_OF.get(e["id"], "UNMAPPED")
        e["file"] = "%s/%s-%s.md" % (e["area"], e["id"], slug(e["id"], e["title"]))
        e["step"] = (STEP.match(e["title"]).group(1) if STEP.match(e["title"]) else "")
        tests = []
        text = "".join(e["text"])
        cited = [(m.start(), m.group(0)) for m in TEST.finditer(text) if m.group(0) in names]
        cited += [(m.start(), by_file[m.group(1)]) for m in re.finditer(r"\b(test_[a-z0-9_]+\.c)\b", text)
                  if m.group(1) in by_file]
        for _, t in sorted(cited):
            if t not in tests:
                tests.append(t)
        e["tests"] = tests
        e["support"] = [rd[k - 1] for k in sorted(SUPPORT) if SUPPORT[k] == e["id"] and k not in DUPLICATE_README_LINES]
    assert set(AREA_OF) == seen, sorted(set(AREA_OF) ^ seen)
    return entries, keep


def mechanic_file(e):
    head = ['<a id="%s"></a>\n' % e["id"], "\n", "# %s. %s\n" % (e["id"], e["title"]), "\n",
            "- Area: %s\n" % e["area"], "- Step: %s\n" % (e["step"] or "-"),
            "- Tests: %s\n" % (", ".join(e["tests"]) or "-"), "\n"]
    if e["id"] == DUP_5DL:
        head.insert(4, "The id 5dl was given twice in decision 0015: to this entry (issue 556) and to K4 Gravity "
                       "(issue 475). Gravity keeps the anchor 5dl, which every code citation means; this entry's "
                       "anchor is 5dl-556.\n\n")
    body = list(e["text"])
    if not body[-1].endswith("\n"):
        body[-1] += "\n"
    out = head + body
    if e["support"]:
        out += ["\n", "## Support\n", "\n"]
        for k, s in enumerate(e["support"]):
            out += ([] if k == 0 else ["\n"]) + [s]
    return "".join(out)


def redirect_table(entries):
    rows = ["### 4.3 The entries: moved to docs/mechanics (restructure step 11)\n", "\n",
            "The entries 5a to 5dy of this section were split into one file per entry under `docs/mechanics/<area>/` "
            "(restructure step 11). Each keeps its text and its frozen id as the anchor; this table is frozen and "
            "maps every old id to its file. New entries are written as mechanic files only "
            "([docs/mechanics/README.md](../mechanics/README.md)); they get no row here. The id 5dl was given twice: "
            "K4 Gravity keeps 5dl, the Illusion entry of issue 556 is 5dl-556. Ids that were cited but never got an "
            "entry point to their record.\n", "\n",
            "| Id | Step | Entry | File |\n", "|---|---|---|---|\n"]
    allrows = [(e["id"], e) for e in entries] + [(i, None) for i in NO_ENTRY]
    for i, e in sorted(allrows, key=lambda r: id_key(r[0])):
        if e is None:
            rows.append("| %s | - | no entry in 0015 | %s |\n" % (i, NO_ENTRY[i]))
        else:
            title = e["title"].replace("|", "\\|")
            rows.append("| %s | %s | %s | [%s](../mechanics/%s#%s) |\n" % (
                i, e["step"] or "-", title, e["file"], e["file"], e["id"]))
    return rows


def new_0015(keep, entries):
    """Everything that is not an entry, in its order; blank lines that only separated entries collapse to one. The
    batch 8 note (it introduced entries that are now files) moves under the table."""
    flow, note = [], []
    for item in keep:
        if isinstance(item, tuple):
            flow.append(None)  # where an entry was
        elif item.startswith("Lane A batch 8 (integrator H32"):
            note.append(item)
        else:
            flow.append(item)
    out, placed, after_entry = [], False, False
    for item in flow:
        if item is None:
            after_entry = True
            continue
        if after_entry and not item.strip() and out and not out[-1].strip():
            continue
        if item.strip():
            after_entry = False
        if not placed and item.startswith("## 5. "):
            while out and not out[-1].strip():
                out.pop()
            out += ["\n"] + redirect_table(entries) + ["\n"] + (note + ["\n"] if note else [])
            placed = True
        out.append(item)
    while out and not out[-1].strip():
        out.pop()
    assert placed
    return "".join(out)


def readme_template(readme):
    """The old README without the lines that mechanic files own, with the generator's three placeholders: the table
    rows go after the last foundation row (old line 42), the paragraphs after the first long G37 paragraph (old line
    54), the manifest section before the licensing facts."""
    out = []
    for n, line in enumerate(readme.splitlines(), 1):
        if n == 43:
            out.append("<!-- mechanic table rows -->")
        if n == 55:
            out += ["", "<!-- mechanic paragraphs -->", ""]
        if line == "## Licensing facts":
            out += ["<!-- support manifest -->", ""]
        if n in SUPPORT or n in DUPLICATE_README_LINES:
            continue
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def main():
    old = Path(sys.argv[1]).read_text(encoding="utf-8")
    readme = Path(sys.argv[2]).read_text(encoding="utf-8")
    root = Path(sys.argv[3])
    entries, keep = split(old, readme, root)
    for e in entries:
        p = root / "docs" / "mechanics" / e["file"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(mechanic_file(e), encoding="utf-8", newline="\n")
        print("%s\t0015:%d\t%s" % (e["id"], e["line"], e["file"]))
    (root / "docs" / "support" / "README.template.md").write_text(readme_template(readme), encoding="utf-8",
                                                                   newline="\n")
    (root / "docs" / "decisions" / "0015-content-expansion-pool.md").write_text(
        new_0015(keep, entries), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
