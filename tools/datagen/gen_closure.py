#!/usr/bin/env python3
"""Generates src/data/closure_tables.{h,c}: the immutable data of the two
reference teams (decision 0004) read from the pinned Pokemon Showdown
checkout (decision 0006 section 2).

usage: python3 tools/datagen/gen_closure.py <pinned checkout> [--team-c | --pool] [--check]

  --team-c  write src/data/extended_tables.{h,c} instead: the closure tables
            followed by Team C (docs/decisions/0009). The closure ids stay an
            exact prefix; the generator checks that before it writes.
  --pool    write src/data/pool_tables.{h,c} instead: the extended tables as
            the prefix, then the rows of the content expansion, with the
            family columns of every item and ability and the moves and
            abilities that each forme may have (docs/decisions/0015). Both
            prefixes are checked row by row before it writes.
  --check   do not write; exit 1 if the committed files differ.

Offline tooling. It extracts static data only; every effect still needs a
typed handler in C (decision 0006). It fails, instead of guessing, when an
input hash differs from the pin, when a move has a field it does not know,
or when a callback is not mapped to a named handler id. The family columns
come from one strict pattern per family; a handler that deviates from the
pattern of its family fails the generator. CTest never needs Python: the
generated files are committed.
"""
import hashlib
import io
import json
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

# ---- Team C (decision 0009): appended to the closure in the extended tables ----
# The closure mode never reads anything below, so its output stays byte-identical.
SETS_C = [
    ('sneasler', 'unburden', 'whiteherb', ['closecombat', 'direclaw', 'protect', 'fakeout'], None),
    ('incineroar', 'intimidate', 'sitrusberry', ['fakeout', 'flareblitz', 'partingshot', 'darkestlariat'], None),
    ('salamence', 'intimidate', 'salamencite', ['protect', 'hypervoice', 'dracometeor', 'tailwind'], 'salamencemega'),
    ('indeedeef', 'psychicsurge', 'rockyhelmet', ['followme', 'trickroom', 'helpinghand', 'psychic'], None),
    ('kingambit', 'defiant', 'chopleberry', ['kowtowcleave', 'suckerpunch', 'ironhead', 'protect'], None),
    ('basculegion', 'adaptability', 'choicescarf', ['wavecrash', 'lastrespects', 'flipturn', 'aquajet'], None),
]
# The 13 new moves in team order; ids follow Struggle (36).
MOVES_C = ['direclaw', 'flareblitz', 'darkestlariat', 'hypervoice', 'dracometeor', 'followme', 'helpinghand',
           'kowtowcleave', 'suckerpunch', 'lastrespects', 'wavecrash', 'aquajet', 'flipturn']
# New encodings (decision 0009 section 3.3). Each names the step that consumes it.
STATUS_C = dict(STATUS, psn=5)                    # poison: step 6
STATUS_IMMUNITY_C = dict(STATUS_IMMUNITY, psn=16)  # Poison and Steel: step 6
IGNORED_TYPE_KEYS_C = IGNORED_TYPE_KEYS - {'psn'}  # tox stays ignored: no toxic source
FLAG_BITS_C = dict(FLAG_BITS, defrost=128)         # Flare Blitz: step 2
SPECIAL_C = dict(SPECIAL, **{
    'darkestlariat': ('DARKEST_LARIAT', set()),                   # step 2
    'lastrespects': ('LAST_RESPECTS', {'basePowerCallback'}),     # step 4
    'suckerpunch': ('SUCKER_PUNCH', {'onTry'}),                   # step 9b
    'helpinghand': ('HELPING_HAND', {'onTryHit'}),                # step 9b
    'followme': ('FOLLOW_ME', {'onTry'}),                         # step 11
})
SPECIAL_IDS_C = SPECIAL_IDS + ['DARKEST_LARIAT', 'LAST_RESPECTS', 'SUCKER_PUNCH', 'HELPING_HAND', 'FOLLOW_ME']
# Data fields that only a named handler consumes.
SPECIAL_FIELDS_C = {'DARKEST_LARIAT': {'ignoreDefensive', 'ignoreEvasion'}}
# Primary volatiles (with their condition blocks) that only a named handler owns.
SPECIAL_VOLATILE_C = {'FOLLOW_ME': 'followme', 'HELPING_HAND': 'helpinghand'}
# Dire Claw's secondary (step 6): its onHit, whitespace-normalised, must be exactly this.
STATUS_PICK_ONHIT = ("onHit(target, source) { const status = this.sample(['psn', 'par', 'slp']); "
                     "target.trySetStatus(status, source); },")
SECONDARY_STATUS_PICK = 4


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


def modelled(table, key, mid, what):
    """The code of a name that the tables model. Anything else fails with a message, never as a KeyError."""
    if key not in table:
        fail('move %s: %s %s is not modelled' % (mid, what, key))
    return table[key]


def parse_move(mid, base, champ, ext=False, pool=False):
    """ext: the extended tables' encodings (decision 0009); the closure mode
    keeps exactly the closure's. pool: the pool tables' encodings (decision
    0015), which are the extended ones plus the named handlers of G2_HANDLERS:
    a move whose callbacks or fields the tables do not model is mapped
    deliberately to one of them, and anything else still fails."""
    ext = ext or pool
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
    handled = (SPECIAL_P if pool else SPECIAL_C if ext else SPECIAL).get(mid, ('NONE', set()))
    owned_fields = SPECIAL_FIELDS_C.get(handled[0], set()) if ext else set()
    # What a pool handler owns: data fields and a secondary that only it consumes, each of which must be present and
    # exactly the pinned text, and a condition block (the callbacks inside it are code, not data).
    owned = G2_OWNED_FIELDS.get(handled[0], {}) if pool else {}
    owned_secondary = G2_OWNED_SECONDARY.get(handled[0]) if pool else None
    owns_condition = pool and handled[0] in G2_OWNED_CONDITION
    for name, text in owned.items():
        if name not in f or norm(f[name][1]) != text:
            fail('move %s: %s is not "%s"' % (mid, name, text))
    if owned_secondary is not None and ('secondary' not in f or norm(f['secondary'][1]) != owned_secondary):
        fail('move %s: the secondary is not "%s"' % (mid, owned_secondary))
    if owns_condition and 'condition' not in f:
        fail('move %s: expected a condition block' % mid)
    for name, (is_fn, _text) in f.items():
        if is_fn:
            if name not in handled[1]:
                fail('move %s: callback %s is not mapped to a handler' % (mid, name))
        elif (name not in DATA_KEYS and name not in IGNORED_KEYS and name not in owned_fields and name not in owned
              and not (pool and name in POOL_COLUMN_KEYS)):
            fail('move %s: unknown field %s' % (mid, name))
    missing = handled[1] - set(n for n, v in f.items() if v[0])
    if missing:
        fail('move %s: expected callbacks %s are absent' % (mid, sorted(missing)))

    def get(name, default=None):
        return scalar(f[name][1]) if name in f else default

    flags = 0
    flag_bits = FLAG_BITS_C if ext else FLAG_BITS
    for fl in re.findall(r'(\w+): 1', f['flags'][1]):
        if fl in flag_bits:
            flags |= flag_bits[fl]
        elif fl not in IGNORED_FLAGS and not (pool and fl in G2_IGNORED_FLAGS):
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
        'thaws_target': 0, 'heal': [0, 0],
        'special': (SPECIAL_IDS_P if pool else SPECIAL_IDS_C if ext else SPECIAL_IDS).index(handled[0]),
    }
    for key in ('recoil', 'drain'):
        if key in f:
            nums = [int(x) for x in re.findall(r'\d+', f[key][1])]
            if len(nums) != 2:
                fail('move %s: %s is not a fraction' % (mid, key))
            rec[key] = nums
    if pool and 'thawsTarget' in f:
        if norm(f['thawsTarget'][1]) != 'thawsTarget: true,':
            fail('move %s: thawsTarget is not "thawsTarget: true,"' % mid)
        rec['thaws_target'] = 1
    if pool and 'heal' in f:
        heal = re.fullmatch(r'heal: \[(\d+), (\d+)\],', norm(f['heal'][1]))
        if heal is None or not 0 < int(heal.group(1)) <= int(heal.group(2)) <= 255:
            fail('move %s: heal is not a fraction "heal: [a, b],"' % mid)
        rec['heal'] = [int(heal.group(1)), int(heal.group(2))]
    vectors = 0
    if 'secondary' in f and owned_secondary is None:
        # The whole secondary must be one modelled effect; anything else (a
        # self block, a callback, several effects) fails instead of being misread.
        sec = re.fullmatch(r'secondary: \{ chance: (\d+), (.*) \},', ' '.join(f['secondary'][1].split()))
        if sec is None:
            fail('move %s: unknown secondary' % mid)
        rec['sec_chance'], effect = int(sec.group(1)), sec.group(2)
        st = re.fullmatch(r"status: '(\w+)',", effect)
        vo = re.fullmatch(r"volatileStatus: '(\w+)',", effect)
        if st:
            rec['sec_kind'], rec['sec_param'] = 2, modelled(STATUS, st.group(1), mid, 'secondary status')
        elif vo:
            rec['sec_kind'], rec['sec_param'] = 3, modelled(VOLATILE, vo.group(1), mid, 'secondary volatile')
        elif re.fullmatch(r'boosts: \{ (?:(?:%s): -?\d+, )+\},' % '|'.join(BOOSTS), effect):
            rec['sec_kind'] = 1
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['SECONDARY_TARGET'], boosts_of(effect)
            vectors += 1
        elif ext and effect == STATUS_PICK_ONHIT:
            rec['sec_kind'] = SECONDARY_STATUS_PICK
        elif re.search(r'\bself: \{', effect):
            fail('move %s: secondary self effects are not supported' % mid)
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
        rec['primary_status'] = modelled(STATUS_C if ext else STATUS, get('status'), mid, 'primary status')
    owned_volatile = SPECIAL_VOLATILE_C.get(handled[0]) if ext else None
    if 'volatileStatus' in f and 'volatileStatus' not in owned and get('volatileStatus') not in ('protect', owned_volatile):
        fail('move %s: unknown primary volatile' % mid)
    if 'sideCondition' in f and 'sideCondition' not in owned:
        rec['side_condition'] = modelled(SIDE_CONDITION, get('sideCondition'), mid, 'side condition')
    if 'pseudoWeather' in f:
        rec['pseudo_weather'] = modelled(PSEUDO_WEATHER, get('pseudoWeather'), mid, 'pseudo weather')
    if 'condition' in f and not (rec['side_condition'] or rec['pseudo_weather'] or mid == 'protect' or
                                 owned_volatile is not None or owns_condition):
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


def build(root, ext=False):
    """The closure tables, or with ext the extended tables: the closure group
    is built completely first (items, abilities, formes with their Mega
    abilities), then Team C, so every closure id keeps its value."""
    src = {rel: Source(root, rel) for rel in INPUTS}
    dex, moves_ts, champ_moves = src['data/pokedex.ts'], src['data/moves.ts'], src['data/mods/champions/moves.ts']
    items_ts, champ_items = src['data/items.ts'], src['data/mods/champions/items.ts']
    abil_ts, champ_abil = src['data/abilities.ts'], src['data/mods/champions/abilities.ts']
    formats, learn = src['data/mods/champions/formats-data.ts'], src['data/mods/champions/learnsets.ts']
    groups = (SETS, SETS_C) if ext else (SETS,)
    sets = [s for g in groups for s in g]

    moves = [parse_move(m, moves_ts, champ_moves, ext) for m in (MOVES + MOVES_C if ext else MOVES)]
    move_index = {m['id']: i for i, m in enumerate(moves)}
    items, item_index = [], {}
    abilities, ability_index = [], {}
    formes, forme_index = [], {}
    for group in groups:
        build_group(group, items, item_index, abilities, ability_index, formes, forme_index, move_index,
                    dex, items_ts, champ_items, abil_ts, champ_abil, formats, learn)
    for fo in formes:
        base = fo['id'] if not fo['is_mega'] else [s for s, _a, _i, _m, mg in sets if mg == fo['id']][0]
        fo['base_forme'] = forme_index[base]
        fo['mega_forme'] = forme_index[fo['mega']] if fo['mega'] else 0xFF
        fo['mega_item'] = fo['set_item'] if (fo['mega'] or fo['is_mega']) else 0xFF
    for it in items:
        it['mega_base'] = forme_index[it['stone'][0]] if it['stone'] else 0xFF
        it['mega_forme'] = forme_index[it['stone'][1]] if it['stone'] else 0xFF

    status_immunity = STATUS_IMMUNITY_C if ext else STATUS_IMMUNITY
    ignored_type_keys = IGNORED_TYPE_KEYS_C if ext else IGNORED_TYPE_KEYS
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
            if key in status_immunity:
                imm |= status_immunity[key]
            elif key not in ignored_type_keys:
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


def build_group(group, items, item_index, abilities, ability_index, formes, forme_index, move_index,
                dex, items_ts, champ_items, abil_ts, champ_abil, formats, learn):
    for _sp, _ab, item, _mv, _mega in group:
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

    def add_ability(aid):
        if aid not in ability_index:
            if abil_ts.entry(aid) is None:
                fail('ability %s not found' % aid)
            refs = [abil_ts.ref(aid)]
            if champ_abil.entry(aid) is not None:
                refs.append(champ_abil.ref(aid))
            ability_index[aid] = len(abilities)
            abilities.append({'id': aid, 'refs': refs})

    for _sp, ab, _it, _mv, _mega in group:
        add_ability(ab)

    for sp, ab, item, mv, mega in group:
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


def closure_prefix(dx, dc):
    """The closure projection of the extended data: its first closure-count
    rows and the closure's immunity bits only."""
    mask = sum(STATUS_IMMUNITY.values())
    return {'formes': dx['formes'][:len(dc['formes'])], 'moves': dx['moves'][:len(dc['moves'])],
            'items': dx['items'][:len(dc['items'])], 'abilities': dx['abilities'][:len(dc['abilities'])],
            'chart': dx['chart'], 'immunity': [v & mask for v in dx['immunity']], 'natures': dx['natures']}


def check_prefix(dx, dc):
    """Decision 0009 section 3.2: the closure is an exact prefix of the extended tables."""
    for key in ('formes', 'moves', 'items', 'abilities'):
        if [r['id'] for r in dx[key][:len(dc[key])]] != [r['id'] for r in dc[key]]:
            fail('extended %s do not start with the closure %s' % (key, key))
    if dx['chart'] != dc['chart'] or dx['natures'] != dc['natures']:
        fail('extended type chart or natures differ from the closure')
    if canonical(closure_prefix(dx, dc)) != canonical(dc):
        fail('the extended tables do not start with the closure tables')


def render_ext(dx, dc):
    can = canonical(dx)
    digest = hashlib.sha256(can).hexdigest()
    nf, nm, ni, na = len(dc['formes']), len(dc['moves']), len(dc['items']), len(dc['abilities'])

    def defines(prefix, rows, start):
        return '\n'.join('#define %s_%s %du' % (prefix, r['id'].upper(), i)
                         for i, r in enumerate(rows) if i >= start)

    new_special = '\n'.join('#define DFI_SPECIAL_%s %du' % (n, i) for i, n in enumerate(SPECIAL_IDS_C)
                            if i >= len(SPECIAL_IDS))
    h = '''#ifndef DUOFORGE_DATA_EXTENDED_TABLES_H
#define DUOFORGE_DATA_EXTENDED_TABLES_H
/*
 * GENERATED by tools/datagen/gen_closure.py --team-c -- do not edit.
 *
 * The extended tables of decision 0009: the closure tables followed by
 * Team C, read from Pokemon Showdown %s (the input files of
 * closure_tables.h). Every id below a closure count (DFI_FORME_COUNT,
 * DFI_MOVE_COUNT, DFI_ITEM_COUNT, DFI_ABILITY_COUNT) is the closure's and
 * its row equals the closure row; the only extension inside that prefix is
 * DFI_IMMUNE_PSN. Team C ids follow. Natures and the type chart are the
 * closure's.
 *
 * Data only. An id names a record; every effect needs a typed handler in C
 * and an entry in the support manifest before a battle may use it.
 */
#include <stddef.h>
#include <stdint.h>

#include "data/closure_tables.h"

/* ---- Team C formes (appended; base formes are selectable) ---- */
%s
#define DFI_EXT_FORME_COUNT %du

/* ---- Team C moves (appended after Struggle) ---- */
%s
#define DFI_EXT_MOVE_COUNT %du

/* ---- Team C abilities ---- */
%s
#define DFI_EXT_ABILITY_COUNT %du

/* ---- Team C items ---- */
%s
#define DFI_EXT_ITEM_COUNT %du

/* ---- encodings new in the extended tables (decision 0009 section 3.3) ---- */
#define DFI_STATUS_PSN 5u
#define DFI_MOVE_FLAG_DEFROST 128u
#define DFI_SECONDARY_STATUS_PICK 4u /* on a hit: sample(['psn', 'par', 'slp']), then trySetStatus */
%s
#define DFI_IMMUNE_PSN 16u

extern const dfi_forme_data dfi_ext_formes[DFI_EXT_FORME_COUNT];
extern const dfi_move_data dfi_ext_moves[DFI_EXT_MOVE_COUNT];
extern const dfi_item_data dfi_ext_items[DFI_EXT_ITEM_COUNT];
extern const uint8_t dfi_ext_type_immunity[DFI_TYPE_COUNT]; /* DFI_IMMUNE_* bits */

/* SHA-256 of the extended canonical bytes (written by the generator). */
#define DFI_EXT_CANONICAL_SIZE %du
extern const uint8_t dfi_ext_table_hash[32];
/* The canonical bytes of the closure layout over the first `formes`, `moves`,
 * `items` and `abilities` rows of the tables above, with every immunity byte
 * masked by `immunity_mask`; natures and the type chart are the closure's.
 * Returns the size, or 0 if a count exceeds its table or capacity is too
 * small. With the closure counts and the closure's immunity bits these are
 * exactly the closure's canonical bytes. */
size_t dfi_ext_canonical_bytes_of(uint8_t *out, size_t capacity, uint32_t formes, uint32_t moves, uint32_t items,
                                  uint32_t abilities, uint32_t immunity_mask);
/* The extended canonical bytes: every row, every immunity bit. */
size_t dfi_ext_canonical_bytes(uint8_t *out, size_t capacity);

#endif
''' % (PIN, defines('DFI_FORME', dx['formes'], nf), len(dx['formes']),
       defines('DFI_MOVE', dx['moves'], nm), len(dx['moves']),
       defines('DFI_ABILITY', dx['abilities'], na), len(dx['abilities']),
       defines('DFI_ITEM', dx['items'], ni), len(dx['items']), new_special, len(can))

    def arr(vals):
        return '{' + ', '.join('%du' % v for v in vals) + '}'

    c = ['#include "data/extended_tables.h"', '',
         '/* GENERATED by tools/datagen/gen_closure.py --team-c -- do not edit. Showdown %s. */' % PIN, '',
         'const dfi_forme_data dfi_ext_formes[DFI_EXT_FORME_COUNT] = {']
    for f in dx['formes']:
        c.append('    /* %s -- %s */' % (f['name'], f['ref']))
        c.append('    {%du, %du, %s, %s, %du, %du, %du, %du, %du, %du, %du, %du, %s},' % (
            f['dex_num'], f['weight_hg'], arr(f['types']), arr(f['base']), f['ability'], f['gender_rule'],
            f['is_mega'], f['base_forme'], f['mega_forme'], f['mega_item'], f['set_item'], len(f['set_moves']),
            arr(f['set_moves'] + [0] * (4 - len(f['set_moves'])))))
    c += ['};', '', 'const dfi_move_data dfi_ext_moves[DFI_EXT_MOVE_COUNT] = {']
    for m in dx['moves']:
        c.append('    /* %s -- %s */' % (m['name'], ', '.join(m['refs'])))
        c.append('    {%du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %s, %s, %du, %du, %du, %du, %s, %du, %du, %du, %du},' % (
            m['type'], m['category'], m['base_power'], m['accuracy'], m['pp_base'], m['pp_max'], m['priority'],
            m['target_class'], m['crit_ratio'], m['flags'], arr(m['recoil']), arr(m['drain']), m['sec_chance'],
            m['sec_kind'], m['sec_param'], m['boost_role'], arr([v + 6 for v in m['boosts']]), m['primary_status'],
            m['side_condition'], m['pseudo_weather'], m['special']))
    c += ['};', '', 'const dfi_item_data dfi_ext_items[DFI_EXT_ITEM_COUNT] = {']
    for it in dx['items']:
        c.append('    /* %s -- %s */' % (it['name'], ', '.join(it['refs'])))
        c.append('    {%du, %du},' % (it['mega_base'], it['mega_forme']))
    c += ['};', '', '/* Abilities carry no table data. Provenance of the Team C abilities:']
    for a in dx['abilities'][na:]:
        c.append(' *   %s -- %s' % (a['id'], ', '.join(a['refs'])))
    c += [' */', '', '/* data/typechart.ts: the closure bits plus psn (Poison, Steel). */',
          'const uint8_t dfi_ext_type_immunity[DFI_TYPE_COUNT] = ' + arr(dx['immunity']) + ';', '',
          'const uint8_t dfi_ext_table_hash[32] = {']
    hb = bytes.fromhex(digest)
    for i in range(0, 32, 8):
        c.append('    ' + ', '.join('0x%02xu' % x for x in hb[i:i + 8]) + ',')
    c += ['};', '', '''static size_t dfi_ext_put_u16(uint8_t *out, size_t n, uint32_t v)
{
    out[n] = (uint8_t)(v & 0xFFu);             /* wide-operands-reviewed */
    out[n + 1u] = (uint8_t)((v >> 8u) & 0xFFu); /* wide-operands-reviewed */
    return n + 2u;
}

size_t dfi_ext_canonical_bytes_of(uint8_t *out, size_t capacity, uint32_t formes, uint32_t moves, uint32_t items,
                                  uint32_t abilities, uint32_t immunity_mask)
{
    if (formes > DFI_EXT_FORME_COUNT || moves > DFI_EXT_MOVE_COUNT || items > DFI_EXT_ITEM_COUNT ||
        abilities > DFI_EXT_ABILITY_COUNT) {
        return 0u;
    }
    /* counts, 24 bytes per forme, 29 per move, 2 per item, chart, immunity, natures */
    const size_t size = 12u + (size_t)formes * 24u + (size_t)moves * 29u + (size_t)items * 2u +
                        DFI_TYPE_COUNT * DFI_TYPE_COUNT + DFI_TYPE_COUNT + DFI_NATURE_COUNT * 2u;
    if (capacity < size) {
        return 0u;
    }
    size_t n = 0u;
    n = dfi_ext_put_u16(out, n, formes);
    n = dfi_ext_put_u16(out, n, moves);
    n = dfi_ext_put_u16(out, n, items);
    n = dfi_ext_put_u16(out, n, abilities);
    n = dfi_ext_put_u16(out, n, DFI_TYPE_COUNT);
    n = dfi_ext_put_u16(out, n, DFI_NATURE_COUNT);
    for (uint32_t i = 0u; i < formes; ++i) {
        const dfi_forme_data *f = &dfi_ext_formes[i];
        n = dfi_ext_put_u16(out, n, f->dex_num);
        out[n++] = f->types[0];
        out[n++] = f->types[1];
        for (uint32_t k = 0u; k < DFI_STAT_COUNT; ++k) {
            out[n++] = f->base[k];
        }
        n = dfi_ext_put_u16(out, n, f->weight_hg);
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
    for (uint32_t i = 0u; i < moves; ++i) {
        const dfi_move_data *m = &dfi_ext_moves[i];
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
    for (uint32_t i = 0u; i < items; ++i) {
        out[n++] = dfi_ext_items[i].mega_base;
        out[n++] = dfi_ext_items[i].mega_forme;
    }
    for (uint32_t d = 0u; d < DFI_TYPE_COUNT; ++d) {
        for (uint32_t a = 0u; a < DFI_TYPE_COUNT; ++a) {
            out[n++] = dfi_closure_type_chart[d][a];
        }
    }
    for (uint32_t i = 0u; i < DFI_TYPE_COUNT; ++i) {
        out[n++] = (uint8_t)(dfi_ext_type_immunity[i] & immunity_mask); /* wide-operands-reviewed: < 256 */
    }
    for (uint32_t i = 0u; i < DFI_NATURE_COUNT; ++i) {
        out[n++] = dfi_closure_natures[i].plus;
        out[n++] = dfi_closure_natures[i].minus;
    }
    return n;
}

size_t dfi_ext_canonical_bytes(uint8_t *out, size_t capacity)
{
    return dfi_ext_canonical_bytes_of(out, capacity, DFI_EXT_FORME_COUNT, DFI_EXT_MOVE_COUNT, DFI_EXT_ITEM_COUNT,
                                      DFI_EXT_ABILITY_COUNT, 0xFFu);
}
''']
    return h, '\n'.join(c), digest, len(can)


# ---- the POOL data kind (decision 0015): the extended tables plus the rows of the expansion ----
# The closure and --team-c modes never read anything below, so their output stays byte-identical.
FORMAT_ID = 'gen9championsvgc2026regmc'
LEGAL_POOL = os.path.join('docs', 'research', 'expansion', 'data', 'legal_pool.json')

# The new items in their fixed order: the families in the order of decision 0015 section 3 (type boosters, then
# resist berries), each by Showdown id (which is also by name). Mystic Water and Miracle Seed (type boosters) and
# Chople Berry (a resist berry) are in the prefix.
POOL_TYPE_BOOSTERS = ['blackbelt', 'blackglasses', 'charcoal', 'dragonfang', 'fairyfeather', 'hardstone', 'magnet',
                      'metalcoat', 'nevermeltice', 'poisonbarb', 'sharpbeak', 'silkscarf', 'silverpowder', 'softsand',
                      'spelltag', 'twistedspoon']
POOL_RESIST_BERRIES = ['babiriberry', 'chartiberry', 'chilanberry', 'cobaberry', 'colburberry', 'habanberry',
                       'kasibberry', 'kebiaberry', 'occaberry', 'passhoberry', 'payapaberry', 'rindoberry',
                       'roseliberry', 'shucaberry', 'tangaberry', 'wacanberry', 'yacheberry']
POOL_ITEMS = POOL_TYPE_BOOSTERS + POOL_RESIST_BERRIES
# The new abilities in the order of decision 0015 section 3: "-ate", then pinch. Aerilate (the "-ate" member),
# Blaze (the pinch member) and the weather and terrain setters are in the prefix.
POOL_ABILITIES = ['pixilate', 'refrigerate', 'overgrow', 'torrent', 'swarm']

# ---- Step G2 (docs/research/expansion/team-gaps.md, data/team_gaps.json "pool_rows"): every row that the 17 target
# teams need, added at once and unmarked, after the rows of step P1. Their order is that of pool_rows. ----
# The new formes: Pelipper, Arcanine-Hisui and Annihilape, and Floette-Eternal with its Mega forme. The set of each is
# a real one of the survey (MC371, MC385, MC196; Floette-Eternal's two pool moves of the survey's most used). Under
# the four frozen kinds these ids are out of range, so the set is table content that only the canonical bytes see;
# under the POOL kinds a member's moves and ability come from dfi_pool_forme_legal.
SETS_G2 = [
    ('pelipper', 'drizzle', 'sitrusberry', ['weatherball', 'hurricane', 'tailwind', 'wideguard'], None),
    ('arcaninehisui', 'rockhead', 'focussash', ['flareblitz', 'headsmash', 'extremespeed', 'protect'], None),
    ('annihilape', 'defiant', 'choicescarf', ['closecombat', 'icepunch', 'shadowclaw', 'uturn'], None),
    ('floetteeternal', 'flowerveil', 'floettite', ['dazzlinggleam', 'protect'], 'floettemega'),
]
G2_ITEMS = ['focussash', 'expertbelt', 'floettite']
G2_ABILITIES = ['rockhead', 'flowerveil', 'fairyaura']
G2_MOVES = ['uturn', 'rockslide', 'throatchop', 'encore', 'doubleedge', 'thunderbolt', 'scald', 'wideguard',
            'flashcannon', 'extremespeed', 'headsmash', 'firstimpression', 'bulkup', 'liquidation', 'icepunch',
            'shadowclaw', 'recover', 'soak', 'psychicnoise', 'drumbeating', 'lowkick', 'dazzlinggleam']
# Nine of the 22 moves have a callback or a field that the tables do not model. As decision 0009 section 3.3 did for
# Sucker Punch or Follow Me, each is mapped deliberately to a named handler id (the value of the move's special
# column) that owns what the columns cannot hold, and the engine refuses it: the move stays unmarked in the support
# manifest, and the turn code returns an error for a special it does not have. The handler may own only the
# callbacks, fields, condition block and secondary named below, each of which must be present and, for a field or a
# secondary, exactly this text of the pinned data; everything else about the move is read by parse_move as for any
# other move, and anything it does not know still fails. Each step that implements one of them (G7 to G11) consumes
# the handler id and, if it needs a column, changes the tables and the POOL fingerprint and says so.
G2_HANDLERS = ['THROAT_CHOP', 'ENCORE', 'SCALD', 'WIDE_GUARD', 'FIRST_IMPRESSION', 'RECOVER', 'SOAK', 'PSYCHIC_NOISE',
               'LOW_KICK']
SPECIAL_P = dict(SPECIAL_C, **{
    'throatchop': ('THROAT_CHOP', set()),                                 # G8a: a lockout volatile of the sound moves
    'encore': ('ENCORE', set()),                                          # G9: the last move, a volatile, a queue change
    'wideguard': ('WIDE_GUARD', {'onTry', 'onHitSide'}),                  # G7: a side condition against spread moves
    'firstimpression': ('FIRST_IMPRESSION', {'onTry', 'onDisableMove'}),  # G10a: first turn out only (Fake Out's rule)
    'soak': ('SOAK', {'onHit'}),                                          # G11: sets the target's type to Water
    'psychicnoise': ('PSYCHIC_NOISE', set()),                             # G8b: Heal Block on every hit target
    'lowkick': ('LOW_KICK', {'basePowerCallback', 'onTryHit'}),           # G10d: base power by the target's weight
})
SPECIAL_IDS_P = SPECIAL_IDS_C + G2_HANDLERS
# Step G10 made two of the nine handlers data: Scald (thawsTarget) and Recover (heal) are read into the move extra
# column below and have the special NONE; their ids stay defined (the ids after them keep their values).
POOL_COLUMN_KEYS = {'thawsTarget', 'heal'}
G2_OWNED_FIELDS = {
    'ENCORE': {'volatileStatus': "volatileStatus: 'encore',"},
    'WIDE_GUARD': {'sideCondition': "sideCondition: 'wideguard',"},
}
G2_OWNED_SECONDARY = {
    'THROAT_CHOP': "secondary: { chance: 100, onHit(target) { target.addVolatile('throatchop'); }, },",
    'PSYCHIC_NOISE': "secondary: { chance: 100, volatileStatus: 'healblock', },",
}
G2_OWNED_CONDITION = {'THROAT_CHOP', 'ENCORE', 'WIDE_GUARD'}
# Move flags that the new moves carry and no row reads. `punch` is read by Iron Fist and `slicing` (already ignored)
# by Sharpness, `allyanim` by nothing in the tables: build_pool fails if one of those readers is a pool ability,
# because ignoring the flag would then hide a mechanic.
G2_IGNORED_FLAGS = {'punch', 'allyanim'}
FLAG_READERS = {'punch': 'ironfist', 'slicing': 'sharpness'}

ITEM_FAMILIES = ['NONE', 'TYPE_BOOSTER', 'RESIST_BERRY']
ABILITY_FAMILIES = ['NONE', 'ATE', 'PINCH', 'WEATHER_SETTER', 'TERRAIN_SETTER']
FAMILY_PARAM_NONE = 0xFF
# The members of each family, as decision 0015 section 3 names them (prefix and new rows). The parameter of a member
# is never listed here: it comes from the pinned handler. Every id of the pool that is not listed has no family.
ITEM_MEMBERS = {'TYPE_BOOSTER': ['miracleseed', 'mysticwater'] + POOL_TYPE_BOOSTERS,
                'RESIST_BERRY': ['chopleberry'] + POOL_RESIST_BERRIES}
ABILITY_MEMBERS = {'ATE': ['aerilate', 'pixilate', 'refrigerate'],
                   'PINCH': ['blaze', 'overgrow', 'torrent', 'swarm'],
                   'WEATHER_SETTER': ['drizzle', 'drought'],
                   'TERRAIN_SETTER': ['grassysurge', 'psychicsurge']}
# The weather and terrain codes of the family column are the engine's state values (DFI_WEATHER_* and
# DFI_TERRAIN_* of src/state/battle_internal.h, which duoforge.data.pool_tables checks), by Showdown's id.
WEATHER_CODES = {'raindance': ('RAIN', 1), 'sunnyday': ('SUN', 2)}
TERRAIN_CODES = {'grassyterrain': ('GRASSY', 1), 'psychicterrain': ('PSYCHIC', 2)}
# A rain or sun setter skips the Primal Pokemon with their orb (data/abilities.ts, Drizzle and Drought). No Primal
# Pokemon is legal in the format; the guard is part of the weather pattern and must be exactly this one.
PRIMAL_GUARD = {'raindance': ('kyogre', 'blueorb'), 'sunnyday': ('groudon', 'redorb')}
# Chilan Berry halves any Normal hit; every other resist berry needs a super effective hit (decision 0015 section 3).
# A Normal move is never super effective, so the variant is the Normal berry.
RESIST_BERRY_NORMAL = ('chilanberry',)


class NoMatch(Exception):
    """An entry does not follow the pattern of a family."""


def norm(text):
    return ' '.join(text.split())


def shape(f, keys):
    """The entry has exactly these top-level fields: nothing that the pattern does not account for."""
    if set(f) != keys:
        raise NoMatch('fields %s, not %s' % (sorted(f), sorted(keys)))


def field_is(f, key, want):
    if norm(f[key][1]) != want:
        raise NoMatch('%s is "%s", not "%s"' % (key, norm(f[key][1]), want))


def field_match(f, key, pattern):
    m = re.fullmatch(pattern, norm(f[key][1]))
    if m is None:
        raise NoMatch('%s deviates from the pattern: %s' % (key, norm(f[key][1])))
    return m


# Items. Type booster: BasePower x4915/4096 for a move of the type, priority 15. The `move &&` guard of seven of the
# eighteen is the only textual variation and has no effect.
ITEM_BOOSTER_KEYS = {'name', 'spritenum', 'fling', 'onBasePowerPriority', 'onBasePower', 'num', 'gen'}
ITEM_BOOSTER_BASE_POWER = (r"onBasePower\(basePower, user, target, move\) \{ if \((?:move && )?move\.type === '(\w+)'\) "
                           r"\{ return this\.chainModify\(\[4915, 4096\]\); \} \},")


def type_booster_type(f, _iid):
    shape(f, ITEM_BOOSTER_KEYS)
    field_is(f, 'onBasePowerPriority', 'onBasePowerPriority: 15,')
    return field_match(f, 'onBasePower', ITEM_BOOSTER_BASE_POWER).group(1)


# Resist berry: the target eats it on a super effective hit of the type (Chilan: on any Normal hit), ModifyDamage
# x0.5. The natural gift type is a second statement of the type and must agree.
ITEM_BERRY_KEYS = {'name', 'spritenum', 'isBerry', 'naturalGift', 'onSourceModifyDamage', 'onEat', 'num', 'gen'}
BERRY_NATURAL_GIFT = r'naturalGift: \{ basePower: 80, type: "(\w+)", \},'
BERRY_HEAD = r"onSourceModifyDamage\(damage, source, target, move\) \{ "
BERRY_EAT = (r"if \(target\.eatItem\(\)\) \{ this\.debug\('-50% reduction'\); "
             r"this\.add\('-enditem', target, this\.effect, '\[weaken\]'\); return this\.chainModify\(0\.5\); "
             r"\} \} \},")
BERRY_SUPER_EFFECTIVE = (BERRY_HEAD + r"if \(move\.type === '(\w+)' && target\.getMoveHitData\(move\)\.typeMod > 0\) \{ "
                         r"const hitSub = target\.volatiles\['substitute'\] && !move\.flags\['bypasssub'\] && "
                         r"!\(move\.infiltrates && this\.gen >= 6\); if \(hitSub\) return; " + BERRY_EAT)
BERRY_NORMAL_HIT = (BERRY_HEAD + r"if \( move\.type === '(Normal)' && \(!target\.volatiles\['substitute'\] \|\| "
                    r"move\.flags\['bypasssub'\] \|\| \(move\.infiltrates && this\.gen >= 6\)\) \) \{ " + BERRY_EAT)


def resist_berry_type(f, iid):
    shape(f, ITEM_BERRY_KEYS)
    field_is(f, 'isBerry', 'isBerry: true,')
    field_is(f, 'onEat', 'onEat() { },')
    gift = field_match(f, 'naturalGift', BERRY_NATURAL_GIFT).group(1)
    pattern = BERRY_NORMAL_HIT if iid in RESIST_BERRY_NORMAL else BERRY_SUPER_EFFECTIVE
    t = field_match(f, 'onSourceModifyDamage', pattern).group(1)
    if t != gift:
        raise NoMatch('the natural gift type %s differs from the handler type %s' % (gift, t))
    return t


ITEM_MATCHERS = [('TYPE_BOOSTER', type_booster_type), ('RESIST_BERRY', resist_berry_type)]

# Abilities. "-ate": Normal moves become the type (ModifyType, priority -1) and get BasePower x4915/4096 (priority 23).
ABILITY_ATE_KEYS = {'onModifyTypePriority', 'onModifyType', 'onBasePowerPriority', 'onBasePower', 'flags', 'name',
                    'rating', 'num'}
ATE_MODIFY_TYPE = (r"onModifyType\(move, pokemon\) \{ const noModifyType = \[ 'judgment', 'multiattack', 'naturalgift', "
                   r"'revelationdance', 'technoblast', 'terrainpulse', 'weatherball', \]; "
                   r"if \(move\.type === 'Normal' && \(!noModifyType\.includes\(move\.id\) \|\| "
                   r"this\.activeMove\?\.isMax\) && !\(move\.isZ && move\.category !== 'Status'\) && "
                   r"!\(move\.name === 'Tera Blast' && pokemon\.terastallized\)\) \{ "
                   r"move\.type = '(\w+)'; move\.typeChangerBoosted = this\.effect; \} \},")
ATE_BASE_POWER = (r"onBasePower\(basePower, pokemon, target, move\) \{ "
                  r"if \(move\.typeChangerBoosted === this\.effect\) return this\.chainModify\(\[4915, 4096\]\); \},")


def ate_type(f):
    shape(f, ABILITY_ATE_KEYS)
    field_is(f, 'onModifyTypePriority', 'onModifyTypePriority: -1,')
    field_is(f, 'onBasePowerPriority', 'onBasePowerPriority: 23,')
    field_is(f, 'flags', 'flags: {},')
    t = field_match(f, 'onModifyType', ATE_MODIFY_TYPE).group(1)
    field_match(f, 'onBasePower', ATE_BASE_POWER)
    return t


# Pinch: Atk and SpA x1.5 for a move of the type at a third of the HP or less (priority 5 for both).
ABILITY_PINCH_KEYS = {'onModifyAtkPriority', 'onModifyAtk', 'onModifySpAPriority', 'onModifySpA', 'flags', 'name',
                      'rating', 'num'}


def pinch_handler(callback, name):
    return (r"%s\(atk, attacker, defender, move\) \{ if \(move\.type === '(\w+)' && attacker\.hp <= attacker\.maxhp / 3\) "
            r"\{ this\.debug\('%s boost'\); return this\.chainModify\(1\.5\); \} \}," % (callback, re.escape(name)))


def pinch_type(f):
    shape(f, ABILITY_PINCH_KEYS)
    field_is(f, 'onModifyAtkPriority', 'onModifyAtkPriority: 5,')
    field_is(f, 'onModifySpAPriority', 'onModifySpAPriority: 5,')
    field_is(f, 'flags', 'flags: {},')
    name = scalar(f['name'][1])
    atk = field_match(f, 'onModifyAtk', pinch_handler('onModifyAtk', name)).group(1)
    spa = field_match(f, 'onModifySpA', pinch_handler('onModifySpA', name)).group(1)
    if atk != spa:
        raise NoMatch('Atk type %s, SpA type %s' % (atk, spa))
    return atk


# Weather and terrain setters: onStart sets the field condition (the weather setters with the Primal guard).
ABILITY_FIELD_KEYS = {'onStart', 'flags', 'name', 'rating', 'num'}


def weather_setter_weather(f):
    shape(f, ABILITY_FIELD_KEYS)
    field_is(f, 'flags', 'flags: {},')
    m = field_match(f, 'onStart', r"onStart\(source\) \{ (?:if \(source\.species\.id === '(\w+)' && "
                                  r"source\.item === '(\w+)'\) return; )?this\.field\.setWeather\('(\w+)'\); \},")
    species, orb, weather = m.groups()
    if weather not in WEATHER_CODES:
        raise NoMatch('weather %s has no state code' % weather)
    if (species, orb) != PRIMAL_GUARD.get(weather, (None, None)):
        raise NoMatch('the Primal guard (%s, %s) is not the one of %s' % (species, orb, weather))
    return weather


def terrain_setter_terrain(f):
    shape(f, ABILITY_FIELD_KEYS)
    field_is(f, 'flags', 'flags: {},')
    terrain = field_match(f, 'onStart', r"onStart\(source\) \{ this\.field\.setTerrain\('(\w+)'\); \},").group(1)
    if terrain not in TERRAIN_CODES:
        raise NoMatch('terrain %s has no state code' % terrain)
    return terrain


ABILITY_MATCHERS = [('ATE', lambda f, _aid: ate_type(f)), ('PINCH', lambda f, _aid: pinch_type(f)),
                    ('WEATHER_SETTER', lambda f, _aid: weather_setter_weather(f)),
                    ('TERRAIN_SETTER', lambda f, _aid: terrain_setter_terrain(f))]


def derive_family(src, champ, rid, expected, matchers, what):
    """The family fact of one item or ability: the pattern result of the family that decision 0015 lists it in.
    A listed member that deviates from the pattern of its family fails; so does an unlisted one that follows a
    pattern (it should be listed). The Champions mod may only change isNonstandard of a member. Returns
    (family, fact) with fact the Showdown name of the type, weather or terrain, None for no family."""
    e = src.entry(rid)
    if e is None:
        fail('%s %s: entry not found in %s' % (what, rid, src.rel))
    f = fields(e[2])
    found, why = {}, {}
    for family, matcher in matchers:
        try:
            found[family] = matcher(f, rid)
        except NoMatch as err:
            why[family] = str(err)
    if expected == 'NONE':
        if found:
            fail('%s %s follows the %s pattern but decision 0015 does not list it as a member' % (
                what, rid, '/'.join(sorted(found))))
        return 'NONE', None
    if expected not in found:
        fail('%s %s is listed as %s but deviates: %s' % (what, rid, expected, why[expected]))
    ce = champ.entry(rid)
    if ce is not None:
        cf = fields(ce[2])
        if set(cf) - {'inherit', 'isNonstandard'}:
            fail('%s %s: the champions mod changes %s' % (what, rid, sorted(set(cf) - {'inherit', 'isNonstandard'})))
    return expected, found[expected]


def load_legal_pool(repo):
    """The ids that TeamValidator accepted at the pin: docs/research/expansion/data/legal_pool.json, the output of
    build_legal_pool.js (its Showdown commit and format are checked), with the legal moves and abilities of every
    species. duoforge.data.pool_families runs the pinned validator on the pool again."""
    with io.open(os.path.join(repo, LEGAL_POOL), encoding='utf-8') as fh:
        legal = json.load(fh)
    if legal['meta']['showdown_commit'] != PIN or legal['meta']['format_id'] != FORMAT_ID:
        fail('%s was not made at the pin for %s' % (LEGAL_POOL, FORMAT_ID))
    return {'items': {i['id'] for i in legal['items']}, 'abilities': {a['id'] for a in legal['abilities']},
            'species': {sp['id']: sp for sp in legal['species']}}


# The legal moves and abilities of a forme (decision 0015 section 2). A forme declares up to three abilities (0, 1 and
# the hidden one); the event-only ones are not legal.
FORME_ABILITIES_MAX = 3
LEARNSET_ENTRY = re.compile(r'\t\t\t(\w+): \["9M"\],')


def learnset_moves(learn, fid):
    """The moves of a forme's entry of data/mods/champions/learnsets.ts: one learnset block in which every entry is
    "9M" (no event, egg or level-up source, as the research note found), so learnable means listed. Any other shape
    fails; it never guesses."""
    e = learn.entry(fid)
    if e is None:
        fail('%s has no champions learnset' % fid)
    body = e[2]
    # The entry may start with `inherit: true,`: the Champions mod then keeps the other fields of the base entry
    # (Floette-Eternal's event data) and replaces the learnset. The validator cross-check of forme_legal decides
    # whether the learnset is the legal one.
    head = 2 if len(body) > 1 and body[1] == '\t\tinherit: true,' else 1
    if len(body) < head + 3 or body[head] != '\t\tlearnset: {' or body[-2] != '\t\t},' or body[-1] != '\t},':
        fail('%s: the champions learnset entry is not a single learnset block' % fid)
    moves = []
    for line in body[head + 1:-2]:
        m = LEARNSET_ENTRY.fullmatch(line)
        if m is None:
            fail('%s: a learnset line that is not "9M": %s' % (fid, line.strip()))
        moves.append(m.group(1))
    if len(set(moves)) != len(moves):
        fail('%s: a move twice in the champions learnset' % fid)
    return set(moves)


def ability_released(abil_ts, champ_abil, aid):
    """Fails for an ability that the pin tags as not released (isNonstandard) unless the Champions mod releases it."""
    e = abil_ts.entry(aid)
    if e is None:
        fail('ability %s not found in %s' % (aid, abil_ts.rel))
    f = fields(e[2])
    if 'isNonstandard' in f:
        ce = champ_abil.entry(aid)
        cf = fields(ce[2]) if ce is not None else {}
        if 'isNonstandard' not in cf or scalar(cf['isNonstandard'][1]) != 'null':
            fail('ability %s is tagged %s' % (aid, scalar(f['isNonstandard'][1])))


def wrap_names(head, names, width=100):
    """Comment lines that hold `head` and then the names, wrapped between names, never inside one."""
    lines, line = [], head
    for i, name in enumerate(names):
        piece = name + (',' if i + 1 < len(names) else '')
        if len(line) + 1 + len(piece) > width and line != head:
            lines.append(line)
            line = '   ' + piece
        else:
            line += ' ' + piece
    lines.append(line)
    return lines


def forme_legal(formes, pool_moves, pool_abilities, learn, legal_species, abil_ts, champ_abil):
    """Per forme: the pool moves it learns (a bitset over pool_moves, bit i of byte i / 8) and its legal abilities (ids
    over pool_abilities, in the pokedex's slot order). The abilities are the declared ones that the validator allows
    in Champions, cut to the pool; a base forme must keep its set's ability, a Mega forme exactly its own, and an ability
    that the pin does not release fails (Lucario-Mega-Z's Aura Guard). The moves are the learnset's, and they must be
    exactly the pool moves that the validator accepts for the species. A Mega forme is never set up: no moves."""
    nbytes = (len(pool_moves) + 7) // 8
    ability_index = {a: i for i, a in enumerate(pool_abilities)}
    out = []
    for fo in formes:
        rec = legal_species.get(fo['id'])
        if rec is None:
            fail('%s is not a species of %s' % (fo['id'], LEGAL_POOL))
        abilities = []
        for aid in fo['abilities']:
            if aid in rec['abilities_legal']:
                if fo['is_mega'] or aid in ability_index:
                    ability_released(abil_ts, champ_abil, aid)
                if aid in ability_index:
                    abilities.append(ability_index[aid])
        if fo['is_mega']:
            if abilities != [fo['ability']] or len(fo['abilities']) != 1:
                fail('%s: a Mega forme must have exactly its one legal ability in the pool' % fo['id'])
            learnable = set()
        else:
            if fo['ability'] not in abilities:
                fail('%s: its set ability is not one of its legal abilities' % fo['id'])
            if len(abilities) > FORME_ABILITIES_MAX:
                fail('%s: more than %d legal abilities' % (fo['id'], FORME_ABILITIES_MAX))
            learnable = learnset_moves(learn, fo['id']) & set(pool_moves)
            legal_moves = set(rec['moves']) & set(pool_moves)
            if learnable != legal_moves:
                fail('%s: the learnset and the validator disagree on %s' % (
                    fo['id'], sorted(learnable ^ legal_moves)))
            if not {pool_moves[k] for k in fo['set_moves']} <= learnable:
                fail('%s: a move of its set is not learnable' % fo['id'])
        bits = [0] * nbytes
        for i, m in enumerate(pool_moves):
            if m in learnable:
                bits[i // 8] |= 1 << (i % 8)
        out.append({'learnable': bits, 'abilities': abilities, 'moves': [m for m in pool_moves if m in learnable]})
    return out


def item_param(family, fact):
    """(parameter byte, its name in C) of an item's family column: the type."""
    if family == 'NONE':
        return FAMILY_PARAM_NONE, 'DFI_FAMILY_PARAM_NONE'
    return TYPES.index(fact), 'DFI_TYPE_' + fact.upper()


def ability_param(family, fact):
    """(parameter byte, its name in C) of an ability's family column: a type, a weather or a terrain."""
    if family in ('ATE', 'PINCH'):
        return TYPES.index(fact), 'DFI_TYPE_' + fact.upper()
    if family == 'WEATHER_SETTER':
        return WEATHER_CODES[fact][1], 'DFI_FAMILY_WEATHER_' + WEATHER_CODES[fact][0]
    if family == 'TERRAIN_SETTER':
        return TERRAIN_CODES[fact][1], 'DFI_FAMILY_TERRAIN_' + TERRAIN_CODES[fact][0]
    return FAMILY_PARAM_NONE, 'DFI_FAMILY_PARAM_NONE'


def check_flag_readers(abilities):
    """A move flag that the tables ignore must have no reader among the pool abilities."""
    for flag, reader in FLAG_READERS.items():
        if any(a['id'] == reader for a in abilities):
            fail('ability %s reads the move flag %s, which the tables ignore' % (reader, flag))


def build_pool(root, repo, dx):
    """The pool tables: the extended data as the prefix, then the new rows of step P1 (POOL_ITEMS, POOL_ABILITIES),
    then those of step G2 (G2_MOVES, G2_ITEMS, G2_ABILITIES and the formes of SETS_G2), then the family columns of
    every item and ability and the legal moves and abilities of every forme, the prefix included."""
    dex, moves_ts = Source(root, 'data/pokedex.ts'), Source(root, 'data/moves.ts')
    champ_moves = Source(root, 'data/mods/champions/moves.ts')
    items_ts, champ_items = Source(root, 'data/items.ts'), Source(root, 'data/mods/champions/items.ts')
    abil_ts, champ_abil = Source(root, 'data/abilities.ts'), Source(root, 'data/mods/champions/abilities.ts')
    formats, learn = Source(root, 'data/mods/champions/formats-data.ts'), Source(root, 'data/mods/champions/learnsets.ts')
    legal = load_legal_pool(repo)
    items, abilities = list(dx['items']), list(dx['abilities'])
    for iid in POOL_ITEMS + G2_ITEMS:
        if any(i['id'] == iid for i in items):
            fail('pool item %s is already in the extended tables' % iid)
        e = items_ts.entry(iid)
        if e is None:
            fail('item %s not found' % iid)
        text = '\n'.join(e[2])
        if 'isNonstandard' in text and champ_items.entry(iid) is None:
            fail('item %s is nonstandard and has no champions override' % iid)
        stone = re.search(r'megaStone: \{ "(.*?)": "(.*?)" \}', text)
        refs = [items_ts.ref(iid)] + ([champ_items.ref(iid)] if champ_items.entry(iid) is not None else [])
        items.append({'id': iid, 'name': re.search(r'name: "(.*?)"', text).group(1), 'refs': refs,
                      'stone': (toid(stone.group(1)), toid(stone.group(2))) if stone else None,
                      'mega_base': 0xFF, 'mega_forme': 0xFF})
    for aid in POOL_ABILITIES + G2_ABILITIES:
        if any(a['id'] == aid for a in abilities):
            fail('pool ability %s is already in the extended tables' % aid)
        if abil_ts.entry(aid) is None:
            fail('ability %s not found' % aid)
        abilities.append({'id': aid, 'refs': [abil_ts.ref(aid)] + ([champ_abil.ref(aid)]
                                                                   if champ_abil.entry(aid) is not None else [])})
    check_flag_readers(abilities)
    moves = list(dx['moves'])
    for mid in G2_MOVES:
        if any(m['id'] == mid for m in moves):
            fail('pool move %s is already in the extended tables' % mid)
        moves.append(parse_move(mid, moves_ts, champ_moves, pool=True))
    move_index = {m['id']: i for i, m in enumerate(moves)}
    item_index = {it['id']: i for i, it in enumerate(items)}
    ability_index = {ab['id']: i for i, ab in enumerate(abilities)}
    formes = list(dx['formes'])
    forme_index = {fo['id']: i for i, fo in enumerate(formes)}
    first_new, n_items, n_abilities = len(formes), len(items), len(abilities)
    build_group(SETS_G2, items, item_index, abilities, ability_index, formes, forme_index, move_index, dex, items_ts,
                champ_items, abil_ts, champ_abil, formats, learn)
    if (len(items), len(abilities)) != (n_items, n_abilities):
        fail('a set of SETS_G2 holds an item or an ability that is not a pool row')
    for fo in formes[first_new:]:
        base = fo['id'] if not fo['is_mega'] else [s for s, _a, _i, _m, mg in SETS_G2 if mg == fo['id']][0]
        fo['base_forme'] = forme_index[base]
        fo['mega_forme'] = forme_index[fo['mega']] if fo['mega'] else 0xFF
        fo['mega_item'] = fo['set_item'] if (fo['mega'] or fo['is_mega']) else 0xFF
    for it in items[len(dx['items']):]:
        it['mega_base'] = forme_index[it['stone'][0]] if it['stone'] else 0xFF
        it['mega_forme'] = forme_index[it['stone'][1]] if it['stone'] else 0xFF
    for it in items:
        if it['id'] not in legal['items']:
            fail('item %s is not legal in %s (%s)' % (it['id'], FORMAT_ID, LEGAL_POOL))
    for ab in abilities:
        if ab['id'] not in legal['abilities']:
            fail('ability %s is not legal in %s (%s)' % (ab['id'], FORMAT_ID, LEGAL_POOL))
    for members, rows, what in ((ITEM_MEMBERS, items, 'item'), (ABILITY_MEMBERS, abilities, 'ability')):
        for family, ids in members.items():
            if len(set(ids)) != len(ids) or any(i not in [r['id'] for r in rows] for i in ids):
                fail('%s family %s lists an id twice or one that is not in the pool' % (what, family))
    item_of = {i: f for f, ids in ITEM_MEMBERS.items() for i in ids}
    ability_of = {a: f for f, ids in ABILITY_MEMBERS.items() for a in ids}
    item_family, ability_family = [], []
    for it in items:
        fam, fact = derive_family(items_ts, champ_items, it['id'], item_of.get(it['id'], 'NONE'), ITEM_MATCHERS, 'item')
        param, pname = item_param(fam, fact)
        item_family.append({'family': fam, 'family_id': ITEM_FAMILIES.index(fam), 'param': param, 'param_name': pname})
    for ab in abilities:
        fam, fact = derive_family(abil_ts, champ_abil, ab['id'], ability_of.get(ab['id'], 'NONE'), ABILITY_MATCHERS,
                                  'ability')
        param, pname = ability_param(fam, fact)
        ability_family.append({'family': fam, 'family_id': ABILITY_FAMILIES.index(fam), 'param': param,
                               'param_name': pname})
    # "All 18": one type booster and one resist berry for every type, and no other member of either family.
    for fam in ('TYPE_BOOSTER', 'RESIST_BERRY'):
        types = sorted(c['param'] for c in item_family if c['family'] == fam)
        if types != list(range(len(TYPES))):
            fail('the %s items do not cover each of the %d types exactly once' % (fam, len(TYPES)))
    legal_formes = forme_legal(formes, [m['id'] for m in moves], [a['id'] for a in abilities], learn,
                               legal['species'], abil_ts, champ_abil)
    # The move extra column: what a move needs beyond the closure row (step G10), one row per pool move. The rows of
    # the extended moves come from a build without these fields, so they have none.
    move_extra = [{'thaws_target': m.get('thaws_target', 0), 'heal': m.get('heal', [0, 0])} for m in moves]
    return dict(dx, formes=formes, moves=moves, items=items, abilities=abilities, item_family=item_family,
                ability_family=ability_family, forme_legal=legal_formes, move_extra=move_extra)


def family_bytes(d):
    """The family columns as they follow the closure layout in the canonical pool bytes: per item, then per ability,
    the family id and the parameter."""
    b = bytearray()
    for col in d['item_family'] + d['ability_family']:
        b.extend([col['family_id'], col['param']])
    return bytes(b)


def forme_legal_bytes(d):
    """The legal moves and abilities of the formes in the canonical pool bytes: per forme, in id order, the learnable
    bitset, the number of legal abilities and the ability ids (unused slots 0xFF)."""
    b = bytearray()
    for fl in d['forme_legal']:
        b.extend(fl['learnable'])
        b.append(len(fl['abilities']))
        b.extend(fl['abilities'] + [0xFF] * (FORME_ABILITIES_MAX - len(fl['abilities'])))
    return bytes(b)


def move_extra_bytes(d):
    """The move extra column in the canonical pool bytes: per move, in id order, the flags (bit 0: the move thaws a
    frozen target) and the heal fraction (numerator, denominator; 0 and 0 for none)."""
    b = bytearray()
    for x in d['move_extra']:
        b.extend([x['thaws_target'], x['heal'][0], x['heal'][1]])
    return bytes(b)


def canonical_pool(d):
    """The canonical pool bytes hashed into the context fingerprint of the POOL kinds: the closure layout over the
    pool data, then the family columns, then the legal moves and abilities of the formes, then the move extra
    column."""
    return canonical(d) + family_bytes(d) + forme_legal_bytes(d) + move_extra_bytes(d)


def ext_prefix(dp, dx):
    """The extended projection of the pool data: its first extended-count rows, every immunity bit."""
    return {'formes': dp['formes'][:len(dx['formes'])], 'moves': dp['moves'][:len(dx['moves'])],
            'items': dp['items'][:len(dx['items'])], 'abilities': dp['abilities'][:len(dx['abilities'])],
            'chart': dp['chart'], 'immunity': dp['immunity'], 'natures': dp['natures']}


def check_pool_prefix(dp, dx, dc):
    """Decision 0015 section 2: every extended row, and so every closure row, is the pool row of its id."""
    for key in ('formes', 'moves', 'items', 'abilities'):
        if dp[key][:len(dx[key])] != dx[key]:
            fail('pool %s do not start with the extended %s' % (key, key))
    for key in ('chart', 'immunity', 'natures'):
        if dp[key] != dx[key]:
            fail('the pool %s differ from the extended ones' % key)
    if canonical(ext_prefix(dp, dx)) != canonical(dx):
        fail('the pool tables do not start with the extended tables')
    if canonical(closure_prefix(dp, dc)) != canonical(dc):
        fail('the pool tables do not start with the closure tables')
    if len(dp['item_family']) != len(dp['items']) or len(dp['ability_family']) != len(dp['abilities']):
        fail('a family column does not have one row per id')
    if len(dp['forme_legal']) != len(dp['formes']):
        fail('the legal moves and abilities do not have one row per forme')
    if len(dp['move_extra']) != len(dp['moves']):
        fail('the move extra column does not have one row per move')
    if any(x['thaws_target'] or x['heal'] != [0, 0] for x in dp['move_extra'][:len(dx['moves'])]):
        fail('a move of the extended tables has a move extra row')


def check_names(dp):
    """The names of the data query API are the ids of the rows: Showdown ids (toID), never empty and unique per
    table, so that a name finds exactly one id."""
    for key in ('formes', 'moves', 'items', 'abilities', 'natures'):
        names = [r['id'] for r in dp[key]]
        if any(re.fullmatch(r'[a-z0-9]+', n) is None for n in names):
            fail('a %s id is not a Showdown id (lower-case letters and digits)' % key)
        if len(set(names)) != len(names):
            fail('two %s have the same id' % key)


def render_pool(dp, dx):
    check_names(dp)
    can = canonical_pool(dp)
    digest = hashlib.sha256(can).hexdigest()
    nx = {key: len(dx[key]) for key in ('formes', 'moves', 'items', 'abilities')}

    def defines(prefix, rows, start):
        return '\n'.join('#define %s_%s %du' % (prefix, r['id'].upper(), i) for i, r in enumerate(rows) if i >= start)

    new_special = '\n'.join('#define DFI_SPECIAL_%s %du' % (n, i) for i, n in enumerate(SPECIAL_IDS_P)
                            if i >= len(SPECIAL_IDS_C))
    h = '''#ifndef DUOFORGE_DATA_POOL_TABLES_H
#define DUOFORGE_DATA_POOL_TABLES_H
/*
 * GENERATED by tools/datagen/gen_closure.py --pool -- do not edit.
 *
 * The pool tables of decision 0015: the extended tables (the closure tables
 * followed by Team C, decision 0009) unchanged as the prefix, then the rows
 * that the steps of the content expansion add, read from Pokemon Showdown
 * %s (the input files of
 * closure_tables.h). Every id below an extended count (DFI_EXT_FORME_COUNT,
 * DFI_EXT_MOVE_COUNT, DFI_EXT_ITEM_COUNT, DFI_EXT_ABILITY_COUNT) is the
 * extended table's and its row equals the extended row. Natures and the type
 * chart are the closure's.
 *
 * The family columns are arrays of their own, so that the row types stay
 * those of the closure tables. They hold, for every item and ability
 * (the prefix included), its family and the parameter the family rule reads;
 * each is the result of one strict pattern over the pinned handler. They are
 * part of the canonical pool bytes and so of the pool table hash, and not of
 * the closure or extended bytes. A family column says what an id is, not
 * that the engine implements it: the support manifest decides that.
 *
 * Data only. An id names a record; every effect needs a typed handler in C
 * and an entry in the support manifest before a battle may use it.
 */
#include <stddef.h>
#include <stdint.h>

#include "data/extended_tables.h"

/* ---- pool formes (appended after the extended ones): step G2 ---- */
%s
#define DFI_POOL_FORME_COUNT %du

/* ---- pool moves (appended after the extended ones): step G2 ---- */
%s
#define DFI_POOL_MOVE_COUNT %du

/* ---- handlers new in the pool tables (step G2): the value of the special column of the moves that have a
 * callback or a field that the columns do not model. The engine refuses every one of them, and so does the
 * support manifest, which leaves the move unmarked. ---- */
%s

/* ---- pool abilities (appended after the extended ones): step P1, then step G2 ---- */
%s
#define DFI_POOL_ABILITY_COUNT %du

/* ---- pool items (appended after the extended ones): step P1 (type boosters, then resist berries), then step G2 ---- */
%s
#define DFI_POOL_ITEM_COUNT %du

/* ---- family columns ----
 * Items: TYPE_BOOSTER holds BasePower x4915/4096 for a move of the type
 * (priority 15); RESIST_BERRY is eaten on a super effective hit of the type
 * (ModifyDamage x0.5); the Normal berry (Chilan) halves any Normal hit,
 * since a Normal move is never super effective.
 * Abilities: ATE turns Normal moves into the type and gives them BasePower
 * x4915/4096 (priority 23); PINCH gives Atk and SpA x1.5 for a move of the
 * type at a third of the HP or less; WEATHER_SETTER and TERRAIN_SETTER set
 * the field condition on entry.
 * The parameter is a DFI_TYPE_* (items; ATE and PINCH), a
 * DFI_FAMILY_WEATHER_* or a DFI_FAMILY_TERRAIN_*, and DFI_FAMILY_PARAM_NONE
 * where there is no family. The weather and terrain codes are the state
 * values of the engine (DFI_WEATHER_*, DFI_TERRAIN_*). */
#define DFI_ITEM_FAMILY_NONE 0u
#define DFI_ITEM_FAMILY_TYPE_BOOSTER 1u
#define DFI_ITEM_FAMILY_RESIST_BERRY 2u
#define DFI_ABILITY_FAMILY_NONE 0u
#define DFI_ABILITY_FAMILY_ATE 1u
#define DFI_ABILITY_FAMILY_PINCH 2u
#define DFI_ABILITY_FAMILY_WEATHER_SETTER 3u
#define DFI_ABILITY_FAMILY_TERRAIN_SETTER 4u
#define DFI_FAMILY_WEATHER_RAIN 1u
#define DFI_FAMILY_WEATHER_SUN 2u
#define DFI_FAMILY_TERRAIN_GRASSY 1u
#define DFI_FAMILY_TERRAIN_PSYCHIC 2u
#define DFI_FAMILY_PARAM_NONE 0xFFu

typedef struct dfi_item_family {
    uint8_t family; /* DFI_ITEM_FAMILY_* */
    uint8_t type;   /* the type of the family rule (DFI_TYPE_*), DFI_FAMILY_PARAM_NONE without a family */
} dfi_item_family;

typedef struct dfi_ability_family {
    uint8_t family; /* DFI_ABILITY_FAMILY_* */
    uint8_t param;  /* ATE, PINCH: DFI_TYPE_*; WEATHER_SETTER: DFI_FAMILY_WEATHER_*; TERRAIN_SETTER: DFI_FAMILY_TERRAIN_* */
} dfi_ability_family;

/* ---- the moves and abilities of each forme (decision 0015 section 2) ----
 * For a base forme: the pool moves it learns (the Champions learnsets, every
 * entry "9M", so learnable means listed; one bit per pool move: bit
 * (move modulo 8) of byte (move divided by 8)) and its legal abilities (the pokedex's, the ones
 * the validator allows in Champions, cut to the pool abilities, in slot
 * order). A Mega forme is never set up: no learnable move, its one ability.
 * Under the POOL kinds a member's moves and ability are chosen from these;
 * under the other kinds the forme's set (the row of dfi_pool_formes). */
#define DFI_POOL_LEARN_BYTES %du
#define DFI_POOL_FORME_ABILITIES_MAX %du

typedef struct dfi_forme_legal {
    uint8_t learnable[DFI_POOL_LEARN_BYTES];
    uint8_t ability_count; /* the first ability_count entries of abilities[] */
    uint8_t abilities[DFI_POOL_FORME_ABILITIES_MAX]; /* ability ids, then DFI_CLOSURE_NONE */
} dfi_forme_legal;

extern const dfi_forme_data dfi_pool_formes[DFI_POOL_FORME_COUNT];
extern const dfi_move_data dfi_pool_moves[DFI_POOL_MOVE_COUNT];
extern const dfi_item_data dfi_pool_items[DFI_POOL_ITEM_COUNT];
extern const uint8_t dfi_pool_type_immunity[DFI_TYPE_COUNT]; /* DFI_IMMUNE_* bits */
extern const dfi_item_family dfi_pool_item_family[DFI_POOL_ITEM_COUNT];
extern const dfi_ability_family dfi_pool_ability_family[DFI_POOL_ABILITY_COUNT];
extern const dfi_forme_legal dfi_pool_forme_legal[DFI_POOL_FORME_COUNT];

/* ---- the move extra column (step G10) ----
 * What a move needs beyond the closure row, one row per pool move, like the
 * family columns: flags (DFI_EXTRA_THAWS_TARGET: the move thaws a frozen
 * target, thawsTarget in the pinned data) and the fraction of the maximum HP
 * that the move heals its user by (heal: [numerator, denominator], 0 and 0 for
 * none). Part of the canonical pool bytes, not of the closure or extended
 * ones. */
#define DFI_EXTRA_THAWS_TARGET 1u

typedef struct dfi_move_extra {
    uint8_t flags;
    uint8_t heal[2];
} dfi_move_extra;

extern const dfi_move_extra dfi_pool_move_extra[DFI_POOL_MOVE_COUNT];

/* ---- names ----
 * The Showdown id (toID: lower-case letters and digits) of every row, as a
 * constant string, for the data query API (duoforge_data_find, _name). They
 * come from the same run as the tables, so an id and its name always belong
 * together; they are not part of the canonical bytes, the table hash or any
 * fingerprint. The CLOSURE and TEAM_C kinds read their prefix of them. A
 * Mega forme's name is the forme's own id (for example staraptormega). */
extern const char *const dfi_pool_forme_names[DFI_POOL_FORME_COUNT];
extern const char *const dfi_pool_move_names[DFI_POOL_MOVE_COUNT];
extern const char *const dfi_pool_item_names[DFI_POOL_ITEM_COUNT];
extern const char *const dfi_pool_ability_names[DFI_POOL_ABILITY_COUNT];
extern const char *const dfi_pool_nature_names[DFI_NATURE_COUNT];

/* SHA-256 of the canonical pool bytes (written by the generator). */
#define DFI_POOL_CANONICAL_SIZE %du
extern const uint8_t dfi_pool_table_hash[32];
/* The canonical bytes of the closure layout over the first `formes`, `moves`,
 * `items` and `abilities` rows of the tables above, with every immunity byte
 * masked by `immunity_mask`; natures and the type chart are the closure's.
 * The family columns are not part of them. Returns the size, or 0 if a count
 * exceeds its table or capacity is too small. With the closure counts and the
 * closure's immunity bits these are exactly the closure's canonical bytes;
 * with the extended counts and every immunity bit, the extended ones. */
size_t dfi_pool_canonical_bytes_of(uint8_t *out, size_t capacity, uint32_t formes, uint32_t moves, uint32_t items,
                                   uint32_t abilities, uint32_t immunity_mask);
/* The canonical pool bytes: every row, every immunity bit, then the family
 * column of every item and of every ability (family, parameter), then for
 * every forme its learnable bytes, ability count and ability ids. */
size_t dfi_pool_canonical_bytes(uint8_t *out, size_t capacity);

#endif
''' % (PIN, defines('DFI_FORME', dp['formes'], nx['formes']), len(dp['formes']),
       defines('DFI_MOVE', dp['moves'], nx['moves']), len(dp['moves']), new_special,
       defines('DFI_ABILITY', dp['abilities'], nx['abilities']), len(dp['abilities']),
       defines('DFI_ITEM', dp['items'], nx['items']), len(dp['items']),
       (len(dp['moves']) + 7) // 8, FORME_ABILITIES_MAX, len(can))

    def arr(vals):
        return '{' + ', '.join('%du' % v for v in vals) + '}'

    c = ['#include "data/pool_tables.h"', '',
         '/* GENERATED by tools/datagen/gen_closure.py --pool -- do not edit. Showdown %s. */' % PIN, '',
         'const dfi_forme_data dfi_pool_formes[DFI_POOL_FORME_COUNT] = {']
    for f in dp['formes']:
        c.append('    /* %s -- %s */' % (f['name'], f['ref']))
        c.append('    {%du, %du, %s, %s, %du, %du, %du, %du, %du, %du, %du, %du, %s},' % (
            f['dex_num'], f['weight_hg'], arr(f['types']), arr(f['base']), f['ability'], f['gender_rule'],
            f['is_mega'], f['base_forme'], f['mega_forme'], f['mega_item'], f['set_item'], len(f['set_moves']),
            arr(f['set_moves'] + [0] * (4 - len(f['set_moves'])))))
    c += ['};', '', 'const dfi_move_data dfi_pool_moves[DFI_POOL_MOVE_COUNT] = {']
    for m in dp['moves']:
        c.append('    /* %s -- %s */' % (m['name'], ', '.join(m['refs'])))
        c.append('    {%du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %s, %s, %du, %du, %du, %du, %s, %du, %du, %du, %du},' % (
            m['type'], m['category'], m['base_power'], m['accuracy'], m['pp_base'], m['pp_max'], m['priority'],
            m['target_class'], m['crit_ratio'], m['flags'], arr(m['recoil']), arr(m['drain']), m['sec_chance'],
            m['sec_kind'], m['sec_param'], m['boost_role'], arr([v + 6 for v in m['boosts']]), m['primary_status'],
            m['side_condition'], m['pseudo_weather'], m['special']))
    c += ['};', '', 'const dfi_item_data dfi_pool_items[DFI_POOL_ITEM_COUNT] = {']
    for it in dp['items']:
        c.append('    /* %s -- %s */' % (it['name'], ', '.join(it['refs'])))
        c.append('    {%du, %du},' % (it['mega_base'], it['mega_forme']))
    c += ['};', '', '/* Abilities carry no table data but their family column. Provenance of the pool abilities:']
    for a in dp['abilities'][nx['abilities']:]:
        c.append(' *   %s -- %s' % (a['id'], ', '.join(a['refs'])))
    c += [' */', '', '/* data/typechart.ts: the closure bits plus psn (Poison, Steel). */',
          'const uint8_t dfi_pool_type_immunity[DFI_TYPE_COUNT] = ' + arr(dp['immunity']) + ';', '',
          '/* Family columns, one row per id (decision 0015 section 2). */',
          'const dfi_item_family dfi_pool_item_family[DFI_POOL_ITEM_COUNT] = {']
    for it, col in zip(dp['items'], dp['item_family']):
        c.append('    [DFI_ITEM_%s] = {DFI_ITEM_FAMILY_%s, %s},' % (it['id'].upper(), col['family'], col['param_name']))
    c += ['};', '', 'const dfi_ability_family dfi_pool_ability_family[DFI_POOL_ABILITY_COUNT] = {']
    for ab, col in zip(dp['abilities'], dp['ability_family']):
        c.append('    [DFI_ABILITY_%s] = {DFI_ABILITY_FAMILY_%s, %s},' % (ab['id'].upper(), col['family'],
                                                                         col['param_name']))
    c += ['};', '', '/* The moves and abilities each forme may have (decision 0015 section 2). */',
          'const dfi_forme_legal dfi_pool_forme_legal[DFI_POOL_FORME_COUNT] = {']
    for fo, fl in zip(dp['formes'], dp['forme_legal']):
        moves = [m['name'] for m in dp['moves'] if m['id'] in fl['moves']]
        for line in (wrap_names('%s -- abilities:' % fo['name'], [dp['abilities'][a]['id'] for a in fl['abilities']]) +
                     wrap_names('   learns:', moves or ['nothing'])):
            c.append('    /* ' + line + ' */')
        slots = ['DFI_ABILITY_' + dp['abilities'][a]['id'].upper() for a in fl['abilities']]
        slots += ['DFI_CLOSURE_NONE'] * (FORME_ABILITIES_MAX - len(slots))
        c.append('    [DFI_FORME_%s] = {{%s}, %du, {%s}},' % (
            fo['id'].upper(), ', '.join('0x%02xu' % b for b in fl['learnable']), len(fl['abilities']), ', '.join(slots)))
    c += ['};', '', '/* The move extra column (step G10): thaws a frozen target, and the heal fraction. */',
          'const dfi_move_extra dfi_pool_move_extra[DFI_POOL_MOVE_COUNT] = {']
    for m, x in zip(dp['moves'], dp['move_extra']):
        if x['thaws_target'] or x['heal'] != [0, 0]:
            c.append('    [DFI_MOVE_%s] = {%s, {%du, %du}},' % (
                m['id'].upper(), 'DFI_EXTRA_THAWS_TARGET' if x['thaws_target'] else '0u', x['heal'][0],
                x['heal'][1]))
    c += ['};', '', '/* Names: the Showdown id of every row (toID), not part of any hash. */']
    for what, rows, table in (('forme', dp['formes'], 'FORME'), ('move', dp['moves'], 'MOVE'),
                              ('item', dp['items'], 'ITEM'), ('ability', dp['abilities'], 'ABILITY')):
        c.append('const char *const dfi_pool_%s_names[DFI_POOL_%s_COUNT] = {' % (what, table))
        for r in rows:
            c.append('    [DFI_%s_%s] = "%s",' % (table, r['id'].upper(), r['id']))
        c += ['};', '']
    c.append('const char *const dfi_pool_nature_names[DFI_NATURE_COUNT] = {')
    for n in dp['natures']:
        c.append('    [DFI_NATURE_%s] = "%s",' % (n['id'].upper(), n['id']))
    c += ['};', '', 'const uint8_t dfi_pool_table_hash[32] = {']
    hb = bytes.fromhex(digest)
    for i in range(0, 32, 8):
        c.append('    ' + ', '.join('0x%02xu' % x for x in hb[i:i + 8]) + ',')
    c += ['};', '', '''static size_t dfi_pool_put_u16(uint8_t *out, size_t n, uint32_t v)
{
    out[n] = (uint8_t)(v & 0xFFu);             /* wide-operands-reviewed */
    out[n + 1u] = (uint8_t)((v >> 8u) & 0xFFu); /* wide-operands-reviewed */
    return n + 2u;
}

size_t dfi_pool_canonical_bytes_of(uint8_t *out, size_t capacity, uint32_t formes, uint32_t moves, uint32_t items,
                                   uint32_t abilities, uint32_t immunity_mask)
{
    if (formes > DFI_POOL_FORME_COUNT || moves > DFI_POOL_MOVE_COUNT || items > DFI_POOL_ITEM_COUNT ||
        abilities > DFI_POOL_ABILITY_COUNT) {
        return 0u;
    }
    /* counts, 24 bytes per forme, 29 per move, 2 per item, chart, immunity, natures */
    const size_t size = 12u + (size_t)formes * 24u + (size_t)moves * 29u + (size_t)items * 2u +
                        DFI_TYPE_COUNT * DFI_TYPE_COUNT + DFI_TYPE_COUNT + DFI_NATURE_COUNT * 2u;
    if (capacity < size) {
        return 0u;
    }
    size_t n = 0u;
    n = dfi_pool_put_u16(out, n, formes);
    n = dfi_pool_put_u16(out, n, moves);
    n = dfi_pool_put_u16(out, n, items);
    n = dfi_pool_put_u16(out, n, abilities);
    n = dfi_pool_put_u16(out, n, DFI_TYPE_COUNT);
    n = dfi_pool_put_u16(out, n, DFI_NATURE_COUNT);
    for (uint32_t i = 0u; i < formes; ++i) {
        const dfi_forme_data *f = &dfi_pool_formes[i];
        n = dfi_pool_put_u16(out, n, f->dex_num);
        out[n++] = f->types[0];
        out[n++] = f->types[1];
        for (uint32_t k = 0u; k < DFI_STAT_COUNT; ++k) {
            out[n++] = f->base[k];
        }
        n = dfi_pool_put_u16(out, n, f->weight_hg);
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
    for (uint32_t i = 0u; i < moves; ++i) {
        const dfi_move_data *m = &dfi_pool_moves[i];
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
    for (uint32_t i = 0u; i < items; ++i) {
        out[n++] = dfi_pool_items[i].mega_base;
        out[n++] = dfi_pool_items[i].mega_forme;
    }
    for (uint32_t d = 0u; d < DFI_TYPE_COUNT; ++d) {
        for (uint32_t a = 0u; a < DFI_TYPE_COUNT; ++a) {
            out[n++] = dfi_closure_type_chart[d][a];
        }
    }
    for (uint32_t i = 0u; i < DFI_TYPE_COUNT; ++i) {
        out[n++] = (uint8_t)(dfi_pool_type_immunity[i] & immunity_mask); /* wide-operands-reviewed: < 256 */
    }
    for (uint32_t i = 0u; i < DFI_NATURE_COUNT; ++i) {
        out[n++] = dfi_closure_natures[i].plus;
        out[n++] = dfi_closure_natures[i].minus;
    }
    return n;
}

size_t dfi_pool_canonical_bytes(uint8_t *out, size_t capacity)
{
    if (capacity < DFI_POOL_CANONICAL_SIZE) {
        return 0u;
    }
    size_t n = dfi_pool_canonical_bytes_of(out, capacity, DFI_POOL_FORME_COUNT, DFI_POOL_MOVE_COUNT,
                                           DFI_POOL_ITEM_COUNT, DFI_POOL_ABILITY_COUNT, 0xFFu);
    for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
        out[n++] = dfi_pool_item_family[i].family;
        out[n++] = dfi_pool_item_family[i].type;
    }
    for (uint32_t i = 0u; i < DFI_POOL_ABILITY_COUNT; ++i) {
        out[n++] = dfi_pool_ability_family[i].family;
        out[n++] = dfi_pool_ability_family[i].param;
    }
    for (uint32_t i = 0u; i < DFI_POOL_FORME_COUNT; ++i) {
        const dfi_forme_legal *l = &dfi_pool_forme_legal[i];
        for (uint32_t k = 0u; k < DFI_POOL_LEARN_BYTES; ++k) {
            out[n++] = l->learnable[k];
        }
        out[n++] = l->ability_count;
        for (uint32_t k = 0u; k < DFI_POOL_FORME_ABILITIES_MAX; ++k) {
            out[n++] = l->abilities[k];
        }
    }
    for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
        out[n++] = dfi_pool_move_extra[i].flags;
        out[n++] = dfi_pool_move_extra[i].heal[0];
        out[n++] = dfi_pool_move_extra[i].heal[1];
    }
    return n;
}
''']
    return h, '\n'.join(c), digest, len(can)


def main():
    team_c = '--team-c' in sys.argv[1:]
    pool = '--pool' in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a not in ('--check', '--team-c', '--pool')]
    check = '--check' in sys.argv[1:]
    if len(args) != 1 or (team_c and pool):
        sys.exit(__doc__)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    d = build(args[0])
    if pool:
        dc = d
        dx = build(args[0], ext=True)
        check_prefix(dx, dc)
        d = build_pool(args[0], repo, dx)
        check_pool_prefix(d, dx, dc)
        h, c, digest, size = render_pool(d, dx)
        stem = 'pool_tables'
    elif team_c:
        dc = d
        d = build(args[0], ext=True)
        check_prefix(d, dc)
        h, c, digest, size = render_ext(d, dc)
        stem = 'extended_tables'
    else:
        h, c, digest, size = render(d)
        stem = 'closure_tables'
    outs = ((os.path.join(repo, 'src', 'data', stem + '.h'), h),
            (os.path.join(repo, 'src', 'data', stem + '.c'), c))
    for path, text in outs:
        if check:
            have = io.open(path, 'rb').read().replace(b'\r\n', b'\n')
            if have != text.encode('ascii'):
                fail('%s differs from the generator output' % path)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with io.open(path, 'w', encoding='ascii', newline='\n') as fh:
                fh.write(text)
    print('%s: %d formes, %d moves, %d items, %d abilities; canonical %d bytes, sha256 %s%s' % (
        stem, len(d['formes']), len(d['moves']), len(d['items']), len(d['abilities']), size, digest,
        ' (check ok)' if check else ''))
    for path, text in outs:
        print('  %s sha256 %s' % (os.path.basename(path), hashlib.sha256(text.encode('ascii')).hexdigest()))


if __name__ == '__main__':
    main()
