"""Restructure step 11: prove the split of decision 0015 (split_0015.py) moved text and lost none.

    git show <base>:docs/decisions/0015-content-expansion-pool.md > OLD.md
    git show <base>:docs/support/README.md > OLD_README.md
    python3 tools/restructure/split_0015_check.py OLD.md OLD_README.md <repo root>

1. Every entry of the old 0015 is the body of exactly one mechanic file, byte for byte (the file's header and its
   "## Support" section aside), and no mechanic file holds anything else.
2. The non-blank lines of the old 0015 outside the entries are the non-blank lines of the new 0015 outside its
   section 4.3, in the same order, but for the batch 8 note, which moved into section 4.3.
3. Every line that the old support README held is in the generated README, but for the one exact duplicate (removed).
Prints the counts; exits 1 on the first difference.
"""
import re
import sys
from collections import Counter
from pathlib import Path

ENTRY = re.compile(r"^(5[a-z]{1,2})\. \*\*")
END = re.compile(r"^(#|[0-9]+\. |Lane A batch 8 \(integrator H32)")
NOTE = "Lane A batch 8 (integrator H32"


def old_parts(old):
    entries, rest, cur = [], [], None
    for line in old.splitlines(keepends=True):
        if ENTRY.match(line):
            cur = [line]
            entries.append(cur)
        elif cur is not None and not END.match(line):
            cur.append(line)
        else:
            cur = None
            rest.append(line)
    for e in entries:
        while not e[-1].strip():
            e.pop()
        if not e[-1].endswith("\n"):
            e[-1] += "\n"
    return ["".join(e) for e in entries], rest


def body_of(text):
    lines = text.splitlines(keepends=True)
    i = next(k for k, l in enumerate(lines) if ENTRY.match(l))
    end = next((k for k in range(i, len(lines)) if lines[k] == "## Support\n"), len(lines))
    while end > i and not lines[end - 1].strip():
        end -= 1
    return "".join(lines[i:end])


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main():
    old = Path(sys.argv[1]).read_text(encoding="utf-8")
    old_readme = Path(sys.argv[2]).read_text(encoding="utf-8")
    root = Path(sys.argv[3])
    entries, rest = old_parts(old)
    files = sorted(p for p in (root / "docs" / "mechanics").glob("*/*.md"))
    bodies = Counter(body_of(p.read_text(encoding="utf-8")) for p in files)
    if Counter(entries) != bodies:
        fail("entries %d, mechanic bodies %d, differing %d" % (
            len(entries), len(files), sum(((Counter(entries) - bodies) + (bodies - Counter(entries))).values())))
    print("1. %d entries = %d mechanic file bodies, byte for byte" % (len(entries), len(files)))

    new = (root / "docs" / "decisions" / "0015-content-expansion-pool.md").read_text(encoding="utf-8").splitlines()
    a = new.index("### 4.3 The entries: moved to docs/mechanics (restructure step 11)")
    b = next(k for k in range(a, len(new)) if new[k].startswith("## 5. "))
    moved_note = [l for l in new[a:b] if l.startswith(NOTE)]
    old_lines = [l.rstrip("\n") for l in rest if l.strip() and not l.startswith(NOTE)]
    new_lines = [l for l in new[:a] + new[b:] if l.strip()]
    if old_lines != new_lines:
        k = next(k for k, (x, y) in enumerate(zip(old_lines + [""], new_lines + [""])) if x != y)
        fail("0015 outside the entries differs at non-blank line %d" % (k + 1))
    if moved_note != [l.rstrip("\n") for l in rest if l.startswith(NOTE)]:
        fail("the batch 8 note")
    print("2. 0015 outside the entries: %d non-blank lines equal in order; the batch 8 note moved to 4.3" % len(new_lines))

    gen = Counter(l for l in (root / "docs" / "support" / "README.md").read_text(encoding="utf-8").splitlines()
                  if l.strip())
    was = Counter(l for l in old_readme.splitlines() if l.strip())
    missing = was - gen
    dup = [l for l, n in was.items() if n > 1]
    if missing != Counter({l: was[l] - 1 for l in dup}):
        fail("support README lines missing: %d" % sum(missing.values()))
    added = gen - was
    print("3. support README: %d of %d non-blank lines kept (%d exact duplicate removed), %d generated lines added"
          % (sum(was.values()) - sum(missing.values()), sum(was.values()), sum(missing.values()), sum(added.values())))


if __name__ == "__main__":
    main()
