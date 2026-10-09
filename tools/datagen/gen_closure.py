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

# More files of the pin, read only by the whole-pool rows of --pool (decision 0015 section 4.2) to find where an item or
# an ability is read by its id; they are not part of the provenance of any table header.
READER_INPUTS = {
    'data/conditions.ts': '03ec1b90913f864a0baab0574a70abb856d5e84f722acf96ab11a7601a72fc35',
    'sim/battle-actions.ts': 'a30408e2f9a53a43333bf4a865366d6adbe26d3d91a836ba51042accce4d9437',
    'sim/battle-queue.ts': '3d9dd71dfb7abc788f961d6123b1b9f7308ccab947af6527f1752dd1d94b95ed',
    'sim/battle.ts': '852dc6eed2876100787090cf049e27d2b061fdb6e808a1edd261468390afaa1f',
    'sim/field.ts': '3c46a9923736a9a0aaa35791e99d491308c255934553c9d104a0cc2ea453aa79',
    'sim/pokemon.ts': 'f40260351baf649b15ad3beacfa4269c3418b2da27947af8f5c1097c888ab122',
    'sim/side.ts': 'a18946aefe31018162956b1c708a9cce27bb33fe0f098cb58c44d8521d53b1f1',
    'data/mods/champions/conditions.ts': '851507309dde0b58807e33b17d8ce7e607dad70893546f67bad294ad70249005',
}

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
# Step G37 (POOL only): the four entry hazards. The values are the DUOFORGE_SIDE_* values of SIDE_START and SIDE_END (Aurora Veil is 4, a
# handler of its own): Stealth Rock 5, Spikes 6, Toxic Spikes 7, Sticky Web 8. Their moves have the target class foeSide.
SIDE_CONDITION_P = dict(SIDE_CONDITION, stealthrock=5, spikes=6, toxicspikes=7, stickyweb=8)
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
BOOST_ROLE = {'NONE': 0, 'PRIMARY_SELF': 1, 'SECONDARY_TARGET': 2, 'SELF_AFTER_HIT': 3, 'PRIMARY_ALLY': 4,
              'SECONDARY_SELF': 5, 'PRIMARY_TARGET': 6}

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
STATUS_P = dict(STATUS_C, tox=6)                  # badly poisoned (POOL only: Toxic, Poison Fang; step G36); the tail's toxic_stage counts it
STATUS_IMMUNITY_C = dict(STATUS_IMMUNITY, psn=16)  # Poison and Steel: step 6
IGNORED_TYPE_KEYS_C = IGNORED_TYPE_KEYS - {'psn'}  # tox stays ignored: no toxic source
# The POOL tables add the immunity to Sandstorm damage (decision 0018 step: Sandstorm and Snowscape): the type chart's
# `sandstorm: 3` of Rock, Ground and Steel. The bit is in the pool's immunity bytes only; the extended and closure
# canonical bytes mask it out. `hail` stays ignored (Snowscape does no damage).
SAND_IMMUNITY = 32
STATUS_IMMUNITY_P = dict(STATUS_IMMUNITY_C, sandstorm=SAND_IMMUNITY)
IGNORED_TYPE_KEYS_P = IGNORED_TYPE_KEYS_C - {'sandstorm'}
SAND_IMMUNE_TYPES = ['Ground', 'Rock', 'Steel']  # in the order of TYPES
POWDER_IMMUNE_TYPES = ['Grass']  # step G30: the chart's `powder: 3`; the engine reads it as the type, no column
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
SECONDARY_SELF_BOOST = 7  # step G28: the secondary's own boosts go to the user (Ancient Power)


def fail(msg):
    sys.exit('gen_closure: ' + msg)


class Source:
    def __init__(self, root, rel, pins=None):
        pins = INPUTS if pins is None else pins
        raw = io.open(os.path.join(root, rel), 'rb').read().replace(b'\r\n', b'\n')
        got = hashlib.sha256(raw).hexdigest()
        if got != pins[rel]:
            fail('%s: sha256 %s differs from the pin %s' % (rel, got, pins[rel]))
        self.rel = rel
        self.lines = raw.decode('utf-8').split('\n')

    def first_lines(self):
        """key -> index of the first line of its top-level entry (the first one of a repeated key), built once."""
        if getattr(self, '_first', None) is None or self._first_of is not self.lines:
            self._first, self._first_of = {}, self.lines
            for i, line in enumerate(self.lines):
                m = re.match(r'^\t(\w+): \{', line)
                if m is not None and m.group(1) not in self._first:
                    self._first[m.group(1)] = i
        return self._first

    def entry(self, key):
        """Returns (first line, last line, body lines) of the top-level entry or None."""
        i = self.first_lines().get(key)
        if i is None:
            return None
        line = self.lines[i]
        if line.rstrip().endswith('},'):  # one-line entry
            return i + 1, i + 1, [line]
        depth = 0
        for j in range(i, len(self.lines)):
            depth += self.lines[j].count('{') - self.lines[j].count('}')
            if depth <= 0:
                if self.lines[j] != '\t},':
                    fail('%s: the entry %s does not end at a line "\\t},"' % (self.rel, key))
                return i + 1, j + 1, self.lines[i:j + 1]
        fail('%s: the entry %s is not closed' % (self.rel, key))

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


def modelled(table, key, mid, what, unmodeled=None):
    """The code of a name that the tables model. Anything else fails with a message, never as a KeyError; in the
    lenient mode (a list `unmodeled`) it is recorded as a feature that the tables do not model and gives 0."""
    if key not in table:
        if unmodeled is None:
            fail('move %s: %s %s is not modelled' % (mid, what, key))
        unmodeled.append('%s %s' % (what, key))
        return 0
    return table[key]


def parse_move(mid, base, champ, ext=False, pool=False, unmodeled=None):
    """ext: the extended tables' encodings (decision 0009); the closure mode
    keeps exactly the closure's. pool: the pool tables' encodings (decision
    0015), which are the extended ones plus the named handlers of G2_HANDLERS:
    a move whose callbacks or fields the tables do not model is mapped
    deliberately to one of them, and anything else still fails.

    unmodeled (a list, pool mode only): the lenient mode of the whole-pool rows (decision 0015 section 4.2). What
    the tables model is encoded exactly as in the strict mode. A callback, field, secondary, status, volatile, side
    condition, pseudo weather, boost shape, target class or flag that they do not model is appended to the list, as
    one feature string each, instead of failing, and the caller maps the move to the UNMODELED handler. What the
    generator cannot read at all (a type, category, PP or accuracy it does not know, a value that does not fit its
    byte) still fails."""
    ext = ext or pool
    lenient = unmodeled is not None
    if lenient and not pool:
        fail('move %s: the lenient mode is for the pool tables only' % mid)

    def bad(message, feature):
        """An unmodelled feature: a failure in the strict mode, a recorded feature in the lenient one."""
        if not lenient:
            fail(message)
        unmodeled.append(feature)

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
        for _name in list(cf):
            # `secondary: undefined, // no inherit` (the Champions Freeze-Dry): the field is removed, not changed.
            if re.match(r'^\t\t%s: undefined,' % _name, cf[_name][1]):
                del f[_name]
        refs.append(champ.ref(mid))
    handled = (SPECIAL_POOL if pool else SPECIAL_C if ext else SPECIAL).get(mid, ('NONE', set()))
    owned_fields = SPECIAL_FIELDS_C.get(handled[0], set()) if ext else set()
    # What a pool handler owns: data fields and a secondary that only it consumes, each of which must be present and
    # exactly the pinned text, and a condition block (the callbacks inside it are code, not data).
    owned = G2_OWNED_FIELDS.get(handled[0], {}) if pool else {}
    owned_secondary = G2_OWNED_SECONDARY.get(handled[0]) if pool else None
    # Step G8: a secondary whose whole text is one of G8_SECONDARIES is a modelled kind (the lockout of Throat Chop, the
    # Heal Block of Psychic Noise), not a handler's: chance 100 and the kind, in every pool row of that text.
    g8_secondary = None
    if pool and 'secondary' in f and norm(f['secondary'][1]) in G8_SECONDARIES:
        g8_secondary = G8_SECONDARIES[norm(f['secondary'][1])]
    owns_condition = (pool and handled[0] in G2_OWNED_CONDITION) or (g8_secondary is not None and g8_secondary[1])
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
                bad('move %s: callback %s is not mapped to a handler' % (mid, name), 'callback %s' % name)
        elif (name not in DATA_KEYS and name not in IGNORED_KEYS and name not in owned_fields and name not in owned
              and not (pool and name in POOL_COLUMN_KEYS)
              and not (pool and name == 'tags' and norm(f[name][1]) == TAGS_PAST_UNOBTAINABLE)):
            bad('move %s: unknown field %s' % (mid, name), 'field %s' % name)
    missing = handled[1] - set(n for n, v in f.items() if v[0])
    if missing:
        fail('move %s: expected callbacks %s are absent' % (mid, sorted(missing)))
    if pool and handled[0] == 'GLAIVE_RUSH':
        if 'condition' not in f or norm(f['condition'][1]) != GLAIVE_RUSH_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
    if pool and handled[0] == 'PERISH_SONG':
        if 'condition' not in f or norm(f['condition'][1]) != PERISH_SONG_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
        if 'onHitField' not in f or norm(f['onHitField'][1]) != PERISH_SONG_HIT_FIELD:
            fail('move %s: onHitField is not the pinned text' % mid)
    if pool and handled[0] in G29_CALLBACKS:
        for name, text in G29_CALLBACKS[handled[0]].items():
            if name not in f or norm(f[name][1]) != text:
                fail('move %s: %s is not the pinned text' % (mid, name))
    if pool and handled[0] == 'KNOCK_OFF':
        for name, text in KNOCK_OFF_CALLBACKS.items():
            if name not in f or norm(f[name][1]) != text:
                fail('move %s: %s is not the pinned text' % (mid, name))
    if pool and handled[0] == 'DISABLE':
        base_condition = fields(base.entry(mid)[2]).get('condition')
        if 'onTryHit' not in f or norm(f['onTryHit'][1]) != DISABLE_ONTRYHIT:
            fail('move %s: onTryHit is not the pinned text' % mid)
        if base_condition is None or norm(base_condition[1]) != DISABLE_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
        if 'condition' not in f or norm(f['condition'][1]) not in (DISABLE_CONDITION, DISABLE_CONDITION_CHAMPIONS):
            fail('move %s: the Champions condition is not the pinned text' % mid)
    if pool and handled[0] == 'RAGE_POWDER':
        if 'onTry' not in f or norm(f['onTry'][1]) != RAGE_POWDER_ONTRY:
            fail('move %s: onTry is not the pinned text' % mid)
        if 'condition' not in f or norm(f['condition'][1]) != RAGE_POWDER_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
    if pool and handled[0] == 'PSYCHIC_FANGS' and ('onTryHit' not in f or norm(f['onTryHit'][1]) != PSYCHIC_FANGS_ONTRYHIT):
        fail('move %s: onTryHit is not the pinned text' % mid)
    if pool and handled[0] == 'SOLAR_BEAM':
        for name, text in SOLAR_BEAM_CALLBACKS.items():
            if name not in f or norm(f[name][1]) != text:
                fail('move %s: %s is not the pinned text' % (mid, name))
    if pool and handled[0] == 'TAUNT' and ('condition' not in f or norm(f['condition'][1]) != TAUNT_CONDITION):
        fail('move %s: the condition is not the pinned text' % mid)
    if pool and handled[0] == 'YAWN':
        if 'onTryHit' not in f or norm(f['onTryHit'][1]) != YAWN_ONTRYHIT:
            fail('move %s: onTryHit is not the pinned text' % mid)
        if 'condition' not in f or norm(f['condition'][1]) != YAWN_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
    if pool and handled[0] == 'AURORA_VEIL' and ('onTry' not in f or norm(f['onTry'][1]) != AURORA_VEIL_ONTRY):
        fail('move %s: onTry is not the pinned text' % mid)
    if pool and handled[0] in G20_PROTECT_HANDLERS:
        punish = PROTECT_VARIANT_PUNISHMENT[handled[0]]
        if 'condition' not in f or norm(f['condition'][1]) != PROTECT_VARIANT_CONDITION % (punish, punish):
            fail('move %s: the condition is not the pinned text' % mid)
        pe = fields(base.entry('protect')[2])
        for name in PROTECT_VARIANT_COPY_FIELDS:
            if name not in f or name not in pe or norm(f[name][1]) != norm(pe[name][1]):
                fail('move %s: %s is not that of protect' % (mid, name))
    if pool and mid in PROTECT_COPIES:
        pe = fields(base.entry(PROTECT_COPIES[mid])[2])
        for name in PROTECT_COPY_FIELDS:
            if name not in f or name not in pe or norm(f[name][1]) != norm(pe[name][1]):
                fail('move %s: %s is not that of %s' % (mid, name, PROTECT_COPIES[mid]))

    def get(name, default=None):
        return scalar(f[name][1]) if name in f else default

    flags = 0
    flags2 = 0
    static_flags = 0  # decision 0020: the public static flags of every row, from the pin's flags object (pool tables only)
    flag_bits = FLAG_BITS_C if ext else FLAG_BITS
    for fl in re.findall(r'(\w+): 1', f['flags'][1]):
        flags2 |= FLAGS2_BITS.get(fl, 0)
        static_flags |= STATIC_FLAG_BITS.get(fl, 0)
        if fl in flag_bits:
            flags |= flag_bits[fl]
        elif lenient:
            # Every flag of the pool is known (POOL_FLAGS) or the generator cannot read the move; a flag that no
            # encoded bit holds is recorded when a modelled row reads it (flags_that_matter), and otherwise ignored.
            if fl not in POOL_FLAGS:
                fail('move %s: unknown flag %s' % (mid, fl))
            if fl in FLAGS_THAT_MATTER:
                unmodeled.append('flag %s' % fl)
        elif fl not in IGNORED_FLAGS and not (pool and fl in G2_IGNORED_FLAGS):
            fail('move %s: unknown flag %s' % (mid, fl))
    for key, bit in EXTRA_FLAG_BITS.items():
        value = get(key, False)
        if value is True:
            flags |= bit
            if key == 'selfSwitch' and lenient and mid not in ENGINE_PIVOT_MOVES:
                # The turn code pivots a damaging move only through a switch flag of its own (dfi_pivot_moves of
                # src/state/closure_member.c: Flip Turn and U-turn, rows of the steps above); Volt Switch or
                # Teleport carry the data flag and nothing else says how they pivot.
                unmodeled.append('field selfSwitch without a switch flag')
        elif value is not False:
            # selfSwitch: "copyvolatile" (Baton Pass) and "shedtail" (Shed Tail) switch the user out and carry
            # something over: no flag of the tables says that.
            bad('move %s: %s is %r, not a flag' % (mid, key, value), 'field %s %s' % (key, value))
    acc = get('accuracy')
    pp_base = get('pp')
    pp_capped = min(pp_base, 20)  # champions init(): data/mods/champions/scripts.ts:3-9
    if flags & EXTRA_FLAG_BITS['noPPBoosts']:
        pp_max = pp_capped
    else:
        if pp_capped % 5 != 0:
            fail('move %s: pp %d is not a multiple of 5' % (mid, pp_capped))
        pp_max = (pp_capped // 5 + 1) * 4  # calculatePP: scripts.ts:41-43
    if get('target') not in (TARGET_CLASS_POOL if lenient else TARGET_CLASS):
        fail('move %s: unknown target class %s' % (mid, get('target')))
    target_class = (TARGET_CLASS_POOL if lenient else TARGET_CLASS)[get('target')]
    if lenient and get('target') not in ENGINE_TARGETS:
        unmodeled.append('target %s' % get('target'))
    for what, table, key in (('type', TYPES, 'type'), ('category', CATEGORIES, 'category')):
        if get(key) not in table:
            fail('move %s: unknown %s %s' % (mid, what, get(key)))
    if 'basePowerCallback' in f and f['basePowerCallback'][0]:
        static_flags |= STATIC_FLAG_POWER_RULE
    hits = [1, 1]  # the pin's multihit: 1/1 for a single hit (decision 0020 item 4)
    if 'multihit' in f:
        mh = re.fullmatch(r'multihit: (?:(\d+)|\[(\d+), (\d+)\]),', norm(f['multihit'][1]))
        if mh is None:
            fail('move %s: multihit is not "multihit: n," or "multihit: [min, max],"' % mid)
        hits = [int(mh.group(1)), int(mh.group(1))] if mh.group(1) else [int(mh.group(2)), int(mh.group(3))]
        if not 1 <= hits[0] <= hits[1] <= 255:
            fail('move %s: multihit %s is not 1 <= min <= max <= 255' % (mid, hits))
    rec = {
        'id': mid, 'name': get('name'), 'refs': refs, 'static_flags': static_flags, 'hits': hits,
        'type': TYPES.index(get('type')), 'category': CATEGORIES[get('category')],
        'base_power': get('basePower'), 'accuracy': 0 if acc is True else acc, 'pp_base': pp_base, 'pp_max': pp_max,
        'priority': get('priority') + 8, 'target_class': target_class,
        'crit_ratio': get('critRatio', 1), 'flags': flags, 'flags2': flags2, 'heal': [0, 0],
        'recoil': [0, 0], 'drain': [0, 0], 'sec_chance': 0, 'sec_kind': 0, 'sec_param': 0,
        'boost_role': 0, 'boosts': [0] * 7, 'primary_status': 0, 'side_condition': 0, 'pseudo_weather': 0,
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
            bad('move %s: thawsTarget is not "thawsTarget: true,"' % mid, 'field thawsTarget')
        else:
            rec['flags2'] |= FLAG2_THAWS_TARGET
    if pool and 'heal' in f:
        heal = re.fullmatch(r'heal: \[(\d+), (\d+)\],', norm(f['heal'][1]))
        if heal is None or not 0 < int(heal.group(1)) <= int(heal.group(2)) <= 255:
            bad('move %s: heal is not a fraction "heal: [a, b],"' % mid, 'field heal')
        else:
            rec['heal'] = [int(heal.group(1)), int(heal.group(2))]
    vectors = 0
    if g8_secondary is not None:
        rec['sec_chance'], rec['sec_kind'] = 100, g8_secondary[0]
    if 'secondary' in f and owned_secondary is None and g8_secondary is None:
        # The whole secondary must be one modelled effect; anything else (a
        # self block, a callback, several effects) fails instead of being misread.
        sec = re.fullmatch(r'secondary: \{ chance: (\d+), (.*) \},', ' '.join(f['secondary'][1].split()))
        if sec is None:
            bad('move %s: unknown secondary' % mid, 'secondary')
            effect = None
        else:
            rec['sec_chance'], effect = int(sec.group(1)), sec.group(2)
        st = re.fullmatch(r"status: '(\w+)',", effect or '')
        vo = re.fullmatch(r"volatileStatus: '(\w+)',", effect or '')
        if effect is None:
            rec['sec_chance'] = 0
        elif st:
            rec['sec_kind'], rec['sec_param'] = 2, modelled(STATUS_P if pool else STATUS, st.group(1), mid, 'secondary status',
                                                            unmodeled)
        elif vo:
            rec['sec_kind'], rec['sec_param'] = 3, modelled(VOLATILE, vo.group(1), mid, 'secondary volatile',
                                                            unmodeled)
        elif re.fullmatch(r'boosts: \{ (?:(?:%s): -?\d+, )+\},' % '|'.join(BOOSTS), effect):
            rec['sec_kind'] = 1
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['SECONDARY_TARGET'], boosts_of(effect)
            vectors += 1
        elif ext and effect == STATUS_PICK_ONHIT:
            rec['sec_kind'] = SECONDARY_STATUS_PICK
        elif pool and re.fullmatch(r'self: \{ boosts: \{ (?:(?:%s): -?\d+, )+\}, \},' % '|'.join(BOOSTS), effect):
            # Step G28: a secondary whose own effect is a stat change of the user (Ancient Power: all five at 10 percent).
            rec['sec_kind'] = SECONDARY_SELF_BOOST
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['SECONDARY_SELF'], boosts_of(effect)
            vectors += 1
        elif re.search(r'\bself: \{', effect):
            bad('move %s: secondary self effects are not supported' % mid, 'secondary self effect')
            rec['sec_chance'] = 0
        else:
            bad('move %s: unknown secondary' % mid, 'secondary')
            rec['sec_chance'] = 0
    if 'self' in f and 'self' not in owned:
        if pool and norm(f['self'][1]) == RECHARGE_SELF:
            # Step G17: the recharge moves (flags.recharge and this self effect, which the turn code reads as the
            # second flags byte's RECHARGE bit: the user must recharge after a hit).
            rec['flags2'] |= FLAG2_RECHARGE
        elif lenient and not re.search(r'\bboosts: ', f['self'][1]):
            unmodeled.append('self effect')
        else:
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['SELF_AFTER_HIT'], boosts_of(f['self'][1])
            vectors += 1
    if pool and ('recharge: 1' in norm(f['flags'][1])) != ((rec['flags2'] & FLAG2_RECHARGE) != 0):
        bad('move %s: the recharge flag and the mustrecharge self effect do not come together' % mid, 'recharge flag')
    if 'boosts' in f:
        if pool and rec['target_class'] == TARGET_CLASS['adjacentAlly'] and rec['category'] == CATEGORIES['Status']:
            # Step G19: Coaching, a status move whose primary boosts go to the ally (BOOST_ROLE PRIMARY_ALLY).
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['PRIMARY_ALLY'], boosts_of(f['boosts'][1])
            vectors += 1
        elif pool and rec['target_class'] == TARGET_CLASS['normal'] and rec['category'] == CATEGORIES['Status']:
            # Step G39: Charm and Fake Tears, a status move of one adjacent target whose primary boosts go to that target
            # (BOOST_ROLE PRIMARY_TARGET); a spread class (Growl) or a Pokemon of any distance stays UNMODELED.
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['PRIMARY_TARGET'], boosts_of(f['boosts'][1])
            vectors += 1
        elif rec['target_class'] != TARGET_CLASS['self']:
            bad('move %s: primary boosts on a non-self target' % mid, 'primary boosts on a non-self target')
        else:
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['PRIMARY_SELF'], boosts_of(f['boosts'][1])
            vectors += 1
    if vectors > 1:
        bad('move %s: more than one boost vector' % mid, 'more than one boost vector')
        rec['boost_role'], rec['boosts'] = 0, [0] * 7
    if 'status' in f:
        rec['primary_status'] = modelled(STATUS_P if pool else STATUS_C if ext else STATUS, get('status'), mid, 'primary status', unmodeled)
    owned_volatile = SPECIAL_VOLATILE_C.get(handled[0]) if ext else None
    if 'volatileStatus' in f and 'volatileStatus' not in owned and get('volatileStatus') not in ('protect', owned_volatile):
        bad('move %s: unknown primary volatile' % mid, 'primary volatile %s' % get('volatileStatus'))
    if 'sideCondition' in f and 'sideCondition' not in owned:
        rec['side_condition'] = modelled(SIDE_CONDITION_P if pool else SIDE_CONDITION, get('sideCondition'), mid, 'side condition', unmodeled)
    if 'pseudoWeather' in f:
        rec['pseudo_weather'] = modelled(PSEUDO_WEATHER, get('pseudoWeather'), mid, 'pseudo weather', unmodeled)
    if 'condition' in f and not (rec['side_condition'] or rec['pseudo_weather'] or mid == 'protect' or
                                 owned_volatile is not None or owns_condition):
        bad('move %s: condition block without a known owner' % mid, 'condition block')
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
        # A forme without an entry of its own (Meowstic-F) is in the format through its base species, as the
        # pinned dex gives it its base species' tier; anything else is not in the format.
        base = re.search(r'\tbaseSpecies: "(.*?)"', text)
        if base is None or formats.entry(toid(base.group(1))) is None:
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


def type_chart(tc, status_immunity, ignored_type_keys):
    """The type chart and the immunity bits of the 18 types read from data/typechart.ts: a key of a type's damageTaken
    that is an immunity (value 3) sets the bit that status_immunity names; a key that no table models must be in
    ignored_type_keys, and anything else fails."""
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
    return chart, immunity


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
    chart, immunity = type_chart(src['data/typechart.ts'], status_immunity, ignored_type_keys)

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
# (SOAK is implemented by the turn code since step G11 and marked; it keeps its handler id, so no table byte changed. The same
# holds for ENCORE since step G9.)
G2_HANDLERS = ['ENCORE', 'SCALD', 'WIDE_GUARD', 'FIRST_IMPRESSION', 'RECOVER', 'SOAK', 'LOW_KICK']
# The two weather moves of the Sandstorm and Snowscape step: rows of the whole pool (not of G2) with a named handler,
# because the field `weather` that sets the weather has no column; the turn code implements both.
WEATHER_HANDLERS = ['SANDSTORM', 'SNOWSCAPE']
# Step G16: Knock Off keeps its two callbacks as a handler of its own that the turn code implements (a row of the whole
# pool, like the weather moves: not one of G2's). The generator checks the callbacks' whole text, whitespace aside
# (data/moves.ts:9959-9984; the Champions mod does not change the move): the item is read with the same
# singleEvent('TakeItem') that the turn code knows (a Mega Stone refuses its own species), the boost is 1.5, and the item is
# taken after the hit with the -enditem line that the converter reads.
G16_HANDLERS = ['KNOCK_OFF']
# Step G19: Glaive Rush keeps its self effect and its condition as a handler of its own that the turn code implements: the
# user is hit by moves that never miss and deal double damage until its next move starts (data/moves.ts:6647-6678). The
# generator checks the self effect and the whole condition text, whitespace aside.
G19_HANDLERS = ['GLAIVE_RUSH']
GLAIVE_RUSH_CONDITION = ("condition: { noCopy: true, onStart(pokemon) { this.add('-singlemove', pokemon, 'Glaive Rush', '[silent]'); }, "
                         "onAccuracy() { return true; }, onSourceModifyDamage() { return this.chainModify(2); }, "
                         "onBeforeMovePriority: 100, onBeforeMove(pokemon) { this.debug('removing Glaive Rush drawback before attack'); "
                         "pokemon.removeVolatile('glaiverush'); }, },")
# Step G20: Aurora Veil is a handler of its own that the turn code implements (a row of the whole pool, like Knock Off:
# not one of G2's). Its onTry is the snow test (data/moves.ts:830-877; the Champions mod does not change the move); the
# condition is read from the pinned text (G20_CONDITION_FACTS) and the side condition itself (a tail field, not a column)
# is owned by the handler.
G20_HANDLERS = ['AURORA_VEIL']
# Step G20, the Protect variants: Spiky Shield (data/moves.ts:17532-17584) is Protect with a contact punishment, so it has a
# handler of its own that the turn code implements (the Protect path plus the punishment). Baneful Bunker (:985-1037) is the
# same with poison, but its only learner, Toxapex, has no supported ability, so it stays UNMODELED until one is marked.
# The generator checks that the fields and both callbacks are Protect's (not its volatile, whose name is the move's, and
# not its type) and the whole condition text of the variant, whitespace aside: onTryHit's contact punishment is the one
# thing that differs. King's Shield stays unmarked (its only learner, Aegislash, has no supported ability either).
G20_PROTECT_HANDLERS = ['SPIKY_SHIELD']
PROTECT_VARIANT_COPY_FIELDS = ('onPrepareHit', 'onHit', 'stallingMove', 'flags', 'priority', 'accuracy', 'target')
PROTECT_VARIANT_CONDITION = (
    "condition: { duration: 1, onStart(target) { this.add('-singleturn', target, 'move: Protect'); }, onTryHitPriority: 3, "
    "onTryHit(target, source, move) { if (this.checkMoveBypassesProtect(move, source, target)) return; "
    "if (move.smartTarget) { move.smartTarget = false; } else { this.add('-activate', target, 'move: Protect'); } "
    "const lockedmove = source.getVolatile('lockedmove'); if (lockedmove) { // Outrage counter is reset "
    "if (source.volatiles['lockedmove'].duration === 2) { delete source.volatiles['lockedmove']; } } "
    "if (this.checkMoveMakesContact(move, source, target)) { %s } return this.NOT_FAIL; }, "
    "onHit(target, source, move) { if (move.isZOrMaxPowered && this.checkMoveMakesContact(move, source, target)) { %s } }, },")
PROTECT_VARIANT_PUNISHMENT = {'SPIKY_SHIELD': 'this.damage(source.baseMaxhp / 8, source, target);'}
# Step G27: Disable (data/moves.ts:3648-3716 with the Champions override data/mods/champions/moves.ts:228-238) is a handler of its
# own that the turn code implements (its onTryHit, and a condition whose state is the tail's disable_slot and disable_turns).
# The generator checks the onTryHit and both condition texts, whitespace aside: the pinned condition (duration 5, the onStart
# that takes one turn off when the target has not moved or when Cursed Body acts, the lines, order 17, onBeforeMove priority
# 7, onDisableMove) and the Champions condition that only changes onBeforeMove (a move with the cantusetwice flag is not
# stopped). Cursed Body (data/abilities.ts:784-797) is an engine row (ENGINE_ROWS).
G27_HANDLERS = ['DISABLE']
DISABLE_ONTRYHIT = ("onTryHit(target) { if (!target.lastMove || target.lastMove.isZOrMaxPowered || target.lastMove.isMax || "
                    "target.lastMove.id === 'struggle') { return false; } },")
DISABLE_CONDITION = (
    "condition: { duration: 5, noCopy: true, // doesn't get copied by Baton Pass onStart(pokemon, source, effect) { "
    "// The target hasn't taken its turn, or Cursed Body activated and the move was not used through Dancer or Instruct "
    "if ( this.queue.willMove(pokemon) || (pokemon === this.activePokemon && this.activeMove && !this.activeMove.isExternal) ) "
    "{ this.effectState.duration!--; } if (!pokemon.lastMove) { this.debug(`Pokemon hasn't moved yet`); return false; } "
    "for (const moveSlot of pokemon.moveSlots) { if (moveSlot.id === pokemon.lastMove.id) { if (!moveSlot.pp) { "
    "this.debug('Move out of PP'); return false; } } } if (effect.effectType === 'Ability') { this.add('-start', pokemon, "
    "'Disable', pokemon.lastMove.name, '[from] ability: ' + effect.name, `[of] ${source}`); } else { this.add('-start', pokemon, "
    "'Disable', pokemon.lastMove.name); } this.effectState.move = pokemon.lastMove.id; }, onResidualOrder: 17, onEnd(pokemon) { "
    "this.add('-end', pokemon, 'Disable'); }, onBeforeMovePriority: 7, onBeforeMove(attacker, defender, move) { "
    "if (!(move.isZ && move.isZOrMaxPowered) && move.id === this.effectState.move) { this.add('cant', attacker, 'Disable', move); "
    "return false; } }, onDisableMove(pokemon) { for (const moveSlot of pokemon.moveSlots) { if (moveSlot.id === "
    "this.effectState.move) { pokemon.disableMove(moveSlot.id); } } }, },")
DISABLE_CONDITION_CHAMPIONS = (
    "condition: { inherit: true, onBeforeMove(attacker, defender, move) { if (!(move.isZ && move.isZOrMaxPowered) && move.id === "
    "this.effectState.move && !move.flags['cantusetwice']) { this.add('cant', attacker, 'Disable', move); return false; } }, },")
# Step G28 (a batch of move rules): Shell Smash keeps its boost order (the pin lists def and spd before atk, spa and spe and the
# engine applies a vector in stat order), Acrobatics and Blizzard their one callback, Feint its `breaksProtect`: handlers
# of their own that the turn code implements. The generator checks their texts (G28_FACTS; Expert Belt, an item rule
# of the turn code, G28_ITEM_FACTS), because the engine hard-codes them. Ancient Power needs no handler: its secondary
# self boost is a new secondary kind (SECONDARY_SELF_BOOST) of the generic columns.
G28_HANDLERS = ['SHELL_SMASH', 'ACROBATICS', 'BLIZZARD', 'FEINT']
G28_FACTS = (
    ('shellsmash', ['accuracy: true,', 'category: "Status",', 'target: "self",', 'priority: 0,',
                    'boosts: { def: -1, spd: -1, atk: 2, spa: 2, spe: 2, },']),
    ('acrobatics', ['accuracy: 100,', 'basePower: 55,', 'category: "Physical",', 'target: "any",', 'type: "Flying",',
                    'flags: { contact: 1, protect: 1, mirror: 1, distance: 1, metronome: 1 },',
                    "basePowerCallback(pokemon, target, move) { if (!pokemon.item) { this.debug(\"BP doubled for no item\"); "
                    "return move.basePower * 2; } return move.basePower; },"]),
    ('blizzard', ['accuracy: 70,', 'basePower: 110,', 'category: "Special",', 'target: "allAdjacentFoes",', 'type: "Ice",',
                  "onModifyMove(move) { if (this.field.isWeather(['hail', 'snowscape'])) move.accuracy = true; },",
                  "secondary: { chance: 10, status: 'frz', },"]),
    ('feint', ['accuracy: 100,', 'basePower: 30,', 'category: "Physical",', 'priority: 2,', 'target: "normal",', 'type: "Normal",',
               'flags: { mirror: 1, noassist: 1, failcopycat: 1 },', 'breaksProtect: true,']),
    ('grassyterrain', ['onBasePowerPriority: 6,',
                       "onBasePower(basePower, attacker, defender, move) { const weakenedMoves = ['earthquake', 'bulldoze', 'magnitude']; "
                       "if (weakenedMoves.includes(move.id) && defender.isGrounded() && !defender.isSemiInvulnerable()) { "
                       "this.debug('move weakened by grassy terrain'); return this.chainModify(0.5); } "
                       "if (move.type === 'Grass' && attacker.isGrounded()) { this.debug('grassy terrain boost'); "
                       "return this.chainModify([5325, 4096]); } },"]),
    ('earthquake', ['accuracy: 100,', 'basePower: 100,', 'category: "Physical",', 'priority: 0,', 'target: "allAdjacent",',
                    'type: "Ground",', 'flags: { protect: 1, mirror: 1, nonsky: 1, metronome: 1 },']),
    ('ancientpower', ['accuracy: 100,', 'basePower: 60,', 'category: "Special",', 'target: "normal",', 'type: "Rock",',
                      "secondary: { chance: 10, self: { boosts: { atk: 1, def: 1, spa: 1, spd: 1, spe: 1, }, }, },"]),
)
# Step G38: Imprison (data/moves.ts:9489-9523; the Champions mod has no entry) keeps its volatile as a handler of its own that
# the turn code implements: the start line `-start|user|move: Imprison`, the foes' hidden disable of every move the user knows
# (onFoeDisableMove, run for every active Pokemon in endTurn) and the BeforeMove check at priority 4 that shows
# `cant|foe|move: Imprison|Move` (onFoeBeforeMove). The generator checks the whole text, whitespace aside, because the engine
# hard-codes it.
G38_HANDLERS = ['IMPRISON']
G38_FACTS = (
    ('imprison', ['accuracy: true,', 'basePower: 0,', 'category: "Status",', 'pp: 10,', 'priority: 0,',
                  'flags: { snatch: 1, bypasssub: 1, metronome: 1, mustpressure: 1 },', "volatileStatus: 'imprison',",
                  'noCopy: true,', "onStart(target) { this.add('-start', target, 'move: Imprison'); },",
                  "onFoeDisableMove(pokemon) { for (const moveSlot of this.effectState.source.moveSlots) { "
                  "if (moveSlot.id === 'struggle') continue; pokemon.disableMove(moveSlot.id, true); } "
                  "pokemon.maybeDisabled = true; },",
                  'onFoeBeforeMovePriority: 4,',
                  "onFoeBeforeMove(attacker, defender, move) { if (move.id !== 'struggle' && "
                  "this.effectState.source.hasMove(move.id) && !move.isZOrMaxPowered) { "
                  "this.add('cant', attacker, 'move: Imprison', move); return false; } },",
                  'target: "self",', 'type: "Psychic",']),
)
# Step G34 (a batch of small rules): Steel Roller (fails without a terrain and ends it), Clangorous Soul (a third of the HP for
# five boosts) and Brick Break (the screens go before the hit) keep their callbacks as handlers of their own that the turn code
# implements; the abilities Compound Eyes, Iron Fist, Sharpness, Solid Rock, Technician, Multiscale and Gale Wings and the item
# Wide Lens are engine rows (ENGINE_ROWS). The generator checks the pinned texts the engine hard-codes (G34_FACTS for the moves,
# G34_ABILITY_FACTS and G34_ITEM_FACTS), the Champions mod overriding none of the entries but Clangorous Soul's accuracy: true,
# which parse_move merges (data/mods/champions/moves.ts:121-124).
G34_HANDLERS = ['STEEL_ROLLER', 'CLANGOROUS_SOUL', 'BRICK_BREAK']
G34_FACTS = (
    ('steelroller', ['accuracy: 100,', 'basePower: 130,', 'category: "Physical",', 'target: "normal",', 'type: "Steel",',
                     'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },',
                     "onTry() { return !this.field.isTerrain(''); },", 'onHit() { this.field.clearTerrain(); },',
                     'onAfterSubDamage() { this.field.clearTerrain(); },']),
    ('clangoroussoul', ['basePower: 0,', 'category: "Status",', 'target: "self",', 'type: "Dragon",', 'priority: 0,',
                        'flags: { snatch: 1, sound: 1, dance: 1 },',
                        "onTry(source) { if (source.hp <= (source.maxhp * 33 / 100) || source.maxhp === 1) return false; },",
                        "onTryHit(pokemon, target, move) { if (!this.boost(move.boosts!)) return null; delete move.boosts; },",
                        "onHit(pokemon) { this.directDamage(pokemon.maxhp * 33 / 100); },",
                        'boosts: { atk: 1, def: 1, spa: 1, spd: 1, spe: 1, },']),
    ('brickbreak', ['accuracy: 100,', 'basePower: 75,', 'category: "Physical",', 'target: "normal",', 'type: "Fighting",',
                    'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },',
                    "onTryHit(pokemon) { // will shatter screens through sub, before you hit pokemon.side.removeSideCondition('reflect'); "
                    "pokemon.side.removeSideCondition('lightscreen'); pokemon.side.removeSideCondition('auroraveil'); },"]),
)
# Step G37 (the entry hazards): the four moves with the target class foeSide are rows of the tables without a handler of
# their own (the side condition is a column: SIDE_CONDITION_P) and the turn code runs their conditions: the layers, the
# damage of the switch-in and the status and the stat drop. The generator checks the whole pinned text the engine hard-codes:
# the Champions mod overrides none of the four (data/mods/champions/moves.ts). Toxic Debris (Glimmora's ability) is an engine
# row (ENGINE_ROWS) with its own text (G37_ABILITY_FACTS).
G37_FACTS = (
    ('stealthrock', ['accuracy: true,', 'category: "Status",', 'target: "foeSide",', 'type: "Rock",', 'priority: 0,',
                     'flags: { reflectable: 1, metronome: 1, mustpressure: 1 },', "sideCondition: 'stealthrock',",
                     "onSideStart(side) { this.add('-sidestart', side, 'move: Stealth Rock'); },",
                     "onSwitchIn(pokemon) { if (pokemon.hasItem('heavydutyboots')) return; "
                     "const typeMod = this.clampIntRange(pokemon.runEffectiveness(this.dex.getActiveMove('stealthrock')), -6, 6); "
                     "this.damage(pokemon.maxhp * (2 ** typeMod) / 8); },"]),
    ('spikes', ['accuracy: true,', 'category: "Status",', 'target: "foeSide",', 'type: "Ground",', 'priority: 0,',
                'flags: { reflectable: 1, nonsky: 1, metronome: 1, mustpressure: 1 },', "sideCondition: 'spikes',",
                "onSideStart(side) { this.add('-sidestart', side, 'Spikes'); this.effectState.layers = 1; },",
                "onSideRestart(side) { if (this.effectState.layers >= 3) return false; this.add('-sidestart', side, 'Spikes'); "
                "this.effectState.layers++; },",
                "onSwitchIn(pokemon) { if (!pokemon.isGrounded() || pokemon.hasItem('heavydutyboots')) return; "
                "const damageAmounts = [0, 3, 4, 6]; // 1/8, 1/6, 1/4 this.damage(damageAmounts[this.effectState.layers] * pokemon.maxhp / 24); },"]),
    ('toxicspikes', ['accuracy: true,', 'category: "Status",', 'target: "foeSide",', 'type: "Poison",', 'priority: 0,',
                     'flags: { reflectable: 1, nonsky: 1, metronome: 1, mustpressure: 1 },', "sideCondition: 'toxicspikes',",
                     "onSideStart(side) { this.add('-sidestart', side, 'move: Toxic Spikes'); this.effectState.layers = 1; },",
                     "onSideRestart(side) { if (this.effectState.layers >= 2) return false; "
                     "this.add('-sidestart', side, 'move: Toxic Spikes'); this.effectState.layers++; },",
                     "onSwitchIn(pokemon) { if (!pokemon.isGrounded()) return; if (pokemon.hasType('Poison')) { "
                     "this.add('-sideend', pokemon.side, 'move: Toxic Spikes', `[of] ${pokemon}`); "
                     "pokemon.side.removeSideCondition('toxicspikes'); } else if (pokemon.hasType('Steel') || "
                     "pokemon.hasItem('heavydutyboots')) { // do nothing } else if (this.effectState.layers >= 2) { "
                     "pokemon.trySetStatus('tox', pokemon.side.foe.active[0]); } else { "
                     "pokemon.trySetStatus('psn', pokemon.side.foe.active[0]); } },"]),
    ('stickyweb', ['accuracy: true,', 'category: "Status",', 'target: "foeSide",', 'type: "Bug",', 'priority: 0,',
                   'flags: { reflectable: 1, metronome: 1 },', "sideCondition: 'stickyweb',",
                   "onSideStart(side) { this.add('-sidestart', side, 'move: Sticky Web'); },",
                   "onSwitchIn(pokemon) { if (!pokemon.isGrounded() || pokemon.hasItem('heavydutyboots')) return; "
                   "this.add('-activate', pokemon, 'move: Sticky Web'); "
                   "this.boost({ spe: -1 }, pokemon, pokemon.side.foe.active[0], this.dex.getActiveMove('stickyweb')); },"]),
)
G37_ABILITY_FACTS = (
    ('toxicdebris', ("onDamagingHit(damage, target, source, move) { const side = source.isAlly(target) ? source.side.foe : source.side; "
                     "const toxicSpikes = side.sideConditions['toxicspikes']; "
                     "if (move.category === 'Physical' && (!toxicSpikes || toxicSpikes.layers < 2)) { "
                     "this.add('-activate', target, 'ability: Toxic Debris'); side.addSideCondition('toxicspikes', target); } },",)),
)
G34_ABILITY_FACTS = (
    ('compoundeyes', ('onSourceModifyAccuracyPriority: -1,',
                      "onSourceModifyAccuracy(accuracy) { if (typeof accuracy !== 'number') return; "
                      "this.debug('compoundeyes - enhancing accuracy'); return this.chainModify([5325, 4096]); },")),
    ('ironfist', ('onBasePowerPriority: 23,',
                  "onBasePower(basePower, attacker, defender, move) { if (move.flags['punch']) { this.debug('Iron Fist boost'); "
                  "return this.chainModify([4915, 4096]); } },")),
    ('sharpness', ('onBasePowerPriority: 19,',
                   "onBasePower(basePower, attacker, defender, move) { if (move.flags['slicing']) { this.debug('Sharpness boost'); "
                   "return this.chainModify(1.5); } },")),
    ('solidrock', ("onSourceModifyDamage(damage, source, target, move) { if (target.getMoveHitData(move).typeMod > 0) { "
                   "this.debug('Solid Rock neutralize'); return this.chainModify(0.75); } },",)),
    ('technician', ('onBasePowerPriority: 30,',
                    "onBasePower(basePower, attacker, defender, move) { const basePowerAfterMultiplier = "
                    "this.modify(basePower, this.event.modifier); this.debug(`Base Power: ${basePowerAfterMultiplier}`); "
                    "if (basePowerAfterMultiplier <= 60) { this.debug('Technician boost'); return this.chainModify(1.5); } },")),
    ('multiscale', ("onSourceModifyDamage(damage, source, target, move) { if (target.hp >= target.maxhp) { "
                    "this.debug('Multiscale weaken'); return this.chainModify(0.5); } },",)),
    ('galewings', ("onModifyPriority(priority, pokemon, target, move) { if (move?.type === 'Flying' && pokemon.hp === pokemon.maxhp) "
                   "return priority + 1; },",)),
)
# Step G35: Friend Guard (the target's partner weakens every hit on it: a ModifyDamage modifier, 3072 of the chain) and Rain Dish (a
# sixteenth of the HP in rain, eachEvent('Weather')) are engine rows (ENGINE_ROWS) read by id; the pinned texts they hard-code are
# checked here, the Champions mod overriding neither. Mold Breaker (Friend Guard is breakable) is not marked.
G35_ABILITY_FACTS = (
    ('friendguard', ("onAnyModifyDamage(damage, source, target, move) { if (target !== this.effectState.target && "
                     "target.isAlly(this.effectState.target)) { this.debug('Friend Guard weaken'); return this.chainModify(0.75); } },",
                     'flags: { breakable: 1 },')),
    ('raindish', ("onWeather(target, source, effect) { if (target.effectiveWeather() !== effect.id) return; "
                  "if (effect.id === 'raindance' || effect.id === 'primordialsea') { this.heal(target.baseMaxhp / 16); } },",)),
)
# Mega batch 2: Aura Guard (a contact hit on its holder: a ModifyDamage modifier, 2048 of the chain; the Mega ability of
# Lucario-Mega-Z) is an engine row read by id; the pinned text it hard-codes is checked here, the Champions mod not overriding it.
# Mold Breaker (Aura Guard is breakable) is not marked.
MEGA2_ABILITY_FACTS = (
    ('auraguard', ("onSourceModifyDamage(damage, source, target, move) { if (move.flags['contact']) return this.chainModify(0.5); },",
                   'flags: { breakable: 1 },')),
)
# Step G39 (thirteen abilities, four moves): the abilities Hyper Cutter, Scrappy, Infiltrator, Queenly Majesty, Damp, Sturdy,
# Snow Cloak, Sand Veil, Static, Justified, Limber, Solar Power and Regenerator are engine rows (ENGINE_ROWS) that the turn code
# reads by id; the pinned callbacks they hard-code are checked here, whole, whitespace aside (Regenerator's is the Champions mod's
# own entry: G32_ENTRY_FACTS-style, champ=True). Mold Breaker, which Hyper Cutter, Queenly Majesty, Damp, Sturdy, Snow Cloak, Sand
# Veil and Limber are breakable against, is not marked. Damp is inert: its callbacks stop Explosion, Mind Blown, Misty Explosion,
# Self-Destruct and Aftermath, none of which is marked (tests/test_pool_g39.c pins it, and Sturdy's OHKO immunity likewise).
G39_ABILITY_FACTS = (
    ('hypercutter', ("onTryBoost(boost, target, source, effect) { if (source && target === source) return; "
                     "if (boost.atk && boost.atk < 0) { delete boost.atk; if (!(effect as ActiveMove).secondaries) { "
                     "this.add('-fail', target, 'unboost', 'atk', '[from] ability: Hyper Cutter', `[of] ${target}`); } } },",
                     'flags: { breakable: 1 },')),
    ('scrappy', ("onModifyMovePriority: -5,",
                 "onModifyMove(move) { if (!move.ignoreImmunity) move.ignoreImmunity = {}; if (move.ignoreImmunity !== true) { "
                 "move.ignoreImmunity['Fighting'] = true; move.ignoreImmunity['Normal'] = true; } },",
                 "onTryBoost(boost, target, source, effect) { if (effect.name === 'Intimidate' && boost.atk) { delete boost.atk; "
                 "this.add('-fail', target, 'unboost', 'atk', '[from] ability: Scrappy', `[of] ${target}`); } },")),
    ('infiltrator', ("onModifyMove(move) { move.infiltrates = true; },",)),
    ('queenlymajesty', ("onFoeTryMove(target, source, move) { const targetAllExceptions = ['perishsong', 'flowershield', 'rototiller']; "
                        "if (move.target === 'foeSide' || (move.target === 'all' && !targetAllExceptions.includes(move.id))) { return; } "
                        "const dazzlingHolder = this.effectState.target; if ((source.isAlly(dazzlingHolder) || move.target === 'all') && "
                        "move.priority > 0.1) { this.attrLastMove('[still]'); this.add('cant', dazzlingHolder, 'ability: Queenly Majesty', "
                        "move, `[of] ${target}`); return false; } },",
                        'flags: { breakable: 1 },')),
    ('damp', ("onAnyTryMove(target, source, effect) { if (['explosion', 'mindblown', 'mistyexplosion', 'selfdestruct']"
              ".includes(effect.id)) { this.attrLastMove('[still]'); this.add('cant', this.effectState.target, 'ability: Damp', "
              "effect, `[of] ${target}`); return false; } },",
              "onAnyDamage(damage, target, source, effect) { if (effect && effect.name === 'Aftermath') { return false; } },")),
    ('sturdy', ("onTryHit(pokemon, target, move) { if (move.ohko) { this.add('-immune', pokemon, '[from] ability: Sturdy'); return null; } },",
                "onDamagePriority: -30,",
                "onDamage(damage, target, source, effect) { if (target.hp === target.maxhp && damage >= target.hp && effect && "
                "effect.effectType === 'Move') { this.add('-ability', target, 'Sturdy'); return target.hp - 1; } },")),
    ('snowcloak', ("onImmunity(type, pokemon) { if (type === 'hail') return false; },", 'onModifyAccuracyPriority: -1,',
                   "onModifyAccuracy(accuracy) { if (typeof accuracy !== 'number') return; if (this.field.isWeather(['hail', 'snowscape'])) { "
                   "this.debug('Snow Cloak - decreasing accuracy'); return this.chainModify([3277, 4096]); } },")),
    ('sandveil', ("onImmunity(type, pokemon) { if (type === 'sandstorm') return false; },", 'onModifyAccuracyPriority: -1,',
                  "onModifyAccuracy(accuracy) { if (typeof accuracy !== 'number') return; if (this.field.isWeather('sandstorm')) { "
                  "this.debug('Sand Veil - decreasing accuracy'); return this.chainModify([3277, 4096]); } },")),
    ('static', ("onDamagingHit(damage, target, source, move) { if (this.checkMoveMakesContact(move, source, target)) { "
                "if (this.randomChance(3, 10)) { source.trySetStatus('par', target); } } },",)),
    ('justified', ("onDamagingHit(damage, target, source, move) { if (move.type === 'Dark') { this.boost({ atk: 1 }); } },",)),
    ('limber', ("onUpdate(pokemon) { if (pokemon.status === 'par') { this.add('-activate', pokemon, 'ability: Limber'); "
                "pokemon.cureStatus(); } },",
                "onSetStatus(status, target, source, effect) { if (status.id !== 'par') return; if ((effect as Move)?.status) { "
                "this.add('-immune', target, '[from] ability: Limber'); } return false; },")),
    ('solarpower', ("onModifySpAPriority: 5,",
                    "onModifySpA(spa, pokemon) { if (['sunnyday', 'desolateland'].includes(pokemon.effectiveWeather())) { "
                    "return this.chainModify(1.5); } },",
                    "onWeather(target, source, effect) { if (target.effectiveWeather() !== effect.id) return; "
                    "if (effect.id === 'sunnyday' || effect.id === 'desolateland') { this.damage(target.baseMaxhp / 8, target, target); } },")),
)
# the moves: Sacred Sword is Darkest Lariat's handler (ignoreEvasion and ignoreDefensive, no callback), Super Fang has the one
# damageCallback of the handler SUPER_FANG, Charm and Fake Tears are data (a status move whose primary boosts go to its target)
G39_HANDLERS = ['SUPER_FANG']
G39_FACTS = (
    ('sacredsword', ['accuracy: 100,', 'basePower: 90,', 'category: "Physical",', 'priority: 0,', 'target: "normal",', 'type: "Fighting",',
                     'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1, slicing: 1 },', 'ignoreEvasion: true,',
                     'ignoreDefensive: true,']),
    ('charm', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,', 'target: "normal",', 'type: "Fairy",',
               'flags: { protect: 1, reflectable: 1, mirror: 1, allyanim: 1, metronome: 1 },', 'boosts: { atk: -2, },']),
    ('faketears', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,', 'target: "normal",', 'type: "Dark",',
                   'flags: { protect: 1, reflectable: 1, mirror: 1, allyanim: 1, metronome: 1 },', 'boosts: { spd: -2, },']),
    ('superfang', ['accuracy: 90,', 'basePower: 0,', 'damageCallback(pokemon, target) { return this.clampIntRange(target.getUndynamaxedHP() / 2, 1); },',
                   'category: "Physical",', 'priority: 0,', 'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },',
                   'target: "normal",', 'type: "Normal",']),
)
# Step G41: Shadow Tag (the Mega ability of Gengar) is an engine row read by id: a foe's switch is refused at the TURN boundary
# (src/combat/turn.c dfi_switch_trapped, read by the request builder), no event and no state. The Champions mod overrides it
# nowhere; Shed Shell and Run Away, which free their holders (the mod's runaway), are not marked, so they never meet it.
G41_ABILITY_FACTS = (
    ('shadowtag', ("onFoeTrapPokemon(pokemon) { if (!pokemon.hasAbility('shadowtag') && "
                   "pokemon.isAdjacent(this.effectState.target)) { pokemon.tryTrap(true); } },",
                   "onFoeMaybeTrapPokemon(pokemon, source) { if (!source) source = this.effectState.target; "
                   "if (!source || !pokemon.isAdjacent(source)) return; if (!pokemon.hasAbility('shadowtag')) { "
                   "pokemon.maybeTrapped = true; } },",
                   'flags: {},')),
)
G34_ITEM_FACTS = (
    ('widelens', ('onSourceModifyAccuracyPriority: -2,',
                  "onSourceModifyAccuracy(accuracy) { if (typeof accuracy === 'number') { return this.chainModify([4505, 4096]); } },")),
)
# Step G32 (small rules): eight handlers of the turn code, one per rule that the generic columns cannot hold: HP_POWER
# (Eruption and Water Spout: power 150 x HP / maximum HP, one callback), BODY_PRESS, FOUL_PLAY and PSYSHOCK (the three
# `override...` fields of the damage formula), RAIN_DANCE and SUNNY_DAY (the weather moves, like Sandstorm and Snowscape),
# FREEZE_DRY (the Water type takes it super effective: onEffectiveness; the Champions mod drops its freeze) and
# CLANGING_SCALES (selfBoost: the user's own Defense drop after a hit). The generator checks their texts (G32_FACTS), and the
# entries of the ability and item rows of the step (G32_ENTRY_FACTS: Soundproof, Unnerve, Speed Boost and the Champions
# Eject Button), because the engine hard-codes them. Life Dew needs no handler (its target class `allies` is now an engine
# class: ENGINE_TARGETS), Volt Switch none (ENGINE_PIVOT_MOVES: a switch flag of its own).
G32_HANDLERS = ['HP_POWER', 'BODY_PRESS', 'FOUL_PLAY', 'PSYSHOCK', 'RAIN_DANCE', 'SUNNY_DAY', 'FREEZE_DRY', 'CLANGING_SCALES']
# Step G33 (the multi-hit batch): two handlers, one per rule that the generic columns cannot hold. MULTI_HIT_2 (Dual Wingbeat
# and Twin Beam: `multihit: 2,`) and TRIPLE_AXEL (`multihit: 3,`, `multiaccuracy: true,` and the power 20 x the hit). Population
# Bomb (ten hits, `multiaccuracy`) has no handler: its only learners, Maushold and Maushold-Four, have no marked ability, so no
# legal team can play it and no battle can be recorded; it gets one with the first of Friend Guard, Cheek Pouch and Technician.
# The hit count lives in the handler, not in a column: the static
# columns of decision 0020 have no engine reader (item 5), and the other multihit rows (random counts, smartTarget, secondaries)
# stay unmodelled. The generator checks the four rows' whole texts (G33_FACTS) and Mirror Armor's entry (G33_ENTRY_FACTS).
G33_HANDLERS = ['MULTI_HIT_2', 'TRIPLE_AXEL']
G33_FACTS = (
    ('dualwingbeat', ['accuracy: 90,', 'basePower: 40,', 'category: "Physical",', 'priority: 0,',
                      'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'multihit: 2,', 'target: "normal",',
                      'type: "Flying",']),
    ('tripleaxel', ['accuracy: 90,', 'basePower: 20,', 'basePowerCallback(pokemon, target, move) { return 20 * move.hit; },',
                    'category: "Physical",', 'priority: 0,', 'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },',
                    'multihit: 3,', 'multiaccuracy: true,', 'target: "normal",', 'type: "Ice",']),
    ('twinbeam', ['accuracy: 100,', 'basePower: 40,', 'category: "Special",', 'priority: 0,',
                  'flags: { protect: 1, mirror: 1 },', 'multihit: 2,', 'target: "normal",', 'type: "Psychic",']),
)
G33_ENTRY_FACTS = (
    ('ability', 'mirrorarmor', False,
     ["if (!source || target === source || !boost || effect.name === 'Mirror Armor') return;",
      "let b: BoostID; for (b in boost) { if (boost[b]! < 0) { if (target.boosts[b] === -6) continue; "
      "const negativeBoost: SparseBoostsTable = {}; negativeBoost[b] = boost[b]; delete boost[b]; if (source.hp) { "
      "this.add('-ability', target, 'Mirror Armor'); this.boost(negativeBoost, source, target, null, true); } } }",
      'flags: { breakable: 1 },']),
)
_HP_POWER_CALLBACK = ("basePowerCallback(pokemon, target, move) { const bp = move.basePower * pokemon.hp / pokemon.maxhp; "
                      "this.debug(`BP: ${bp}`); return bp; },")
G32_FACTS = (
    ('eruption', ['accuracy: 100,', 'basePower: 150,', _HP_POWER_CALLBACK, 'category: "Special",', 'priority: 0,',
                  'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "allAdjacentFoes",', 'type: "Fire",']),
    ('waterspout', ['accuracy: 100,', 'basePower: 150,', _HP_POWER_CALLBACK, 'category: "Special",', 'priority: 0,',
                    'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "allAdjacentFoes",', 'type: "Water",']),
    ('bodypress', ['accuracy: 100,', 'basePower: 80,', 'category: "Physical",', 'priority: 0,',
                   'flags: { contact: 1, protect: 1, mirror: 1 },', "overrideOffensiveStat: 'def',", 'target: "normal",',
                   'type: "Fighting",']),
    ('foulplay', ['accuracy: 100,', 'basePower: 95,', 'category: "Physical",', 'priority: 0,',
                  'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', "overrideOffensivePokemon: 'target',",
                  'target: "normal",', 'type: "Dark",']),
    ('psyshock', ['accuracy: 100,', 'basePower: 80,', 'category: "Special",', "overrideDefensiveStat: 'def',", 'priority: 0,',
                  'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "normal",', 'type: "Psychic",']),
    ('raindance', ['accuracy: true,', 'category: "Status",', 'priority: 0,', 'flags: { metronome: 1 },', "weather: 'RainDance',",
                   'target: "all",', 'type: "Water",']),
    ('sunnyday', ['accuracy: true,', 'category: "Status",', 'priority: 0,', 'flags: { metronome: 1 },', "weather: 'sunnyday',",
                  'target: "all",', 'type: "Fire",']),
    ('freezedry', ['accuracy: 100,', 'basePower: 70,', 'category: "Special",', 'priority: 0,',
                   'flags: { protect: 1, mirror: 1, metronome: 1 },',
                   "onEffectiveness(typeMod, target, type) { if (type === 'Water') return 1; },", 'target: "normal",',
                   'type: "Ice",']),
    ('clangingscales', ['accuracy: 100,', 'basePower: 110,', 'category: "Special",', 'priority: 0,',
                        'flags: { protect: 1, mirror: 1, sound: 1, bypasssub: 1, metronome: 1 },',
                        'selfBoost: { boosts: { def: -1, }, },', 'target: "allAdjacentFoes",', 'type: "Dragon",']),
    ('voltswitch', ['accuracy: 100,', 'basePower: 70,', 'category: "Special",', 'priority: 0,',
                    'flags: { protect: 1, mirror: 1, metronome: 1 },', 'selfSwitch: true,', 'target: "normal",',
                    'type: "Electric",']),
    ('lifedew', ['accuracy: true,', 'category: "Status",', 'priority: 0,', 'flags: { snatch: 1, heal: 1, bypasssub: 1 },',
                 'heal: [1, 4],', 'target: "allies",', 'type: "Water",']),
)
# Ability and item rows that the turn code runs by id: the entry of the pin (or of the Champions mod, which is read first
# for the item) must have exactly these texts. (kind, id, in the Champions file, texts)
G32_ENTRY_FACTS = (
    ('ability', 'regenerator', True,
     ["onSwitchOut(pokemon) { if (pokemon.heal(pokemon.baseMaxhp / 3)) { this.add('-heal', pokemon, pokemon.getHealth, "
      "'[from] ability: Regenerator', '[silent]'); } },"]),
    ('ability', 'soundproof', False,
     ["onTryHit(target, source, move) { if (target !== source && move.flags['sound']) { "
      "this.add('-immune', target, '[from] ability: Soundproof'); return null; } },",
      'flags: { breakable: 1 },']),
    ('ability', 'unnerve', False,
     ['onSwitchInPriority: 1,',
      "onStart(pokemon) { if (this.effectState.unnerved) return; this.add('-ability', pokemon, 'Unnerve'); "
      "this.effectState.unnerved = true; },",
      'onEnd() { this.effectState.unnerved = false; },',
      'onFoeTryEatItem() { return !this.effectState.unnerved; },', 'flags: {},']),
    ('ability', 'speedboost', False,
     ['onResidualOrder: 28,', 'onResidualSubOrder: 2,', 'onResidual(pokemon) { if (pokemon.activeTurns) { this.boost({ spe: 1 }); } },',
      'flags: {},']),
    ('item', 'ejectbutton', True,
     ["onAfterMoveSecondary(target, source, move) { if (source && source !== target && target.hp && move && "
      "move.category !== 'Status' && !move.flags['futuremove']) { if (!this.canSwitch(target.side) || target.forceSwitchFlag || "
      "target.beingCalledBack || target.isSkyDropped()) return; if (target.volatiles['commanding'] || "
      "target.volatiles['commanded']) return; for (const pokemon of this.getAllActive()) { "
      "if (pokemon.switchFlag === true) return; } target.switchFlag = true; if (!target.useItem()) { "
      "target.switchFlag = false; } } },"]),
)
# Rain Dance and Sunny Day (data/conditions.ts, as Sandstorm and Snowscape): the duration (5; 8 with the rock item, which is
# UNMODELED and so never held), the start line without a source, the upkeep and the end line.
G32_WEATHER_FACTS = (
    ('raindance', ['duration: 5,', "if (source?.hasItem('damprock')) { return 8; } return 5;",
                   "onFieldStart(field, source, effect) { if (effect?.effectType === 'Ability') { if (this.gen <= 5) "
                   "this.effectState.duration = 0; this.add('-weather', 'RainDance', '[from] ability: ' + effect.name, `[of] ${source}`); } "
                   "else { this.add('-weather', 'RainDance'); } },", 'onFieldResidualOrder: 1,',
                   "this.add('-weather', 'RainDance', '[upkeep]'); this.eachEvent('Weather');",
                   "this.add('-weather', 'none');"]),
    ('sunnyday', ['duration: 5,', "if (source?.hasItem('heatrock')) { return 8; } return 5;",
                  "onFieldStart(battle, source, effect) { if (effect?.effectType === 'Ability') { if (this.gen <= 5) "
                  "this.effectState.duration = 0; this.add('-weather', 'SunnyDay', '[from] ability: ' + effect.name, `[of] ${source}`); } "
                  "else { this.add('-weather', 'SunnyDay'); } },", 'onFieldResidualOrder: 1,',
                  "this.add('-weather', 'SunnyDay', '[upkeep]'); this.eachEvent('Weather');",
                  "this.add('-weather', 'none');",
                  "onImmunity(type, pokemon) { if (pokemon.effectiveWeather() !== 'sunnyday') return; if (type === 'frz') return false; },"]),
)
G28_ITEM_FACTS = (
    ('expertbelt', ["onModifyDamage(damage, source, target, move) { if (move && target.getMoveHitData(move).typeMod > 0) { "
                    "return this.chainModify([4915, 4096]); } },"]),
)
# Step G31: Taunt (data/moves.ts:18974-19016) and Yawn (:21131-21162) are handlers of their own that the turn code implements
# (a condition whose state is the tail's taunt_turns / yawn_turns). The Champions mod changes neither. The generator checks
# the whole condition text of both and Yawn's onTryHit, whitespace aside: Taunt's duration 3 (4 when the target has been out
# for a turn and has no move queued), order 15, onBeforeMove priority 5 and the Status-category bar; Yawn's duration 2,
# order 23 and the silent end that calls trySetStatus('slp').
G31_HANDLERS = ['TAUNT', 'YAWN']
# Step G50 (decision 0025 items 1 and 2): Double Shock. Its onTryMove fails without the Electric type (data/moves.ts:3954-3959);
# its self onHit sets the type ??? in place of Electric and shows -start|X|typechange|???/Fighting (data/moves.ts:3960-3964). The
# Champions mod adds the punch flag (its flags column) and nothing else. The self text is owned by the handler (G2_OWNED_FIELDS),
# whole, so a change at the pin fails the generator.
G50_HANDLERS = ['DOUBLE_SHOCK']
TAUNT_CONDITION = (
    "condition: { duration: 3, onStart(target) { if (target.activeTurns && !this.queue.willMove(target)) { "
    "this.effectState.duration!++; } this.add('-start', target, 'move: Taunt'); }, onResidualOrder: 15, onEnd(target) { "
    "this.add('-end', target, 'move: Taunt'); }, onDisableMove(pokemon) { for (const moveSlot of pokemon.moveSlots) { "
    "const move = this.dex.moves.get(moveSlot.id); if (move.category === 'Status' && move.id !== 'mefirst') { "
    "pokemon.disableMove(moveSlot.id); } } }, onBeforeMovePriority: 5, onBeforeMove(attacker, defender, move) { "
    "if (!(move.isZ && move.isZOrMaxPowered) && move.category === 'Status' && move.id !== 'mefirst') { "
    "this.add('cant', attacker, 'move: Taunt', move); return false; } }, },")
YAWN_ONTRYHIT = "onTryHit(target) { if (target.status || !target.runStatusImmunity('slp')) { return false; } },"
YAWN_CONDITION = (
    "condition: { noCopy: true, // doesn't get copied by Baton Pass duration: 2, onStart(target, source) { "
    "this.add('-start', target, 'move: Yawn', `[of] ${source}`); }, onResidualOrder: 23, onEnd(target) { "
    "this.add('-end', target, 'move: Yawn', '[silent]'); target.trySetStatus('slp', this.effectState.source); }, },")
# Step G25 (Electric Terrain, Misty Terrain): the two terrain moves keep their `terrain` field and their condition as handlers of
# their own that the turn code implements (setTerrain, then the terrain's rules in the damage chain and in SetStatus and
# TryAddVolatile), and Rising Voltage and Terrain Pulse keep the callback that reads the terrain (base power; type and
# base power). Their texts are G25_FACTS, read from the pin, because the engine hard-codes them.
G25_HANDLERS = ['ELECTRIC_TERRAIN', 'MISTY_TERRAIN', 'RISING_VOLTAGE', 'TERRAIN_PULSE']

# Step G29: the item-transfer moves. Trick and Switcheroo (status, onTryImmunity and onHit), Thief and Covet (damaging, onAfterHit)
# keep their callbacks as handlers of their own that the turn code implements (rows of the whole pool). The generator checks the
# whole text of each callback, whitespace aside (data/moves.ts:19865-19911, :18644-18690, :19302-19330, :3099-3123; the Champions
# mod changes none): the Sticky Hold test of Trick's target, the TakeItem checks (a Mega Stone refuses the species it belongs to), the
# order of the takes and sets, and the lines that the converter reads (-activate move: Trick, -item and the silent -enditem, with
# [from] move: and, for Thief and Covet, [of]).
G29_HANDLERS = ['TRICK', 'SWITCHEROO', 'THIEF', 'COVET']
G29_CALLBACKS = {
    'TRICK': {
        'onTryImmunity': "onTryImmunity(target) { return !target.hasAbility('stickyhold'); },",
        'onHit': "onHit(target, source, move) { const yourItem = target.takeItem(source); const myItem = source.takeItem(); if (yourItem === false || myItem === false || (!yourItem && !myItem)) { if (yourItem) target.item = yourItem.id; if (myItem) source.item = myItem.id; return false; } if ( (myItem && !this.singleEvent('TakeItem', myItem, source.itemState, target, source, move, myItem)) || (yourItem && !this.singleEvent('TakeItem', yourItem, target.itemState, source, target, move, yourItem)) ) { if (yourItem) target.item = yourItem.id; if (myItem) source.item = myItem.id; return false; } this.add('-activate', source, 'move: Trick', `[of] ${target}`); if (myItem) { target.setItem(myItem); this.add('-item', target, myItem, '[from] move: Trick'); } else { this.add('-enditem', target, yourItem, '[silent]', '[from] move: Trick'); } if (yourItem) { source.setItem(yourItem); this.add('-item', source, yourItem, '[from] move: Trick'); } else { this.add('-enditem', source, myItem, '[silent]', '[from] move: Trick'); } },",
    },
    'SWITCHEROO': {
        'onTryImmunity': "onTryImmunity(target) { return !target.hasAbility('stickyhold'); },",
        'onHit': "onHit(target, source, move) { const yourItem = target.takeItem(source); const myItem = source.takeItem(); if (yourItem === false || myItem === false || (!yourItem && !myItem)) { if (yourItem) target.item = yourItem.id; if (myItem) source.item = myItem.id; return false; } if ( (myItem && !this.singleEvent('TakeItem', myItem, source.itemState, target, source, move, myItem)) || (yourItem && !this.singleEvent('TakeItem', yourItem, target.itemState, source, target, move, yourItem)) ) { if (yourItem) target.item = yourItem.id; if (myItem) source.item = myItem.id; return false; } this.add('-activate', source, 'move: Trick', `[of] ${target}`); if (myItem) { target.setItem(myItem); this.add('-item', target, myItem, '[from] move: Switcheroo'); } else { this.add('-enditem', target, yourItem, '[silent]', '[from] move: Switcheroo'); } if (yourItem) { source.setItem(yourItem); this.add('-item', source, yourItem, '[from] move: Switcheroo'); } else { this.add('-enditem', source, myItem, '[silent]', '[from] move: Switcheroo'); } },",
    },
    'THIEF': {
        'onAfterHit': "onAfterHit(target, source, move) { if (source.item || source.volatiles['gem']) { return; } const yourItem = target.takeItem(source); if (!yourItem) { return; } if (!this.singleEvent('TakeItem', yourItem, target.itemState, source, target, move, yourItem) || !source.setItem(yourItem)) { target.item = yourItem.id; // bypass setItem so we don't break choicelock or anything return; } this.add('-enditem', target, yourItem, '[silent]', '[from] move: Thief', `[of] ${source}`); this.add('-item', source, yourItem, '[from] move: Thief', `[of] ${target}`); },",
    },
    'COVET': {
        'onAfterHit': "onAfterHit(target, source, move) { if (source.item || source.volatiles['gem']) { return; } const yourItem = target.takeItem(source); if (!yourItem) { return; } if ( !this.singleEvent('TakeItem', yourItem, target.itemState, source, target, move, yourItem) || !source.setItem(yourItem) ) { target.item = yourItem.id; // bypass setItem so we don't break choicelock or anything return; } this.add('-item', source, yourItem, '[from] move: Covet', `[of] ${target}`); },",
    },
}
AURORA_VEIL_ONTRY = "onTry() { return this.field.isWeather(['hail', 'snowscape']); },"
# Step G26: Perish Song keeps its onHitField and its condition as a handler of its own that the turn code implements: every
# active Pokemon without the volatile gets it with a duration of 4, the residual (order 24) shows the count and the end
# shows perish0 and faints the holder (data/moves.ts:13233-13277). The generator checks both texts, whitespace aside.
G26_HANDLERS = ['PERISH_SONG']
PERISH_SONG_HIT_FIELD = ("onHitField(target, source, move) { let result = false; let message = false; "
                         "for (const pokemon of this.getAllActive()) { "
                         "if (this.runEvent('Invulnerability', pokemon, source, move) === false) { "
                         "this.add('-miss', source, pokemon); result = true; } "
                         "else if (this.runEvent('TryHit', pokemon, source, move) === null) { result = true; } "
                         "else if (!pokemon.volatiles['perishsong']) { pokemon.addVolatile('perishsong'); "
                         "this.add('-start', pokemon, 'perish3', '[silent]'); result = true; message = true; } } "
                         "if (!result) return false; if (message) this.add('-fieldactivate', 'move: Perish Song'); },")
PERISH_SONG_CONDITION = ("condition: { duration: 4, onEnd(target) { this.add('-start', target, 'perish0'); target.faint(); }, "
                         "onResidualOrder: 24, onResidual(pokemon) { const duration = pokemon.volatiles['perishsong'].duration; "
                         "this.add('-start', pokemon, `perish${duration}`); }, },")
KNOCK_OFF_CALLBACKS = {
    'onBasePower': "onBasePower(basePower, source, target, move) { const item = target.getItem(); "
                   "if (!this.singleEvent('TakeItem', item, target.itemState, target, target, move, item)) return; "
                   "if (item.id) { return this.chainModify(1.5); } },",
    'onAfterHit': "onAfterHit(target, source) { const item = target.takeItem(); if (item) { "
                  "this.add('-enditem', target, item.name, '[from] move: Knock Off', `[of] ${source}`); } },",
}
# Step G15 (Psychic Terrain): Expanding Force has a handler of its own, because its two callbacks change the move's
# base power and its target class and no column holds either; the turn code implements it, and the row is marked.
G15_HANDLERS = ['EXPANDING_FORCE']
# Step G30: Rage Powder, Psychic Fangs and Solar Beam keep what the columns cannot hold as handlers of their own that the turn
# code implements (rows of the whole pool, like Knock Off). Rage Powder is Follow Me's redirection with the powder immunity of
# its user's foes (data/moves.ts:14598-14630); Psychic Fangs breaks the screens before the hit (14060-14078); Solar Beam is a
# two-turn move that sun skips and rain, sand and snow halve (17224-17258). The generator checks the whole text of each callback
# and of the condition, whitespace aside; the Champions mod changes none of them.
G30_HANDLERS = ['RAGE_POWDER', 'PSYCHIC_FANGS', 'SOLAR_BEAM']
RAGE_POWDER_ONTRY = "onTry(source) { return this.activePerHalf > 1; },"
RAGE_POWDER_CONDITION = ("condition: { duration: 1, onStart(pokemon) { this.add('-singleturn', pokemon, 'move: Rage Powder'); }, "
                         "onFoeRedirectTargetPriority: 1, onFoeRedirectTarget(target, source, source2, move) { "
                         "const ragePowderUser = this.effectState.target; if (ragePowderUser.isSkyDropped()) return; "
                         "if (source.runStatusImmunity('powder') && this.validTarget(ragePowderUser, source, move.target)) { "
                         "if (move.smartTarget) move.smartTarget = false; this.debug(\"Rage Powder redirected target of move\"); "
                         "return ragePowderUser; } }, },")
PSYCHIC_FANGS_ONTRYHIT = ("onTryHit(pokemon) { // will shatter screens through sub, before you hit pokemon.side.removeSideCondition('reflect'); "
                          "pokemon.side.removeSideCondition('lightscreen'); pokemon.side.removeSideCondition('auroraveil'); },")
SOLAR_BEAM_CALLBACKS = {
    'onTryMove': "onTryMove(attacker, defender, move) { if (attacker.removeVolatile(move.id)) { return; } "
                 "this.add('-prepare', attacker, move.name); "
                 "if (['sunnyday', 'desolateland'].includes(attacker.effectiveWeather(undefined, true))) { "
                 "this.attrLastMove('[still]'); this.addMove('-anim', attacker, move.name, defender); return; } "
                 "if (!this.runEvent('ChargeMove', attacker, defender, move)) { return; } "
                 "attacker.addVolatile('twoturnmove', defender); return null; },",
    'onBasePower': "onBasePower(basePower, pokemon, target) { "
                   "const weakWeathers = ['raindance', 'primordialsea', 'sandstorm', 'hail', 'snowscape']; "
                   "if (weakWeathers.includes(pokemon.effectiveWeather())) { this.debug('weakened by weather'); "
                   "return this.chainModify(0.5); } },",
}
# Step G30: the abilities that the turn code implements by id (ENGINE_ROWS), as whole callbacks of the pinned entries, whitespace
# aside; the Champions mod overrides none of them (data/mods/champions/abilities.ts). The engine reads Flame Body's 3 in 10 as
# one draw (DFI_SITE_FLAME_BODY), Clear Body's drop filter for the sources other than the holder, Hospitality's quarter heal of
# the adjacent allies at the switch-in priority -2, and Overcoat's immunity to sand and powder.
G30_ABILITY_FACTS = (
    ('flamebody', ("onDamagingHit(damage, target, source, move) { if (this.checkMoveMakesContact(move, source, target)) { "
                   "if (this.randomChance(3, 10)) { source.trySetStatus('brn', target); } } },",)),
    ('clearbody', ("onTryBoost(boost, target, source, effect) { if (source && target === source) return; "
                   "let showMsg = false; let i: BoostID; for (i in boost) { if (boost[i]! < 0) { delete boost[i]; showMsg = true; } } "
                   "if (showMsg && !(effect as ActiveMove).secondaries && effect.id !== 'octolock') { "
                   "this.add('-fail', target, 'unboost', '[from] ability: Clear Body', `[of] ${target}`); } },",)),
    ('hospitality', ("onSwitchInPriority: -2,",
                     "onStart(pokemon) { for (const ally of pokemon.adjacentAllies()) { this.heal(ally.baseMaxhp / 4, ally, pokemon); } },")),
    ('overcoat', ("onImmunity(type, pokemon) { if (type === 'sandstorm' || type === 'hail' || type === 'powder') return false; },",
                  "onTryHitPriority: 1,",
                  "onTryHit(target, source, move) { if (move.flags['powder'] && target !== source && "
                  "this.dex.getImmunity('powder', target)) { this.add('-immune', target, '[from] ability: Overcoat'); return null; } },")),
)
SPECIAL_P = dict(SPECIAL_C, **{
    'perishsong': ('PERISH_SONG', {'onHitField'}),                        # G26: a volatile on every active Pokemon, faints at 0
    'glaiverush': ('GLAIVE_RUSH', set()),                                 # G19: the volatile that makes its user hit as vulnerable
    'knockoff': ('KNOCK_OFF', {'onAfterHit', 'onBasePower'}),             # G16: takes the target's item, x1.5 while it has one
    'encore': ('ENCORE', set()),                                          # G9 (implemented): last move, a volatile, a queue change
    'disable': ('DISABLE', {'onTryHit'}),                                 # G27: bars the target's last move
    'spikyshield': ('SPIKY_SHIELD', {'onPrepareHit', 'onHit'}),           # G20: Protect that damages a contact attacker
    'taunt': ('TAUNT', set()),                                            # G31: bars the Status moves for three or four turns
    'yawn': ('YAWN', {'onTryHit'}),                                       # G31: sleep at the end of the next turn
    'auroraveil': ('AURORA_VEIL', {'onTry'}),                             # G20: a screen against both categories, in snow only
    'trick': ('TRICK', {'onTryImmunity', 'onHit'}),                         # G29: swaps the two items
    'switcheroo': ('SWITCHEROO', {'onTryImmunity', 'onHit'}),               # G29: Trick's text with its own name in the lines
    'thief': ('THIEF', {'onAfterHit'}),                                    # G29: takes the target's item after the hit
    'covet': ('COVET', {'onAfterHit'}),                                    # G29: the same without the silent -enditem line
    'wideguard': ('WIDE_GUARD', {'onTry', 'onHitSide'}),                 # G7: a side condition against spread moves
    'firstimpression': ('FIRST_IMPRESSION', {'onTry', 'onDisableMove'}),  # G10a: first turn out only (Fake Out's rule)
    'soak': ('SOAK', {'onHit'}),                                          # G11: sets the target's type to Water
    'lowkick': ('LOW_KICK', {'basePowerCallback', 'onTryHit'}),           # G10d: base power by the target's weight
    'sandstorm': ('SANDSTORM', set()),                                    # weather: sets the weather (for 5 turns)
    'snowscape': ('SNOWSCAPE', set()),
    'expandingforce': ('EXPANDING_FORCE', {'onBasePower', 'onModifyMove'}),  # G15: x1.5 and a spread in Psychic Terrain
    'shellsmash': ('SHELL_SMASH', set()),                                 # G28: its boosts apply in the pin's order
    'acrobatics': ('ACROBATICS', {'basePowerCallback'}),                  # G28: doubled without an item
    'blizzard': ('BLIZZARD', {'onModifyMove'}),                           # G28: never misses in snow
    'feint': ('FEINT', set()),                                            # G28: breaks Protect and Wide Guard
    'ragepowder': ('RAGE_POWDER', {'onTry'}),                              # G30: Follow Me for the foes that are not powder immune
    'psychicfangs': ('PSYCHIC_FANGS', {'onTryHit'}),                       # G30: the screens go before the hit
    'solarbeam': ('SOLAR_BEAM', {'onBasePower', 'onTryMove'}),             # G30: a two-turn move that sun skips, x0.5 in rain, sand, snow
    'steelroller': ('STEEL_ROLLER', {'onTry', 'onHit', 'onAfterSubDamage'}),  # G34: fails without a terrain and ends it
    'clangoroussoul': ('CLANGOROUS_SOUL', {'onTry', 'onTryHit', 'onHit'}),    # G34: a third of the HP for five boosts
    'brickbreak': ('BRICK_BREAK', {'onTryHit'}),
    'imprison': ('IMPRISON', set()),                                      # G38: the foes may not use the moves it knows                          # G34: the screens go before the hit
    'eruption': ('HP_POWER', {'basePowerCallback'}),                      # G32: power by the user's HP
    'waterspout': ('HP_POWER', {'basePowerCallback'}),
    'bodypress': ('BODY_PRESS', set()),                                   # G32: the Defense stat attacks
    'foulplay': ('FOUL_PLAY', set()),                                     # G32: the target's Attack and stages
    'psyshock': ('PSYSHOCK', set()),                                      # G32: a special hit at the Defense stat
    'raindance': ('RAIN_DANCE', set()),                                   # G32: weather moves
    'sunnyday': ('SUNNY_DAY', set()),
    'freezedry': ('FREEZE_DRY', {'onEffectiveness'}),                     # G32: Water takes it super effective
    'clangingscales': ('CLANGING_SCALES', set()),                         # G32: the user's Defense falls after a hit
    'electricterrain': ('ELECTRIC_TERRAIN', set()),                       # G25: sets the terrain (5 turns)
    'mistyterrain': ('MISTY_TERRAIN', set()),
    'risingvoltage': ('RISING_VOLTAGE', {'basePowerCallback'}),           # G25: doubled at a grounded target in Electric Terrain
    'terrainpulse': ('TERRAIN_PULSE', {'onModifyType', 'onModifyMove'}),  # G25: the terrain's type, doubled for a grounded user
    'dualwingbeat': ('MULTI_HIT_2', set()),                               # G33: two hits
    'twinbeam': ('MULTI_HIT_2', set()),
    'tripleaxel': ('TRIPLE_AXEL', {'basePowerCallback'}),                 # G33: three hits, a check for each, 20 x the hit
    'sacredsword': ('DARKEST_LARIAT', set()),                             # G39: Darkest Lariat's ignoreDefensive and ignoreEvasion
    'superfang': ('SUPER_FANG', {'damageCallback'}),                      # G39: half the target's current HP
    'doubleshock': ('DOUBLE_SHOCK', {'onTryMove'}),                       # G50: fails without Electric; its self effect is owned
})
# Step G13: Detect is Protect (data/moves.ts:3526-3547 against 13961-14005): the same handler (not one of the G2 handlers,
# so it is added to the pool's map only), and the generator checks that its stalling fields and both callbacks are,
# whitespace aside, the text of Protect's; its volatile 'protect' is Protect's condition, which lives on the Protect
# entry. The engine reads the special column, so the stall counter is shared (the pin's StallMove event is per Pokemon,
# not per move).
SPECIAL_POOL = dict(SPECIAL_P, detect=('PROTECT', {'onPrepareHit', 'onHit'}))
PROTECT_COPIES = {'detect': 'protect'}
# Step G13: Light of Ruin carries tags: ["Past Unobtainable"] next to isNonstandard: "Past"; the Champions mod (data/mods/
# champions/moves.ts:581-584) sets isNonstandard to null, which makes it legal, and the tag has no reader in the tables.
TAGS_PAST_UNOBTAINABLE = 'tags: ["Past Unobtainable"],'
PROTECT_COPY_FIELDS = ('onPrepareHit', 'onHit', 'stallingMove', 'volatileStatus', 'priority', 'accuracy', 'target')
SPECIAL_IDS_P = SPECIAL_IDS_C + G2_HANDLERS + WEATHER_HANDLERS + G16_HANDLERS + G15_HANDLERS + G19_HANDLERS + G20_HANDLERS + G20_PROTECT_HANDLERS + G28_HANDLERS + G30_HANDLERS + G32_HANDLERS + G34_HANDLERS + G27_HANDLERS + G25_HANDLERS + G26_HANDLERS + G33_HANDLERS + G38_HANDLERS + G29_HANDLERS + G39_HANDLERS + G31_HANDLERS + G50_HANDLERS + ['UNMODELED']
# Step G10 made two of these handlers data: Scald (thawsTarget) and Recover (heal) are read into the second flags
# byte (bit 4, thaws the target) and the heal column, and have the special NONE; their ids stay defined (the ids after
# them keep their values). First Impression and Low Kick keep theirs: the turn code implements them.
POOL_COLUMN_KEYS = {'thawsTarget', 'heal'}
G2_OWNED_FIELDS = {
    'ENCORE': {'volatileStatus': "volatileStatus: 'encore',"},
    'WIDE_GUARD': {'sideCondition': "sideCondition: 'wideguard',"},
    'AURORA_VEIL': {'sideCondition': "sideCondition: 'auroraveil',"},
    'DISABLE': {'volatileStatus': "volatileStatus: 'disable',"},
    'SPIKY_SHIELD': {'volatileStatus': "volatileStatus: 'spikyshield',"},
    'TAUNT': {'volatileStatus': "volatileStatus: 'taunt',"},
    'YAWN': {'volatileStatus': "volatileStatus: 'yawn',"},
    'SANDSTORM': {'weather': "weather: 'Sandstorm',"},
    'SNOWSCAPE': {'weather': "weather: 'snowscape',"},
    'ELECTRIC_TERRAIN': {'terrain': "terrain: 'electricterrain',"},
    'MISTY_TERRAIN': {'terrain': "terrain: 'mistyterrain',"},
    'SHELL_SMASH': {'boosts': "boosts: { def: -1, spd: -1, atk: 2, spa: 2, spe: 2, },"},
    'FEINT': {'breaksProtect': "breaksProtect: true, // Breaking protection implemented in scripts.js"},
    'GLAIVE_RUSH': {'self': "self: { volatileStatus: 'glaiverush', },"},
    'RAGE_POWDER': {'volatileStatus': "volatileStatus: 'ragepowder',"},
    'MULTI_HIT_2': {'multihit': 'multihit: 2,'},
    'DOUBLE_SHOCK': {'self': "self: { onHit(pokemon) { pokemon.setType(pokemon.getTypes(true).map(type => type === \"Electric\" ? \"???\" : type)); this.add('-start', pokemon, 'typechange', pokemon.getTypes().join('/'), '[from] move: Double Shock'); }, },"},
    'TRIPLE_AXEL': {'multihit': 'multihit: 3,', 'multiaccuracy': 'multiaccuracy: true,'},
    'BODY_PRESS': {'overrideOffensiveStat': "overrideOffensiveStat: 'def',"},
    'FOUL_PLAY': {'overrideOffensivePokemon': "overrideOffensivePokemon: 'target',"},
    'PSYSHOCK': {'overrideDefensiveStat': "overrideDefensiveStat: 'def',"},
    'RAIN_DANCE': {'weather': "weather: 'RainDance',"},
    'SUNNY_DAY': {'weather': "weather: 'sunnyday',"},
    'CLANGING_SCALES': {'selfBoost': "selfBoost: { boosts: { def: -1, }, },"},
    'IMPRISON': {'volatileStatus': "volatileStatus: 'imprison',"},
}
G2_OWNED_SECONDARY = {}
G2_OWNED_CONDITION = {'ENCORE', 'WIDE_GUARD', 'GLAIVE_RUSH', 'AURORA_VEIL', 'SPIKY_SHIELD', 'RAGE_POWDER', 'DISABLE',
                      'ELECTRIC_TERRAIN', 'MISTY_TERRAIN', 'PERISH_SONG', 'IMPRISON', 'TAUNT', 'YAWN'}
# Step G8 (Throat Chop and Psychic Noise): the two secondaries become modelled kinds, and the column that their
# consumers read is the move's second flags byte (the first is full): the `sound` flag (Throat Chop bars the sound
# moves) and the `heal` flag (Heal Block bars the moves that heal). Both are derived for every pool move, the prefix
# included; the CLOSURE and extended bytes do not have them. Decision 0015 section 2.
SECONDARY_LOCKOUT = 5     # Throat Chop: chance 100, addVolatile('throatchop'): the target may not use sound moves
SECONDARY_HEAL_BLOCK = 6  # Psychic Noise: chance 100, volatileStatus 'healblock' (2 turns from Psychic Noise)
G8_SECONDARIES = {
    "secondary: { chance: 100, onHit(target) { target.addVolatile('throatchop'); }, },": (SECONDARY_LOCKOUT, True),
    "secondary: { chance: 100, volatileStatus: 'healblock', },": (SECONDARY_HEAL_BLOCK, False),
}
FLAGS2_BITS = {'sound': 1, 'heal': 2, 'powder': 16, 'punch': 32, 'slicing': 64}  # steps G30 (powder) and G34 (punch, slicing)
# Decision 0020: the public static flags of a move (DUOFORGE_MOVE_STATIC_FLAG_*, include/duoforge/duoforge.h), one bit per
# Showdown flag name, additive only; the generated column dfi_pool_move_static_flags holds them for every pool row and has
# no engine reader. POWER_RULE is not a flag of the pin: the move has a basePowerCallback (its basePower is not the damage).
STATIC_FLAG_BITS = {'contact': 1, 'sound': 2, 'punch': 4, 'bite': 8, 'bullet': 16, 'pulse': 32, 'slicing': 64,
                    'wind': 128, 'dance': 256, 'powder': 512}
STATIC_FLAG_POWER_RULE = 1024
FLAG2_RECHARGE = 8  # step G17: flags.recharge with self: {volatileStatus: 'mustrecharge'} (data/moves.ts, Hyper Beam 9113-9128)
RECHARGE_SELF = "self: { volatileStatus: 'mustrecharge', },"
FLAG2_THAWS_TARGET = 4  # step G10: thawsTarget (data/moves.ts:15770), the move cures a frozen target after the secondaries
# What the engine hard-codes about the two conditions, read from the pin (build_pool checks it): the duration and the
# residual order of Throat Chop's condition, and Heal Block's (the move healblock) order and Psychic Noise duration.
G8_CONDITION_FACTS = (
    ('throatchop', ['duration: 2,', 'onResidualOrder: 22,', "if (this.dex.moves.get(moveSlot.id).flags['sound']) {",
                    "if (!move.isZOrMaxPowered && move.flags['sound']) {", 'onBeforeMovePriority: 6,']),
    ('healblock', ['onResidualOrder: 20,', 'onBeforeMovePriority: 6,', 'if (effect?.name === "Psychic Noise") {',
                   'return 2;', "if (this.dex.moves.get(moveSlot.id).flags['heal']) {",
                   "if (move.flags['heal'] && !move.isZ && !move.isMax) {",
                   'onTryHeal(damage, target, source, effect) {']),
)
# Step G20: what the engine hard-codes about Aurora Veil, whole callbacks and values of the pinned entry (the
# durations, the damage modifier and its two exceptions, the order among the side conditions, both lines).
G20_CONDITION_FACTS = (
    ('auroraveil', ['duration: 5,',
                    "durationCallback(target, source, effect) { if (source?.hasItem('lightclay')) { return 8; } return 5; },",
                    "onAnyModifyDamage(damage, source, target, move) { if (target !== source && "
                    "this.effectState.target.hasAlly(target)) { "
                    "if ((target.side.getSideCondition('reflect') && this.getCategory(move) === 'Physical') || "
                    "(target.side.getSideCondition('lightscreen') && this.getCategory(move) === 'Special')) { return; } "
                    "if (!target.getMoveHitData(move).crit && !move.infiltrates) { this.debug('Aurora Veil weaken'); "
                    "if (this.activePerHalf > 1) return this.chainModify([2732, 4096]); return this.chainModify(0.5); } } },",
                    "onSideStart(side) { this.add('-sidestart', side, 'move: Aurora Veil'); },",
                    'onSideResidualOrder: 26,', 'onSideResidualSubOrder: 10,',
                    "onSideEnd(side) { this.add('-sideend', side, 'move: Aurora Veil'); },"]),
)
# Step G25: what the engine hard-codes about Electric Terrain and Misty Terrain (data/moves.ts:4497-4551 and 12151-12205), Rising
# Voltage (:15137-15162) and Terrain Pulse (:19265-19311), whole callbacks and values of the pinned entries: the durations
# (and Terrain Extender's 8, which no marked item gives), the residual order, the sleep and status refusals and which of
# them print the -activate line, the confusion refusal of Misty Terrain, the base power modifiers, the lines of the field.
# The converter reads the one quirk of the pin: Misty Terrain's -fieldend line has no "move: " in it.
G25_TERRAIN_COMMON = ('terrain: \'%(id)s\',', 'category: "Status",', 'accuracy: true,', 'target: "all",', 'duration: 5,',
                      "durationCallback(source, effect) { if (source?.hasItem('terrainextender')) { return 8; } return 5; },",
                      'onBasePowerPriority: 6,',
                      "onFieldStart(field, source, effect) { if (effect?.effectType === 'Ability') { "
                      "this.add('-fieldstart', 'move: %(name)s', '[from] ability: ' + effect.name, `[of] ${source}`); } else { "
                      "this.add('-fieldstart', 'move: %(name)s'); } },",
                      'onFieldResidualOrder: 27,', 'onFieldResidualSubOrder: 7,')
G25_FACTS = (
    ('electricterrain', [f % {'id': 'electricterrain', 'name': 'Electric Terrain'} for f in G25_TERRAIN_COMMON] + [
        "onSetStatus(status, target, source, effect) { if (status.id === 'slp' && target.isGrounded() && "
        "!target.isSemiInvulnerable()) { if (effect.id === 'yawn' || (effect.effectType === 'Move' && !effect.secondaries)) { "
        "this.add('-activate', target, 'move: Electric Terrain'); } return false; } },",
        "onTryAddVolatile(status, target) { if (!target.isGrounded() || target.isSemiInvulnerable()) return; "
        "if (status.id === 'yawn') { this.add('-activate', target, 'move: Electric Terrain'); return null; } },",
        "onBasePower(basePower, attacker, defender, move) { if (move.type === 'Electric' && attacker.isGrounded() && "
        "!attacker.isSemiInvulnerable()) { this.debug('electric terrain boost'); return this.chainModify([5325, 4096]); } },",
        "onFieldEnd() { this.add('-fieldend', 'move: Electric Terrain'); },"]),
    ('mistyterrain', [f % {'id': 'mistyterrain', 'name': 'Misty Terrain'} for f in G25_TERRAIN_COMMON] + [
        "onSetStatus(status, target, source, effect) { if (!target.isGrounded() || target.isSemiInvulnerable()) return; "
        "if (effect && ((effect as Move).status || effect.id === 'yawn')) { this.add('-activate', target, 'move: Misty Terrain'); } "
        "return false; },",
        "onTryAddVolatile(status, target, source, effect) { if (!target.isGrounded() || target.isSemiInvulnerable()) return; "
        "if (status.id === 'confusion') { if (effect.effectType === 'Move' && !effect.secondaries) "
        "this.add('-activate', target, 'move: Misty Terrain'); return null; } },",
        "onBasePower(basePower, attacker, defender, move) { if (move.type === 'Dragon' && defender.isGrounded() && "
        "!defender.isSemiInvulnerable()) { this.debug('misty terrain weaken'); return this.chainModify(0.5); } },",
        "onFieldEnd() { this.add('-fieldend', 'Misty Terrain'); },"]),
    ('risingvoltage', ['basePower: 70,', 'accuracy: 100,', 'category: "Special",', 'target: "normal",', 'type: "Electric",',
                       "basePowerCallback(source, target, move) { if (this.field.isTerrain('electricterrain') && "
                       "target.isGrounded()) { if (!source.isAlly(target)) this.hint(`${move.name}'s BP doubled on "
                       "grounded target.`); return move.basePower * 2; } return move.basePower; },"]),
    ('terrainpulse', ['basePower: 50,', 'accuracy: 100,', 'category: "Special",', 'target: "normal",', 'type: "Normal",',
                      'flags: { protect: 1, mirror: 1, metronome: 1, pulse: 1 },',
                      "onModifyType(move, pokemon) { if (!pokemon.isGrounded()) return; switch (this.field.terrain) { "
                      "case 'electricterrain': move.type = 'Electric'; break; case 'grassyterrain': move.type = 'Grass'; break; "
                      "case 'mistyterrain': move.type = 'Fairy'; break; case 'psychicterrain': move.type = 'Psychic'; break; } },",
                      "onModifyMove(move, pokemon) { if (this.field.terrain && pokemon.isGrounded()) { move.basePower *= 2; "
                      "this.debug('BP doubled in Terrain'); } },"]),
)
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
                   'WEATHER_SETTER': ['drizzle', 'drought', 'sandstream', 'snowwarning'],
                   'TERRAIN_SETTER': ['grassysurge', 'psychicsurge', 'electricsurge']}
# The weather and terrain codes of the family column are the engine's state values (DFI_WEATHER_* and
# DFI_TERRAIN_* of src/state/battle_internal.h, which duoforge.data.pool_tables checks), by Showdown's id.
WEATHER_CODES = {'raindance': ('RAIN', 1), 'sunnyday': ('SUN', 2), 'sandstorm': ('SAND', 3), 'snowscape': ('SNOW', 4)}
TERRAIN_CODES = {'grassyterrain': ('GRASSY', 1), 'psychicterrain': ('PSYCHIC', 2), 'electricterrain': ('ELECTRIC', 3),
                 'mistyterrain': ('MISTY', 4)}
# A rain or sun setter skips the Primal Pokemon with their orb (data/abilities.ts, Drizzle and Drought). No Primal
# Pokemon is legal in the format; the guard is part of the weather pattern and must be exactly this one.
PRIMAL_GUARD = {'raindance': ('kyogre', 'blueorb'), 'sunnyday': ('groudon', 'redorb')}
# Chilan Berry halves any Normal hit; every other resist berry needs a super effective hit (decision 0015 section 3).
# A Normal move is never super effective, so the variant is the Normal berry.
RESIST_BERRY_NORMAL = ('chilanberry',)

# ---- The whole legal pool (decision 0015 section 4.2): a row for every move, item, ability and forme of the format,
# appended after the rows of the steps above. A row that the tables model fully is encoded exactly as before; one that
# has anything unmodelled gets the UNMODELED handler (the move's special column; the handler column of an item or an
# ability) and a recorded list of the features that are not modelled. Such rows are never marked in the manifest. ----
# Target classes of the pool that the closure encodings lack, as codes of the generated header only (the public
# DUOFORGE_TARGET_CLASS_* values stay 1 to 9; Struggle's randomNormal is 10). They are encoded; the turn code does not
# implement them, so a move with one is UNMODELED.
TARGET_CLASS_POOL = dict(TARGET_CLASS, allAdjacent=11, scripted=12, allyTeam=13, allies=14, foeSide=15)
TARGET_CLASS_POOL_NAMES = {11: 'ALL_ADJACENT', 12: 'SCRIPTED', 13: 'ALLY_TEAM', 14: 'ALLIES', 15: 'FOE_SIDE'}
# The target classes that the turn code resolves (src/combat/turn.c, dfi_resolve_targets and request.c).
ENGINE_TARGETS = {'normal', 'any', 'adjacentAlly', 'adjacentFoe', 'self', 'allAdjacentFoes', 'allySide', 'all',
                  'randomNormal', 'allAdjacent', 'allies', 'foeSide'}  # allAdjacent: step G28 (Earthquake hits the ally too); allies: G32 (Life Dew); foeSide: G37 (the four hazards)
# Every move flag of the 510 pool moves: a flag outside this set is something the generator cannot read.
POOL_FLAGS = (set(FLAG_BITS_C) | IGNORED_FLAGS | G2_IGNORED_FLAGS |
              {'bite', 'recharge', 'minimize', 'gravity', 'powder', 'noparentalbond', 'futuremove', 'cantusetwice',
               'mustpressure', 'nosketch'})
# The move flags that no bit holds and that a modelled row reads. It is filled by build_pool from the rows that are
# modelled by definition (the prefix); a move with such a flag is UNMODELED. The set is empty while no modelled row
# reads an unencoded flag; the day one does, the move rows that carry the flag change by rule, never silently.
FLAGS_THAT_MATTER = set()
# Flags that a row of the prefix reads and that still do not matter, each with the reason and the row whose
# modelling would make it matter (build_pool fails if that row is modelled):
#   bypasssub -- Chople Berry reads it next to the substitute volatile, which no modelled row has (Substitute is
#                UNMODELED); pledgecombo -- Lightning Rod reads it; only the pledge moves have it, none is in the pool.
INERT_FLAG_READS = {'bypasssub': 'substitute', 'pledgecombo': None}
HANDLER_IDS = ['NONE', 'UNMODELED']
# Items and abilities that a step of the expansion implements in the turn code by id (they have no family): modelled
# by definition, like the closure and Team C rows. The step that marks such a row in the support manifest adds its id
# here, which changes the handler column and so the POOL table hash, as any pool change does; a row that is marked and
# still has the UNMODELED handler fails duoforge.data.pool_tables. G4: Focus Sash, Rock Head. G12: Floettite (the Mega
# Stone of Floette-Eternal), Flower Veil and Fairy Aura. G14: Rough Skin, Poison Touch and Thermal Exchange. G16: Sticky Hold (Knock Off reads it by id). AC1: Trace (the entry copy of a foe's ability). G15: Psychic Seed (Grassy Seed's rule for the other terrain). G22: Sand Rush, Swift Swim, Slush Rush and Chlorophyll (the doubled Speed in their weather, tools/datagen/pool_families.js ENGINE_ORDER), Sand Rush's immunity to Sandstorm, Inner Focus (no flinch, no Intimidate drop) and Liquid Voice (a sound move becomes Water). G23-C: Levitate (isGrounded and the Ground immunity).
ENGINE_ROWS = {'items': ['focussash', 'floettite', 'psychicseed', 'electricseed', 'mistyseed', 'expertbelt', 'ejectbutton',
                         'widelens'],
               'abilities': ['rockhead', 'flowerveil', 'fairyaura', 'roughskin', 'poisontouch', 'thermalexchange',
                             'stickyhold', 'trace', 'levitate', 'sandrush', 'swiftswim', 'slushrush', 'chlorophyll',
                             'innerfocus', 'liquidvoice', 'flamebody', 'clearbody', 'hospitality', 'overcoat',
                             'soundproof', 'unnerve', 'speedboost', 'compoundeyes', 'ironfist', 'sharpness', 'solidrock',
                             'technician', 'multiscale', 'galewings', 'raindish', 'friendguard', 'cursedbody', 'mirrorarmor', 'auraguard',
                             'hypercutter',
                             'scrappy',
                             'infiltrator',
                             'queenlymajesty',
                             'damp',
                             'sturdy',
                             'snowcloak',
                             'sandveil',
                             'static',
                             'justified',
                             'limber',
                             'solarpower',
                             'regenerator', 'toxicdebris', 'shadowtag']}
# The moves of the whole pool that the turn code pivots with a switch flag of their own (dfi_pivot_moves,
# src/state/closure_member.c) beyond Flip Turn and U-turn, which are rows of the steps. Empty: Volt Switch comes with the
# step that gives it a flag value, and adds its id here.
ENGINE_PIVOT_MOVES = ('voltswitch',)  # step G32: switch flag 6
# The one ability that the pin tags as not released and that the pool still has: Aura Guard is the ability of
# Lucario-Mega-Z, whose set the pinned validator accepts (docs/research/expansion/data/legal_pool.json, 'abilities_mega_only').
# The row exists because the format has the forme; it is UNMODELED like every ability with a callback. Any other tag fails.
LEGAL_DESPITE_TAG = {'auraguard': 'Future'}
# What an ability or item entry may have and still be pure data. Anything else is a callback or a field that the
# tables do not model.
INERT_ABILITY_KEYS = {'name', 'num', 'rating', 'gen', 'isNonstandard', 'flags'}
INERT_ITEM_KEYS = {'name', 'spritenum', 'fling', 'num', 'gen', 'isNonstandard', 'naturalGift', 'isBerry', 'isChoice',
                   'isGem', 'isPokeball', 'megaStone', 'itemUser', 'megaEvolves'}
# The onTakeItem of every Mega Stone at the pin (it only stops Knock Off and Trick on the holder): data for the
# Mega link, not a mechanic of the tables.
STONE_TAKE_ITEM = ("onTakeItem(item, source) { return !item.megaStone?.[source.baseSpecies.baseSpecies]; },",
                   "onTakeItem(item, source) { return !item.megaStone || (!item.megaStone[source.baseSpecies.name] && "
                   "!Object.values(item.megaStone).includes(source.baseSpecies.name)); },")
# Field widths that the whole pool has to fit, read from the sources that own them (check_bounds).
BOUND_SOURCES = {
    'state': os.path.join('src', 'state', 'battle_internal.h'),
    'api': os.path.join('include', 'duoforge', 'duoforge.h'),
    'context': os.path.join('src', 'state', 'context_internal.h'),
}


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
            'species': {sp['id']: sp for sp in legal['species']},
            # The pool in the file's own order (alphabetical by id for moves, items and abilities, the dex for
            # species): the order in which the whole-pool rows are appended after the rows of the steps.
            'move_order': [m['id'] for m in legal['moves']], 'item_order': [i['id'] for i in legal['items']],
            'ability_order': [a['id'] for a in legal['abilities']], 'species_order': [sp['id'] for sp in legal['species']],
            'stones': {i['id']: list(i['mega_stone'].items()) for i in legal['items'] if i['is_mega_stone']},
            'counts': legal['counts']}


# The legal moves and abilities of a forme (decision 0015 section 2). A forme declares up to three abilities (0, 1 and
# the hidden one); the event-only ones are not legal.
FORME_ABILITIES_MAX = 3
LEARNSET_ENTRY = re.compile(r'\t\t\t(\w+): \["9M"\],')


def learnset_moves(learn, fid, base=None):
    """The moves of a forme's entry of data/mods/champions/learnsets.ts: one learnset block in which every entry is
    "9M" (no event, egg or level-up source, as the research note found), so learnable means listed. Any other shape
    fails; it never guesses."""
    e = learn.entry(fid)
    if e is not None and e[2] == ['\t%s: {},' % fid]:
        e = None  # an empty entry (Gourgeist-Super) is no learnset of its own
    if e is None and base is not None and base != fid:
        # A forme without a learnset of its own (Gourgeist-Small) learns what its base species learns; the
        # validator cross-check of forme_legal decides whether that is right for the forme.
        e = learn.entry(base)
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
            if LEGAL_DESPITE_TAG.get(aid) == scalar(f['isNonstandard'][1]):
                return
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
            learnable = learnset_moves(learn, fo['id'], rec.get('base_species')) & set(pool_moves)
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


def prefix_flag_reads(srcs, dx):
    """The move flags that the rows of the extended prefix (the closure and Team C, whose handlers are code in the turn
    core) read in their pinned handlers: `flags['x']` or `.flags.x`. A flag that a modelled row reads and that no bit
    holds would matter to the move rows that carry it."""
    items_ts, champ_items, abil_ts, champ_abil, moves_ts, champ_moves = srcs
    reads = set()
    for src, champ, rows in ((abil_ts, champ_abil, dx['abilities']), (items_ts, champ_items, dx['items']),
                             (moves_ts, champ_moves, dx['moves'])):
        for r in rows:
            for s in (src, champ):
                e = s.entry(r['id'])
                if e is not None:
                    text = '\n'.join(e[2])
                    reads.update(re.findall(r"flags\['(\w+)'\]", text))
                    reads.update(re.findall(r'\.flags\.(\w+)', text))
    return reads


def parse_pool_move(mid, moves_ts, champ_moves):
    """A move of the whole pool that no step has handled: parsed in the lenient mode. Everything that the tables
    model is encoded as parse_move encodes it; a move with any unmodelled feature gets the UNMODELED handler, its effect
    columns neutral (a refused row claims nothing beyond its plain data: type, category, power, accuracy, PP,
    priority, target class, crit ratio, flags, recoil and drain), and the list of its features."""
    features = []
    rec = parse_move(mid, moves_ts, champ_moves, pool=True, unmodeled=features)
    rec['unmodeled'] = sorted(set(features))
    if rec['unmodeled']:
        rec.update(sec_chance=0, sec_kind=0, sec_param=0, boost_role=0, boosts=[0] * 7, primary_status=0,
                   side_condition=0, pseudo_weather=0, special=SPECIAL_IDS_P.index('UNMODELED'), heal=[0, 0],
                   flags2=rec['flags2'] & ~(FLAG2_THAWS_TARGET | FLAG2_RECHARGE))
    return rec


class ReaderIndex:
    """Where the quoted id of an item or ability appears in the pinned code: the data files that hold handlers (moves,
    abilities, items, conditions and the Champions mod) and the sim files that run them. An item or ability with no
    callback of its own can still be read by its id elsewhere (Damp Rock by Rain Dance, Levitate by isGrounded, Binding
    Band by the trapping condition): its effect is then code in the reader, not data in its row."""

    QUOTED = re.compile(r"""['"]([a-z][a-z0-9]*)['"]""")

    def __init__(self, root, loaded):
        self.lines = {rel: Source(root, rel, READER_INPUTS).lines for rel in READER_INPUTS}
        for rel in ('data/abilities.ts', 'data/items.ts', 'data/moves.ts', 'data/mods/champions/abilities.ts',
                    'data/mods/champions/items.ts', 'data/mods/champions/moves.ts', 'data/mods/champions/scripts.ts'):
            self.lines[rel] = loaded[rel].lines
        self.index = {}
        for rel, lines in self.lines.items():
            for n, line in enumerate(lines, 1):
                for tok in self.QUOTED.findall(line):
                    self.index.setdefault(tok, []).append((rel, n))

    def files(self, rid, own):
        """The files that read the id outside the id's own entries (own: (file, first line, last line) triples)."""
        return sorted({rel for rel, n in self.index.get(rid, []) if not any(r == rel and a <= n <= b for r, a, b in own)})


def entry_features(src, champ, rid, inert_keys, stone=False, readers=None):
    """The features of an item or ability entry that the tables do not model: every callback (a function field, or
    any field named onX), a condition block and every field outside the inert keys. The Champions mod adds or
    replaces fields of the same entry. A Mega Stone's onTakeItem is data of its Mega link (STONE_TAKE_ITEM)."""
    e = src.entry(rid)
    if e is None:
        fail('%s not found in %s' % (rid, src.rel))
    f = fields(e[2])
    ce = champ.entry(rid)
    if ce is not None:
        f.update({k: v for k, v in fields(ce[2]).items() if k != 'inherit'})
    feats = []
    for name, (is_fn, text) in sorted(f.items()):
        if name == 'condition':
            feats.append('condition block')
        elif is_fn or re.match(r'on[A-Z]', name):
            if stone and name == 'onTakeItem' and norm(re.sub(r'//[^\n]*', '', text)) in STONE_TAKE_ITEM:
                continue
            feats.append('callback %s' % name)
        elif name not in inert_keys:
            feats.append('field %s' % name)
    if readers is not None:
        own = [(src.rel, e[0], e[1])] + ([(champ.rel, ce[0], ce[1])] if ce is not None else [])
        feats += ['read by id in %s' % rel for rel in readers.files(rid, own)]
    return feats


def check_bounds(d, repo):
    """The whole pool has to fit the widths that the state, the observation, the context and the tables give its ids
    (decision 0015 section 4.2). The widths are read from the sources that own them, so a field that becomes
    narrower fails the generator here, never as a silent truncation at setup."""
    def read(key):
        with io.open(os.path.join(repo, BOUND_SOURCES[key]), encoding='utf-8') as fh:
            return fh.read().replace('\r\n', '\n')

    def width(text, owner, field):
        """The bit width of `field` in the struct that starts at `owner` (the first declaration after it)."""
        a = text.find(owner)
        if a < 0:
            fail('bounds: %s not found' % owner)
        m = re.search(r'\buint(8|16|32)_t\s+%s\b' % re.escape(field), text[a:text.index('}', a)])
        if m is None:
            fail('bounds: no integer field %s in %s' % (field, owner))
        return int(m.group(1))

    state, api, ctx = read('state'), read('api'), read('context')
    n = {k: len(d[k]) for k in ('formes', 'moves', 'items', 'abilities')}
    # A member's species and each move slot are u16 in the state (a forme id below 0xFFFF, which is the "no forme"
    # value of the tables); its item and ability are u8 holding 1 + the id (0 is none) and the tables use 0xFF as
    # their own "none", so an id is at most 254 and 1 + an id at most 255.
    limits = [
        ('species_id of dfi_member', width(state, 'typedef struct dfi_member {', 'species_id'), n['formes'] - 1),
        ('move_id of dfi_move_slot', width(state, 'typedef struct dfi_move_slot {', 'move_id'), n['moves'] - 1),
        ('item of dfi_member', width(state, 'typedef struct dfi_member {', 'item'), n['items']),
        ('ability of dfi_member', width(state, 'typedef struct dfi_member {', 'ability'), n['abilities']),
        ('species_id of duoforge_member_view', width(api, 'typedef struct duoforge_member_view {', 'species_id'),
         n['formes'] - 1),
        ('ability of duoforge_member_view', width(api, 'typedef struct duoforge_member_view {', 'ability'),
         n['abilities']),
        ('item of duoforge_member_view', width(api, 'typedef struct duoforge_member_view {', 'item'), n['items']),
        ('move_ids of duoforge_member_view', width(api, 'typedef struct duoforge_member_view {', 'move_ids'),
         n['moves'] - 1),
        ('id of duoforge_event', width(api, 'typedef struct duoforge_event {', 'id'), max(n['formes'] - 1, n['moves'] - 1)),
        ('id2 of duoforge_event', width(api, 'typedef struct duoforge_event {', 'id2'),
         max(n['moves'] - 1, n['items'], n['abilities'])),
        ('species_count of the context', width(ctx, 'struct duoforge_context {', 'species_count'), n['formes']),
        ('move_count of the context', width(ctx, 'struct duoforge_context {', 'move_count'), n['moves']),
    ]
    for what, bits, biggest in limits:
        if biggest > (1 << bits) - 1:
            fail('bounds: %s is %d bits, the pool needs %d' % (what, bits, biggest))
    if width(api, 'typedef struct duoforge_member_view {', 'species_id') != 16:
        fail('bounds: species_id of the member view is no longer 16 bits')
    m = re.search(r'#define DUOFORGE_DATA_MAX_FORME_MOVES\s+(\d+)u', api)
    if m is None or n['moves'] > int(m.group(1)):
        fail('bounds: %d moves exceed DUOFORGE_DATA_MAX_FORME_MOVES' % n['moves'])
    m = re.search(r'#define DUOFORGE_DATA_MAX_FORME_ABILITIES\s+(\d+)u', api)
    if m is None or FORME_ABILITIES_MAX > int(m.group(1)):
        fail('bounds: a forme may have more legal abilities than DUOFORGE_DATA_MAX_FORME_ABILITIES')
    # The u8 row fields of the tables: ability, item and move ids (the none value 0xFF is not an id), and ids in the
    # forme legal lists. Forme ids are u16 in the pool rows (0xFFFF is none).
    if n['abilities'] > 254 or n['items'] > 254:
        fail('bounds: the pool has %d abilities and %d items; a u8 id field holds at most 254 (0xFF is none)' % (
            n['abilities'], n['items']))
    if n['formes'] > 0xFFFE or n['moves'] > 0xFFFF:
        fail('bounds: %d formes and %d moves exceed the u16 ids' % (n['formes'], n['moves']))
    for fo in d['formes']:
        if any(v > 254 for v in fo['set_moves']) or fo['set_item'] > 254 and fo['set_item'] != 0xFF:
            fail('bounds: the set of %s does not fit the u8 fields of its row' % fo['id'])
        if fo['dex_num'] > 0xFFFF or fo['weight_hg'] > 0xFFFF or any(not 0 <= b <= 255 for b in fo['base']):
            fail('bounds: %s has a dex number, weight or base stat outside its field' % fo['id'])
    if len(d['forme_legal'][0]['learnable']) * 8 < n['moves']:
        fail('bounds: the learnable bitset is too short for %d moves' % n['moves'])


# Sandstorm and Snowscape (data/conditions.ts, read through READER_INPUTS) and Weather Ball (data/moves.ts): what the
# engine hard-codes about them, as normalised texts that must be in the pinned entries: the duration (5; 8 with the rock
# item, which is UNMODELED and so never held in a battle), the stat modifiers and their handler priority, the residual
# order, the damage, the upkeep line and the type and power of Weather Ball.
WEATHER_FACTS = (
    ('sandstorm', ['duration: 5,', "if (source?.hasItem('smoothrock')) { return 8; } return 5;",
                   'onModifySpDPriority: 10,',
                   "if (pokemon.hasType('Rock') && pokemon.effectiveWeather() === 'sandstorm') { return this.modify(spd, 1.5); }",
                   'onFieldResidualOrder: 1,',
                   "this.add('-weather', 'Sandstorm', '[upkeep]'); if (this.field.isWeather('sandstorm')) this.eachEvent('Weather');",
                   'onWeather(target) { this.damage(target.baseMaxhp / 16); },',
                   "this.add('-weather', 'Sandstorm', '[from] ability: ' + effect.name, `[of] ${source}`);",
                   "this.add('-weather', 'none');"]),
    ('snowscape', ['duration: 5,', "if (source?.hasItem('icyrock')) { return 8; } return 5;",
                   'onModifyDefPriority: 10,',
                   "if (pokemon.hasType('Ice') && pokemon.effectiveWeather() === 'snowscape') { return this.modify(def, 1.5); }",
                   'onFieldResidualOrder: 1,',
                   "this.add('-weather', 'Snowscape', '[upkeep]'); if (this.field.isWeather('snowscape')) this.eachEvent('Weather');",
                   "this.add('-weather', 'Snowscape', '[from] ability: ' + effect.name, `[of] ${source}`);",
                   "this.add('-weather', 'none');"]),
)
# Snowscape has no onWeather: it does no damage (the hail condition does, and the format does not have Hail).
WEATHER_ABSENT = (('snowscape', 'onWeather'),)
WEATHER_BALL_FACTS = ("case 'sandstorm': move.type = 'Rock'; break; case 'hail': case 'snowscape': move.type = 'Ice'; break;",
                      "case 'sandstorm': move.basePower *= 2; break; case 'hail': case 'snowscape': move.basePower *= 2; break;")


def check_weather_facts(conditions_ts, moves_ts):
    """Every fact of WEATHER_FACTS is in the pinned condition entry, the absent ones are not, and Weather Ball has the
    types and the doubling that the engine reads for every weather."""
    for cid, facts in WEATHER_FACTS + G32_WEATHER_FACTS:
        e = conditions_ts.entry(cid)
        if e is None:
            fail('condition %s not found' % cid)
        text = norm('\n'.join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('condition %s: the entry no longer has "%s"' % (cid, fact))
    for cid, name in WEATHER_ABSENT:
        if name in '\n'.join(conditions_ts.entry(cid)[2]):
            fail('condition %s now has %s' % (cid, name))
    e = moves_ts.entry('weatherball')
    if e is None:
        fail('move weatherball not found')
    text = norm('\n'.join(e[2]))
    for fact in WEATHER_BALL_FACTS:
        if norm(fact) not in text:
            fail('move weatherball: the entry no longer has "%s"' % fact)


# Step G15 (Psychic Terrain), what the engine hard-codes, as normalised texts that must be in the pinned entries:
#  - Expanding Force (data/moves.ts:4943-4965): 80 base power, a x1.5 chain modifier from the move's own onBasePower
#    (handler priority 0, so after the terrain's 5325/4096 at 6 and Helping Hand's 1.5 at 10) and the target class
#    allAdjacentFoes from onModifyMove, both for a user that isGrounded in Psychic Terrain; its base target is "normal";
#  - Psychic Terrain (data/moves.ts:14095-14150): the base power modifier and the priority block that Team C reads;
#  - Psychic Seed (data/items.ts:4903-4922) is Grassy Seed (data/items.ts:2595-2614) for the other terrain and the Special
#    Defense instead of the Defense: the same switch-in priority, onStart and onTerrainChange, one boost of +1.
EXPANDING_FORCE_FACTS = (
    'basePower: 80,', 'category: "Special",', 'accuracy: 100,', 'priority: 0,', 'target: "normal",', 'type: "Psychic",',
    "onBasePower(basePower, source) { if (this.field.isTerrain('psychicterrain') && source.isGrounded()) { "
    "this.debug('terrain buff'); return this.chainModify(1.5); } },",
    "onModifyMove(move, source, target) { if (this.field.isTerrain('psychicterrain') && source.isGrounded()) { "
    "move.target = 'allAdjacentFoes'; } },")
PSYCHIC_TERRAIN_FACTS = (
    'onBasePowerPriority: 6,',
    "onBasePower(basePower, attacker, defender, move) { if (move.type === 'Psychic' && attacker.isGrounded() && "
    "!attacker.isSemiInvulnerable()) { this.debug('psychic terrain boost'); return this.chainModify([5325, 4096]); } },",
    'duration: 5,')
SEED_PAIRS = (('psychicseed', 'psychicterrain', 'spd'), ('electricseed', 'electricterrain', 'def'),
              ('mistyseed', 'mistyterrain', 'spd'))


def check_g15_facts(moves_ts, items_ts):
    """Every fact of EXPANDING_FORCE_FACTS and PSYCHIC_TERRAIN_FACTS is in the pinned move entry, and each seed of
    SEED_PAIRS is Grassy Seed with its terrain and its stat (the engine reads one rule for the terrain seeds)."""
    for mid, facts in (('expandingforce', EXPANDING_FORCE_FACTS), ('psychicterrain', PSYCHIC_TERRAIN_FACTS)):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))
    grassy = items_ts.entry('grassyseed')
    if grassy is None:
        fail('item grassyseed not found')
    g = fields(grassy[2])
    for iid, terrain, stat in SEED_PAIRS:
        e = items_ts.entry(iid)
        if e is None:
            fail('item %s not found' % iid)
        f = fields(e[2])
        for name in ('onSwitchInPriority', 'onStart', 'onTerrainChange'):
            if name not in f or name not in g or norm(f[name][1]) != norm(g[name][1]).replace('grassyterrain', terrain):
                fail('item %s: %s is not that of grassyseed for %s' % (iid, name, terrain))
        if 'boosts' not in f or norm(f['boosts'][1]) != 'boosts: { %s: 1, },' % stat:
            fail('item %s: boosts is not %s +1' % (iid, stat))
        if set(f) != set(g):
            fail('item %s has other fields than grassyseed: %s' % (iid, sorted(set(f) ^ set(g))))


def check_g30_facts(abil_ts, champ_abil):
    """Every fact of G30_ABILITY_FACTS is in the pinned ability entry, whitespace aside, and the Champions mod has no
    entry of its own for it (an override would change what the engine reads)."""
    for aid, facts in G30_ABILITY_FACTS:
        e = abil_ts.entry(aid)
        if e is None:
            fail('ability %s not found' % aid)
        if champ_abil.entry(aid) is not None:
            fail('ability %s: the champions mod overrides the entry' % aid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('ability %s: the entry no longer has "%s"' % (aid, fact))


def check_g28_items(items_ts, only=None):
    """Step G28: the text of Expert Belt's onModifyDamage (G28_ITEM_FACTS) is in the pinned entry, whole."""
    for iid, facts in (G28_ITEM_FACTS if only is None else only):
        e = items_ts.entry(iid)
        if e is None:
            fail('item %s not found' % iid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('item %s: the entry no longer has "%s"' % (iid, fact))


def check_g34_facts(abil_ts, champ_abil, items_ts, champ_items):
    """Steps G34, G35, Mega batch 2 and G39: every fact of G34_ABILITY_FACTS, G35_ABILITY_FACTS, MEGA2_ABILITY_FACTS, G39_ABILITY_FACTS and G34_ITEM_FACTS is in the pinned entry, whitespace aside, and the
    Champions mod has no entry of its own for it (an override would change what the engine reads)."""
    for kind, facts_by_id, src, champ in (('ability', G34_ABILITY_FACTS + G35_ABILITY_FACTS + MEGA2_ABILITY_FACTS + G39_ABILITY_FACTS + G41_ABILITY_FACTS, abil_ts, champ_abil),
                                          ('item', G34_ITEM_FACTS, items_ts, champ_items)):
        for rid, facts in facts_by_id:
            e = src.entry(rid)
            if e is None:
                fail('%s %s not found' % (kind, rid))
            if champ.entry(rid) is not None:
                fail('%s %s: the champions mod overrides the entry' % (kind, rid))
            text = norm(chr(10).join(e[2]))
            for fact in facts:
                if norm(fact) not in text:
                    fail('%s %s: the entry no longer has "%s"' % (kind, rid, fact))


def check_g37_facts(abil_ts, champ_abil):
    """Step G37: the text of Toxic Debris that the engine hard-codes (G37_ABILITY_FACTS) is in the pinned entry, whitespace aside, and
    the Champions mod has no entry of its own for it."""
    for rid, facts in G37_ABILITY_FACTS:
        e = abil_ts.entry(rid)
        if e is None:
            fail('ability %s not found' % rid)
        if champ_abil.entry(rid) is not None:
            fail('ability %s: the champions mod overrides the entry' % rid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('ability %s: the entry no longer has "%s"' % (rid, fact))


def check_g32_entries(items_ts, champ_items, abil_ts, champ_abil, only=None):
    """Step G32: the ability and item entries that the turn code runs by id (G32_ENTRY_FACTS) have the pinned texts, whole;
    the Champions Eject Button is read from the mod's file. `only`: a tuple of such entries (the generator's tests)."""
    for kind, eid, champ, facts in (G32_ENTRY_FACTS + G33_ENTRY_FACTS if only is None else only):
        src = (champ_items if champ else items_ts) if kind == 'item' else (champ_abil if champ else abil_ts)
        e = src.entry(eid)
        if e is None:
            fail('%s %s not found' % (kind, eid))
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('%s %s: the entry no longer has "%s"' % (kind, eid, fact))


def check_g8_conditions(moves_ts, only=None):
    """The engine hard-codes the durations, orders and tests of the Throat Chop and Heal Block conditions (step G8), those of
    Aurora Veil (step G20) and the texts of G25_FACTS (the two terrains, Rising Voltage, Terrain Pulse): every one of them
    must be in the pinned entry, as one normalised text. `only`: a tuple of (move id, facts) to check instead of all of
    them (the generator's tests)."""
    for mid, facts in (G8_CONDITION_FACTS + G20_CONDITION_FACTS + G28_FACTS + G32_FACTS + G34_FACTS + G25_FACTS +
                       G33_FACTS + G38_FACTS + G39_FACTS + G37_FACTS if only is None else only):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the condition no longer has "%s"' % (mid, fact))


def build_pool(root, repo, dx):
    """The pool tables: the extended data as the prefix, then the new rows of step P1 (POOL_ITEMS, POOL_ABILITIES),
    then those of step G2 (G2_MOVES, G2_ITEMS, G2_ABILITIES and the formes of SETS_G2), then every other move, item,
    ability and forme of the legal pool (docs/research/expansion/data/legal_pool.json) in the file's order, then the
    family columns of every item and ability, the handler columns, and the legal moves and abilities of every forme,
    the prefix included. Cosmetic formes that the validator treats as their base forme are one row of the base forme
    plus a name alias."""
    dex, moves_ts = Source(root, 'data/pokedex.ts'), Source(root, 'data/moves.ts')
    champ_moves = Source(root, 'data/mods/champions/moves.ts')
    items_ts, champ_items = Source(root, 'data/items.ts'), Source(root, 'data/mods/champions/items.ts')
    abil_ts, champ_abil = Source(root, 'data/abilities.ts'), Source(root, 'data/mods/champions/abilities.ts')
    formats, learn = Source(root, 'data/mods/champions/formats-data.ts'), Source(root, 'data/mods/champions/learnsets.ts')
    legal = load_legal_pool(repo)
    check_g8_conditions(moves_ts)
    check_g15_facts(moves_ts, items_ts)
    check_g30_facts(abil_ts, champ_abil)
    check_g28_items(items_ts)
    check_g34_facts(abil_ts, champ_abil, items_ts, champ_items)
    check_g37_facts(abil_ts, champ_abil)
    check_g32_entries(items_ts, champ_items, abil_ts, champ_abil)
    check_weather_facts(Source(root, 'data/conditions.ts', READER_INPUTS), moves_ts)
    FLAGS_THAT_MATTER.clear()
    FLAGS_THAT_MATTER.update(prefix_flag_reads((items_ts, champ_items, abil_ts, champ_abil, moves_ts, champ_moves), dx)
                             - set(FLAG_BITS_C) - set(INERT_FLAG_READS))
    # The prefix rows keep the closure's "none" (0xFF) for the forme ids of a Mega link in the extended data; the pool
    # rows use None for it, because a forme id above 254 is real here.
    items, abilities = [dict(it, mega_base=None if it['mega_base'] == 0xFF else it['mega_base'],
                             mega_forme=None if it['mega_forme'] == 0xFF else it['mega_forme']) for it in dx['items']], \
        [dict(a) for a in dx['abilities']]

    def item_row(iid):
        if any(i['id'] == iid for i in items):
            fail('pool item %s is already in the tables' % iid)
        e = items_ts.entry(iid)
        if e is None:
            fail('item %s not found' % iid)
        text = '\n'.join(e[2])
        if 'isNonstandard' in text and champ_items.entry(iid) is None:
            fail('item %s is nonstandard and has no champions override' % iid)
        stone = re.search(r'megaStone: \{ "(.*?)": "(.*?)" \}', text)
        refs = [items_ts.ref(iid)] + ([champ_items.ref(iid)] if champ_items.entry(iid) is not None else [])
        stones = legal['stones'].get(iid, [])
        if stone and stones != [(toid(stone.group(1)), toid(stone.group(2)))]:
            fail('item %s: the Mega Stone of the pin and of the legal pool differ' % iid)
        return {'id': iid, 'name': re.search(r'name: "(.*?)"', text).group(1), 'refs': refs,
                'stone': stones[0] if stones else None, 'stones': stones, 'mega_base': None, 'mega_forme': None}

    for iid in POOL_ITEMS + G2_ITEMS:
        items.append(item_row(iid))
    for aid in POOL_ABILITIES + G2_ABILITIES:
        if any(a['id'] == aid for a in abilities):
            fail('pool ability %s is already in the extended tables' % aid)
        if abil_ts.entry(aid) is None:
            fail('ability %s not found' % aid)
        abilities.append({'id': aid, 'refs': [abil_ts.ref(aid)] + ([champ_abil.ref(aid)]
                                                                   if champ_abil.entry(aid) is not None else [])})
    n_steps = (len(items), len(abilities))
    # The second flags byte (step G8) of the prefix moves, read from the pin as the new rows are: the prefix rows
    # themselves (the CLOSURE and extended bytes) do not have it.
    moves = [dict(m, flags2=parse_move(m['id'], moves_ts, champ_moves, ext=True, pool=True)['flags2'])
             for m in dx['moves']]
    for mid in G2_MOVES:
        if any(m['id'] == mid for m in moves):
            fail('pool move %s is already in the extended tables' % mid)
        moves.append(parse_move(mid, moves_ts, champ_moves, pool=True))
    n_steps_moves = len(moves)
    move_index = {m['id']: i for i, m in enumerate(moves)}
    item_index = {it['id']: i for i, it in enumerate(items)}
    ability_index = {ab['id']: i for i, ab in enumerate(abilities)}
    formes = [dict(fo, mega_forme=None if fo['mega_forme'] == 0xFF else fo['mega_forme']) for fo in dx['formes']]
    forme_index = {fo['id']: i for i, fo in enumerate(formes)}
    first_new, n_items, n_abilities = len(formes), len(items), len(abilities)
    build_group(SETS_G2, items, item_index, abilities, ability_index, formes, forme_index, move_index, dex, items_ts,
                champ_items, abil_ts, champ_abil, formats, learn)
    if (len(items), len(abilities)) != (n_items, n_abilities):
        fail('a set of SETS_G2 holds an item or an ability that is not a pool row')
    for fo in formes[first_new:]:
        base = fo['id'] if not fo['is_mega'] else [s for s, _a, _i, _m, mg in SETS_G2 if mg == fo['id']][0]
        fo['base_forme'] = forme_index[base]
        fo['mega_forme'] = forme_index[fo['mega']] if fo['mega'] else None
        fo['mega_item'] = fo['set_item'] if (fo['mega'] or fo['is_mega']) else 0xFF

    # ---- the whole legal pool: every other move, item and ability, in the legal pool's order ----
    for mid in legal['move_order']:
        if mid not in move_index:
            moves.append(parse_pool_move(mid, moves_ts, champ_moves))
            move_index[mid] = len(moves) - 1
    for iid in legal['item_order']:
        if iid not in item_index:
            items.append(item_row(iid))
            item_index[iid] = len(items) - 1
    for aid in legal['ability_order']:
        if aid not in ability_index:
            if abil_ts.entry(aid) is None:
                fail('ability %s not found' % aid)
            abilities.append({'id': aid, 'refs': [abil_ts.ref(aid)] + ([champ_abil.ref(aid)]
                                                                       if champ_abil.entry(aid) is not None else [])})
            ability_index[aid] = len(abilities) - 1
    # Struggle is the one move of the tables that no forme learns, so it is not in the legal pool.
    if sorted(m['id'] for m in moves) != sorted(set(legal['move_order']) | {'struggle'}):
        fail('the move rows are not the legal pool plus Struggle')
    if {i['id'] for i in items} != legal['items'] or {a['id'] for a in abilities} != legal['abilities']:
        fail('the item or ability rows are not the legal pool')

    # ---- the formes: every selectable forme that is not a cosmetic copy, each followed by its Mega formes ----
    species = legal['species']
    megas_of = {}
    for sid in legal['species_order']:
        rec = species[sid]
        if rec['kind'] == 'mega':
            megas_of.setdefault(rec['holders'][0]['species'], []).append(rec)
    aliases = []

    def new_row(rec, is_mega, base_id=None):
        fid = rec['id']
        fo = parse_forme(fid, dex, formats)
        if fo['types'] != [TYPES.index(t) for t in rec['types']] + [0xFF] * (2 - len(rec['types'])) or \
                fo['base'] != [rec['base_stats'][k] for k in STATS]:
            fail('%s: the pokedex and the legal pool disagree on its types or base stats' % fid)
        if sorted(fo['abilities']) != sorted(rec['abilities_declared'].values()):
            fail('%s: the pokedex and the legal pool disagree on its declared abilities' % fid)
        legal_abilities = [a for a in fo['abilities'] if a in rec['abilities_legal']]
        if not legal_abilities:
            fail('%s has no legal ability' % fid)
        for aid in legal_abilities:
            if aid not in ability_index:
                fail('%s: the legal ability %s is not a pool row' % (fid, aid))
        fo['ability'] = ability_index[legal_abilities[0]]
        fo['set_moves'], fo['is_mega'] = [], 1 if is_mega else 0
        fo['mega_forme'] = None
        if is_mega:
            if fo['required_item'] != rec['required_item'] or fo['required_item'] not in item_index:
                fail('%s: its stone is not the stone of the legal pool' % fid)
            fo['gender_rule'] = formes[forme_index[base_id]]['gender_rule']
            fo['set_item'] = fo['mega_item'] = item_index[fo['required_item']]
            fo['base_forme'] = forme_index[base_id]
        else:
            fo['set_item'] = fo['mega_item'] = 0xFF
        fo['mega'] = None
        if rec.get('gender') is not None and fo['gender_rule'] != {'M': 1, 'F': 2, 'N': 3}[rec['gender']]:
            fail('%s: the pokedex and the legal pool disagree on its gender' % fid)
        return fo

    for sid in legal['species_order']:
        rec = species[sid]
        if rec['kind'] != 'selectable':
            continue
        if rec['mechanically_identical_to'] is not None:
            aliases.append((sid, rec['mechanically_identical_to']))
            continue
        if sid not in forme_index:
            fo = new_row(rec, False)
            forme_index[sid] = len(formes)
            fo['base_forme'] = len(formes)
            formes.append(fo)
        base_index = forme_index[sid]
        for mega in megas_of.get(sid, []):
            if mega['id'] in forme_index:
                continue
            mf = new_row(mega, True, sid)
            forme_index[mega['id']] = len(formes)
            formes.append(mf)
            if formes[base_index]['mega_forme'] is None:
                # The first Mega of the legal pool's order is the one the base forme's row links; a base forme
                # that already links one (Charizard-Mega-Y, Raichu-Mega-Y: the closure) keeps it.
                formes[base_index]['mega_forme'] = forme_index[mega['id']]
                formes[base_index]['mega_item'] = mf['mega_item']
    for alias, base in aliases:
        if base not in forme_index:
            fail('the alias %s names %s, which is no row' % (alias, base))
    for sid in legal['species_order']:
        rec = species[sid]
        if rec['kind'] == 'selectable' and rec['mechanically_identical_to'] is None and sid not in forme_index:
            fail('forme %s has no row' % sid)
        if rec['kind'] == 'mega' and sid not in forme_index:
            fail('Mega forme %s has no row' % sid)
    # A Mega Stone's item row links the first (base, Mega) pair of the stone.
    for it in items[len(dx['items']):]:
        if it['stone'] is not None:
            it['mega_base'] = forme_index[it['stone'][0]]
            it['mega_forme'] = forme_index[it['stone'][1]]
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

    # ---- what the tables model: the handler columns ----
    loaded = {'data/abilities.ts': abil_ts, 'data/items.ts': items_ts, 'data/moves.ts': moves_ts,
              'data/mods/champions/abilities.ts': champ_abil, 'data/mods/champions/items.ts': champ_items,
              'data/mods/champions/moves.ts': champ_moves, 'data/mods/champions/scripts.ts': Source(
                  root, 'data/mods/champions/scripts.ts')}
    readers = ReaderIndex(root, loaded)
    n_ext_items, n_ext_abilities = len(dx['items']), len(dx['abilities'])
    for i, (it, col) in enumerate(zip(items, item_family)):
        if i < n_ext_items or col['family'] != 'NONE' or it['id'] in ENGINE_ROWS['items']:
            feats = []  # the closure and Team C are code in the turn core; a family is a table rule
        else:
            feats = entry_features(items_ts, champ_items, it['id'], INERT_ITEM_KEYS, stone=it['stone'] is not None,
                                   readers=readers)
            if it['stone'] is not None:
                # Mega by stone (step G23-A): the Mega that a stone takes a base forme to is the base forme's own link or,
                # failing that, the stone's own row (its first pair): the engine finds it from (forme, stone)
                # (dfi_mega_of). A pair that neither names would be unreachable, and the build fails here.
                first = (forme_index[it['stones'][0][0]], forme_index[it['stones'][0][1]])
                for base, mega in it['stones']:
                    primary = formes[forme_index[base]]['mega_forme']
                    if primary != forme_index[mega] and (forme_index[base], forme_index[mega]) != first:
                        fail('stone %s: the Mega %s of %s is neither the link of its base forme nor the first pair of '
                             'the stone' % (it['id'], mega, base))
        it['unmodeled'] = sorted(set(feats))
    for i, (ab, col) in enumerate(zip(abilities, ability_family)):
        if i < n_ext_abilities or col['family'] != 'NONE' or ab['id'] in ENGINE_ROWS['abilities']:
            feats = []
        else:
            feats = entry_features(abil_ts, champ_abil, ab['id'], INERT_ABILITY_KEYS, readers=readers)
        ab['unmodeled'] = sorted(set(feats))
    for m in moves:
        m.setdefault('unmodeled', [])
    for fo in formes:
        fo.setdefault('unmodeled', [])
    legal_formes = forme_legal(formes, [m['id'] for m in moves], [a['id'] for a in abilities], learn,
                               legal['species'], abil_ts, champ_abil)
    chart, immunity = type_chart(Source(root, 'data/typechart.ts'), STATUS_IMMUNITY_P, IGNORED_TYPE_KEYS_P)
    if chart != dx['chart'] or [v & ~SAND_IMMUNITY for v in immunity] != dx['immunity']:
        fail('the pool type chart and immunity bits are not the extended ones plus Sandstorm')
    if [t for t, v in zip(TYPES, immunity) if v & SAND_IMMUNITY] != SAND_IMMUNE_TYPES:
        fail('the types immune to Sandstorm are not %s' % SAND_IMMUNE_TYPES)
    # Step G30: the engine reads the powder immunity of the types as the Grass type (a key of the chart that no column holds)
    tc = Source(root, 'data/typechart.ts')
    powder = [t for t in TYPES if re.search(r'^			powder: 3,', chr(10).join(tc.entry(t.lower())[2]), re.M)]
    if powder != POWDER_IMMUNE_TYPES:
        fail('the types immune to powder moves are not %s' % POWDER_IMMUNE_TYPES)
    # A Pokemon with Heal Block and Throat Chop has two BeforeMove handlers of equal priority whose shuffle (a draw)
    # trace_to_c.py drops, which is right while no move is stopped by both: none may have the sound and the heal flags.
    for m in moves:
        if m['flags2'] & FLAGS2_BITS['sound'] and m['flags2'] & FLAGS2_BITS['heal']:
            fail('move %s has the sound and the heal flags: the BeforeMove tie of Throat Chop and Heal Block would show' % m['id'])
    d = dict(dx, immunity=immunity, formes=formes, moves=moves, items=items, abilities=abilities,
             item_family=item_family,
             ability_family=ability_family, forme_legal=legal_formes, aliases=aliases, legal_counts=legal['counts'],
             flags_that_matter=sorted(FLAGS_THAT_MATTER), steps=dict(items=n_steps[0], abilities=n_steps[1],
                                                                    moves=n_steps_moves))
    for flag, owner in INERT_FLAG_READS.items():
        if owner is not None and not moves[move_index[owner]]['unmodeled']:
            fail('the move %s is modelled, so the flag %s that a modelled row reads now matters' % (owner, flag))
    check_bounds(d, repo)
    return d


def family_bytes(d):
    """The family columns as they follow the rows in the canonical pool bytes: per item, then per ability, the family
    id and the parameter."""
    b = bytearray()
    for col in d['item_family'] + d['ability_family']:
        b.extend([col['family_id'], col['param']])
    return bytes(b)


def handler_of(row):
    """The handler column value of an item or ability: 1 (UNMODELED) iff it has an unmodelled feature."""
    return HANDLER_IDS.index('UNMODELED') if row['unmodeled'] else HANDLER_IDS.index('NONE')


def handler_bytes(d):
    """The handler columns: per item, then per ability, 0 (modelled) or 1 (UNMODELED)."""
    return bytes([handler_of(r) for r in d['items']] + [handler_of(r) for r in d['abilities']])


def forme_legal_bytes(d):
    """The legal moves and abilities of the formes in the canonical pool bytes: per forme, in id order, the learnable
    bitset, the number of legal abilities and the ability ids (unused slots 0xFF)."""
    b = bytearray()
    for fl in d['forme_legal']:
        b.extend(fl['learnable'])
        b.append(len(fl['abilities']))
        b.extend(fl['abilities'] + [0xFF] * (FORME_ABILITIES_MAX - len(fl['abilities'])))
    return bytes(b)


def forme_id16(v):
    """A forme id field of a pool row: 0xFFFF for none."""
    return 0xFFFF if v is None else v


def flags2_bytes(d):
    """The second flags byte of every move, in id order, in the canonical pool bytes (step G8; bit 4 is step G10)."""
    return bytes(m['flags2'] for m in d['moves'])


def heal_bytes(d):
    """The heal fraction of every move, in id order, in the canonical pool bytes (step G10): numerator and
    denominator, 0 and 0 for a move that does not heal by a fraction."""
    b = bytearray()
    for m in d['moves']:
        b.extend(m.get('heal', [0, 0]))
    return bytes(b)


def static_flags_bytes(d):
    """The static flags of every move (decision 0020), in id order, 4 bytes little-endian each, in the canonical pool bytes."""
    b = bytearray()
    for m in d['moves']:
        b.extend(m['static_flags'].to_bytes(4, 'little'))
    return bytes(b)


def static_hits_bytes(d):
    """The hit counts (minimum, maximum) of every move (decision 0020), in id order, in the canonical pool bytes."""
    b = bytearray()
    for m in d['moves']:
        b.extend(m['hits'])
    return bytes(b)


def canonical_pool(d):
    """The canonical pool bytes hashed into the context fingerprint of the POOL kinds (the pool layout): the six
    counts, a row per forme (the forme links are u16: the pool has more than 255 formes), per move (the closure's
    29 bytes), per item (two u16 forme links), the type chart, immunity and natures of the closure, then the family
    columns, the handler columns and the legal moves and abilities of the formes."""
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
        b.extend([f['ability'], f['gender_rule'], f['is_mega']])
        u16(f['base_forme'])
        u16(forme_id16(f['mega_forme']))
        b.extend([f['mega_item'], f['set_item'], len(f['set_moves'])])
        b.extend(f['set_moves'] + [0] * (4 - len(f['set_moves'])))
    for m in d['moves']:
        b.extend([m['type'], m['category'], m['base_power'], m['accuracy'], m['pp_base'], m['pp_max'], m['priority'],
                  m['target_class'], m['crit_ratio'], m['flags'], m['recoil'][0], m['recoil'][1], m['drain'][0],
                  m['drain'][1], m['sec_chance'], m['sec_kind'], m['sec_param'], m['boost_role']])
        b.extend(v + 6 for v in m['boosts'])
        b.extend([m['primary_status'], m['side_condition'], m['pseudo_weather'], m['special']])
    for it in d['items']:
        u16(forme_id16(it['mega_base']))
        u16(forme_id16(it['mega_forme']))
    for row in d['chart']:
        b.extend(row)
    b.extend(d['immunity'])
    for n in d['natures']:
        b.extend([n['plus'], n['minus']])
    return bytes(b) + family_bytes(d) + handler_bytes(d) + forme_legal_bytes(d) + flags2_bytes(d) + heal_bytes(d) +         static_flags_bytes(d) + static_hits_bytes(d)


def closure_projection(rows, key):
    """The closure layout's view of pool rows: a forme link of None is the closure's 0xFF."""
    if key == 'formes':
        return [dict(r, mega_forme=0xFF if r['mega_forme'] is None else r['mega_forme']) for r in rows]
    if key == 'items':
        return [dict(r, mega_base=0xFF if r['mega_base'] is None else r['mega_base'],
                     mega_forme=0xFF if r['mega_forme'] is None else r['mega_forme']) for r in rows]
    return rows


def ext_prefix(dp, dx):
    """The extended projection of the pool data: its first extended-count rows, every immunity bit."""
    return {'formes': closure_projection(dp['formes'][:len(dx['formes'])], 'formes'), 'moves': dp['moves'][:len(dx['moves'])],
            'items': closure_projection(dp['items'][:len(dx['items'])], 'items'),
            'abilities': dp['abilities'][:len(dx['abilities'])],
            'chart': dp['chart'], 'immunity': [v & ~SAND_IMMUNITY for v in dp['immunity']], 'natures': dp['natures']}


def check_pool_prefix(dp, dx, dc):
    """Decision 0015 section 2: every extended row, and so every closure row, is the pool row of its id."""
    prefix = ext_prefix(dp, dx)
    for key in ('formes', 'moves', 'items', 'abilities'):
        want = dx[key]
        got = prefix[key]
        # The pool rows carry the unmodelled lists; the extended rows have none.
        if [{k: v for k, v in r.items() if k != 'unmodeled'} for r in got] != want:
            fail('pool %s do not start with the extended %s' % (key, key))
    for key in ('chart', 'immunity', 'natures'):
        got = [v & ~SAND_IMMUNITY for v in dp[key]] if key == 'immunity' else dp[key]
        if got != dx[key]:
            fail('the pool %s differ from the extended ones' % key)
    if canonical(prefix) != canonical(dx):
        fail('the pool tables do not start with the extended tables')
    if canonical(closure_prefix(prefix, dc)) != canonical(dc):
        fail('the pool tables do not start with the closure tables')
    if len(dp['item_family']) != len(dp['items']) or len(dp['ability_family']) != len(dp['abilities']):
        fail('a family column does not have one row per id')
    if len(dp['forme_legal']) != len(dp['formes']):
        fail('the legal moves and abilities do not have one row per forme')
    # The rows of the steps (P1 and G2) are the rows of the committed tables of those steps: their first values are
    # checked by tests/test_pool_tables.c (literal values read from the pin), so here only that they are in place.
    if len(dp['moves']) < dp['steps']['moves'] or len(dp['items']) < dp['steps']['items'] or \
            len(dp['abilities']) < dp['steps']['abilities']:
        fail('the whole-pool rows are fewer than the rows of the steps')


def check_names(dp):
    """The names of the data query API are the ids of the rows: Showdown ids (toID), never empty and unique per
    table, so that a name finds exactly one id. The aliases of the cosmetic formes are Showdown ids too, and are
    neither a row's name nor each other's."""
    for key in ('formes', 'moves', 'items', 'abilities', 'natures'):
        names = [r['id'] for r in dp[key]]
        if any(re.fullmatch(r'[a-z0-9]+', n) is None for n in names):
            fail('a %s id is not a Showdown id (lower-case letters and digits)' % key)
        if len(set(names)) != len(names):
            fail('two %s have the same id' % key)
    alias_names = [a for a, _b in dp['aliases']]
    if len(set(alias_names)) != len(alias_names) or set(alias_names) & {r['id'] for r in dp['formes']}:
        fail('an alias is a name twice or the name of a row')
    if any(re.fullmatch(r'[a-z0-9]+', n) is None for n in alias_names):
        fail('an alias is not a Showdown id')


def feature_summary(d):
    """Counts for the report: rows and unmodelled rows per table, and the number of rows that each kind of feature
    ("callback", "field", "target", ...) appears in."""
    out = {}
    for key, rows in (('moves', d['moves']), ('items', d['items']), ('abilities', d['abilities'])):
        kinds = {}
        for r in rows:
            for kind in sorted({f.split(' ')[0] for f in r['unmodeled']}):
                kinds[kind] = kinds.get(kind, 0) + 1
        out[key] = {'rows': len(rows), 'unmodeled': sum(1 for r in rows if r['unmodeled']), 'by_kind': kinds}
    return out


def render_pool(dp, dx):
    check_names(dp)
    can = canonical_pool(dp)
    digest = hashlib.sha256(can).hexdigest()
    nx = {key: len(dx[key]) for key in ('formes', 'moves', 'items', 'abilities')}

    def defines(prefix, rows, start):
        return '\n'.join('#define %s_%s %du' % (prefix, r['id'].upper(), i) for i, r in enumerate(rows) if i >= start)

    new_special = '\n'.join('#define DFI_SPECIAL_%s %du' % (n, i) for i, n in enumerate(SPECIAL_IDS_P)
                            if i >= len(SPECIAL_IDS_C))
    new_special += '''

/* ---- the second flags byte of every move (step G8: the general byte for the flags that the first one has no room
 * for; bits 4 to 128 are free) and the secondary kinds that it comes with ---- */
#define DFI_MOVE_FLAG2_SOUND 1u /* data/moves.ts flags.sound: Throat Chop bars these moves */
#define DFI_MOVE_FLAG2_HEAL 2u  /* flags.heal: Heal Block bars these moves */
#define DFI_MOVE_FLAG2_THAWS_TARGET 4u /* thawsTarget (step G10): the move cures a frozen target after the secondaries */
#define DFI_MOVE_FLAG2_RECHARGE 8u /* flags.recharge with self.volatileStatus mustrecharge (step G17): the user must recharge after a hit */
#define DFI_MOVE_FLAG2_POWDER 16u /* flags.powder (step G30): a Grass type, Overcoat and Safety Goggles are immune to the move */
#define DFI_MOVE_FLAG2_PUNCH 32u /* flags.punch (step G34): Iron Fist boosts these moves (internal; the public static flag is not read) */
#define DFI_MOVE_FLAG2_SLICING 64u /* flags.slicing (step G34): Sharpness boosts these moves */
#define DFI_BOOST_ROLE_PRIMARY_ALLY 4u /* step G19: a status move whose primary boosts go to the adjacent ally (Coaching) */
#define DFI_BOOST_ROLE_SECONDARY_SELF 5u /* step G28: the secondary's roll gives these boosts to the user (Ancient Power) */
#define DFI_BOOST_ROLE_PRIMARY_TARGET 6u /* step G39: a status move whose primary boosts go to its one target (Charm, Fake Tears) */
#define DFI_SECONDARY_SELF_BOOST 7u /* step G28: boosts[] applied to the user with the secondary roll */
#define DFI_SECONDARY_LOCKOUT 5u    /* chance 100: the target may not use sound moves (Throat Chop) */
#define DFI_SECONDARY_HEAL_BLOCK 6u /* chance 100: the target may not heal (Psychic Noise) */

/* ---- the immunity bit of the pool (the extended bits are 1 to 16): the type chart's `sandstorm: 3` of Rock, Ground
 * and Steel. It is in the pool's immunity bytes only; the closure and extended canonical bytes mask it out. ---- */
#define DFI_IMMUNE_SAND 32u'''
    new_targets = '\n'.join('#define DFI_TARGET_CLASS_%s %du' % (n, v) for v, n in sorted(TARGET_CLASS_POOL_NAMES.items()))
    h = '''#ifndef DUOFORGE_DATA_POOL_TABLES_H
#define DUOFORGE_DATA_POOL_TABLES_H
/*
 * GENERATED by tools/datagen/gen_closure.py --pool -- do not edit.
 *
 * The pool tables of decision 0015: the extended tables (the closure tables
 * followed by Team C, decision 0009) unchanged as the prefix, then the rows
 * that the steps of the content expansion add (P1, G2) and then a row for
 * every other move, item, ability and forme of the legal pool of the format
 * (docs/research/expansion/data/legal_pool.json, the output of the pinned
 * TeamValidator), read from Pokemon Showdown %s (the input files of
 * closure_tables.h). Every id below an extended count (DFI_EXT_FORME_COUNT,
 * DFI_EXT_MOVE_COUNT, DFI_EXT_ITEM_COUNT, DFI_EXT_ABILITY_COUNT) is the
 * extended table's and its row equals the extended row. Natures and the type
 * chart are the closure's.
 *
 * The forme and item rows of the pool are their own types (dfi_pool_forme_data,
 * dfi_pool_item_data): the pool has more than 255 formes, so a forme link is a
 * u16 here (DFI_FORME_NONE for none). The extended and closure rows keep their
 * u8 types and their bytes.
 *
 * The family columns are arrays of their own. They hold, for every item and
 * ability (the prefix included), its family and the parameter the family rule
 * reads; each is the result of one strict pattern over the pinned handler. They
 * are part of the canonical pool bytes and so of the pool table hash, and not of
 * the closure or extended bytes. A family column says what an id is, not that
 * the engine implements it: the support manifest decides that.
 *
 * What the tables model, and what they do not (decision 0015 section 4.2): a
 * move, ability or item row that has a callback, a field, a target class or a
 * flag that the tables do not model carries the UNMODELED handler (the move's
 * special column; the handler column of an item or an ability) and a list of
 * those features (dfi_pool_*_unmodeled; NULL for a modelled row). Such a row is
 * never marked in the support manifest, so setup refuses it with E_UNSUPPORTED.
 *
 * Data only. An id names a record; every effect needs a typed handler in C
 * and an entry in the support manifest before a battle may use it.
 */
#include <stddef.h>
#include <stdint.h>

#include "data/extended_tables.h"

/* ---- pool formes (appended after the extended ones): step G2, then the legal pool ---- */
%s
#define DFI_POOL_FORME_COUNT %du
#define DFI_FORME_NONE 0xFFFFu /* a forme link that points nowhere */

/* ---- pool moves (appended after the extended ones): step G2, then the legal pool ---- */
%s
#define DFI_POOL_MOVE_COUNT %du

/* ---- handlers new in the pool tables: the value of the special column of the moves that have a callback or a
 * field that the columns do not model. The engine refuses every one of them, and so does the support manifest,
 * which leaves the move unmarked. UNMODELED is the handler of every move of the pool that has any unmodelled
 * feature (dfi_pool_move_unmodeled lists them). ---- */
%s

/* ---- target classes of the pool beyond the public DUOFORGE_TARGET_CLASS_* values (1 to 9) and Struggle's 10:
 * encoded, not implemented by the turn code, so a move with one is UNMODELED. ---- */
%s

/* ---- pool abilities (appended after the extended ones): step P1, step G2, then the legal pool ---- */
%s
#define DFI_POOL_ABILITY_COUNT %du

/* ---- pool items (appended after the extended ones): step P1 (type boosters, then resist berries), step G2, then
 * the legal pool ---- */
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
#define DFI_FAMILY_WEATHER_SAND 3u
#define DFI_FAMILY_WEATHER_SNOW 4u
#define DFI_FAMILY_TERRAIN_GRASSY 1u
#define DFI_FAMILY_TERRAIN_PSYCHIC 2u
#define DFI_FAMILY_TERRAIN_ELECTRIC 3u
#define DFI_FAMILY_TERRAIN_MISTY 4u
#define DFI_FAMILY_PARAM_NONE 0xFFu

/* ---- handler columns of the items and abilities: NONE for a row that the tables model (the closure and Team C
 * rows are code in the turn core, a family member is a table rule, an inert entry has nothing to model) and
 * UNMODELED for a row with any callback, condition or field that they do not model. ---- */
#define DFI_HANDLER_NONE 0u
#define DFI_HANDLER_UNMODELED 1u

typedef struct dfi_item_family {
    uint8_t family; /* DFI_ITEM_FAMILY_* */
    uint8_t type;   /* the type of the family rule (DFI_TYPE_*), DFI_FAMILY_PARAM_NONE without a family */
} dfi_item_family;

typedef struct dfi_ability_family {
    uint8_t family; /* DFI_ABILITY_FAMILY_* */
    uint8_t param;  /* ATE, PINCH: DFI_TYPE_*; WEATHER_SETTER: DFI_FAMILY_WEATHER_*; TERRAIN_SETTER: DFI_FAMILY_TERRAIN_* */
} dfi_ability_family;

/* The row of a forme. Its layout up to gender_rule is that of dfi_forme_data; the forme links are u16. A base forme
 * of the pool outside the closure and Team C has no set of its own: set_item is DFI_CLOSURE_NONE and set_move_count
 * 0, its ability is its first legal ability, and under the POOL kinds its moves and abilities come from
 * dfi_pool_forme_legal. */
typedef struct dfi_pool_forme_data {
    uint16_t dex_num;
    uint16_t weight_hg;
    uint8_t types[2]; /* second is DFI_CLOSURE_NONE for a single type */
    uint8_t base[DFI_STAT_COUNT];
    uint8_t ability;     /* the set's ability (the first legal one outside the closure and Team C); for a Mega forme its own */
    uint8_t gender_rule; /* DFI_GENDER_RULE_* */
    uint8_t is_mega;
    uint16_t base_forme; /* the forme itself for a base forme */
    uint16_t mega_forme; /* the Mega forme this base forme links, DFI_FORME_NONE if none */
    uint8_t mega_item;   /* the stone of the linked Mega (a Mega forme: its own stone), or DFI_CLOSURE_NONE */
    uint8_t set_item;    /* the item of the set in decision 0004 and 0009; DFI_CLOSURE_NONE for the rest */
    uint8_t set_move_count;
    uint8_t set_moves[4]; /* the moves of the set (move ids below 255) */
} dfi_pool_forme_data;

typedef struct dfi_pool_item_data {
    uint16_t mega_base;  /* the forme that can hold it as a Mega Stone (the first of its pairs), or DFI_FORME_NONE */
    uint16_t mega_forme; /* the Mega forme of that pair */
} dfi_pool_item_data;

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

/* The cosmetic formes that the validator treats as their base forme (Vivillon patterns, Alcremie creams, ...): no
 * row of their own, the name of the base forme's row instead. They are in no canonical bytes. */
#define DFI_POOL_ALIAS_COUNT %du
typedef struct dfi_pool_alias {
    const char *name;  /* the Showdown id of the cosmetic forme */
    uint16_t forme;    /* the row it stands for */
} dfi_pool_alias;

extern const dfi_pool_forme_data dfi_pool_formes[DFI_POOL_FORME_COUNT];
extern const dfi_move_data dfi_pool_moves[DFI_POOL_MOVE_COUNT];
extern const dfi_pool_item_data dfi_pool_items[DFI_POOL_ITEM_COUNT];
extern const uint8_t dfi_pool_type_immunity[DFI_TYPE_COUNT]; /* DFI_IMMUNE_* bits */
extern const dfi_item_family dfi_pool_item_family[DFI_POOL_ITEM_COUNT];
extern const dfi_ability_family dfi_pool_ability_family[DFI_POOL_ABILITY_COUNT];
extern const uint8_t dfi_pool_item_handler[DFI_POOL_ITEM_COUNT];       /* DFI_HANDLER_* */
extern const uint8_t dfi_pool_ability_handler[DFI_POOL_ABILITY_COUNT]; /* DFI_HANDLER_* */
extern const dfi_forme_legal dfi_pool_forme_legal[DFI_POOL_FORME_COUNT];
/* The second flags byte of every move (DFI_MOVE_FLAG2_*), by move id; the last part of the canonical pool bytes. */
extern const uint8_t dfi_pool_move_flags2[DFI_POOL_MOVE_COUNT];
/* The heal fraction of every move (step G10, heal: [numerator, denominator] in the pin; 0 and 0 for none), by move id;
 * the very last part of the canonical pool bytes. */
extern const uint8_t dfi_pool_move_heal[DFI_POOL_MOVE_COUNT][2];
/* Decision 0020: the static flags of every move (DUOFORGE_MOVE_STATIC_FLAG_*: one bit per Showdown flag name, plus
 * POWER_RULE for a move with a basePowerCallback) and its hit counts (the pin's multihit; 1 and 1 for a single hit), by
 * move id, for every row, modelled or not. The engine reads neither: they are data for duoforge_data_move_static, and the
 * last parts of the canonical pool bytes. */
extern const uint32_t dfi_pool_move_static_flags[DFI_POOL_MOVE_COUNT];
extern const uint8_t dfi_pool_move_static_hits[DFI_POOL_MOVE_COUNT][2];
extern const dfi_pool_alias dfi_pool_forme_aliases[DFI_POOL_ALIAS_COUNT];

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

/* ---- the unmodelled features of a row (not in any hash) ----
 * NULL for a row that the tables model; otherwise one string of the features, separated by "; ": "callback onHit",
 * "field multihit", "secondary", "target allAdjacent", "flag sound", ... They are what a step that models the row has
 * to account for, and the data of the generated comments of the rows. */
extern const char *const dfi_pool_move_unmodeled[DFI_POOL_MOVE_COUNT];
extern const char *const dfi_pool_item_unmodeled[DFI_POOL_ITEM_COUNT];
extern const char *const dfi_pool_ability_unmodeled[DFI_POOL_ABILITY_COUNT];

/* SHA-256 of the canonical pool bytes (written by the generator). */
#define DFI_POOL_CANONICAL_SIZE %du
extern const uint8_t dfi_pool_table_hash[32];
/* The canonical bytes of the closure layout over the first `formes`, `moves`,
 * `items` and `abilities` rows of the tables above, with every immunity byte
 * masked by `immunity_mask`; natures and the type chart are the closure's.
 * The family and handler columns are not part of them. Returns the size, or 0
 * if a count exceeds its table or capacity is too small, or if a row has a
 * forme link that the closure layout's byte cannot hold (a link above 254).
 * With the closure counts and the closure's immunity bits these are exactly
 * the closure's canonical bytes; with the extended counts and the extended
 * immunity bits (every bit but DFI_IMMUNE_SAND), the extended ones. */
size_t dfi_pool_canonical_bytes_of(uint8_t *out, size_t capacity, uint32_t formes, uint32_t moves, uint32_t items,
                                   uint32_t abilities, uint32_t immunity_mask);
/* The canonical pool bytes (the pool layout): the six counts; per forme the
 * closure's 24 bytes with the two forme links as u16; per move the closure's
 * 29 bytes; per item the two forme links as u16; the type chart, the
 * immunity bits and the natures; then the family column of every item and of
 * every ability (family, parameter), the handler column of every item and of
 * every ability, and for every forme its learnable bytes, ability count and
 * ability ids. */
size_t dfi_pool_canonical_bytes(uint8_t *out, size_t capacity);

#endif
''' % (PIN, defines('DFI_FORME', dp['formes'], nx['formes']), len(dp['formes']),
       defines('DFI_MOVE', dp['moves'], nx['moves']), len(dp['moves']), new_special, new_targets,
       defines('DFI_ABILITY', dp['abilities'], nx['abilities']), len(dp['abilities']),
       defines('DFI_ITEM', dp['items'], nx['items']), len(dp['items']),
       (len(dp['moves']) + 7) // 8, FORME_ABILITIES_MAX, len(dp['aliases']), len(can))

    def arr(vals):
        return '{' + ', '.join('%du' % v for v in vals) + '}'

    def link(v):
        return 'DFI_FORME_NONE' if v is None else '%du' % v

    def note(row):
        return ('  [unmodelled: %s]' % '; '.join(row['unmodeled'])) if row['unmodeled'] else ''

    c = ['#include <stdbool.h>', '', '#include "data/pool_tables.h"', '',
         '/* GENERATED by tools/datagen/gen_closure.py --pool -- do not edit. Showdown %s. */' % PIN, '',
         'const dfi_pool_forme_data dfi_pool_formes[DFI_POOL_FORME_COUNT] = {']
    for f in dp['formes']:
        c.append('    /* %s -- %s */' % (f['name'], f['ref']))
        c.append('    {%du, %du, %s, %s, %du, %du, %du, %du, %s, %du, %du, %du, %s},' % (
            f['dex_num'], f['weight_hg'], arr(f['types']), arr(f['base']), f['ability'], f['gender_rule'],
            f['is_mega'], f['base_forme'], link(f['mega_forme']), f['mega_item'], f['set_item'], len(f['set_moves']),
            arr(f['set_moves'] + [0] * (4 - len(f['set_moves'])))))
    c += ['};', '', 'const dfi_move_data dfi_pool_moves[DFI_POOL_MOVE_COUNT] = {']
    for m in dp['moves']:
        c.append('    /* %s -- %s%s */' % (m['name'], ', '.join(m['refs']), note(m)))
        c.append('    {%du, %du, %du, %du, %du, %du, %du, %du, %du, %du, %s, %s, %du, %du, %du, %du, %s, %du, %du, %du, %du},' % (
            m['type'], m['category'], m['base_power'], m['accuracy'], m['pp_base'], m['pp_max'], m['priority'],
            m['target_class'], m['crit_ratio'], m['flags'], arr(m['recoil']), arr(m['drain']), m['sec_chance'],
            m['sec_kind'], m['sec_param'], m['boost_role'], arr([v + 6 for v in m['boosts']]), m['primary_status'],
            m['side_condition'], m['pseudo_weather'], m['special']))
    c += ['};', '', 'const dfi_pool_item_data dfi_pool_items[DFI_POOL_ITEM_COUNT] = {']
    for it in dp['items']:
        c.append('    /* %s -- %s%s */' % (it['name'], ', '.join(it['refs']), note(it)))
        c.append('    {%s, %s},' % (link(it['mega_base']), link(it['mega_forme'])))
    c += ['};', '', '/* Abilities carry no table data but their columns. Provenance of the pool abilities:']
    for a in dp['abilities'][nx['abilities']:]:
        c.append(' *   %s -- %s%s' % (a['id'], ', '.join(a['refs']), note(a)))
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
    c += ['};', '', '/* Handler columns: what the tables model (decision 0015 section 4.2). */',
          'const uint8_t dfi_pool_item_handler[DFI_POOL_ITEM_COUNT] = {']
    for it in dp['items']:
        c.append('    [DFI_ITEM_%s] = DFI_HANDLER_%s,' % (it['id'].upper(), HANDLER_IDS[handler_of(it)]))
    c += ['};', '', 'const uint8_t dfi_pool_ability_handler[DFI_POOL_ABILITY_COUNT] = {']
    for ab in dp['abilities']:
        c.append('    [DFI_ABILITY_%s] = DFI_HANDLER_%s,' % (ab['id'].upper(), HANDLER_IDS[handler_of(ab)]))
    c += ['};', '', '/* The moves and abilities each forme may have (decision 0015 section 2). */',
          'const dfi_forme_legal dfi_pool_forme_legal[DFI_POOL_FORME_COUNT] = {']
    for fo, fl in zip(dp['formes'], dp['forme_legal']):
        for line in wrap_names('%s -- abilities:' % fo['name'], [dp['abilities'][a]['id'] for a in fl['abilities']]):
            c.append('    /* ' + line + ' */')
        c.append('    /* %d learnable moves */' % len(fl['moves']))
        slots = ['DFI_ABILITY_' + dp['abilities'][a]['id'].upper() for a in fl['abilities']]
        slots += ['DFI_CLOSURE_NONE'] * (FORME_ABILITIES_MAX - len(slots))
        c.append('    [DFI_FORME_%s] = {{%s}, %du, {%s}},' % (
            fo['id'].upper(), ', '.join('0x%02xu' % b for b in fl['learnable']), len(fl['abilities']), ', '.join(slots)))
    c += ['};', '', '/* The second flags byte of every move (data/moves.ts flags.sound and flags.heal), by move id. */',
          'const uint8_t dfi_pool_move_flags2[DFI_POOL_MOVE_COUNT] = {']
    for m in dp['moves']:
        names = [n for n, bit in (('DFI_MOVE_FLAG2_SOUND', 1), ('DFI_MOVE_FLAG2_HEAL', 2),
                                  ('DFI_MOVE_FLAG2_THAWS_TARGET', 4), ('DFI_MOVE_FLAG2_RECHARGE', 8),
                                  ('DFI_MOVE_FLAG2_POWDER', 16), ('DFI_MOVE_FLAG2_PUNCH', 32),
                                  ('DFI_MOVE_FLAG2_SLICING', 64)) if m['flags2'] & bit]
        c.append('    [DFI_MOVE_%s] = %s, /* %s */' % (m['id'].upper(), ' | '.join(names) if names else '0u', m['name']))
    c += ['};', '', '/* The heal fraction of the moves that heal by one (step G10): numerator, denominator. */',
          'const uint8_t dfi_pool_move_heal[DFI_POOL_MOVE_COUNT][2] = {']
    for m in dp['moves']:
        if m.get('heal', [0, 0]) != [0, 0]:
            c.append('    [DFI_MOVE_%s] = {%du, %du}, /* %s */' % (m['id'].upper(), m['heal'][0], m['heal'][1], m['name']))
    c += ['};', '', '/* The static flags of every move (decision 0020): the public bit set, see duoforge.h. */',
          'const uint32_t dfi_pool_move_static_flags[DFI_POOL_MOVE_COUNT] = {']
    for m in dp['moves']:
        if m['static_flags']:
            c.append('    [DFI_MOVE_%s] = 0x%xu, /* %s */' % (m['id'].upper(), m['static_flags'], m['name']))
    c += ['};', '', '/* The hit counts of every move (decision 0020): minimum and maximum, 1 and 1 for a single hit. */',
          'const uint8_t dfi_pool_move_static_hits[DFI_POOL_MOVE_COUNT][2] = {']
    for m in dp['moves']:
        c.append('    [DFI_MOVE_%s] = {%du, %du}, /* %s */' % (m['id'].upper(), m['hits'][0], m['hits'][1], m['name']))
    c += ['};', '', '/* Cosmetic formes: a name for the row of the base forme (decision 0015 section 4.2). */',
          'const dfi_pool_alias dfi_pool_forme_aliases[DFI_POOL_ALIAS_COUNT] = {']
    for alias, base in dp['aliases']:
        c.append('    {"%s", DFI_FORME_%s},' % (alias, base.upper()))
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
    c += ['};', '', '/* The unmodelled features of the rows that have any (NULL: modelled). */']
    for what, rows, table in (('move', dp['moves'], 'MOVE'), ('item', dp['items'], 'ITEM'),
                              ('ability', dp['abilities'], 'ABILITY')):
        c.append('const char *const dfi_pool_%s_unmodeled[DFI_POOL_%s_COUNT] = {' % (what, table))
        for r in rows:
            if r['unmodeled']:
                c.append('    [DFI_%s_%s] = "%s",' % (table, r['id'].upper(), '; '.join(r['unmodeled'])))
        c += ['};', '']
    c += ['const uint8_t dfi_pool_table_hash[32] = {']
    hb = bytes.fromhex(digest)
    for i in range(0, 32, 8):
        c.append('    ' + ', '.join('0x%02xu' % x for x in hb[i:i + 8]) + ',')
    c += ['};', '', r'''static size_t dfi_pool_put_u16(uint8_t *out, size_t n, uint32_t v)
{
    out[n] = (uint8_t)(v & 0xFFu);             /* wide-operands-reviewed */
    out[n + 1u] = (uint8_t)((v >> 8u) & 0xFFu); /* wide-operands-reviewed */
    return n + 2u;
}

/* One byte of a forme link in the closure layout: DFI_FORME_NONE is 0xFF, a link below 255 is itself, anything
 * else has no byte there. */
static bool dfi_pool_link_byte(uint32_t link, uint8_t *out)
{
    if (link == DFI_FORME_NONE) {
        *out = 0xFFu;
        return true;
    }
    if (link >= 0xFFu) {
        return false;
    }
    *out = (uint8_t)link; /* wide-operands-reviewed: < 255 */
    return true;
}

/* The bytes of a move row, the same in both layouts. */
static size_t dfi_pool_put_move(uint8_t *out, size_t n, const dfi_move_data *m)
{
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
    return n;
}

/* The type chart, the immunity bits and the natures, the same in both layouts. */
static size_t dfi_pool_put_tail(uint8_t *out, size_t n, uint32_t immunity_mask)
{
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
        const dfi_pool_forme_data *f = &dfi_pool_formes[i];
        uint8_t base_forme = 0u;
        uint8_t mega_forme = 0u;
        if (!dfi_pool_link_byte(f->base_forme, &base_forme) || !dfi_pool_link_byte(f->mega_forme, &mega_forme)) {
            return 0u;
        }
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
        out[n++] = base_forme;
        out[n++] = mega_forme;
        out[n++] = f->mega_item;
        out[n++] = f->set_item;
        out[n++] = f->set_move_count;
        for (uint32_t k = 0u; k < 4u; ++k) {
            out[n++] = f->set_moves[k];
        }
    }
    for (uint32_t i = 0u; i < moves; ++i) {
        n = dfi_pool_put_move(out, n, &dfi_pool_moves[i]);
    }
    for (uint32_t i = 0u; i < items; ++i) {
        uint8_t mega_base = 0u;
        uint8_t mega_forme = 0u;
        if (!dfi_pool_link_byte(dfi_pool_items[i].mega_base, &mega_base) ||
            !dfi_pool_link_byte(dfi_pool_items[i].mega_forme, &mega_forme)) {
            return 0u;
        }
        out[n++] = mega_base;
        out[n++] = mega_forme;
    }
    return dfi_pool_put_tail(out, n, immunity_mask);
}

size_t dfi_pool_canonical_bytes(uint8_t *out, size_t capacity)
{
    if (capacity < DFI_POOL_CANONICAL_SIZE) {
        return 0u;
    }
    size_t n = 0u;
    n = dfi_pool_put_u16(out, n, DFI_POOL_FORME_COUNT);
    n = dfi_pool_put_u16(out, n, DFI_POOL_MOVE_COUNT);
    n = dfi_pool_put_u16(out, n, DFI_POOL_ITEM_COUNT);
    n = dfi_pool_put_u16(out, n, DFI_POOL_ABILITY_COUNT);
    n = dfi_pool_put_u16(out, n, DFI_TYPE_COUNT);
    n = dfi_pool_put_u16(out, n, DFI_NATURE_COUNT);
    for (uint32_t i = 0u; i < DFI_POOL_FORME_COUNT; ++i) {
        const dfi_pool_forme_data *f = &dfi_pool_formes[i];
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
        n = dfi_pool_put_u16(out, n, f->base_forme);
        n = dfi_pool_put_u16(out, n, f->mega_forme);
        out[n++] = f->mega_item;
        out[n++] = f->set_item;
        out[n++] = f->set_move_count;
        for (uint32_t k = 0u; k < 4u; ++k) {
            out[n++] = f->set_moves[k];
        }
    }
    for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
        n = dfi_pool_put_move(out, n, &dfi_pool_moves[i]);
    }
    for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
        n = dfi_pool_put_u16(out, n, dfi_pool_items[i].mega_base);
        n = dfi_pool_put_u16(out, n, dfi_pool_items[i].mega_forme);
    }
    n = dfi_pool_put_tail(out, n, 0xFFu);
    for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
        out[n++] = dfi_pool_item_family[i].family;
        out[n++] = dfi_pool_item_family[i].type;
    }
    for (uint32_t i = 0u; i < DFI_POOL_ABILITY_COUNT; ++i) {
        out[n++] = dfi_pool_ability_family[i].family;
        out[n++] = dfi_pool_ability_family[i].param;
    }
    for (uint32_t i = 0u; i < DFI_POOL_ITEM_COUNT; ++i) {
        out[n++] = dfi_pool_item_handler[i];
    }
    for (uint32_t i = 0u; i < DFI_POOL_ABILITY_COUNT; ++i) {
        out[n++] = dfi_pool_ability_handler[i];
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
        out[n++] = dfi_pool_move_flags2[i];
    }
    for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
        out[n++] = dfi_pool_move_heal[i][0];
        out[n++] = dfi_pool_move_heal[i][1];
    }
    for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
        const uint32_t v = dfi_pool_move_static_flags[i];
        out[n++] = (uint8_t)(v & 0xFFu);          /* wide-operands-reviewed */
        out[n++] = (uint8_t)((v >> 8u) & 0xFFu);  /* wide-operands-reviewed */
        out[n++] = (uint8_t)((v >> 16u) & 0xFFu); /* wide-operands-reviewed */
        out[n++] = (uint8_t)((v >> 24u) & 0xFFu); /* wide-operands-reviewed */
    }
    for (uint32_t i = 0u; i < DFI_POOL_MOVE_COUNT; ++i) {
        out[n++] = dfi_pool_move_static_hits[i][0];
        out[n++] = dfi_pool_move_static_hits[i][1];
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
        summary = feature_summary(d)
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
    if pool:
        print(json.dumps(dict(summary, aliases=len(d['aliases']), flags_that_matter=d['flags_that_matter']), indent=1,
                         sort_keys=True))
    print('%s: %d formes, %d moves, %d items, %d abilities; canonical %d bytes, sha256 %s%s' % (
        stem, len(d['formes']), len(d['moves']), len(d['items']), len(d['abilities']), size, digest,
        ' (check ok)' if check else ''))
    for path, text in outs:
        print('  %s sha256 %s' % (os.path.basename(path), hashlib.sha256(text.encode('ascii')).hexdigest()))


if __name__ == '__main__':
    main()
