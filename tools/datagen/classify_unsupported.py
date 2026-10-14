#!/usr/bin/env python3
"""Classifies the pool entries that the engine does not support (decision 0015), reading the pinned Showdown
checkout with gen_closure.py's parsers and the committed pool tables.

usage: python3 tools/datagen/classify_unsupported.py <pinned checkout> [--out PATH] [--check PATH]

  --out PATH    write the JSON (sorted, stable) and print nothing else but the summary line.
  --check PATH  compare a fresh computation with the JSON at PATH; exit 1 on any difference.
  (no option)   print a compact table.

The entries: every move that the pool tables leave UNMODELLED (the special dfi_pool_move_unmodeled) and every
modelled move that the support manifest does not mark; every pool item and every pool ability that the manifest
does not mark. Each entry gets exactly one class:

  modelled-unmarked  the tables model it (no unmodelled feature); reason: the manifest or generator comment that
                     names it, else "unmarked: no recorded reason".
  hand-work          the pinned object has a callback (a function-valued property at any depth) or a condition;
                     reasons name them ("callback onHit", "condition").
  data-only          the pinned object has no callback and no condition. Its family is the modelled and marked
                     entry (the witness, lowest id, plain handler preferred) that has every non-column data field
                     with the same shape; "none" when no single witness does, with the fields no witness has.

Data fields are the top-level properties that are not functions and not cosmetic. Column fields (num, name, type,
category, basePower, accuracy, pp, priority, critRatio, ...) are carried by every move's column and need no
witness. Flags count one by one ("flags.bullet"). A shape is the normalised value text: numbers become N, an
array keeps its length ([N,N]), a string keeps its literal value, and whitespace and trailing commas are dropped.

Offline tooling. Reads the pinned data files with gen_closure.Source (their sha256 is checked against the pin)
and the committed src/data tables; it changes no file. CTest does not run it.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gen_closure as gc  # noqa: E402  (the parsers, the pin and the inert key sets are shared, not copied)

REPO = os.path.dirname(os.path.dirname(HERE))
KINDS = ('move', 'item', 'ability')
KIND_TOKEN = {'move': 'MOVE', 'item': 'ITEM', 'ability': 'ABILITY'}
KIND_FILES = {
    'move': ('data/moves.ts', 'data/mods/champions/moves.ts'),
    'item': ('data/items.ts', 'data/mods/champions/items.ts'),
    'ability': ('data/abilities.ts', 'data/mods/champions/abilities.ts'),
}
EXPECTED_COUNTS = {'move': 511, 'item': 166, 'ability': 215}
POOL_COUNT_NAME = {'move': 'DFI_POOL_MOVE_COUNT', 'item': 'DFI_POOL_ITEM_COUNT', 'ability': 'DFI_POOL_ABILITY_COUNT'}
SPECIAL_FIELD_INDEX = 28  # the flat move row of src/data/pool_tables.c: the special is the 29th number
MOVE_ROW_LENGTH = 29
CLASSES = ('data-only', 'hand-work', 'modelled-unmarked')

COMMON_COSMETIC = {'shortDesc', 'desc', 'tags', 'contestType', 'zMove', 'maxMove', 'hasSheerForceBoost', 'inherit',
                   'isNonstandard', 'gen', 'num', 'name', 'rating'}
COLUMN_KEYS = {'num', 'name', 'gen', 'rating', 'isNonstandard', 'spritenum', 'fling', 'type', 'category', 'basePower',
               'accuracy', 'pp', 'priority', 'critRatio'}
INERT = {'move': COMMON_COSMETIC,
         'item': COMMON_COSMETIC | gc.INERT_ITEM_KEYS,
         'ability': COMMON_COSMETIC | gc.INERT_ABILITY_KEYS}
CALL_KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'catch', 'function'}
METHOD = re.compile(r'^\s*([A-Za-z_]\w*)\s*\([^)]*\)\s*(\{|=>)', re.M)
PROP_FUNCTION = re.compile(r'^\s*([A-Za-z_]\w*)\s*:\s*(function\b|\([^)]*\)\s*=>|[A-Za-z_]\w*\s*=>)', re.M)
CONDITION = re.compile(r'^\s*condition\s*:', re.M)
# A property named on* or *Callback is a callback property whatever its value (Stall: onFractionalPriority: -0.1).
CALLBACK_NAME = re.compile(r'^\s*((?:on[A-Z]\w*)|\w*Callback)\s*:', re.M)
# The string values of these properties are parameters of their family (a status, a volatile), not the shape.
PARAMETER_KEYS = ('secondary', 'secondaries', 'self')


def _strip_comments(lines):
    return [line if line.find('//') < 0 else line[:line.find('//')] for line in lines]


def normalize(value):
    """The shape of a field value: whitespace, trailing commas and the quote style dropped, numbers as N, an array
    as [N,...] with its length."""
    v = re.sub(r'\s+', '', value).replace('"', "'").rstrip(',')
    v = re.sub(r',(?=[}\]])', '', v)
    v = re.sub(r'\[(-?\d+(?:,-?\d+)*)\]', lambda m: '[' + ','.join('N' for _ in m.group(1).split(',')) + ']', v)
    return re.sub(r'-?\d+', 'N', v)


def callbacks_of(lines):
    """The names of the function-valued properties (method shorthand or a function/arrow value) at any depth, and
    'condition' for a condition property, sorted."""
    text = '\n'.join(_strip_comments(lines))
    names = {m.group(1) for m in METHOD.finditer(text) if m.group(1) not in CALL_KEYWORDS}
    names |= {m.group(1) for m in PROP_FUNCTION.finditer(text)}
    names |= {m.group(1) for m in CALLBACK_NAME.finditer(text)}
    out = sorted(names)
    if CONDITION.search(text):
        out.append('condition')
    return out


def parts(kind, bodies):
    """(callbacks, fields, columns) of one pinned object, the bodies being its base entry and its Champions override
    (in that order; the override wins per field). fields: shape key -> shape; flags are one key each."""
    callbacks, fields, columns = set(), {}, set()
    inert = INERT[kind]
    for body in bodies:
        if body is None:
            continue
        lines = _strip_comments(body)
        callbacks |= set(callbacks_of(lines))
        for name, (is_fn, text) in gc.fields(lines).items():
            if is_fn or name == 'condition':
                continue
            if name in inert:
                continue
            if name in COLUMN_KEYS:
                columns.add(name)
                continue
            value = text.split(':', 1)[1] if ':' in text else text
            if name in PARAMETER_KEYS:
                value = re.sub(r"'[^']*'|\"[^\"]*\"", "'S'", value)
            if name == 'flags':
                for flag in re.findall(r'(\w+)\s*:\s*1', value):
                    fields['flags.' + flag] = '1'
                continue
            fields[name] = normalize(value)
    return sorted(callbacks), fields, columns


def covers(witness_fields, need):
    return all(witness_fields.get(key) == shape for key, shape in need.items())


def classify_entry(kind, eid, name, modelled, callbacks, fields, witnesses, pin_lines, recorded=None):
    """One entry's record. witnesses: the modelled and marked entries of the same kind, dicts with id, handler and
    fields. recorded: the comment that names the entry (modelled-unmarked only), or None."""
    if modelled:
        reason = 'unmarked: ' + (recorded if recorded else 'no recorded reason')
        return _record(kind, eid, name, 'modelled-unmarked', [reason], None, pin_lines)
    if callbacks:
        reasons = ['condition' if c == 'condition' else 'callback ' + c for c in callbacks]
        return _record(kind, eid, name, 'hand-work', reasons, None, pin_lines)
    ordered = sorted(witnesses, key=lambda w: (w['handler'] != 'NONE', w['id']))
    best = next((w for w in ordered if covers(w['fields'], fields)), None)
    if best is not None:
        family = {'id': best['id'], 'handler': best['handler']}
        reasons = ['no callback', 'fields expressed by %s (%s)' % (best['id'], best['handler'])]
        return _record(kind, eid, name, 'data-only', reasons, family, pin_lines)
    uncovered = sorted(k for k, v in fields.items() if not any(w['fields'].get(k) == v for w in witnesses))
    if uncovered:
        reasons = ['no callback', 'uncovered: ' + ', '.join(uncovered)]
    else:
        reasons = ['no callback', 'no single witness has all fields: ' + ', '.join(sorted(fields))]
    return _record(kind, eid, name, 'data-only', reasons, 'none', pin_lines)


def _record(kind, eid, name, cls, reasons, family, pin_lines):
    return {'kind': kind, 'id': eid, 'name': name, 'class': cls, 'reasons': reasons, 'family': family,
            'pin_lines': pin_lines}


# ---- the committed tables and the manifest (C text) ----

def read_text(rel):
    with open(os.path.join(REPO, rel), encoding='utf-8') as f:
        return f.read()


def c_block(text, header):
    """The lines of the initialiser that starts with `header` up to its closing '};'."""
    lines = text.split('\n')
    start = next((i for i, line in enumerate(lines) if line.startswith(header)), None)
    if start is None:
        sys.exit('classify_unsupported: %s not found' % header)
    out = []
    for line in lines[start + 1:]:
        if line.startswith('};'):
            return out
        out.append(line)
    sys.exit('classify_unsupported: %s is not closed' % header)


def pool_names(pool_text):
    """kind -> {enum suffix: id}: the ids of the pool, from the names table (the id is the TS key)."""
    out = {}
    for kind in KINDS:
        tok = KIND_TOKEN[kind]
        names = {}
        for line in c_block(pool_text, 'const char *const dfi_pool_%s_names[' % kind):
            m = re.match(r'^\s*\[DFI_%s_(\w+)\] = "(\w+)",' % tok, line)
            if m:
                names[m.group(1)] = m.group(2)
        out[kind] = names
    return out


def define_values(header_texts):
    """enum suffix -> value, for the DFI_MOVE_/DFI_ITEM_/DFI_ABILITY_ defines of the data headers."""
    out = {}
    for text in header_texts:
        for m in re.finditer(r'^#define DFI_(MOVE|ITEM|ABILITY)_(\w+) (\d+)u\b', text, re.M):
            if m.group(2) == 'COUNT':
                continue
            out[(m.group(1), m.group(2))] = int(m.group(3))
    return out


def unmodeled_text(pool_text, kind):
    out = {}
    tok = KIND_TOKEN[kind]
    for line in c_block(pool_text, 'const char *const dfi_pool_%s_unmodeled[' % kind):
        m = re.match(r'^\s*\[DFI_%s_(\w+)\] = "(.*)",?$' % tok, line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def move_specials(pool_text):
    """The special handler name of every move row, by row index (the index of the enum value)."""
    rows = []
    for line in c_block(pool_text, 'const dfi_move_data dfi_pool_moves['):
        m = re.match(r'^\s*\{(.*)\},\s*$', line)
        if m:
            rows.append([int(x) for x in re.findall(r'(\d+)u', m.group(1))])
    for row in rows:
        if len(row) != MOVE_ROW_LENGTH:
            sys.exit('classify_unsupported: a move row has %d numbers, expected %d' % (len(row), MOVE_ROW_LENGTH))
    return [gc.SPECIAL_IDS_P[row[SPECIAL_FIELD_INDEX]] for row in rows]


def family_names(pool_text, kind):
    """id -> family name ('NONE' or the family) of the item or ability family column."""
    tok = KIND_TOKEN[kind]
    out = {}
    if kind == 'move':
        return out
    header = 'const dfi_item_family dfi_pool_item_family[' if kind == 'item' else 'const dfi_ability_family dfi_pool_ability_family['
    for line in c_block(pool_text, header):
        m = re.match(r'^\s*\[DFI_%s_(\w+)\] = \{DFI_%s_FAMILY_(\w+),' % (tok, tok), line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def manifest_marks(manifest_text):
    """kind -> set of enum suffixes marked 1u in the manifest section of that kind."""
    marks = {kind: set() for kind in KINDS}
    section = None
    sections = {'.moves =': 'move', '.items =': 'item', '.abilities =': 'ability'}
    for line in manifest_text.split('\n'):
        m = re.match(r'^    (\.\w+) =', line)
        if m:
            section = sections.get(m.group(1) + ' =')
            continue
        if line.startswith('};') or re.match(r'^    \.\w+', line):
            section = None
            continue
        if section is None:
            continue
        for mm in re.finditer(r'\[DFI_%s_(\w+)\] = 1u' % KIND_TOKEN[section], line):
            marks[section].add(mm.group(1))
    return marks


def recorded_comments(texts):
    """The comment lines of the manifest and the generator, for the reason of an unmarked entry."""
    out = []
    for text in texts:
        for line in text.split('\n'):
            s = line.strip()
            if s.startswith('#') or s.startswith('/*') or s.startswith('*') or s.startswith('//'):
                out.append(s)
    return out


def recorded_reason(name, comments):
    """The first comment that names the entry and says it is not marked (the manifest's "Not marked: ..." lines)."""
    pattern = re.compile(r'(?<![A-Za-z])%s(?![A-Za-z])' % re.escape(name), re.I)
    for line in comments:
        if re.search(r'not marked|unmarked', line, re.I) and pattern.search(line):
            return line[:200]
    return None


def build(checkout):
    pool_text = read_text('src/data/pool_tables.c')
    headers = [read_text('src/data/' + f) for f in sorted(os.listdir(os.path.join(REPO, 'src', 'data')))
               if f.endswith('.h')]
    manifest_text = read_text('src/data/support_manifest.c')
    comments = recorded_comments([manifest_text, read_text('tools/datagen/gen_closure.py')])
    names = pool_names(pool_text)
    values = define_values(headers)
    marks = manifest_marks(manifest_text)
    specials = move_specials(pool_text)
    records, summary_rows = [], {}
    for kind in KINDS:
        ids = names[kind]
        if len(ids) != EXPECTED_COUNTS[kind]:
            sys.exit('classify_unsupported: %s names: %d entries, expected %d' % (kind, len(ids), EXPECTED_COUNTS[kind]))
        unmodeled = unmodeled_text(pool_text, kind)
        for enum in unmodeled:
            if enum not in ids:
                sys.exit('classify_unsupported: unmodelled %s %s has no name' % (kind, enum))
    for kind in KINDS:
        base_rel, champ_rel = KIND_FILES[kind]
        base, champ = gc.Source(checkout, base_rel), gc.Source(checkout, champ_rel)
        unmodeled = unmodeled_text(pool_text, kind)
        families = family_names(pool_text, kind)
        pending, witnesses = [], []
        for enum, eid in sorted(names[kind].items(), key=lambda kv: kv[1]):
            entries = [src.entry(eid) for src in (base, champ)]
            if entries[0] is None and entries[1] is None:
                sys.exit('classify_unsupported: %s %s not found in the pinned %s' % (kind, eid, base_rel))
            bodies = [e[2] if e else None for e in entries]
            refs = [src.ref(eid) for src, e in zip((base, champ), entries) if e]
            callbacks, fields, _columns = parts(kind, bodies)
            name = eid
            if entries[0] is not None:
                fm = gc.fields(_strip_comments(entries[0][2])).get('name')
                if fm is not None:
                    name = gc.scalar(fm[1])
            is_marked = enum in marks[kind]
            modelled = enum not in unmodeled
            if kind == 'move':
                handler = specials[values[('MOVE', enum)]]
            else:
                handler = families.get(enum, 'NONE')
            if modelled and is_marked:
                witnesses.append({'id': eid, 'handler': handler, 'fields': fields})
            elif not modelled or not is_marked:
                pending.append((eid, name, modelled, callbacks, fields, refs, comments))
        for eid, name, modelled, callbacks, fields, refs, _c in pending:
            recorded = recorded_reason(name, comments) if modelled else None
            records.append(classify_entry(kind, eid, name, modelled, callbacks, fields, witnesses, '; '.join(refs),
                                          recorded))
    records.sort(key=lambda r: (KINDS.index(r['kind']), r['id']))
    return records


def summarize(records):
    counts = {}
    for kind in KINDS:
        rows = [r for r in records if r['kind'] == kind]
        counts[kind] = {cls: sum(1 for r in rows if r['class'] == cls) for cls in CLASSES}
        counts[kind]['total'] = len(rows)
        counts[kind]['family_none'] = sum(1 for r in rows if r['family'] == 'none')
    return {'counts': counts, 'entries': len(records)}


def to_json(records):
    return json.dumps({'entries': records, 'summary': summarize(records)}, indent=2, sort_keys=True) + '\n'


def table(records):
    lines = ['kind\tname\tclass\treason\twitness']
    for r in records:
        w = r['family']
        wit = '-' if w is None else (w if w == 'none' else '%s (%s)' % (w['id'], w['handler']))
        lines.append('%s\t%s\t%s\t%s\t%s' % (r['kind'], r['name'], r['class'], '; '.join(r['reasons']), wit))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('checkout')
    ap.add_argument('--out')
    ap.add_argument('--check')
    args = ap.parse_args(argv)
    records = build(args.checkout)
    text = to_json(records)
    if args.check:
        with open(args.check, encoding='utf-8') as f:
            if f.read() != text:
                sys.exit('classify_unsupported: %s differs from a fresh computation' % args.check)
        print('classify_unsupported: %s matches (%d entries)' % (args.check, len(records)))
        return 0
    if args.out:
        with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        print(json.dumps(summarize(records)['counts'], sort_keys=True))
        return 0
    print(table(records))
    return 0


if __name__ == '__main__':
    sys.exit(main())
