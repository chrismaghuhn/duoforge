"""The historical test names and their renames (restructure step 6).

Usage:
  python3 tools/restructure/test_audit.py [ROOT] --check     the table tests/renames.tsv against the tree (CTest: duoforge.lint.test_renames)
  python3 tools/restructure/test_audit.py [ROOT] --report    a Markdown table of every row with its file's size and checks

tests/renames.tsv has one row per historical C test file (a file whose name carries a content-expansion step number such
as G62, K3, I2, AC1 or a Mega batch, or one of the listed `test_pool_*` files) with its CTest name, the action (rename,
split, merge), the new file and CTest name, and the state (planned or done). The check:

- every row is well-formed, every old file and every old CTest name is in exactly one row, a rename names a new file
  `tests/<area>/test_<behaviour>.c` with the CTest name `duoforge.<area>.<behaviour>` and no step number in it;
- every test file of the tree whose name carries a step number has its row, so a new historical name cannot appear;
- a planned row's old file exists and is registered under its old CTest name (tests/<area>/tests.cmake);
- a part row (step 6e: one of the files a split makes) has the split row of its source, is done and registered under its
  new name; a split is done with two parts or more, its old file gone;
- a done row's new file exists and is registered under its new CTest name, its old file is gone, and neither the old
  CTest name nor the old file name is left in a living file: every tracked file but this table and the frozen records
  under docs/ (history, benchmarks, research, decisions, superpowers), which keep the old names (the table is their
  bridge).

Stdlib only.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

COLUMNS = ['old_file', 'old_ctest', 'action', 'new_file', 'new_ctest', 'state', 'subject']
ACTIONS = ('rename', 'split', 'merge', 'part')
STATES = ('planned', 'done')
# A content-expansion step in a file name: _g62, _g72b, _k3, _i2, _ac1, _a2a, _mega2 (followed by the end or by _).
STEP = re.compile(r'_(?:g\d+[a-z]?|k\d+|i\d+|ac\d+|a\d+a|mega\d+)(?=_|$)')
FROZEN = ('docs/history/', 'docs/benchmarks/', 'docs/research/', 'docs/decisions/', 'docs/superpowers/')
TABLE = 'tests/renames.tsv'


def registrations(root, area='*'):
    """{source under tests/: [CTest names]} from every tests/<area>/tests.cmake (or the one of `area`)."""
    reg = {}
    for f in sorted((root / 'tests').glob('%s/tests.cmake' % area)):
        for m in re.finditer(r'duoforge_add_test\(NAME (\S+) SOURCES ([^\s)]+)', f.read_text(encoding='utf-8')):
            reg.setdefault(m.group(2), []).append(m.group(1))
    return reg


def read_table(root):
    rows = []
    lines = (root / TABLE).read_text(encoding='utf-8').splitlines()
    body = [l for l in lines if l and not l.startswith('#')]
    if not body or body[0].split('\t') != COLUMNS:
        raise SystemExit('%s: the header must be %s' % (TABLE, '\t'.join(COLUMNS)))
    for n, line in enumerate(body[1:], 2):
        cells = line.split('\t')
        if len(cells) != len(COLUMNS):
            raise SystemExit('%s: row %d has %d cells, not %d' % (TABLE, n, len(cells), len(COLUMNS)))
        rows.append(dict(zip(COLUMNS, cells)))
    return rows


def living_files(root):
    names = subprocess.run(['git', 'ls-files'], cwd=root, capture_output=True, text=True, check=True).stdout.split('\n')
    return [n for n in names if n and n != TABLE and not n.startswith(FROZEN)]


def check(root):
    problems = []
    rows = read_table(root)
    reg = registrations(root)
    seen_files, seen_names, seen_new = set(), set(), {}
    sources = {r['old_file']: r for r in rows if r['action'] != 'part'}
    parts_of = {}
    for r in rows:
        where = r['old_file']
        if r['action'] not in ACTIONS or r['state'] not in STATES:
            problems.append('%s: action %r, state %r' % (where, r['action'], r['state']))
        if r['action'] == 'part':
            # A part of a split (step 6e): its source has a split row, the part is done when written.
            if any(x['new_file'] == r['new_file'] for x in parts_of.get(where, [])):
                problems.append('%s: two part rows of one source name %s' % (where, r['new_file']))
            parts_of.setdefault(where, []).append(r)
            src = sources.get(where)
            if src is None or src['action'] != 'split' or src['old_ctest'] != r['old_ctest']:
                problems.append('%s: a part row whose source has no split row of the same CTest name' % where)
            elif src['state'] != 'done':
                problems.append('%s: a part row while its split is planned (the old test would still run beside it)' % where)
            if r['state'] != 'done':
                problems.append('%s: a part row is written when its file is (state done)' % where)
        else:
            for key, seen in (('old_file', seen_files), ('old_ctest', seen_names)):
                if r[key] in seen:
                    problems.append('%s: %s %s is in two rows' % (where, key, r[key]))
                seen.add(r[key])
        merge_targets = {x['new_file'] for x in rows if x['action'] == 'merge'}
        if r['action'] in ('rename', 'part') and r['new_file'] != '-':
            if r['new_file'] in seen_new and not (r['action'] == 'part' and r['new_file'] in merge_targets):
                problems.append('%s: the new file %s is in two rows' % (where, r['new_file']))
            seen_new[r['new_file']] = where
        if r['action'] == 'split':
            if r['new_file'] != '-' or r['new_ctest'] != '-':
                problems.append('%s: a split names its new files in rows of their own (step 6e), not here' % where)
        else:
            m = re.fullmatch(r'([a-z]+)/test_([a-z0-9_]+)\.c', r['new_file'])
            if not m or STEP.search('_' + m.group(2)) or r['new_ctest'] != 'duoforge.%s.%s' % (m.group(1), m.group(2)):
                problems.append('%s: new name %s / %s is not tests/<area>/test_<behaviour>.c with duoforge.<area>.<behaviour>'
                                % (where, r['new_file'], r['new_ctest']))
        old_exists = (root / 'tests' / r['old_file']).exists()
        if r['action'] == 'part':
            if r['new_ctest'] not in reg.get(r['new_file'], []):
                problems.append('%s: part %s is not registered as %s' % (where, r['new_file'], r['new_ctest']))
            elif r['new_file'] not in registrations(root, r['new_file'].split('/')[0]):
                problems.append('%s: part %s is registered outside tests/%s/tests.cmake'
                                % (where, r['new_file'], r['new_file'].split('/')[0]))
            continue
        if r['state'] == 'planned':
            if not old_exists:
                problems.append('%s: planned, but the file is gone' % where)
            elif r['old_ctest'] not in reg.get(r['old_file'], []):
                problems.append('%s: planned, but not registered as %s' % (where, r['old_ctest']))
        else:
            if old_exists:
                problems.append('%s: done, but the old file still exists' % where)
            if r['action'] != 'split' and r['new_ctest'] not in reg.get(r['new_file'], []):
                problems.append('%s: done, but %s is not registered as %s' % (where, r['new_file'], r['new_ctest']))
    for src, r in sources.items():
        if r['action'] == 'split' and r['state'] == 'done' and len(parts_of.get(src, [])) < 2:
            problems.append('%s: a split is done with %d part row(s); a single subject is a rename' % (src, len(parts_of.get(src, []))))
    for src in reg:
        if STEP.search(Path(src).stem) and src not in seen_files:
            problems.append('%s: a historical name without a row in %s' % (src, TABLE))
    done = [r for r in rows if r['state'] == 'done' and r['action'] != 'part']
    if done:
        olds = {r['old_ctest']: r['old_ctest'] for r in done}
        olds.update({Path(r['old_file']).name: r['old_file'] for r in done})
        for name, found in sorted(old_names_in_living_files(root, olds).items()):
            for old in sorted(found):
                problems.append('%s: still names %s (renamed, see %s)' % (name, old, TABLE))
    return problems


def old_names_in_living_files(root, olds):
    """{living file: {old name the table maps to}} for every old name (a key of `olds`) that a living file names as a word:
    neither a word character before it nor after it. One `git grep` over the tracked files with every name as a fixed
    string (-F -w): a Python alternation over the tree took 17 s here and a minute on the CI runner. Binary files are
    skipped (-I), as a file that is no UTF-8 text was before."""
    excludes = [':(exclude)%s' % TABLE] + [':(exclude)%s' % d for d in FROZEN]
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', suffix='.txt', delete=False) as f:
        f.write(''.join(o + '\n' for o in sorted(olds)))
        patterns = f.name
    try:
        run = subprocess.run(['git', 'grep', '-I', '-o', '-w', '-F', '-h', '--null', '-H', '-f', patterns, '--', '.']
                             + excludes, cwd=root, capture_output=True)
    finally:
        os.unlink(patterns)
    if run.returncode not in (0, 1):  # 1: no match
        raise SystemExit('test_audit: git grep failed: %s' % run.stderr.decode('utf-8', 'replace').strip())
    out = {}
    for line in run.stdout.decode('utf-8').splitlines():
        name, _, match = line.partition('\0')
        if match not in olds:
            raise SystemExit('test_audit: git grep matched %r, which is no old name' % match)
        out.setdefault(name, set()).add(olds[match])
    return out


def report(root):
    rows = read_table(root)
    out = ['| Old file | Old CTest | Lines | Checks | Action | New CTest | Subject |', '|---|---|---:|---:|---|---|---|']
    for r in rows:
        path = root / 'tests' / r['old_file']
        text = path.read_text(encoding='utf-8') if path.exists() else ''
        checks = len(re.findall(r'\bDF_CHECK\w*\(', text))
        out.append('| `%s` | `%s` | %d | %d | %s | %s | %s |' % (
            r['old_file'], r['old_ctest'], text.count('\n'), checks, r['action'],
            '`%s`' % r['new_ctest'] if r['new_ctest'] != '-' else '(6e)', r['subject']))
    counts = {a: sum(1 for r in rows if r['action'] == a) for a in ACTIONS}
    out.append('')
    out.append('%d rows: %s.' % (len(rows), ', '.join('%d %s' % (counts[a], a) for a in ACTIONS)))
    return '\n'.join(out)


def main(argv):
    args = [a for a in argv if not a.startswith('--')]
    modes = [a for a in argv if a.startswith('--')]
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[2]
    if modes == ['--check']:
        problems = check(root)
        for p in problems:
            print(p)
        print('test_audit: %d row(s), %d problem(s)' % (len(read_table(root)), len(problems)))
        return 1 if problems else 0
    if modes == ['--report']:
        print(report(root))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
