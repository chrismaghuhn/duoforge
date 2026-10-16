"""Formes and Pokemon: the reference team sets, the forme and type chart parsers, the format's legal pool,
the learnsets and the forme legality.

Part of the table generator tools/datagen/gen_closure.py (restructure step 5: split by area; every
statement is unchanged from gen_closure.py@001a492e).
"""
import io
import json
import os
import re

import gen_format

from .source import fail, fields, PIN, scalar, toid, TYPES

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
# Type-chart keys without a consumer in the closure (no poison source, powder
# move, sandstorm or hail, and no trapping).
IGNORED_TYPE_KEYS = {'psn', 'tox', 'powder', 'sandstorm', 'hail', 'trapped'}

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
IGNORED_TYPE_KEYS_C = IGNORED_TYPE_KEYS - {'psn'}  # tox stays ignored: no toxic source
IGNORED_TYPE_KEYS_P = IGNORED_TYPE_KEYS_C - {'sandstorm'}
SAND_IMMUNE_TYPES = ['Ground', 'Rock', 'Steel']  # in the order of TYPES
POWDER_IMMUNE_TYPES = ['Grass']  # step G30: the chart's `powder: 3`; the engine reads it as the type, no column


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


# ---- the POOL data kind (decision 0015): the extended tables plus the rows of the expansion ----
# The closure and --team-c modes never read anything below, so their output stays byte-identical.
# The format and its pool source come from the format definition data/formats/reg-mc.json (restructure step 10):
# load_format checks its pool source's sha256, Showdown commit and format id.
FORMAT = gen_format.load_format()
if FORMAT['showdown_commit'] != PIN:
    fail('%s is not at the pin %s' % (gen_format.FORMAT_FILE, PIN))
FORMAT_ID = FORMAT['showdown_format_id']
LEGAL_POOL = os.path.join(*FORMAT['pool']['source'].split('/'))

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
# Step G13: Light of Ruin carries tags: ["Past Unobtainable"] next to isNonstandard: "Past"; the Champions mod (data/mods/
# champions/moves.ts:581-584) sets isNonstandard to null, which makes it legal, and the tag has no reader in the tables.
TAGS_PAST_UNOBTAINABLE = 'tags: ["Past Unobtainable"],'
# Step G66 (decision 0040): the Blade of Stance Change. It is a battle-only forme (kind battle_only in the legal pool, reached
# from Aegislash), so the selectable rows do not reach it; it gets a row of its own, appended after every other forme, with no
# legal set (no learnable move, its one ability), like a Mega forme. Its temporary change is the mechanic's, not a set's.
BATTLE_ONLY_ROWS = ['aegislashblade']
# The one ability that the pin tags as not released and that the pool still has: Aura Guard is the ability of
# Lucario-Mega-Z, whose set the pinned validator accepts (data/formats/pools/reg-mc.json, 'abilities_mega_only').
# The row exists because the format has the forme; it is UNMODELED like every ability with a callback. Any other tag fails.
LEGAL_DESPITE_TAG = {'auraguard': 'Future'}


def load_legal_pool(repo):
    """The ids that TeamValidator accepted at the pin: data/formats/pools/reg-mc.json, the output of
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
        if fo['is_mega'] or fo['id'] in BATTLE_ONLY_ROWS:
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


# Step G59: the facts of Mega Sol's effectiveWeather side (sim/pokemon.ts, Pokemon#effectiveWeather: the holder's active move
# reads as sun for its effects of kind Move, Weather or Mega Sol itself) and of the sunnyday handler that Mega Sol calls
# (data/conditions.ts). The refusal of dfi_mega_sol_refused rests on them, and the modifier of the engine on the handler's Fire
# and Water lines.
G59_POKEMON_FACTS = (
    "if (this.battle.activePokemon?.hasAbility('megasol') && sourceEffect &&",
    "(sourceEffect.id === 'megasol' || sourceEffect.effectType === 'Move' || sourceEffect.effectType === 'Weather') &&",
    "sourceEffect.id !== 'electroshot') {",
    "return 'sunnyday' as ID;",
)
