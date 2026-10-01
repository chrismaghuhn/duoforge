#!/usr/bin/env python3
"""Generates src/data/closure_tables.{h,c}: the immutable data of the two
reference teams (decision 0004) read from the pinned Pokemon Showdown
checkout (decision 0006 section 2).

usage: python3 tools/datagen/gen_closure.py <pinned checkout> [--check]

  --check   do not write; exit 1 if the committed files differ.

Offline tooling. It extracts static data only; every effect still needs a
typed handler in C (decision 0006). It fails, instead of guessing, when an
input hash differs from the pin, when a move has a field it does not know,
or when a callback is not mapped to a named handler id. CTest never needs
Python: the generated files are committed.
"""
import hashlib
import io
import os
import re
import sys

PIN = 'b2cb775b0616115b775534eaeff50300e1fc81fc'

# sha256 of the input files at the pin, after CRLF -> LF normalisation.
INPUTS = {
    'data/pokedex.ts': '73048386b864be5aff093e9393acf32e8016299e9d7b76078bf5120b769e2fe0',
    'data/moves.ts': '6b44af2a393739e00fc444dc574eaa79659b68867777012b0f7ce4727a9b7734',
    'data/abilities.ts': '818edd100c8eb5bdf4d4ded8dd1b1ce9d394f87f40f7d9d53a5414276e84f82b',
    'data/items.ts': '75da206e2cb09868bb549360f38a144c2f50b24e1d189e03b485d550a4f6357a',
    'data/typechart.ts': '7b0eae126bdcf98edfd71cbe75af00b763f5f0d5db36024b6f3e7c5e4aea95ac',
    'data/natures.ts': '5cfefee4c23dd19f629deb9a67f75361226bd24fe34cefe9a13d30d985428416',
    'data/mods/champions/moves.ts': '1d317da33d3e36d430a9cbe195c2ef9bb9a6fc2f3e0516ba2200da8a394080bc',
    'data/mods/champions/items.ts': 'b39dafa66d136ebb1a8576367ced2c9f4519aa1c17d5d65c59b368ac15d7de77',
    'data/mods/champions/abilities.ts': '86c3843d402f1ff7be276d8f2da08d6744b8a8822349560b300ddcfa9c1fbc52',
    'data/mods/champions/formats-data.ts': 'a512b537a84574a324c250c6ff99ad60f0cf1e82420fdae60d4635eec8661e13',
    'data/mods/champions/learnsets.ts': '826d302703358260a1c4967e2bf8edd15f1fe7e0f664c8ab14aff734906cc9d0',
    'data/mods/champions/scripts.ts': 'a6cc11eeb525ad58dee9010dd0d42274a5b4dacb39ce8653f4888cbd2f4f459d',
}

# The closure: the two teams of decision 0004.
# (species, ability, item, moves, mega forme or None)
SETS = [
    ('rillaboom', 'grassysurge', 'miracleseed', ['woodhammer', 'grassyglide', 'fakeout', 'highhorsepower'], None),
    ('staraptor', 'intimidate', 'staraptite', ['bravebird', 'closecombat', 'tailwind', 'protect'], 'staraptormega'),
    ('milotic', 'competitive', 'sitrusberry', ['muddywater', 'coil', 'icebeam', 'hypnosis'], None),
    ('ceruledge', 'flashfire', 'grassyseed', ['bitterblade', 'shadowsneak', 'swordsdance', 'protect'], None),
    ('raichu', 'lightningrod', 'raichunitey', ['zapcannon', 'focusblast', 'fakeout', 'protect'], 'raichumegay'),
    ('gholdengo', 'goodasgold', 'lifeorb', ['makeitrain', 'shadowball', 'nastyplot', 'protect'], None),
    ('politoed', 'drizzle', 'mysticwater', ['weatherball', 'muddywater', 'icebeam', 'protect'], None),
    ('golisopod', 'emergencyexit', 'golisopite', ['leechlife', 'ironhead', 'drillrun', 'protect'], 'golisopodmega'),
    ('archaludon', 'stamina', 'leftovers', ['dragonpulse', 'electroshot', 'snarl', 'protect'], None),
    ('farigiraf', 'armortail', 'sitrusberry', ['psychic', 'grassknot', 'trickroom', 'protect'], None),
    ('charizard', 'blaze', 'charizarditey', ['heatwave', 'weatherball', 'hurricane', 'protect'], 'charizardmegay'),
    ('grimmsnarl', 'prankster', 'lightclay', ['spiritbreak', 'reflect', 'lightscreen', 'partingshot'], None),
]

# Move ids 0..35 in the order of decision 0005 (fixture table T1); Struggle is 36.
MOVES = ['woodhammer', 'grassyglide', 'fakeout', 'highhorsepower', 'bravebird', 'closecombat', 'tailwind', 'protect',
         'muddywater', 'coil', 'icebeam', 'hypnosis', 'bitterblade', 'shadowsneak', 'swordsdance', 'zapcannon',
         'focusblast', 'makeitrain', 'shadowball', 'nastyplot', 'weatherball', 'leechlife', 'ironhead', 'drillrun',
         'dragonpulse', 'electroshot', 'snarl', 'psychic', 'grassknot', 'trickroom', 'heatwave', 'hurricane',
         'spiritbreak', 'reflect', 'lightscreen', 'partingshot', 'struggle']

TYPES = ['Bug', 'Dark', 'Dragon', 'Electric', 'Fairy', 'Fighting', 'Fire', 'Flying', 'Ghost', 'Grass', 'Ground',
         'Ice', 'Normal', 'Poison', 'Psychic', 'Rock', 'Steel', 'Water']
STATS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe']
BOOSTS = ['atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion']
CATEGORIES = {'Physical': 0, 'Special': 1, 'Status': 2}
TARGET_CLASS = {'normal': 1, 'any': 2, 'adjacentAlly': 3, 'adjacentAllyOrSelf': 4, 'adjacentFoe': 5, 'self': 6,
                'allAdjacentFoes': 7, 'allySide': 8, 'all': 9, 'randomNormal': 10}
STATUS = {'brn': 1, 'frz': 2, 'par': 3, 'slp': 4}
VOLATILE = {'flinch': 1, 'confusion': 2}
SIDE_CONDITION = {'tailwind': 1, 'reflect': 2, 'lightscreen': 3}
PSEUDO_WEATHER = {'trickroom': 1}
STATUS_IMMUNITY = {'brn': 1, 'frz': 2, 'par': 4, 'prankster': 8}
# Type-chart keys without a consumer in the closure (no poison source, powder
# move, sandstorm or hail, and no trapping).
IGNORED_TYPE_KEYS = {'psn', 'tox', 'powder', 'sandstorm', 'hail', 'trapped'}

FLAG_BITS = {'contact': 1, 'protect': 2, 'charge': 4}
EXTRA_FLAG_BITS = {'stallingMove': 8, 'selfSwitch': 16, 'noPPBoosts': 32, 'struggleRecoil': 64}
# Move flags without a consumer in the closure (no Soundproof, Bulletproof,
# Mega Launcher, Sharpness, Wind Rider, Magic Bounce, Snatch, Dancer, Heal
# Block, Gravity, Metronome, Mirror Move, Assist, Copycat, Substitute, Encore,
# Me First, Sleep Talk, Mimic, Instruct or Sketch).
IGNORED_FLAGS = {'bullet', 'bypasssub', 'dance', 'distance', 'failcopycat', 'failencore', 'failinstruct',
                 'failmefirst', 'failmimic', 'heal', 'metronome', 'mirror', 'noassist', 'nonsky', 'nosketch',
                 'nosleeptalk', 'pulse', 'reflectable', 'slicing', 'snatch', 'sound', 'wind'}
# Callbacks are code, not data. Each one is accounted for by a named handler.
SPECIAL = {
    'grassknot': ('GRASS_KNOT', {'basePowerCallback', 'onTryHit'}),
    'weatherball': ('WEATHER_BALL', {'onModifyType', 'onModifyMove'}),
    'hurricane': ('HURRICANE', {'onModifyMove'}),
    'grassyglide': ('GRASSY_GLIDE', {'onModifyPriority'}),
    'electroshot': ('ELECTRO_SHOT', {'onTryMove'}),
    'fakeout': ('FAKE_OUT', {'onTry', 'onDisableMove'}),
    'partingshot': ('PARTING_SHOT', {'onHit'}),
    'protect': ('PROTECT', {'onPrepareHit', 'onHit'}),
    'struggle': ('STRUGGLE', {'onModifyMove'}),
}
SPECIAL_IDS = ['NONE', 'GRASS_KNOT', 'WEATHER_BALL', 'HURRICANE', 'GRASSY_GLIDE', 'ELECTRO_SHOT', 'FAKE_OUT',
               'PARTING_SHOT', 'PROTECT', 'STRUGGLE']
DATA_KEYS = {'num', 'accuracy', 'basePower', 'category', 'name', 'pp', 'priority', 'flags', 'target', 'type',
             'critRatio', 'secondary', 'self', 'boosts', 'recoil', 'drain', 'status', 'volatileStatus',
             'sideCondition', 'pseudoWeather', 'selfSwitch', 'stallingMove', 'noPPBoosts', 'struggleRecoil',
             'condition'}
# Keys that describe other generations, contests or mechanics outside the
# closure (Z-Moves, Max Moves, Sheer Force), or mod bookkeeping.
IGNORED_KEYS = {'contestType', 'zMove', 'maxMove', 'isNonstandard', 'hasSheerForceBoost', 'inherit'}
BOOST_ROLE = {'NONE': 0, 'PRIMARY_SELF': 1, 'SECONDARY_TARGET': 2, 'SELF_AFTER_HIT': 3}


def fail(msg):
    sys.exit('gen_closure: ' + msg)


class Source:
    def __init__(self, root, rel):
        raw = io.open(os.path.join(root, rel), 'rb').read().replace(b'\r\n', b'\n')
        got = hashlib.sha256(raw).hexdigest()
        if got != INPUTS[rel]:
            fail('%s: sha256 %s differs from the pin %s' % (rel, got, INPUTS[rel]))
        self.rel = rel
        self.lines = raw.decode('utf-8').split('\n')

    def entry(self, key):
        """Returns (first line, last line, body lines) of the top-level entry or None."""
        for i, line in enumerate(self.lines):
            if re.match(r'^\t%s: \{' % re.escape(key), line):
                if line.rstrip().endswith('},'):  # one-line entry
                    return i + 1, i + 1, [line]
                depth = 0
                for j in range(i, len(self.lines)):
                    depth += self.lines[j].count('{') - self.lines[j].count('}')
                    if depth <= 0:
                        return i + 1, j + 1, self.lines[i:j + 1]
        return None

    def ref(self, key):
        e = self.entry(key)
        if e is None:
            fail('%s: entry %s not found' % (self.rel, key))
        return '%s:%d-%d' % (self.rel, e[0], e[1])


def fields(body):
    """Top-level fields of an entry body: name -> (is_function, text)."""
    out = {}
    name = None
    for line in body[1:-1]:
        m = re.match(r'^\t\t([A-Za-z]+)([:(])', line)
        if m:
            name = m.group(1)
            out[name] = [m.group(2) == '(', line]
        elif name is not None:
            out[name][1] += '\n' + line
    return out


def scalar(text):
    v = text.split(':', 1)[1].strip().rstrip(',')
    if v == 'true':
        return True
    if v == 'false':
        return False
    if re.match(r'^-?\d+$', v):
        return int(v)
    return v.strip('"\'')


def boosts_of(text):
    vec = [0] * len(BOOSTS)
    found = re.findall(r'\b(atk|def|spa|spd|spe|accuracy|evasion): (-?\d+)', text)
    if not found:
        fail('no boosts in %r' % text[:60])
    for name, val in found:
        vec[BOOSTS.index(name)] = int(val)
    return vec


def parse_move(mid, base, champ):
    e = base.entry(mid)
    if e is None:
        fail('move %s not found' % mid)
    f = fields(e[2])
    ce = champ.entry(mid)
    refs = [base.ref(mid)]
    if ce is not None:
        cf = fields(ce[2])
        if 'inherit' not in cf:
            fail('champions override of %s does not inherit' % mid)
        f.update(cf)
        refs.append(champ.ref(mid))
    handled = SPECIAL.get(mid, ('NONE', set()))
    for name, (is_fn, _text) in f.items():
        if is_fn:
            if name not in handled[1]:
                fail('move %s: callback %s is not mapped to a handler' % (mid, name))
        elif name not in DATA_KEYS and name not in IGNORED_KEYS:
            fail('move %s: unknown field %s' % (mid, name))
    missing = handled[1] - set(n for n, v in f.items() if v[0])
    if missing:
        fail('move %s: expected callbacks %s are absent' % (mid, sorted(missing)))

    def get(name, default=None):
        return scalar(f[name][1]) if name in f else default

    flags = 0
    for fl in re.findall(r'(\w+): 1', f['flags'][1]):
        if fl in FLAG_BITS:
            flags |= FLAG_BITS[fl]
        elif fl not in IGNORED_FLAGS:
            fail('move %s: unknown flag %s' % (mid, fl))
    for key, bit in EXTRA_FLAG_BITS.items():
        if get(key, False):
            flags |= bit
    acc = get('accuracy')
    pp_base = get('pp')
    pp_capped = min(pp_base, 20)  # champions init(): data/mods/champions/scripts.ts:3-9
    if flags & EXTRA_FLAG_BITS['noPPBoosts']:
        pp_max = pp_capped
    else:
        if pp_capped % 5 != 0:
            fail('move %s: pp %d is not a multiple of 5' % (mid, pp_capped))
        pp_max = (pp_capped // 5 + 1) * 4  # calculatePP: scripts.ts:41-43
    rec = {
        'id': mid, 'name': get('name'), 'refs': refs,
        'type': TYPES.index(get('type')), 'category': CATEGORIES[get('category')],
        'base_power': get('basePower'), 'accuracy': 0 if acc is True else acc, 'pp_base': pp_base, 'pp_max': pp_max,
        'priority': get('priority') + 8, 'target_class': TARGET_CLASS[get('target')],
        'crit_ratio': get('critRatio', 1), 'flags': flags,
        'recoil': [0, 0], 'drain': [0, 0], 'sec_chance': 0, 'sec_kind': 0, 'sec_param': 0,
        'boost_role': 0, 'boosts': [0] * 7, 'primary_status': 0, 'side_condition': 0, 'pseudo_weather': 0,
        'special': SPECIAL_IDS.index(handled[0]),
    }
    for key in ('recoil', 'drain'):
        if key in f:
            nums = [int(x) for x in re.findall(r'\d+', f[key][1])]
            if len(nums) != 2:
                fail('move %s: %s is not a fraction' % (mid, key))
            rec[key] = nums
    vectors = 0
    if 'secondary' in f:
        text = f['secondary'][1]
        rec['sec_chance'] = int(re.search(r'chance: (\d+)', text).group(1))
        st = re.search(r"\bstatus: '(\w+)'", text)
        vo = re.search(r"volatileStatus: '(\w+)'", text)
        if st:
            rec['sec_kind'], rec['sec_param'] = 2, STATUS[st.group(1)]
        elif vo:
            rec['sec_kind'], rec['sec_param'] = 3, VOLATILE[vo.group(1)]
        elif 'boosts' in text:
            rec['sec_kind'] = 1
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['SECONDARY_TARGET'], boosts_of(text)
            vectors += 1
        else:
            fail('move %s: unknown secondary' % mid)
    if 'self' in f:
        rec['boost_role'], rec['boosts'] = BOOST_ROLE['SELF_AFTER_HIT'], boosts_of(f['self'][1])
        vectors += 1
    if 'boosts' in f:
        if rec['target_class'] != TARGET_CLASS['self']:
            fail('move %s: primary boosts on a non-self target' % mid)
        rec['boost_role'], rec['boosts'] = BOOST_ROLE['PRIMARY_SELF'], boosts_of(f['boosts'][1])
        vectors += 1
    if vectors > 1:
        fail('move %s: more than one boost vector' % mid)
    if 'status' in f:
        rec['primary_status'] = STATUS[get('status')]
    if 'volatileStatus' in f and get('volatileStatus') != 'protect':
        fail('move %s: unknown primary volatile' % mid)
    if 'sideCondition' in f:
        rec['side_condition'] = SIDE_CONDITION[get('sideCondition')]
    if 'pseudoWeather' in f:
        rec['pseudo_weather'] = PSEUDO_WEATHER[get('pseudoWeather')]
    if 'condition' in f and not (rec['side_condition'] or rec['pseudo_weather'] or mid == 'protect'):
        fail('move %s: condition block without a known owner' % mid)
    for k in ('base_power', 'accuracy', 'pp_base', 'pp_max', 'priority', 'crit_ratio'):
        if not 0 <= rec[k] <= 255:
            fail('move %s: %s out of range' % (mid, k))
    return rec


def toid(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def parse_forme(key, dex, formats):
    e = dex.entry(key)
    if e is None:
        fail('species %s not found' % key)
    text = '\n'.join(e[2])
    if formats.entry(key) is None:
        fail('species %s has no champions formats-data entry' % key)
    bs = re.search(r'baseStats: \{ hp: (\d+), atk: (\d+), def: (\d+), spa: (\d+), spd: (\d+), spe: (\d+) \}', text)
    types = [t.strip().strip('"') for t in re.search(r'types: \[(.*?)\]', text).group(1).split(',')]
    gender = re.search(r'\bgender: "(\w)"', text)
    return {
        'id': key, 'name': re.search(r'name: "(.*?)"', text).group(1), 'ref': dex.ref(key),
        'dex_num': int(re.search(r'num: (\d+)', text).group(1)),
        'types': [TYPES.index(types[0]), TYPES.index(types[1]) if len(types) > 1 else 0xFF],
        'base': [int(x) for x in bs.groups()],
        'weight_hg': int(round(float(re.search(r'weightkg: ([0-9.]+)', text).group(1)) * 10)),
        'abilities': [toid(a) for a in re.findall(r'[0-9A-Z]+: "(.*?)"', re.search(r'abilities: \{(.*?)\}', text).group(1))],
        'gender_rule': {'M': 1, 'F': 2, 'N': 3}[gender.group(1)] if gender else 0,
        'required_item': toid(re.search(r'requiredItem: "(.*?)"', text).group(1)) if 'requiredItem' in text else None,
    }


def build(root):
    src = {rel: Source(root, rel) for rel in INPUTS}
    dex, moves_ts, champ_moves = src['data/pokedex.ts'], src['data/moves.ts'], src['data/mods/champions/moves.ts']
    items_ts, champ_items = src['data/items.ts'], src['data/mods/champions/items.ts']
    abil_ts, champ_abil = src['data/abilities.ts'], src['data/mods/champions/abilities.ts']
    formats, learn = src['data/mods/champions/formats-data.ts'], src['data/mods/champions/learnsets.ts']

    moves = [parse_move(m, moves_ts, champ_moves) for m in MOVES]
    move_index = {m['id']: i for i, m in enumerate(moves)}

    items, item_index = [], {}
    for _sp, _ab, item, _mv, _mega in SETS:
        if item not in item_index:
            e = items_ts.entry(item)
            if e is None:
                fail('item %s not found' % item)
            refs = [items_ts.ref(item)]
            if champ_items.entry(item) is not None:
                refs.append(champ_items.ref(item))
            text = '\n'.join(e[2])
            stone = re.search(r'megaStone: \{ "(.*?)": "(.*?)" \}', text)
            if 'isNonstandard' in text and champ_items.entry(item) is None:
                fail('item %s is nonstandard and has no champions override' % item)
            item_index[item] = len(items)
            items.append({'id': item, 'name': re.search(r'name: "(.*?)"', text).group(1), 'refs': refs,
                          'stone': (toid(stone.group(1)), toid(stone.group(2))) if stone else None})

    abilities, ability_index = [], {}

    def add_ability(aid):
        if aid not in ability_index:
            if abil_ts.entry(aid) is None:
                fail('ability %s not found' % aid)
            refs = [abil_ts.ref(aid)]
            if champ_abil.entry(aid) is not None:
                refs.append(champ_abil.ref(aid))
            ability_index[aid] = len(abilities)
            abilities.append({'id': aid, 'refs': refs})

    for _sp, ab, _it, _mv, _mega in SETS:
        add_ability(ab)

    formes, forme_index = [], {}
    for sp, ab, item, mv, mega in SETS:
        fo = parse_forme(sp, dex, formats)
        if ab not in fo['abilities']:
            fail('%s cannot have ability %s' % (sp, ab))
        le = learn.entry(sp)
        if le is None:
            fail('%s has no champions learnset' % sp)
        ltext = '\n'.join(le[2])
        for m in mv:
            if not re.search(r'\b%s: \[' % m, ltext):
                fail('%s cannot learn %s in champions' % (sp, m))
        fo.update({'ability': ability_index[ab], 'set_item': item_index[item],
                   'set_moves': [move_index[m] for m in mv], 'mega': mega, 'is_mega': 0})
        forme_index[sp] = len(formes)
        formes.append(fo)
        if mega:
            mf = parse_forme(mega, dex, formats)
            stone = items[item_index[item]]['stone']
            if stone != (sp, mega) or mf['required_item'] != item:
                fail('%s: %s is not the stone for %s' % (sp, item, mega))
            if len(mf['abilities']) != 1:
                fail('%s: expected exactly one ability' % mega)
            add_ability(mf['abilities'][0])
            mf.update({'ability': ability_index[mf['abilities'][0]], 'set_item': item_index[item],
                       'set_moves': [], 'mega': None, 'is_mega': 1, 'gender_rule': fo['gender_rule']})
            forme_index[mega] = len(formes)
            formes.append(mf)
    for fo in formes:
        base = fo['id'] if not fo['is_mega'] else [s for s, _a, _i, _m, mg in SETS if mg == fo['id']][0]
        fo['base_forme'] = forme_index[base]
        fo['mega_forme'] = forme_index[fo['mega']] if fo['mega'] else 0xFF
        fo['mega_item'] = fo['set_item'] if (fo['mega'] or fo['is_mega']) else 0xFF
    for it in items:
        it['mega_base'] = forme_index[it['stone'][0]] if it['stone'] else 0xFF
        it['mega_forme'] = forme_index[it['stone'][1]] if it['stone'] else 0xFF

    tc = src['data/typechart.ts']
    chart, immunity = [], []
    for t in TYPES:
        e = tc.entry(t.lower())
        text = '\n'.join(e[2])
        row = []
        for a in TYPES:
            row.append(int(re.search(r'\b%s: (\d)' % a, text).group(1)))
        chart.append(row)
        imm = 0
        for key, val in re.findall(r'^\t\t\t([a-z]+): (\d),', text, re.M):
            if val != '3':
                fail('type %s: status key %s is not an immunity' % (t, key))
            if key in STATUS_IMMUNITY:
                imm |= STATUS_IMMUNITY[key]
            elif key not in IGNORED_TYPE_KEYS:
                fail('type %s: unknown key %s' % (t, key))
        immunity.append(imm)

    nat_src = src['data/natures.ts']
    natures = []
    for m in re.finditer(r'^\t([a-z]+): \{\n(.*?)\n\t\},', '\n'.join(nat_src.lines), re.S | re.M):
        plus = re.search(r"plus: '(\w+)'", m.group(2))
        minus = re.search(r"minus: '(\w+)'", m.group(2))
        natures.append({'id': m.group(1), 'plus': STATS.index(plus.group(1)) if plus else 0xFF,
                        'minus': STATS.index(minus.group(1)) if minus else 0xFF})
    if len(natures) != 25:
        fail('expected 25 natures, found %d' % len(natures))
    return {'formes': formes, 'moves': moves, 'items': items, 'abilities': abilities, 'chart': chart,
            'immunity': immunity, 'natures': natures}


def canonical(d):
    """The canonical table bytes hashed into the context fingerprint."""
    b = bytearray()

    def u16(v):
        b.extend([v & 0xFF, (v >> 8) & 0xFF])

    for n in (len(d['formes']), len(d['moves']), len(d['items']), len(d['abilities']), len(TYPES), len(d['natures'])):
        u16(n)
    for f in d['formes']:
        u16(f['dex_num'])
        b.extend(f['types'])
        b.extend(f['base'])
        u16(f['weight_hg'])
        b.extend([f['ability'], f['gender_rule'], f['is_mega'], f['base_forme'], f['mega_forme'], f['mega_item'],
                  f['set_item'], len(f['set_moves'])])
        b.extend(f['set_moves'] + [0] * (4 - len(f['set_moves'])))
    for m in d['moves']:
        b.extend([m['type'], m['category'], m['base_power'], m['accuracy'], m['pp_base'], m['pp_max'], m['priority'],
                  m['target_class'], m['crit_ratio'], m['flags'], m['recoil'][0], m['recoil'][1], m['drain'][0],
                  m['drain'][1], m['sec_chance'], m['sec_kind'], m['sec_param'], m['boost_role']])
        b.extend(v + 6 for v in m['boosts'])
        b.extend([m['primary_status'], m['side_condition'], m['pseudo_weather'], m['special']])
    for it in d['items']:
        b.extend([it['mega_base'], it['mega_forme']])
    for row in d['chart']:
        b.extend(row)
    b.extend(d['immunity'])
    for n in d['natures']:
        b.extend([n['plus'], n['minus']])
    return bytes(b)


def define_block(prefix, names):
    return '\n'.join('#define %s_%s %du' % (prefix, n.upper(), i) for i, n in enumerate(names))


def render(d):
    can = canonical(d)
    digest = hashlib.sha256(can).hexdigest()
    prov = '\n'.join(' *   %s  %s' % (INPUTS[rel], rel) for rel in INPUTS)
    h = '''#ifndef DUOFORGE_DATA_CLOSURE_TABLES_H
#define DUOFORGE_DATA_CLOSURE_TABLES_H
/*
 * GENERATED by tools/datagen/gen_closure.py -- do not edit.
 *
 * Immutable data of the two reference teams (docs/decisions/0004, 0006),
 * read from Pokemon Showdown %s.
 * Input files (sha256 after CRLF -> LF):
%s
 *
 * Data only. An id names a record; every effect needs a typed handler in C
 * and an entry in the support manifest before a battle may use it.
 */
#include <stddef.h>
#include <stdint.h>

#define DFI_CLOSURE_NONE 0xFFu

/* ---- formes (base formes are selectable; Mega formes are reached in battle) ---- */
%s
#define DFI_FORME_COUNT %du

/* ---- moves: ids 0..35 follow decision 0005 (fixture table T1) ---- */
%s
#define DFI_MOVE_COUNT %du

/* ---- abilities ---- */
%s
#define DFI_ABILITY_COUNT %du

/* ---- items ---- */
%s
#define DFI_ITEM_COUNT %du

/* ---- types (the 18 battle types; Stellar is not part of Champions) ---- */
%s
#define DFI_TYPE_COUNT %du

/* ---- natures ---- */
%s
#define DFI_NATURE_COUNT %du

/* ---- stat and stage indices ---- */
#define DFI_STAT_HP 0u
#define DFI_STAT_ATK 1u
#define DFI_STAT_DEF 2u
#define DFI_STAT_SPA 3u
#define DFI_STAT_SPD 4u
#define DFI_STAT_SPE 5u
#define DFI_STAT_COUNT 6u
#define DFI_STAGE_ATK 0u
#define DFI_STAGE_DEF 1u
#define DFI_STAGE_SPA 2u
#define DFI_STAGE_SPD 3u
#define DFI_STAGE_SPE 4u
#define DFI_STAGE_ACCURACY 5u
#define DFI_STAGE_EVASION 6u
#define DFI_STAGE_COUNT 7u
#define DFI_STAGE_BIAS 6u /* a stored stage value v means v - 6 */

#define DFI_CATEGORY_PHYSICAL 0u
#define DFI_CATEGORY_SPECIAL 1u
#define DFI_CATEGORY_STATUS 2u

#define DFI_STATUS_NONE 0u
#define DFI_STATUS_BRN 1u
#define DFI_STATUS_FRZ 2u
#define DFI_STATUS_PAR 3u
#define DFI_STATUS_SLP 4u

#define DFI_VOLATILE_FLINCH 1u
#define DFI_VOLATILE_CONFUSION 2u

#define DFI_GENDER_RULE_ANY 0u    /* male or female */
#define DFI_GENDER_RULE_MALE 1u
#define DFI_GENDER_RULE_FEMALE 2u
#define DFI_GENDER_RULE_NONE 3u   /* genderless */

/* Move flags. */
#define DFI_MOVE_FLAG_CONTACT 1u
#define DFI_MOVE_FLAG_PROTECT 2u
#define DFI_MOVE_FLAG_CHARGE 4u
#define DFI_MOVE_FLAG_STALLING 8u
#define DFI_MOVE_FLAG_SELF_SWITCH 16u
#define DFI_MOVE_FLAG_NO_PP_BOOSTS 32u
#define DFI_MOVE_FLAG_STRUGGLE_RECOIL 64u

#define DFI_PRIORITY_BIAS 8u /* a stored priority p means p - 8 */
#define DFI_TARGET_CLASS_RANDOM_NORMAL 10u /* Struggle only; never selectable */

#define DFI_SECONDARY_NONE 0u
#define DFI_SECONDARY_BOOST 1u    /* boosts[] applied to the target */
#define DFI_SECONDARY_STATUS 2u   /* sec_param is a DFI_STATUS_* */
#define DFI_SECONDARY_VOLATILE 3u /* sec_param is a DFI_VOLATILE_* */

#define DFI_BOOST_ROLE_NONE 0u
#define DFI_BOOST_ROLE_PRIMARY_SELF 1u     /* a status move boosting its user */
#define DFI_BOOST_ROLE_SECONDARY_TARGET 2u /* applied with the secondary roll */
#define DFI_BOOST_ROLE_SELF_AFTER_HIT 3u   /* applied to the user after a hit */

#define DFI_SIDE_CONDITION_TAILWIND 1u
#define DFI_SIDE_CONDITION_REFLECT 2u
#define DFI_SIDE_CONDITION_LIGHT_SCREEN 3u
#define DFI_PSEUDO_WEATHER_TRICK_ROOM 1u

/* Handlers for callbacks that are code in the reference. */
%s

/* Type chart codes (the reference's damageTaken values). */
#define DFI_EFFECT_NEUTRAL 0u
#define DFI_EFFECT_SUPER 1u
#define DFI_EFFECT_RESISTED 2u
#define DFI_EFFECT_IMMUNE 3u
#define DFI_IMMUNE_BRN 1u
#define DFI_IMMUNE_FRZ 2u
#define DFI_IMMUNE_PAR 4u
#define DFI_IMMUNE_PRANKSTER 8u

typedef struct dfi_forme_data {
    uint16_t dex_num;
    uint16_t weight_hg;
    uint8_t types[2]; /* second is DFI_CLOSURE_NONE for a single type */
    uint8_t base[DFI_STAT_COUNT];
    uint8_t ability;     /* the set's ability; for a Mega forme its own */
    uint8_t gender_rule; /* DFI_GENDER_RULE_* */
    uint8_t is_mega;
    uint8_t base_forme;
    uint8_t mega_forme; /* DFI_CLOSURE_NONE if the species has no Mega in the closure */
    uint8_t mega_item;  /* the stone, or DFI_CLOSURE_NONE */
    uint8_t set_item;   /* the item of the set in decision 0004 */
    uint8_t set_move_count;
    uint8_t set_moves[4]; /* the moves of the set in decision 0004 */
} dfi_forme_data;

typedef struct dfi_move_data {
    uint8_t type;
    uint8_t category;
    uint8_t base_power;
    uint8_t accuracy; /* 0: never misses */
    uint8_t pp_base;  /* the pp of the Champions data (mod overrides included), before the cap at 20 and calculatePP */
    uint8_t pp_max;   /* Champions maximum PP */
    uint8_t priority; /* biased by DFI_PRIORITY_BIAS */
    uint8_t target_class;
    uint8_t crit_ratio;
    uint8_t flags;
    uint8_t recoil[2]; /* numerator, denominator of damage dealt; 0/0 none */
    uint8_t drain[2];
    uint8_t sec_chance; /* 0: no secondary effect */
    uint8_t sec_kind;
    uint8_t sec_param;
    uint8_t boost_role;
    uint8_t boosts[DFI_STAGE_COUNT]; /* biased by DFI_STAGE_BIAS */
    uint8_t primary_status;
    uint8_t side_condition;
    uint8_t pseudo_weather;
    uint8_t special;
} dfi_move_data;

typedef struct dfi_item_data {
    uint8_t mega_base;  /* forme that can hold it as a Mega Stone, or DFI_CLOSURE_NONE */
    uint8_t mega_forme;
} dfi_item_data;

typedef struct dfi_nature_data {
    uint8_t plus;  /* DFI_STAT_* or DFI_CLOSURE_NONE */
    uint8_t minus;
} dfi_nature_data;

extern const dfi_forme_data dfi_closure_formes[DFI_FORME_COUNT];
extern const dfi_move_data dfi_closure_moves[DFI_MOVE_COUNT];
extern const dfi_item_data dfi_closure_items[DFI_ITEM_COUNT];
extern const dfi_nature_data dfi_closure_natures[DFI_NATURE_COUNT];
/* [defender type][attacking type] -> DFI_EFFECT_* */
extern const uint8_t dfi_closure_type_chart[DFI_TYPE_COUNT][DFI_TYPE_COUNT];
extern const uint8_t dfi_closure_type_immunity[DFI_TYPE_COUNT]; /* DFI_IMMUNE_* bits */

/* SHA-256 of the canonical table bytes (written by the generator). */
#define DFI_CLOSURE_CANONICAL_SIZE %du
extern const uint8_t dfi_closure_table_hash[32];
/* Writes the canonical table bytes from the tables above; returns the size
 * (DFI_CLOSURE_CANONICAL_SIZE) or 0 if capacity is too small. */
size_t dfi_closure_canonical_bytes(uint8_t *out, size_t capacity);

#endif
''' % (PIN, prov,
       define_block('DFI_FORME', [f['id'] for f in d['formes']]), len(d['formes']),
       define_block('DFI_MOVE', [m['id'] for m in d['moves']]), len(d['moves']),
       define_block('DFI_ABILITY', [a['id'] for a in d['abilities']]), len(d['abilities']),
       define_block('DFI_ITEM', [i['id'] for i in d['items']]), len(d['items']),
       define_block('DFI_TYPE', TYPES), len(TYPES),
       define_block('DFI_NATURE', [n['id'] for n in d['natures']]), len(d['natures']),
       define_block('DFI_SPECIAL', SPECIAL_IDS), len(can))

    def arr(vals):
        return '{' + ', '.join('%du' % v for v in vals) + '}'

    c = ['#include "data/closure_tables.h"', '',
         '/* GENERATED by tools/datagen/gen_closure.py -- do not edit. Showdown %s. */' % PIN, '',
         'const dfi_forme_data dfi_closure_formes[DFI_FORME_COUNT] = {']
    for f in d['formes']:
        c.append('    /* %s -- %s */' % (f['name'], f['ref']))
        c.append('    {%du, %du, %s, %s, %du, %du, %du, %du, %du, %du, %du, %du, %s},' % (
            f['dex_num'], f['weight_hg'], arr(f['types']), arr(f['base']), f['ability'], f['gender_rule'],
            f['is_mega'], f['base_forme'], f['mega_forme'], f['mega_item'], f['set_item'], len(f['set_moves']),
            arr(f['set_moves'] + [0] * (4 - len(f['set_moves'])))))
    c += ['};', '', 'const dfi_move_data dfi_closure_moves[DFI_MOVE_COUNT] = {']
    for m in d['moves']:
        c.append('    /* %s -- %s */' % (m['name'], ', '.join(m['refs'])))
        c.append('    {%du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %s, %s, %du, %du, %du, %du, %s, %du, %du, %du, %du},' % (
            m['type'], m['category'], m['base_power'], m['accuracy'], m['pp_base'], m['pp_max'], m['priority'],
            m['target_class'], m['crit_ratio'], m['flags'], arr(m['recoil']), arr(m['drain']), m['sec_chance'],
            m['sec_kind'], m['sec_param'], m['boost_role'], arr([v + 6 for v in m['boosts']]), m['primary_status'],
            m['side_condition'], m['pseudo_weather'], m['special']))
    c += ['};', '', 'const dfi_item_data dfi_closure_items[DFI_ITEM_COUNT] = {']
    for it in d['items']:
        c.append('    /* %s -- %s */' % (it['name'], ', '.join(it['refs'])))
        c.append('    {%du, %du},' % (it['mega_base'], it['mega_forme']))
    c += ['};', '', '/* Abilities carry no table data. Provenance:']
    for a in d['abilities']:
        c.append(' *   %s -- %s' % (a['id'], ', '.join(a['refs'])))
    c += [' */', '', 'const dfi_nature_data dfi_closure_natures[DFI_NATURE_COUNT] = {']
    for n in d['natures']:
        c.append('    {%du, %du}, /* %s */' % (n['plus'], n['minus'], n['id']))
    c += ['};', '', '/* data/typechart.ts: rows are defender types, columns attacking types. */',
          'const uint8_t dfi_closure_type_chart[DFI_TYPE_COUNT][DFI_TYPE_COUNT] = {']
    for t, row in zip(TYPES, d['chart']):
        c.append('    %s, /* %s */' % (arr(row), t))
    c += ['};', '', 'const uint8_t dfi_closure_type_immunity[DFI_TYPE_COUNT] = ' + arr(d['immunity']) + ';', '',
          'const uint8_t dfi_closure_table_hash[32] = {']
    hb = bytes.fromhex(digest)
    for i in range(0, 32, 8):
        c.append('    ' + ', '.join('0x%02xu' % x for x in hb[i:i + 8]) + ',')
    c += ['};', '', '''static size_t dfi_put_u16(uint8_t *out, size_t n, uint32_t v)
{
    out[n] = (uint8_t)(v & 0xFFu);             /* wide-operands-reviewed */
    out[n + 1u] = (uint8_t)((v >> 8u) & 0xFFu); /* wide-operands-reviewed */
    return n + 2u;
}

size_t dfi_closure_canonical_bytes(uint8_t *out, size_t capacity)
{
    size_t n = 0u;
    if (capacity < DFI_CLOSURE_CANONICAL_SIZE) {
        return 0u;
    }
    n = dfi_put_u16(out, n, DFI_FORME_COUNT);
    n = dfi_put_u16(out, n, DFI_MOVE_COUNT);
    n = dfi_put_u16(out, n, DFI_ITEM_COUNT);
    n = dfi_put_u16(out, n, DFI_ABILITY_COUNT);
    n = dfi_put_u16(out, n, DFI_TYPE_COUNT);
    n = dfi_put_u16(out, n, DFI_NATURE_COUNT);
    for (uint32_t i = 0u; i < DFI_FORME_COUNT; ++i) {
        const dfi_forme_data *f = &dfi_closure_formes[i];
        n = dfi_put_u16(out, n, f->dex_num);
        out[n++] = f->types[0];
        out[n++] = f->types[1];
        for (uint32_t k = 0u; k < DFI_STAT_COUNT; ++k) {
            out[n++] = f->base[k];
        }
        n = dfi_put_u16(out, n, f->weight_hg);
        out[n++] = f->ability;
        out[n++] = f->gender_rule;
        out[n++] = f->is_mega;
        out[n++] = f->base_forme;
        out[n++] = f->mega_forme;
        out[n++] = f->mega_item;
        out[n++] = f->set_item;
        out[n++] = f->set_move_count;
        for (uint32_t k = 0u; k < 4u; ++k) {
            out[n++] = f->set_moves[k];
        }
    }
    for (uint32_t i = 0u; i < DFI_MOVE_COUNT; ++i) {
        const dfi_move_data *m = &dfi_closure_moves[i];
        out[n++] = m->type;
        out[n++] = m->category;
        out[n++] = m->base_power;
        out[n++] = m->accuracy;
        out[n++] = m->pp_base;
        out[n++] = m->pp_max;
        out[n++] = m->priority;
        out[n++] = m->target_class;
        out[n++] = m->crit_ratio;
        out[n++] = m->flags;
        out[n++] = m->recoil[0];
        out[n++] = m->recoil[1];
        out[n++] = m->drain[0];
        out[n++] = m->drain[1];
        out[n++] = m->sec_chance;
        out[n++] = m->sec_kind;
        out[n++] = m->sec_param;
        out[n++] = m->boost_role;
        for (uint32_t k = 0u; k < DFI_STAGE_COUNT; ++k) {
            out[n++] = m->boosts[k];
        }
        out[n++] = m->primary_status;
        out[n++] = m->side_condition;
        out[n++] = m->pseudo_weather;
        out[n++] = m->special;
    }
    for (uint32_t i = 0u; i < DFI_ITEM_COUNT; ++i) {
        out[n++] = dfi_closure_items[i].mega_base;
        out[n++] = dfi_closure_items[i].mega_forme;
    }
    for (uint32_t d = 0u; d < DFI_TYPE_COUNT; ++d) {
        for (uint32_t a = 0u; a < DFI_TYPE_COUNT; ++a) {
            out[n++] = dfi_closure_type_chart[d][a];
        }
    }
    for (uint32_t i = 0u; i < DFI_TYPE_COUNT; ++i) {
        out[n++] = dfi_closure_type_immunity[i];
    }
    for (uint32_t i = 0u; i < DFI_NATURE_COUNT; ++i) {
        out[n++] = dfi_closure_natures[i].plus;
        out[n++] = dfi_closure_natures[i].minus;
    }
    return n;
}
''']
    return h, '\n'.join(c), digest, len(can)


def main():
    args = [a for a in sys.argv[1:] if a != '--check']
    check = '--check' in sys.argv[1:]
    if len(args) != 1:
        sys.exit(__doc__)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    d = build(args[0])
    h, c, digest, size = render(d)
    outs = ((os.path.join(repo, 'src', 'data', 'closure_tables.h'), h),
            (os.path.join(repo, 'src', 'data', 'closure_tables.c'), c))
    for path, text in outs:
        if check:
            have = io.open(path, 'rb').read().replace(b'\r\n', b'\n')
            if have != text.encode('ascii'):
                fail('%s differs from the generator output' % path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with io.open(path, 'w', encoding='ascii', newline='\n') as fh:
                fh.write(text)
    print('closure tables: %d formes, %d moves, %d items, %d abilities; canonical %d bytes, sha256 %s%s' % (
        len(d['formes']), len(d['moves']), len(d['items']), len(d['abilities']), size, digest,
        ' (check ok)' if check else ''))
    for path, text in outs:
        print('  %s sha256 %s' % (os.path.basename(path), hashlib.sha256(text.encode('ascii')).hexdigest()))


if __name__ == '__main__':
    main()
