"""Split tools/datagen/gen_closure.py into the area modules of tools/datagen/tablegen/ (restructure step 5).

Every top-level statement moves verbatim, with the comment lines right above it, into the module of its area
(area3.json, from assign.py), in its original order. Each module imports, by name, what it uses from lower modules.
gen_closure.py keeps its docstring and main() and re-exports every name of the modules.
Usage: python3 split.py <repo> <dir of stmts.json and area3.json> <base commit>
"""
import json
import os
import sys
from collections import defaultdict

repo, s5, base = sys.argv[1], sys.argv[2], sys.argv[3]
src_path = os.path.join(repo, 'tools', 'datagen', 'gen_closure.py')
lines = open(src_path).read().split('\n')
S = json.load(open(os.path.join(s5, 'stmts.json')))['stmts']
area = {int(k): v for k, v in json.load(open(os.path.join(s5, 'area3.json'))).items()}
ORDER = ['source', 'species', 'moves', 'families', 'items', 'abilities', 'rules', 'tables', 'output']
DOC = {
    'source': 'The pinned Showdown inputs and the shared parsing helpers: the pin and the input hashes, Source (a pinned\n'
              'file read with its hash checked), the entry parsers, the id and name helpers and the pattern matchers.',
    'species': 'Formes and Pokemon: the reference team sets, the forme and type chart parsers, the format\'s legal pool,\n'
               'the learnsets and the forme legality.',
    'moves': 'Moves: the move parser and its key, flag, target and status tables, the special handlers and their pinned\n'
             'callbacks by step, the move and field-condition facts and their checks.',
    'families': 'What the item and ability families share: the parameter codes of weather and terrain, the family\n'
                'derivation from one strict pattern, the handler ids and the rows the turn code implements by id.',
    'items': 'Items: the item families (type boosters, resist berries and the rest), their matchers and parameters, the\n'
             'item facts by step and their checks.',
    'abilities': 'Abilities: the ability families (-ate, pinch, weather and terrain setters), their matchers and\n'
                 'parameters, the ability facts by step and their checks.',
    'rules': 'The pin checks of steps that span moves, items and abilities: the cross-area facts of single steps and\n'
             'the content batches (C1, C2, C4, C5, K2, A0, A0P1).',
    'tables': 'The table assembly: the closure, Team C and pool builds and the width bounds the pool has to fit.',
    'output': 'The output: the canonical byte forms and the C writers of the closure, extended and pool tables.',
}
defs = {n: s['i'] for s in S for n in s['defines']}
mod_of = {}
for s in S:
    for n in s['defines']:
        mod_of[n] = area[s['i']]
# The text of each statement: its lines and the comment lines directly above it (back to the previous statement).
starts = {}
prev_end = None
first = None
for s in S:
    if s['i'] == 0:
        prev_end = s['end']  # the module docstring stays in gen_closure.py
        continue
    # everything between the previous statement and this one (blank lines, comments) travels with this one
    starts[s['i']] = prev_end
    prev_end = s['end']
out = defaultdict(list)
last_def = {}
imports = defaultdict(lambda: defaultdict(set))
std = {'hashlib', 'io', 'json', 'os', 're', 'sys', 'gen_format'}
for s in S:
    if s['i'] == 0:
        continue
    a = area[s['i']]
    if a == 'main':
        continue
    if s['kind'] in ('Import', 'ImportFrom'):
        continue
    text = lines[starts[s['i']]:s['end']]
    is_def = s['kind'] in ('FunctionDef', 'ClassDef')
    if out[a] and (is_def or last_def.get(a)):
        # a function or class has two blank lines on each side, as in the original file
        while text and not text[0].strip():
            text = text[1:]
        text = ['', ''] + text
    last_def[a] = is_def
    out[a].append('\n'.join(text))
    for u in s['uses']:
        if u in std:
            imports[a]['__std__'].add(u)
        elif u in mod_of and mod_of[u] != a:
            assert ORDER.index(mod_of[u]) < ORDER.index(a), (s['defines'], a, u, mod_of[u])
            imports[a][mod_of[u]].add(u)
pkg = os.path.join(repo, 'tools', 'datagen', 'tablegen')
os.makedirs(pkg, exist_ok=True)


def wrap_import(mod, names):
    head = 'from .%s import ' % mod
    names = sorted(names, key=lambda n: (n.lower(), n))
    one = head + ', '.join(names)
    if len(one) <= 120:
        return one
    rows, cur = [], ''
    for n in names:
        piece = n + ', '
        if len('    ' + cur + piece) > 120:
            rows.append('    ' + cur.rstrip())
            cur = ''
        cur += piece
    rows.append('    ' + cur.rstrip().rstrip(','))
    return head + '(\n' + '\n'.join(rows) + ')'


for a in ORDER:
    head = ['"""%s\n\nPart of the table generator tools/datagen/gen_closure.py (restructure step 5: split by area; every\n'
            'statement is unchanged from gen_closure.py@%s).\n"""' % (DOC[a], base[:8])]
    std_used = sorted(imports[a].get('__std__', ()))
    head += ['import %s' % m for m in std_used if m != 'gen_format']
    if 'gen_format' in std_used:
        head.append('')
        head.append('import gen_format')
    deps = [m for m in ORDER if m in imports[a] and m != '__std__']
    if deps:
        head.append('')
        head += [wrap_import(m, imports[a][m]) for m in deps]
    body = '\n'.join(out[a]).lstrip('\n')
    gap = '\n\n\n' if body.startswith(('def ', 'class ')) else '\n\n'
    text = '\n'.join(head) + gap + body.rstrip('\n') + '\n'
    open(os.path.join(pkg, a + '.py'), 'w').write(text)
open(os.path.join(pkg, '__init__.py'), 'w').write(
    '"""The area modules of the table generator (tools/datagen/gen_closure.py, restructure step 5)."""\n')

# gen_closure.py: the docstring, the imports, the re-export, main() and the __main__ block.
main_s = [s for s in S if area[s['i']] == 'main']
doc_end = S[0]['end']
gc = lines[:doc_end]
gc += ['import hashlib', 'import io', 'import json', 'import os', 'import sys', '']
gc += ['from tablegen import %s' % ', '.join(sorted(ORDER)), '',
       '# Every name of the area modules stays readable as gen_closure.<name> (the tests, classify_unsupported.py and',
       '# tools/reference/team_registry.py read the parsers, the pin and the fact tables from here); main() below uses',
       '# build, build_pool, check_prefix, check_pool_prefix, render, render_ext, render_pool and feature_summary.',
       'for _area in (%s):' % ', '.join(ORDER),
       "    globals().update({k: v for k, v in vars(_area).items() if not k.startswith('__')})",
       'del _area', '', '']
for s in main_s:
    gc.append('\n'.join(lines[starts[s['i']]:s['end']]).lstrip('\n'))
    gc.append('')
    gc.append('')
text = '\n'.join(gc).rstrip('\n') + '\n'
open(src_path, 'w').write(text)
for a in ORDER:
    print(a, sum(1 for _ in open(os.path.join(pkg, a + '.py'))))
print('gen_closure.py', len(text.split('\n')) - 1)
