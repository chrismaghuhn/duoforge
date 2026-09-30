#!/usr/bin/env python3
"""Verification pass of docs/research/matchup-inventory-draft.jsonl against the
pinned Pokemon Showdown files (decision 0004). Offline research tooling: it
reads data only, runs no simulator, and CTest never runs it.

usage: python3 tools/research/verify_inventory.py <dir with the pinned files>

The directory mirrors the Showdown tree (sim/, data/, config/). Files that
the inventory references and that are missing are fetched with curl from the
pinned commit, except learnsets. Output: markdown tables (species with
recomputed Champions stats, moves with overrides applied, abilities and
items) and a "Checks" section.
"""
import io
import json
import os
import re
import subprocess
import sys

if len(sys.argv) != 2:
    sys.exit(__doc__)
PS = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).replace(chr(92), '/') + '/'
BASE = 'https://raw.githubusercontent.com/smogon/pokemon-showdown/b2cb775b0616115b775534eaeff50300e1fc81fc/'
INV = REPO + 'docs/research/matchup-inventory-draft.jsonl'


def text(rel):
    return io.open(PS + rel, encoding='utf-8').read()


def entry(src_lines, key):
    for i, l in enumerate(src_lines):
        if re.match(r'^\t%s: \{' % re.escape(key), l):
            depth = 0
            for j in range(i, len(src_lines)):
                depth += src_lines[j].count('{') - src_lines[j].count('}')
                if depth <= 0:
                    return i + 1, j + 1, '\n'.join(src_lines[i:j + 1])
    return None


# ---------------------------------------------------------------- teams (decision 0004)
NATURES = {'Adamant': ('atk', 'spa'), 'Jolly': ('spe', 'spa'), 'Calm': ('spd', 'atk'), 'Timid': ('spe', 'atk'),
           'Modest': ('spa', 'atk'), 'Bold': ('def', 'atk'), 'Sassy': ('spd', 'spe')}
STATMAP = {'HP': 'hp', 'Atk': 'atk', 'Def': 'def', 'SpA': 'spa', 'SpD': 'spd', 'Spe': 'spe'}
d4 = io.open(REPO + 'docs/decisions/0004-owner-selections-champions-reference-teams.md', encoding='utf-8').read()
blocks = re.findall(r'```text\n(.*?)```', d4, re.S)
teams = []
for bi, blk in enumerate(blocks[:2]):
    for mon in blk.strip().split('\n\n'):
        ls = mon.strip().split('\n')
        name = re.sub(r' \(M\)| \(F\)', '', ls[0].split(' @ ')[0]).strip()
        item = ls[0].split(' @ ')[1].strip()
        sp = dict.fromkeys(STATMAP.values(), 0)
        nature = None
        moves = []
        ability = None
        for l in ls[1:]:
            if l.startswith('EVs:'):
                for part in l[4:].split('/'):
                    n, s = part.strip().split(' ')
                    sp[STATMAP[s]] = int(n)
            elif l.endswith('Nature'):
                nature = l.split(' ')[0]
            elif l.startswith('- '):
                moves.append(l[2:].strip())
            elif l.startswith('Ability:'):
                ability = l.split(':', 1)[1].strip()
        teams.append({'team': 'AB'[bi], 'name': name, 'item': item, 'sp': sp, 'nature': nature, 'moves': moves,
                      'ability': ability})
assert len(teams) == 12, len(teams)

dex = text('data/pokedex.ts').split('\n')


def toid(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())


def champ_stats(base, sp, nature):
    out = {}
    plus, minus = NATURES[nature]
    for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe'):
        if k == 'hp':
            out[k] = base[k] + sp[k] + 75
            continue
        v = base[k] + sp[k] + 20
        if k == plus:
            v = (v * 110) // 100
        elif k == minus:
            v = (v * 90) // 100
        out[k] = v
    return out


def species(key):
    a, b, body = entry(dex, key)
    bs = re.search(r'baseStats: \{ hp: (\d+), atk: (\d+), def: (\d+), spa: (\d+), spd: (\d+), spe: (\d+) \}', body)
    types = re.search(r'types: \[(.*?)\]', body).group(1).replace('"', '')
    w = float(re.search(r'weightkg: ([0-9.]+)', body).group(1))
    ab = re.search(r'abilities: \{(.*?)\}', body).group(1).replace('"', '').strip()
    base = dict(zip(('hp', 'atk', 'def', 'spa', 'spd', 'spe'), map(int, bs.groups())))
    return {'lines': (a, b), 'base': base, 'types': types, 'weighthg': int(round(w * 10)), 'abilities': ab}


MEGA = {'Staraptor': 'staraptormega', 'Raichu': 'raichumegay', 'Golisopod': 'golisopodmega', 'Charizard': 'charizardmegay'}
print('### Species, computed Champions stats (formula data/mods/champions/scripts.ts:10-40)\n')
print('| Team | Forme | Types | Base HP/Atk/Def/SpA/SpD/Spe | Set stats HP/Atk/Def/SpA/SpD/Spe | hg | Grass Knot BP | pokedex.ts |')
print('|---|---|---|---|---|---|---|---|')
stats_by_name = {}
for t in teams:
    keys = [toid(t['name'])] + ([MEGA[t['name']]] if t['name'] in MEGA else [])
    for k in keys:
        s = species(k)
        st = champ_stats(s['base'], t['sp'], t['nature'])
        stats_by_name[k] = st
        w = s['weighthg']
        bp = 120 if w >= 2000 else 100 if w >= 1000 else 80 if w >= 500 else 60 if w >= 250 else 40 if w >= 100 else 20
        print('| %s | %s | %s | %s | %s | %d | %d | %d-%d |' % (
            t['team'], k, s['types'], '/'.join(str(s['base'][x]) for x in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')),
            '/'.join(str(st[x]) for x in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')), w, bp, s['lines'][0], s['lines'][1]))

# ---------------------------------------------------------------- moves
mv = text('data/moves.ts').split('\n')
cmv = text('data/mods/champions/moves.ts').split('\n')
print('\n### Moves (data/moves.ts with data/mods/champions/moves.ts overrides applied)\n')
print('| Move | Users | Cat | Type | BP | Acc | Prio | Target | PP base -> Champions max | Secondary / notes | moves.ts | Override |')
print('|---|---|---|---|---|---|---|---|---|---|---|---|')
allmoves = {}
for t in teams:
    for mname in t['moves']:
        allmoves.setdefault(toid(mname), []).append(t['name'])
targets = {}
for mid in sorted(allmoves):
    a, b, body = entry(mv, mid)
    ov = entry(cmv, mid)
    merged = body
    ovtxt = ''
    fields = {}
    for f in ('accuracy', 'basePower', 'category', 'pp', 'priority', 'target', 'type'):
        mm = re.search(r'^\t\t%s: (.+?),$' % f, body, re.M)
        fields[f] = mm.group(1).strip('"') if mm else '?'
    sec = re.search(r'secondary: \{(.*?)\n\t\t\},', body, re.S)
    note = ''
    if sec:
        ch = re.search(r'chance: (\d+)', sec.group(1))
        what = re.sub(r'\s+', ' ', re.sub(r'chance: \d+,', '', sec.group(1))).strip()
        note = '%s%% %s' % (ch.group(1) if ch else '?', what)
    if ov:
        ovtxt = '%d-%d' % (ov[0], ov[1])
        for f in ('accuracy', 'basePower', 'pp', 'priority', 'target', 'type'):
            mm = re.search(r'^\t\t%s: (.+?),$' % f, ov[2], re.M)
            if mm:
                fields[f] = mm.group(1).strip('"')
        osec = re.search(r'secondary: \{(.*?)\n\t\t\},', ov[2], re.S)
        if osec:
            ch = re.search(r'chance: (\d+)', osec.group(1))
            what = re.sub(r'\s+', ' ', re.sub(r'chance: \d+,', '', osec.group(1))).strip()
            note = '%s%% %s (champions)' % (ch.group(1) if ch else '?', what)
        extra = [x for x in ('onDisableMove', 'onTry', 'self:', 'boosts') if x in ov[2] and x not in ('boosts',)]
        if extra:
            note += ' [override has ' + ', '.join(extra) + ']'
    pp = min(int(fields['pp']), 20)
    noboost = 'noPPBoosts' in body
    cpp = pp if noboost else (pp // 5 + 1) * 4
    targets[mid] = fields['target']
    print('| %s | %s | %s | %s | %s | %s | %s | %s | %s -> %d | %s | %d-%d | %s |' % (
        mid, ', '.join(sorted(set(allmoves[mid]))), fields['category'][:4], fields['type'], fields['basePower'],
        fields['accuracy'], fields['priority'], fields['target'], fields['pp'], cpp, note, a, b, ovtxt))

# ---------------------------------------------------------------- abilities / items
ab = text('data/abilities.ts').split('\n')
cab = text('data/mods/champions/abilities.ts').split('\n')
it = text('data/items.ts').split('\n')
cit = text('data/mods/champions/items.ts').split('\n')
megas_ab = {'staraptormega': 'Contrary', 'raichumegay': 'No Guard', 'golisopodmega': 'Tough Claws', 'charizardmegay': 'Drought'}
print('\n### Abilities and items in the closure\n')
print('| Kind | Name | Holder | Base lines | Champions override |')
print('|---|---|---|---|---|')
for t in teams:
    e = entry(ab, toid(t['ability']))
    o = entry(cab, toid(t['ability']))
    print('| ability | %s | %s | data/abilities.ts:%d-%d | %s |' % (t['ability'], t['name'], e[0], e[1],
                                                                  'abilities.ts:%d-%d' % (o[0], o[1]) if o else '-'))
for k, a in megas_ab.items():
    e = entry(ab, toid(a))
    o = entry(cab, toid(a))
    print('| ability (Mega) | %s | %s | data/abilities.ts:%d-%d | %s |' % (a, k, e[0], e[1],
                                                                          'abilities.ts:%d-%d' % (o[0], o[1]) if o else '-'))
for t in teams:
    e = entry(it, toid(t['item']))
    o = entry(cit, toid(t['item']))
    print('| item | %s | %s | data/items.ts:%d-%d | %s |' % (t['item'], t['name'], e[0], e[1],
                                                           'items.ts:%d-%d' % (o[0], o[1]) if o else '-'))

# ---------------------------------------------------------------- checks
print('\n### Checks\n')
rows = [json.loads(l) for l in io.open(INV, encoding='utf-8').read().split('\n') if l.strip()]
# (1) reference bounds
refs = {}
for r in rows:
    for mm in r['mechanics']:
        for ref in mm.get('showdown_refs', []):
            refs.setdefault(ref, []).append((r['pokemon_agent'], mm['id']))
noline = sorted(ref for ref in refs if not re.search(r':\d', ref))
files = sorted({ref.split(':')[0] for ref in refs if ref not in noline})
lengths = {}
missing = []
for f in files:
    p = PS + f
    if not os.path.exists(p) and 'learnsets' not in f:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        subprocess.run(['curl', '-sSf', '-o', p, BASE + f])
    if os.path.exists(p):
        lengths[f] = len(io.open(p, encoding='utf-8').read().split('\n'))
    else:
        missing.append(f)
bad = []
for ref in refs:
    f, _, rng = ref.partition(':')
    if f not in lengths or ref in noline:
        continue
    nums = [int(x) for x in re.findall(r'\d+', rng)]
    if not nums or max(nums) > lengths[f] or (len(nums) >= 2 and nums[0] > nums[1]):
        bad.append(ref)
print('- References: %d distinct across %d files; files not fetched: %s; out-of-range references: %s; '
      'references without a line range: %s' % (len(refs), len(files), missing or 'none', bad or 'none', noline or 'none'))
# (2) species stat lines quoted in the rows
mismatch = []
checked = 0
for r in rows:
    for mm in r['mechanics']:
        if mm['category'] != 'species':
            continue
        key = toid(r['pokemon_agent'].split('-', 2)[2])
        for found in re.finditer(r'HP (\d+), Atk (\d+), Def (\d+), SpA (\d+), SpD (\d+), Spe (\d+)', mm['behavior']):
            got = tuple(map(int, found.groups()))
            cands = [k for k in stats_by_name if k.startswith(key)]
            ok = any(got == tuple(stats_by_name[k][x] for x in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')) for k in cands)
            checked += 1
            if not ok:
                mismatch.append((r['pokemon_agent'], got))
print('- Species stat lines quoted in the rows: %d checked against the recomputed formula; mismatches: %s' % (
    checked, mismatch or 'none'))
# (3) M2 fixture table T1 mirrors the pinned target classes
order = ['woodhammer', 'grassyglide', 'fakeout', 'highhorsepower', 'bravebird', 'closecombat', 'tailwind', 'protect',
         'muddywater', 'coil', 'icebeam', 'hypnosis', 'bitterblade', 'shadowsneak', 'swordsdance', 'zapcannon',
         'focusblast', 'makeitrain', 'shadowball', 'nastyplot', 'weatherball', 'leechlife', 'ironhead', 'drillrun',
         'dragonpulse', 'electroshot', 'snarl', 'psychic', 'grassknot', 'trickroom', 'heatwave', 'hurricane',
         'spiritbreak', 'reflect', 'lightscreen', 'partingshot']
cls = {'normal': 1, 'any': 2, 'self': 6, 'allAdjacentFoes': 7, 'allySide': 8, 'all': 9}
t1 = [1, 1, 1, 1, 2, 1, 8, 6, 7, 6, 1, 1, 1, 1, 6, 1, 1, 7, 1, 6, 1, 1, 1, 1, 2, 1, 7, 1, 1, 9, 7, 2, 1, 8, 8, 1]
diff = [o for o, c in zip(order, t1) if cls[targets[o]] != c]
print('- M2 fixture table T1 vs pinned target classes (36 moves): %s' % ('identical' if not diff else diff))
print('- Distinct moves %d, rows %d, mechanics %d' % (len(allmoves), len(rows), sum(len(r['mechanics']) for r in rows)))
