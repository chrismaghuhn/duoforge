"""Carry out the planned renames of tests/renames.tsv for some test areas (restructure steps 6b-6d).

Usage:
  python3 tools/restructure/rename_tests.py mv    --areas abilities,items,forms   git mv of each file (commit this alone)
  python3 tools/restructure/rename_tests.py names --areas abilities,items,forms   the names everywhere, the rows done
  (either with --root DIR for another tree)

`mv` moves every planned `rename` row of the areas with `git mv` (a 100 % rename, so history follows it). `names` then
- rewrites the row's registration in tests/<area>/tests.cmake (NAME and SOURCES),
- replaces the old CTest name and the old file name (with its tests/ and area prefixes or alone) by the new ones in every
  living file (tools/restructure/test_audit.py: every tracked file but the table and the frozen records under docs/),
- sets the rows' state to done, and runs test_audit --check.
The step number stays in each test's header text ("step G62 of the content expansion"); the table is the bridge from the
old names. Splits and merges are step 6e. Stdlib only.
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_audit  # noqa: E402


def rows_for(root, areas):
    rows = test_audit.read_table(root)
    chosen = [r for r in rows if r['action'] == 'rename' and r['state'] == 'planned' and r['old_file'].split('/')[0] in areas]
    if not chosen:
        raise SystemExit('rename_tests: no planned rename in %s' % ','.join(sorted(areas)))
    return rows, chosen


def do_mv(root, chosen):
    for r in chosen:
        new = root / 'tests' / r['new_file']
        if new.exists():
            raise SystemExit('rename_tests: %s exists' % new)
    for r in chosen:
        subprocess.run(['git', 'mv', 'tests/' + r['old_file'], 'tests/' + r['new_file']], cwd=root, check=True)
        print('git mv tests/%s tests/%s' % (r['old_file'], r['new_file']))


def replacements(chosen):
    """One pattern and its table: the CTest name, the file name with its tests/<area>/ prefix, its <area>/ prefix and the
    flat tests/ of before restructure step 1 (all to the new path), then the file name with any other prefix or alone.
    Longest first, so that a path is replaced whole before its file name could be."""
    table = {}
    for r in chosen:
        old_name, new_name = Path(r['old_file']).name, Path(r['new_file']).name
        table[r['old_ctest']] = r['new_ctest']
        table['tests/' + r['old_file']] = 'tests/' + r['new_file']
        table[r['old_file']] = r['new_file']
        table['tests/' + old_name] = 'tests/' + r['new_file']
        table[old_name] = new_name
    pattern = re.compile(r'(?<![\w])(?:%s)(?![\w])' % '|'.join(re.escape(o) for o in sorted(table, key=len, reverse=True)))
    return pattern, table


def do_names(root, rows, chosen):
    for r in chosen:
        if not (root / 'tests' / r['new_file']).exists():
            raise SystemExit('rename_tests: run mv first (%s is missing)' % r['new_file'])
    pattern, table_of = replacements(chosen)
    changed = []
    for name in test_audit.living_files(root):
        path = root / name
        try:
            raw = path.read_bytes()
            text = raw.decode('utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        new = pattern.sub(lambda m: table_of[m.group(0)], text)
        if new != text:
            path.write_bytes(new.encode('utf-8'))  # the bytes as they were, line ends included
            changed.append(name)
    # The registration: the NAME and SOURCES pair (the generic replacement has done both; check that it did).
    reg = test_audit.registrations(root)
    for r in chosen:
        if r['new_ctest'] not in reg.get(r['new_file'], []):
            raise SystemExit('rename_tests: %s is not registered as %s after the rewrite' % (r['new_file'], r['new_ctest']))
    table = root / test_audit.TABLE
    lines = table.read_text(encoding='utf-8').split('\n')
    done = {r['old_file'] for r in chosen}
    for i, line in enumerate(lines):
        cells = line.split('\t')
        if len(cells) == len(test_audit.COLUMNS) and cells[0] in done:
            cells[5] = 'done'
            lines[i] = '\t'.join(cells)
    table.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print('%d rows done, %d files changed' % (len(chosen), len(changed)))
    for name in changed:
        print('  ' + name)
    problems = test_audit.check(root)
    for p in problems:
        print(p)
    return 1 if problems else 0


def main(argv):
    root = Path(__file__).resolve().parents[2]
    if len(argv) == 5 and argv[3] == '--root':
        root, argv = Path(argv[4]).resolve(), argv[:3]
    if len(argv) != 3 or argv[0] not in ('mv', 'names') or argv[1] != '--areas':
        print(__doc__)
        return 2
    areas = set(argv[2].split(','))
    rows, chosen = rows_for(root, areas)
    if argv[0] == 'mv':
        do_mv(root, chosen)
        return 0
    return do_names(root, rows, chosen)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
