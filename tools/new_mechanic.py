"""Scaffold a new mechanic (restructure step 12): its test, its registration, its documentation stub, its numbers.

Usage:
  python3 tools/new_mechanic.py <area> <behaviour> --id <entry id> --lane <lane> --title "<title>"
      [--step <code>] [--doc-area <area>] [--draw-site NAME=ID ...] [--residual-kind NAME=NUMBER ...] [--root DIR] [--dry-run]

Writes, and changes nothing that runs:
- tests/<area>/test_<behaviour>.c, a white-box test whose one check fails ("scaffold of <id>: write the mechanic's
  checks") until real checks replace it: an unfilled scaffold never passes, and its line in tests/<area>/tests.cmake: duoforge.<area>.<behaviour>, tier quick, the area
  label (the names of restructure step 6: tests/renames.tsv, tools/restructure/test_audit.py);
- docs/mechanics/<doc area>/<id>-<slug>.md from docs/mechanics/TEMPLATE.md (restructure step 11), with the anchor, the
  title, the area, the step and the Tests line filled in, without the optional ## Support section; the id is the next one of the lane's block in
  docs/process/NUMBERS.md, which the lane gives here (the tool hands out no number, and refuses an id outside the block
  of --lane, read from the row "Decision 0015 entry ids", or one that has its file or anchor already);
- for each --draw-site NAME=ID: the line DFI_DRAW_SITE(NAME, IDu, "name") of src/rng/draw_sites.def, the #define
  DFI_SITE_NAME of src/rng/draw.h and the entry of tools/reference/trace_to_c.py's SITES (restructure step 5c), with an id
  that the HS gave out (NUMBERS.md) and that is free and below DFI_SITE_COUNT;
- for each --residual-kind NAME=NUMBER: the line DFI_RES_KIND(NAME, NUMBERu, "name") of src/combat/residual_kinds.def and
  the #define DFI_RES_NAME of src/combat/residual_order.h, with a free number.

Everything is checked before anything is written: an existing file, CTest name, id, site or kind, a name with a step
number, an unknown area or a site at or above the count is refused (exit 2, nothing written). The flag spaces
(DFI_VOL_*, DFI_POSFLAG_*) are full: a new flag needs a state revision, which no scaffold makes. --dry-run prints the
plan and writes nothing. Stdlib only.
"""
import argparse
import re
import sys
from pathlib import Path

TEST_AREAS = ('abilities', 'items', 'moves', 'mechanics', 'forms', 'flow', 'interactions')
DOC_AREAS = ('flow', 'mechanics', 'items', 'abilities', 'moves', 'forms', 'field')
STEP = re.compile(r'(?:^|_)(?:g\d+[a-z]?|k\d+|i\d+|ac\d+|a\d+a|mega\d+)(?=_|$)')  # as tools/restructure/test_audit.py


class Refused(Exception):
    pass


def read(path):
    return path.read_text(encoding='utf-8').replace('\r\n', '\n')


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def slug_of(title):
    words = re.findall(r'[a-z0-9]+', title.lower())
    if not words:
        raise Refused('the title %r has no word for the file name' % title)
    return '-'.join(words[:6])


def test_source(area, behaviour, name, doc, entry):
    return '''/*
 * {name} (white-box): {title_line}
 *
 * The mechanic's documentation is {doc}; its Tests line names this test. Replace the placeholder below with the checks
 * that the recorded reference battles cannot show by themselves (marks, pinned rows, public values, refusals).
 */
#include <stdbool.h>

#include <duoforge/duoforge.h>

#include "support/check.h"

/* The scaffold's placeholder: it fails until the mechanic's own checks replace it (tools/new_mechanic.py), so that an unfilled
 * scaffold never passes. */
static void check_placeholder(df_test *t)
{{
    const bool mechanic_checks_written = false;
    DF_CHECK(t, mechanic_checks_written && "scaffold of {entry}: write the mechanic's checks");
}}

int main(void)
{{
    df_test t;
    df_test_begin(&t, "{name}");
    check_placeholder(&t);
    return df_test_end(&t);
}}
'''.format(name=name, doc=doc, entry=entry, title_line='scaffolded by tools/new_mechanic.py (%s, %s).' % (area, behaviour))


def doc_text(template, entry, title, area, step, tests):
    t = template
    t = t.replace('<a id="<id>"></a>', '<a id="%s"></a>' % entry)
    t = t.replace('# <id>. <step code>, <title>', '# %s. %s, %s' % (entry, step, title) if step != '-' else '# %s. %s' % (entry, title))
    t = re.sub(r'^- Area: .*$', '- Area: %s' % area, t, count=1, flags=re.M)
    t = re.sub(r'^- Step: .*$', '- Step: %s' % step, t, count=1, flags=re.M)
    t = re.sub(r'^- Tests: .*$', '- Tests: %s' % tests, t, count=1, flags=re.M)
    t = t.replace('<id>. **<step code>, <title>**', '%s. **%s**' % (entry, '%s, %s' % (step, title) if step != '-' else title))
    # The optional ## Support section is left out (TEMPLATE.md: delete it when the step has none); a step that has a support
    # line adds it and runs tools/docs/mechanics_docs.py --write (docs/mechanics/README.md).
    if '\n## Support' in t:
        t = t[:t.index('\n## Support')].rstrip('\n') + '\n'
    if '<id>' in t.split('\n', 3)[0] or '- Tests: %s' % tests not in t:
        raise Refused('docs/mechanics/TEMPLATE.md does not have the header this tool fills in')
    return t


def id_key(entry):
    """The order of the entry ids: shorter first, then by letter (5z < 5aa < 5ea < 5ez < 5fa)."""
    return (len(entry), entry)


def lane_blocks(numbers):
    """{lane: [(first, last)]} of the row "Decision 0015 entry ids" of docs/process/NUMBERS.md ("Content: 5ea-5ez; ...")."""
    m = re.search(r'^\| Decision 0015 entry ids \| ([^|]*)\|', numbers, re.M)
    if not m:
        raise Refused('docs/process/NUMBERS.md has no row "Decision 0015 entry ids"')
    blocks = {}
    for part in m.group(1).split(';'):
        lane, _, ranges = part.strip().partition(':')
        for first, last in re.findall(r'(5[a-z]+)-(5[a-z]+)', ranges):
            blocks.setdefault(lane.strip(), []).append((first, last))
    return blocks


def check_id(entry, lane, numbers):
    """The id lies in the lane's block of NUMBERS.md; the HS hands out every id outside the other lanes' blocks."""
    blocks = lane_blocks(numbers)
    inside = lambda ranges: any(id_key(a) <= id_key(entry) <= id_key(b) for a, b in ranges)
    if lane == 'HS':
        others = [r for name, rs in blocks.items() if name != 'HS' for r in rs]
        if inside(others):
            raise Refused('entry id %s lies in another lane\'s block of docs/process/NUMBERS.md' % entry)
        return
    if lane not in blocks:
        raise Refused('lane %r has no block of entry ids in docs/process/NUMBERS.md (%s)' % (lane, ', '.join(sorted(blocks))))
    if not inside(blocks[lane]):
        raise Refused('entry id %s is outside the %s block of docs/process/NUMBERS.md (%s)'
                      % (entry, lane, ', '.join('%s-%s' % r for r in blocks[lane])))


def parse_pairs(values, what):
    out = []
    for v in values:
        m = re.fullmatch(r'([A-Z][A-Z0-9_]*)=(\d+)', v)
        if not m:
            raise Refused('%s %r is not NAME=NUMBER (NAME in capitals)' % (what, v))
        out.append((m.group(1), int(m.group(2))))
    return out


def insert_def_line(text, macro, name, value, label):
    """The definition file with the new line in value order (after the last line of a smaller value)."""
    lines = text.split('\n')
    pattern = re.compile(r'^%s\(([A-Z0-9_]+), (\d+)u, "[a-z0-9-]+"\)$' % macro)
    at = None
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            if m.group(1) == name or int(m.group(2)) == value:
                raise Refused('%s %s=%d: the name or the value is taken (%s)' % (macro, name, value, line))
            if int(m.group(2)) < value:
                at = i
            elif at is None:
                at = i - 1
    if at is None:
        raise Refused('no %s line found' % macro)
    lines.insert(at + 1, '%s(%s, %du, "%s")' % (macro, name, value, label))
    return '\n'.join(lines)


def insert_define(text, prefix, name, value, comment, before):
    """The header with `#define <prefix><name> <value>u` before the line that starts with `before`."""
    if re.search(r'^#define %s%s\b' % (prefix, name), text, re.M):
        raise Refused('%s%s is already defined' % (prefix, name))
    if re.search(r'^#define %s[A-Z0-9_]+ %du\b' % (prefix, value), text, re.M):
        raise Refused('%s value %d is taken' % (prefix, value))
    at = text.index(before)
    return text[:at] + '#define %s%s %du /* %s */\n' % (prefix, name, value, comment) + text[at:]


def plan(args):
    root = Path(args.root).resolve()
    area, behaviour = args.area, args.behaviour
    if area not in TEST_AREAS:
        raise Refused('area %r: one of %s' % (area, ', '.join(TEST_AREAS)))
    if not re.fullmatch(r'[a-z][a-z0-9_]*[a-z0-9]', behaviour) or STEP.search(behaviour):
        raise Refused('behaviour %r: lowercase words with _, no step number (restructure step 6)' % behaviour)
    doc_area = args.doc_area or area
    if doc_area not in DOC_AREAS:
        raise Refused('documentation area %r: one of %s (--doc-area)' % (doc_area, ', '.join(DOC_AREAS)))
    if not re.fullmatch(r'5[a-z]{1,3}', args.id):
        raise Refused('entry id %r: 5 and one to three letters, from the lane block of docs/process/NUMBERS.md' % args.id)
    name = 'duoforge.%s.%s' % (area, behaviour)
    test_rel = 'tests/%s/test_%s.c' % (area, behaviour)
    doc_rel = 'docs/mechanics/%s/%s-%s.md' % (doc_area, args.id, slug_of(args.title))
    writes = {}
    if (root / test_rel).exists():
        raise Refused('%s exists' % test_rel)
    cmake = root / 'tests' / area / 'tests.cmake'
    cmake_text = read(cmake)
    for f in sorted((root / 'tests').glob('*/tests.cmake')):
        if re.search(r'NAME %s(?=[\s)])' % re.escape(name), read(f)):
            raise Refused('the CTest name %s is taken (%s)' % (name, f.relative_to(root)))
    mechanics = root / 'docs' / 'mechanics'
    if any(mechanics.glob('*/%s-*.md' % args.id)) or any(
            '<a id="%s"></a>' % args.id in read(f) for f in mechanics.glob('*/*.md')):
        raise Refused('entry id %s has its file or anchor already' % args.id)
    check_id(args.id, args.lane, read(root / 'docs' / 'process' / 'NUMBERS.md'))
    writes[test_rel] = test_source(area, behaviour, name, doc_rel, args.id)
    line = ('# %s (%s): %s. Scaffolded by tools/new_mechanic.py.\n'
            'duoforge_add_test(NAME %s SOURCES %s/test_%s.c WHITEBOX TIMEOUT 60 TIER quick AREA %s)\n'
            % (args.id, args.step, args.title, name, area, behaviour, area))
    writes['tests/%s/tests.cmake' % area] = cmake_text + ('' if cmake_text.endswith('\n') else '\n') + line
    writes[doc_rel] = doc_text(read(mechanics / 'TEMPLATE.md'), args.id, args.title, doc_area, args.step, name)
    sites = parse_pairs(args.draw_site, '--draw-site')
    if sites:
        draw_h, draw_def, trace = 'src/rng/draw.h', 'src/rng/draw_sites.def', 'tools/reference/trace_to_c.py'
        h, d, tr = read(root / draw_h), read(root / draw_def), read(root / trace)
        count = int(re.search(r'^#define DFI_SITE_COUNT (\d+)u', h, re.M).group(1))
        for site, value in sites:
            if not 0 < value < count:
                raise Refused('draw site %s=%d: outside 1..%d (DFI_SITE_COUNT %d; raising it is the HS\'s change)'
                              % (site, value, count - 1, count))
            d = insert_def_line(d, 'DFI_DRAW_SITE', site, value, site.lower().replace('_', '-'))
            h = insert_define(h, 'DFI_SITE_', site, value, '%s (%s): scaffolded, describe the draw' % (args.title, args.id),
                              '#define DFI_SITE_COUNT ')
            if tr.count('\nSITES = {') != 1 or re.search(r"[{\s]'%s':" % site, tr[tr.index('\nSITES = {'):]
                                                                 [:tr[tr.index('\nSITES = {'):].index('}')]):
                raise Refused('%s: SITES not found once, or %s already in it' % (trace, site))
            tr = tr.replace('\nSITES = {', "\nSITES = {'%s': %d,  # %d: %s (%s), scaffolded\n         " % (site, value, value, args.title, args.id), 1)
        writes[draw_h], writes[draw_def], writes[trace] = h, d, tr
    kinds = parse_pairs(args.residual_kind, '--residual-kind')
    if kinds:
        res_h, res_def = 'src/combat/residual_order.h', 'src/combat/residual_kinds.def'
        h, d = read(root / res_h), read(root / res_def)
        for kind, value in kinds:
            if not 0 < value < 0xFFFFFFFF:
                raise Refused('residual kind %s=%d: out of range' % (kind, value))
            d = insert_def_line(d, 'DFI_RES_KIND', kind, value, kind.lower().replace('_', '-'))
            h = insert_define(h, 'DFI_RES_', kind, value, '%s (%s): scaffolded, describe the handler' % (args.title, args.id),
                              '#define DFI_RES_NO_ORDER ')
        writes[res_h], writes[res_def] = h, d
    return root, writes


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('area')
    p.add_argument('behaviour')
    p.add_argument('--id', required=True)
    p.add_argument('--lane', required=True, help='the lane whose block of docs/process/NUMBERS.md the id is from (Content, Fuzz, HS)')
    p.add_argument('--title', required=True)
    p.add_argument('--step', default='-')
    p.add_argument('--doc-area')
    p.add_argument('--draw-site', action='append', default=[])
    p.add_argument('--residual-kind', action='append', default=[])
    p.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    try:
        root, writes = plan(args)
    except Refused as e:
        print('new_mechanic: refused: %s (nothing written)' % e, file=sys.stderr)
        return 2
    for rel in sorted(writes):
        print('%s %s' % ('would write' if args.dry_run else 'writes', rel))
        if not args.dry_run:
            write(root / rel, writes[rel])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
