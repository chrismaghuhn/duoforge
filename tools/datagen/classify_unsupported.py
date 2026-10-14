#!/usr/bin/env python3
"""Classifies the pool entries that the engine does not support (decision 0015), reading the pinned Showdown
checkout with gen_closure.py's parsers and the committed pool tables.

usage: python3 tools/datagen/classify_unsupported.py <pinned checkout> [--out PATH] [--check PATH]

  --out PATH    write the JSON (sorted, stable) and print the per-kind counts.
  --check PATH  compare a fresh computation with the JSON at PATH; exit 1 on any difference.
  (no option)   print a compact table.

The entries: every move that the pool tables leave UNMODELLED (the special dfi_pool_move_unmodeled) and every
modelled move that the support manifest does not mark; every pool item and every pool ability that the manifest
does not mark. Each entry gets exactly one class, in this order:

  modelled-unmarked  the tables model it (no unmodelled feature); reason: the manifest or generator comment that
                     says it is not marked and names it, else "unmarked: no recorded reason".
  hand-work          the pinned object has a callback (a property named on* or *Callback, or a function value, at any
                     depth), a condition, or its id is referenced in the pinned code (see below). Reasons name the
                     callbacks and every reference: "callback onHit", "condition", "referenced by id at file:line".
  data-only          none of the above. Every effect field is covered on its own (the family, per field):
                     - a generic column (flags.X, target, boosts, secondary, status, sideCondition, pseudoWeather,
                       flags as a set of names): covered by any modelled and marked entry that has the same key with
                       the same value ("flags.bullet": {"id", "column": "flags"});
                     - a dedicated field (multihit, secondaries, self, volatileStatus, ...): covered by the exact text
                       of a dedicated witness ("multihit": {"id", "special": "MULTI_HIT_2_5"});
                     - an item or an ability field: covered by an entry of the same kind with the same key and text
                       ("boosts": {"id", "family": "NONE"}).
                     An entry with no effect field gets family "no effect fields". Otherwise family is the
                     per-field map when every field is covered; else family "none" with "uncovered" fields, and
                     "nearest" when a dedicated witness has the field with other text ({id, special, differs}).

Pinned facts used:
- A move's generic columns are the record keys of gen_closure.py parse_move (lines 507-623): type, category,
  basePower, accuracy, pp, priority, target, critRatio, flags, recoil, drain, a single secondary, boosts (through
  boost_role), status, sideCondition, pseudoWeather. Their values are data: any modelled and marked entry with the
  same key and the same value covers the field, not necessarily the same entry.
- A move's dedicated specials are the templates of gen_closure.py SPECIAL_P (2876-2915). Each pins the exact text
  of its fields: ICE_FANG pins `status: 'frz'` (2899), MULTI_HIT_2_5 `multihit: [2, 5]` (2900), CONFUSE
  `volatileStatus: 'confusion'` (2910), PARTIAL_TRAP `volatileStatus: 'partiallytrapped'` (2914), LOCKED_MOVE
  `self: { volatileStatus: 'lockedmove' }` (2884), MULTI_HIT_2 `multihit: 2` (2888). So a witness with a dedicated
  special matches a field only by exact text. Items and abilities: every family other than NONE is dedicated.
- Non-column fields of a move: multihit, secondaries (plural), volatileStatus, self (its volatile part), selfdestruct,
  ohko and the rest of the special templates. They are matched by exact text in every case.

A data-only batch (a pool move with fields that no existing special owns) needs, in gen_closure.py:
- only columns when every field is a generic column with a value that some entry already has (no change needed);
- otherwise an entry in the special map for its id: SPECIAL_P (2354-2483), `'<id>': ('<HANDLER>', set())`, and the
  handler's owned text in G2_OWNED_FIELDS (2858-2915), because parse_move (316-350) looks the special up by move id
  and fails on a dedicated field (multihit, secondaries, self volatile) that the id does not own. Other column fields
  combine freely with it, as the owned-field check only pins the owned fields' exact text.
Two caveats: a flag in IGNORED_FLAGS (gen_closure.py 113-116: bullet, metronome, mirror, ...) has no engine effect, so
covering it by a witness only shows that the generator accepts the name; and multihit is parsed for every move by
its values (gen_closure.py 499-503), the special is what gives it an engine effect.

Id references (the scan of the pinned code, data/conditions.ts and sim/*.ts and the Champions mod, minus its definition
tables moves/abilities/items/learnsets/formats-data/text, plus data/rulesets.ts and data/scripts.ts when present).
A quoted lowercase id counts as a reference when it is:
  hasAbility('x'), hasItem('x'), hasMove('x') and every has*('x') call;
  .id === 'x' or .name !== 'x' (any == or != comparison of .id or .name);
  case 'x': in a switch;
  .includes('x');
  a quoted id inside one [...] on the same line (an array, a list or a key lookup such as volatiles['x']).
Lines are compared after their // comments are removed. A reference on a line that spans several lines is not seen.

Offline tooling. Reads the pinned checkout (its HEAD must be the pin; the hash-checked files of gen_closure.py are
checked again) and the committed src/data tables; it changes no file. CTest does not run it.
"""
import argparse
import glob
import json
import os
import re
import subprocess
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
SPECIAL_FIELD_INDEX = 28  # the flat move row of src/data/pool_tables.c: the special is the 29th number
MOVE_ROW_LENGTH = 29
CLASSES = ('data-only', 'hand-work', 'modelled-unmarked')
EXCLUDED_CHAMPION_FILES = {'moves.ts', 'abilities.ts', 'items.ts', 'learnsets.ts', 'formats-data.ts', 'text.ts'}

COMMON_COSMETIC = {'shortDesc', 'desc', 'tags', 'contestType', 'zMove', 'maxMove', 'hasSheerForceBoost', 'inherit',
                   'isNonstandard', 'gen', 'num', 'name', 'rating'}
COLUMN_KEYS = {'num', 'name', 'gen', 'rating', 'isNonstandard', 'spritenum', 'fling', 'type', 'category', 'basePower',
               'accuracy', 'pp', 'priority', 'critRatio'}
# The move fields that a generic column carries (gen_closure.py parse_move): their values are data, not a dedicated text.
GENERIC_MOVE_KEYS = {'target', 'flags', 'recoil', 'drain', 'secondary', 'boosts', 'status', 'sideCondition',
                     'pseudoWeather'}
INERT = {'move': COMMON_COSMETIC,
         'item': COMMON_COSMETIC | gc.INERT_ITEM_KEYS,
         'ability': COMMON_COSMETIC | gc.INERT_ABILITY_KEYS}
CALL_KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'catch', 'function'}
METHOD = re.compile(r'^\s*([A-Za-z_]\w*)\s*\([^)]*\)\s*(\{|=>)', re.M)
PROP_FUNCTION = re.compile(r'^\s*([A-Za-z_]\w*)\s*:\s*(function\b|\([^)]*\)\s*=>|[A-Za-z_]\w*\s*=>)', re.M)
CONDITION = re.compile(r'^\s*condition\s*:', re.M)
CALLBACK_NAME = re.compile(r'^\s*((?:on[A-Z]\w*)|\w*Callback)\s*:', re.M)
# The string values of these properties are parameters of their family (a status, a volatile), not the shape.
PARAMETER_KEYS = ('secondary', 'secondaries', 'self')
ID = r'([a-z0-9]+)'
REFERENCE_PATTERNS = [
    re.compile(r"\bhas\w*\(\s*['\"]" + ID + r"['\"]"),
    re.compile(r"\.(?:id|name)\s*[!=]==?\s*['\"]" + ID + r"['\"]"),
    re.compile(r"\bcase\s+['\"]" + ID + r"['\"]\s*:"),
    re.compile(r"\.includes\(\s*['\"]" + ID + r"['\"]"),
]
BRACKETS = re.compile(r"\[([^\]\n]*)\]")
QUOTED_ID = re.compile(r"['\"]" + ID + r"['\"]")


def _strip_comments(lines):
    return [line if line.find('//') < 0 else line[:line.find('//')] for line in lines]


def exact_text(value):
    """The text of a field value with its layout removed: whitespace, trailing commas and the quote style dropped.
    Numbers and strings are kept as written."""
    v = re.sub(r'\s+', '', value).replace('"', "'").rstrip(',')
    return re.sub(r',(?=[}\]])', '', v)


def normalize(value, name=None):
    """The shape of a field value: exact_text with the parameters abstracted: a string of a PARAMETER key is S, an
    array keeps its length ([N,N]) and every other number is N."""
    v = value
    if name in PARAMETER_KEYS:
        v = re.sub(r"'[^']*'|\"[^\"]*\"", "'S'", v)
    v = exact_text(v)
    v = re.sub(r'\[(-?\d+(?:,-?\d+)*)\]', lambda m: '[' + ','.join('N' for _ in m.group(1).split(',')) + ']', v)
    return re.sub(r'-?\d+', 'N', v)


def callbacks_of(lines):
    """The names of the function-valued or on*/*Callback properties at any depth, and 'condition' for a condition
    property, sorted."""
    text = '\n'.join(_strip_comments(lines))
    names = {m.group(1) for m in METHOD.finditer(text) if m.group(1) not in CALL_KEYWORDS}
    names |= {m.group(1) for m in PROP_FUNCTION.finditer(text)}
    names |= {m.group(1) for m in CALLBACK_NAME.finditer(text)}
    out = sorted(names)
    if CONDITION.search(text):
        out.append('condition')
    return out


def analyse(kind, bodies):
    """The pinned object of one entry: its base body and its Champions override (in that order; the override wins per
    field). Returns callbacks (sorted), fields (key -> shape), exact (key -> exact text), columns (the column keys
    present). Flags are one key each (flags.bullet = 1)."""
    callbacks, fields, exact, columns = set(), {}, {}, set()
    inert = INERT[kind]
    for body in bodies:
        if body is None:
            continue
        lines = _strip_comments(body)
        callbacks |= set(callbacks_of(lines))
        for name, (is_fn, text) in gc.fields(lines).items():
            if is_fn or name == 'condition' or name in inert:
                continue
            if name in COLUMN_KEYS:
                columns.add(name)
                continue
            value = text.split(':', 1)[1] if ':' in text else text
            if name == 'flags':
                for flag in re.findall(r'(\w+)\s*:\s*1', value):
                    fields['flags.' + flag] = '1'
                    exact['flags.' + flag] = '1'
                continue
            fields[name] = normalize(value, name)
            exact[name] = exact_text(value)
    return {'callbacks': sorted(callbacks), 'fields': fields, 'exact': exact, 'columns': columns}


def make_witness(eid, handler, bodies, kind='move'):
    a = analyse(kind, bodies)
    return {'id': eid, 'handler': handler, 'fields': a['fields'], 'exact': a['exact']}


def is_generic(kind, key):
    """A generic column of a move (a flag, a target, a boosts dict, a secondary ...): covered by any entry that has the
    same key with the same value. Every other move field, and every item and ability field, is dedicated: covered by
    the exact text of a dedicated witness."""
    if kind != 'move':
        return False
    return key.startswith('flags.') or key in GENERIC_MOVE_KEYS


def field_witness(kind, key, cand, witnesses):
    """The witness of one field of the candidate, or None (the first in order that covers it)."""
    for w in _ordered(witnesses):
        if key not in w['exact'] or w['exact'][key] != cand['exact'][key]:
            continue
        if is_generic(kind, key) or kind != 'move' or w['handler'] != 'NONE':
            return w
    return None


def _entry_for(kind, key, w):
    """The family entry of one covered field: the special of a dedicated field, the column of a generic one."""
    if kind != 'move':
        return {'id': w['id'], 'family': w['handler']}
    if is_generic(kind, key):
        return {'id': w['id'], 'column': key.split('.')[0]}
    return {'id': w['id'], 'special': w['handler']}


def _ordered(witnesses):
    return sorted(witnesses, key=lambda w: (w['handler'] != 'NONE', w['id']))


def _token_diff(cand, wit):
    pattern = r"'[^']*'|-?\d+|[A-Za-z_]+"
    a, b = re.findall(pattern, cand), re.findall(pattern, wit)
    if len(a) == len(b):
        pairs = [(x, y) for x, y in zip(a, b) if x != y]
        if pairs:
            return ', '.join('%s vs %s' % p for p in pairs)
    return '%s vs %s' % (cand, wit)


def nearest_of(kind, key, cand, witnesses):
    """A dedicated witness of an uncovered dedicated field whose text differs from the candidate's."""
    if kind != 'move' or is_generic(kind, key):
        return None
    for w in _ordered(witnesses):
        if w['handler'] != 'NONE' and key in w['exact']:
            return {'id': w['id'], 'special': w['handler'],
                    'differs': '%s %s' % (key, _token_diff(cand['exact'][key], w['exact'][key]))}
    return None


def classify_entry(kind, eid, name, modelled, analysis, witnesses, pin_lines, recorded=None, references=()):
    """One entry's record. analysis: analyse() of its pinned object. witnesses: the modelled and marked entries of the
    same kind (make_witness). recorded: the comment that names the entry (modelled-unmarked only). references: the
    'file:line' sites that reference its id."""
    if modelled:
        reason = 'unmarked: ' + (recorded if recorded else 'no recorded reason')
        return _record(kind, eid, name, 'modelled-unmarked', [reason], None, None, pin_lines)
    callbacks = analysis['callbacks']
    if callbacks or references:
        reasons = ['condition' if c == 'condition' else 'callback ' + c for c in callbacks]
        reasons += ['referenced by id at ' + site for site in references]
        return _record(kind, eid, name, 'hand-work', reasons, None, None, pin_lines)
    fields = analysis['fields']
    if not fields:
        return _record(kind, eid, name, 'data-only', ['no callback', 'no id reference', 'no effect fields'],
                       'no effect fields', None, pin_lines)
    family, uncovered, nearest = {}, [], None
    for key in sorted(fields):
        w = field_witness(kind, key, analysis, witnesses)
        if w is None:
            uncovered.append(key)
            nearest = nearest or nearest_of(kind, key, analysis, witnesses)
        else:
            family[key] = _entry_for(kind, key, w)
    base = ['no callback', 'no id reference']
    if not uncovered:
        return _record(kind, eid, name, 'data-only', base + ['every field covered'], family, None, pin_lines)
    reasons = base + ['uncovered: ' + ', '.join(uncovered)]
    return _record(kind, eid, name, 'data-only', reasons, 'none', nearest, pin_lines)


def _record(kind, eid, name, cls, reasons, family, nearest, pin_lines):
    return {'kind': kind, 'id': eid, 'name': name, 'class': cls, 'reasons': reasons, 'family': family,
            'nearest': nearest, 'pin_lines': pin_lines}


# ---- id references in the pinned code ----

def index_references(sources):
    """id -> ['file:line', ...] for every quoted lowercase id that a reference pattern names, over (rel, lines)."""
    index = {}
    for rel, lines in sources:
        for number, line in enumerate(_strip_comments(lines), 1):
            found = set()
            for pattern in REFERENCE_PATTERNS:
                found.update(pattern.findall(line))
            for m in BRACKETS.finditer(line):
                found.update(QUOTED_ID.findall(m.group(1)))
            for eid in found:
                index.setdefault(eid, []).append('%s:%d' % (rel, number))
    return index


def find_references(eid, sources):
    return index_references(sources).get(eid, [])


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
    """(token, enum suffix) -> value, for the DFI_MOVE_/DFI_ITEM_/DFI_ABILITY_ defines of the data headers."""
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
    header = ('const dfi_item_family dfi_pool_item_family[' if kind == 'item'
              else 'const dfi_ability_family dfi_pool_ability_family[')
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


def checkout_sources(checkout):
    """The pinned files that hold the references: (rel, lines). The checkout's HEAD must be the pin."""
    head = subprocess.check_output(['git', '-C', checkout, 'rev-parse', 'HEAD'], text=True).strip()
    if head != gc.PIN:
        sys.exit('classify_unsupported: the checkout is at %s, the pin is %s' % (head, gc.PIN))
    rels = ['data/conditions.ts', 'data/rulesets.ts', 'data/scripts.ts']
    rels += [os.path.relpath(p, checkout).replace(os.sep, '/') for p in sorted(glob.glob(os.path.join(checkout, 'sim', '*.ts')))]
    rels += [os.path.relpath(p, checkout).replace(os.sep, '/')
             for p in sorted(glob.glob(os.path.join(checkout, 'data', 'mods', 'champions', '*.ts')))
             if os.path.basename(p) not in EXCLUDED_CHAMPION_FILES]
    out = []
    for rel in dict.fromkeys(rels):
        full = os.path.join(checkout, rel)
        if not os.path.exists(full):
            continue
        if rel in gc.READER_INPUTS:
            out.append((rel, gc.Source(checkout, rel, gc.READER_INPUTS).lines))
        else:
            with open(full, 'rb') as f:
                out.append((rel, f.read().replace(b'\r\n', b'\n').decode('utf-8').split('\n')))
    return out


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
    references = index_references(checkout_sources(checkout))
    for kind in KINDS:
        if len(names[kind]) != EXPECTED_COUNTS[kind]:
            sys.exit('classify_unsupported: %s names: %d entries, expected %d' % (kind, len(names[kind]),
                                                                                    EXPECTED_COUNTS[kind]))
    records = []
    for kind in KINDS:
        base_rel, champ_rel = KIND_FILES[kind]
        base, champ = gc.Source(checkout, base_rel), gc.Source(checkout, champ_rel)
        unmodeled = unmodeled_text(pool_text, kind)
        families = family_names(pool_text, kind)
        analysed, witnesses, pending = {}, [], []
        for enum, eid in sorted(names[kind].items(), key=lambda kv: kv[1]):
            entries = [src.entry(eid) for src in (base, champ)]
            if entries[0] is None and entries[1] is None:
                sys.exit('classify_unsupported: %s %s not found in the pinned %s' % (kind, eid, base_rel))
            bodies = [e[2] if e else None for e in entries]
            refs = [src.ref(eid) for src, e in zip((base, champ), entries) if e]
            analysis = analyse(kind, bodies)
            name = eid
            if entries[0] is not None:
                fm = gc.fields(_strip_comments(entries[0][2])).get('name')
                if fm is not None:
                    name = gc.scalar(fm[1])
            is_marked = enum in marks[kind]
            modelled = enum not in unmodeled
            handler = specials[values[(KIND_TOKEN[kind], enum)]] if kind == 'move' else families.get(enum, 'NONE')
            if modelled and is_marked:
                witnesses.append({'id': eid, 'handler': handler, 'fields': analysis['fields'],
                                  'exact': analysis['exact']})
            else:
                pending.append((eid, name, modelled, analysis, refs))
        for eid, name, modelled, analysis, refs in pending:
            recorded = recorded_reason(name, comments) if modelled else None
            sites = [] if modelled else references.get(eid, [])
            records.append(classify_entry(kind, eid, name, modelled, analysis, witnesses,
                                          '; '.join(refs), recorded, sites))
    records.sort(key=lambda r: (KINDS.index(r['kind']), r['id']))
    return records


def summarize(records):
    counts = {}
    for kind in KINDS:
        rows = [r for r in records if r['kind'] == kind]
        counts[kind] = {cls: sum(1 for r in rows if r['class'] == cls) for cls in CLASSES}
        counts[kind]['total'] = len(rows)
        counts[kind]['family_none'] = sum(1 for r in rows if r['family'] == 'none')
        counts[kind]['no_effect_fields'] = sum(1 for r in rows if r['family'] == 'no effect fields')
    return {'counts': counts, 'entries': len(records)}


def to_json(records):
    return json.dumps({'entries': records, 'summary': summarize(records)}, indent=2, sort_keys=True) + '\n'


def table(records):
    lines = ['kind\tname\tclass\treason\twitness']
    for r in records:
        f = r['family']
        wit = '-' if f is None else (f if isinstance(f, str) else '%s (%s)' % (f['id'], f['handler']))
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
