"""The table assembly: the closure, Team C and pool builds and the width bounds the pool has to fit.

Part of the table generator tools/datagen/gen_closure.py (restructure step 5: split by area; every
statement is unchanged from gen_closure.py@8800b625).
"""
import io
import os
import re

from .source import fail, INPUTS, READER_INPUTS, ReaderIndex, Source, STATS, toid, TYPES
from .species import (
    BATTLE_ONLY_ROWS, FORMAT_ID, FORME_ABILITIES_MAX, forme_legal, IGNORED_TYPE_KEYS, IGNORED_TYPE_KEYS_C,
    IGNORED_TYPE_KEYS_P, LEGAL_POOL, load_legal_pool, parse_forme, POWDER_IMMUNE_TYPES, SAND_IMMUNE_TYPES, SETS,
    SETS_C, SETS_G2, type_chart)
from .moves import (
    check_g32_entries, check_g56_facts, check_g58_facts, check_g59_facts, check_g72b_facts, check_g76_facts,
    check_g78_facts, check_g79_facts, check_g80_facts, check_g82_facts, check_g84_facts, check_g86_facts,
    check_g88_facts, check_g8_conditions, check_g90_facts, check_g92_facts, check_g96_facts, check_weather_facts,
    FLAG_BITS_C, FLAGS2_BITS, FLAGS3_BITS, FLAGS_THAT_MATTER, G2_MOVES, INERT_FLAG_READS, MOVES, MOVES_C, parse_move,
    parse_pool_move, prefix_flag_reads, SAND_IMMUNITY, STATUS_IMMUNITY, STATUS_IMMUNITY_C, STATUS_IMMUNITY_P)
from .families import derive_family, ENGINE_ROWS, HANDLER_IDS
from .items import (
    check_g28_items, check_g49_facts, check_g55_items, entry_features, G2_ITEMS, INERT_ITEM_KEYS, ITEM_FAMILIES,
    ITEM_MATCHERS, ITEM_MEMBERS, item_param, POOL_ITEMS)
from .abilities import (
    ABILITY_FAMILIES, ABILITY_MATCHERS, ABILITY_MEMBERS, ability_param, check_a2a_facts, check_g30_facts, check_g37_facts,
    check_g57_facts, check_i2_facts, FAILSKILLSWAP_SOURCE, G2_ABILITIES, INERT_ABILITY_KEYS, POOL_ABILITIES)
from .rules import (
    C1_PART4_FACTS, check_a0_facts, check_a0p1_facts, check_c1_facts, check_c2_facts, check_c4_facts, check_c5_facts,
    check_failskillswap, check_g15_facts, check_g34_facts, check_g61_facts, check_k2_facts)


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


# Field widths that the whole pool has to fit, read from the sources that own them (check_bounds).
BOUND_SOURCES = {
    'state': os.path.join('src', 'state', 'battle_internal.h'),
    'api': os.path.join('include', 'duoforge', 'duoforge.h'),
    'context': os.path.join('src', 'state', 'context_internal.h'),
}


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


def build_pool(root, repo, dx):
    """The pool tables: the extended data as the prefix, then the new rows of step P1 (POOL_ITEMS, POOL_ABILITIES),
    then those of step G2 (G2_MOVES, G2_ITEMS, G2_ABILITIES and the formes of SETS_G2), then every other move, item,
    ability and forme of the legal pool (data/formats/pools/reg-mc.json) in the file's order, then the
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
    check_c4_facts(moves_ts, champ_moves)
    check_c5_facts(moves_ts, champ_moves)
    check_c1_facts(moves_ts, champ_moves)
    check_a0_facts(moves_ts, champ_moves)
    check_a0p1_facts(moves_ts, champ_moves, items_ts, champ_items, legal)
    check_g15_facts(moves_ts, items_ts)
    check_g30_facts(abil_ts, champ_abil)
    check_a2a_facts(abil_ts, champ_abil, {rel: Source(root, rel, READER_INPUTS) for rel in ('sim/pokemon.ts', 'data/conditions.ts')})
    check_g28_items(items_ts)
    check_g34_facts(abil_ts, champ_abil, items_ts, champ_items)
    check_g61_facts(root, abil_ts, champ_abil)
    check_g49_facts(items_ts, champ_items)
    check_g59_facts(abil_ts, champ_abil, Source(root, 'sim/pokemon.ts', READER_INPUTS),
                    Source(root, 'data/conditions.ts', READER_INPUTS))
    check_g79_facts(Source(root, 'sim/field.ts', READER_INPUTS), Source(root, 'sim/battle.ts', READER_INPUTS),
                    Source(root, 'sim/battle-actions.ts', READER_INPUTS), Source(root, 'data/conditions.ts', READER_INPUTS))
    check_g55_items(items_ts, champ_items)
    check_g37_facts(abil_ts, champ_abil)
    check_g57_facts(abil_ts, champ_abil)
    check_i2_facts(abil_ts, champ_abil)
    check_g32_entries(items_ts, champ_items, abil_ts, champ_abil)
    check_weather_facts(Source(root, 'data/conditions.ts', READER_INPUTS), moves_ts)
    check_g56_facts(Source(root, 'data/conditions.ts', READER_INPUTS), moves_ts)
    check_g58_facts(moves_ts)
    check_g72b_facts(moves_ts)
    check_g84_facts(moves_ts)
    check_g82_facts(moves_ts)
    check_g80_facts(moves_ts)
    check_g76_facts(moves_ts)
    check_g78_facts(moves_ts)
    check_g96_facts(moves_ts)
    check_k2_facts(Source(root, 'sim/battle.ts', READER_INPUTS), Source(root, 'data/mods/champions/scripts.ts'), moves_ts)
    check_g88_facts(moves_ts)
    check_c2_facts(moves_ts, champ_moves)
    check_c2_facts(moves_ts, champ_moves, only=C1_PART4_FACTS)  # step A0 part 4: Shelter (the C1 row)
    check_g86_facts(moves_ts)
    check_g92_facts(moves_ts)
    check_g90_facts(Source(root, 'data/conditions.ts', READER_INPUTS), moves_ts)
    FLAGS_THAT_MATTER.clear()
    FLAGS_THAT_MATTER.update(prefix_flag_reads((items_ts, champ_items, abil_ts, champ_abil, moves_ts, champ_moves), dx)
                             - set(FLAG_BITS_C) - set(INERT_FLAG_READS) - set(FLAGS3_BITS))
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
    moves = [dict(m, flags2=parse_move(m['id'], moves_ts, champ_moves, ext=True, pool=True)['flags2'],
                  flags3=parse_move(m['id'], moves_ts, champ_moves, ext=True, pool=True)['flags3'])
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
    with io.open(os.path.join(repo, FAILSKILLSWAP_SOURCE), encoding='utf-8') as fh:
        check_failskillswap([a['id'] for a in abilities], abil_ts, champ_abil, fh.read())

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
    for sid in BATTLE_ONLY_ROWS:
        rec = species[sid]
        base_sid = rec.get('reached_from')
        if rec['kind'] != 'battle_only' or base_sid not in forme_index or sid in forme_index:
            fail('%s: not a battle-only forme of a row' % sid)
        fo = new_row(rec, False)
        fo['base_forme'] = forme_index[base_sid]
        fo['gender_rule'] = formes[forme_index[base_sid]]['gender_rule']
        forme_index[sid] = len(formes)
        formes.append(fo)
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


def handler_of(row):
    """The handler column value of an item or ability: 1 (UNMODELED) iff it has an unmodelled feature."""
    return HANDLER_IDS.index('UNMODELED') if row['unmodeled'] else HANDLER_IDS.index('NONE')
