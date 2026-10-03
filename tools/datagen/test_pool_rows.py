#!/usr/bin/env python3
"""The generated pool tables against docs/research/expansion/data/legal_pool.json (decision 0015 section 4.2).

gen_closure.py --pool writes a row for every forme, move, item and ability of the legal pool of the format. This test
reads the committed src/data/pool_tables.{h,c} and the committed output of the pinned TeamValidator and checks, with
code of its own and without a checkout, that:
  - the tables have exactly the legal ids (the moves plus Struggle), the formes of the legal pool without its 29
    cosmetic copies, and a name alias for each of those;
  - a forme row has the dex number, weight, types, base stats and gender rule of the record, a base forme links the
    first Mega forme of its stones and every Mega forme names its base forme and stone;
  - the learnable bits of a base forme are the record's moves (cut to the pool) and its abilities the record's legal
    abilities in the pokedex's slot order; a Mega forme learns nothing and has its one ability;
  - a move row has the record's type, category, power, accuracy, PP, priority and target class;
  - an item or ability or move has the UNMODELED marker exactly where it has a list of unmodelled features, and a
    move with a target class that the closure lacks is UNMODELED.
The checks of the pinned handlers and of the validator itself are tools/datagen/pool_families.js.

usage: python3 tools/datagen/test_pool_rows.py
"""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TYPES = ['Bug', 'Dark', 'Dragon', 'Electric', 'Fairy', 'Fighting', 'Fire', 'Flying', 'Ghost', 'Grass', 'Ground', 'Ice',
         'Normal', 'Poison', 'Psychic', 'Rock', 'Steel', 'Water']
CATEGORIES = {'Physical': 0, 'Special': 1, 'Status': 2}
TARGETS = {'normal': 1, 'any': 2, 'adjacentAlly': 3, 'adjacentAllyOrSelf': 4, 'adjacentFoe': 5, 'self': 6,
           'allAdjacentFoes': 7, 'allySide': 8, 'all': 9, 'randomNormal': 10, 'allAdjacent': 11, 'scripted': 12,
           'allyTeam': 13, 'allies': 14, 'foeSide': 15}
ENGINE_TARGETS = {1, 2, 3, 5, 6, 7, 8, 9, 10, 11}  # 11: allAdjacent, since step G28
GENDER = {None: 0, 'M': 1, 'F': 2, 'N': 3}
NONE16 = 0xFFFF


def read(rel):
    with open(os.path.join(ROOT, rel), 'rb') as fh:
        return fh.read().decode('ascii').replace('\r\n', '\n')


HEADER = read('src/data/pool_tables.h')
SOURCE = read('src/data/pool_tables.c')
LEGAL = json.load(open(os.path.join(ROOT, 'docs', 'research', 'expansion', 'data', 'legal_pool.json'), encoding='utf-8'))


def define(name):
    return int(re.search(r'^#define %s (\d+)u$' % name, HEADER, re.M).group(1))


def block(start, end='\n};'):
    a = SOURCE.index(start)
    return SOURCE[a:SOURCE.index(end, a)]


def names(array):
    return re.findall(r'^\s*\[DFI_[A-Z]+_[A-Z0-9]+\] = "([^"]*)",$', block('const char *const %s[' % array), re.M)


def ints(text):
    return [int(x) for x in re.findall(r'\d+', text)]


class Rows:
    formes = names('dfi_pool_forme_names')
    moves = names('dfi_pool_move_names')
    items = names('dfi_pool_item_names')
    abilities = names('dfi_pool_ability_names')

    forme_rows = []
    for line in re.findall(r'^    \{(.*)\},$', block('const dfi_pool_forme_data dfi_pool_formes['), re.M):
        forme_rows.append(line.replace('DFI_FORME_NONE', '65535u'))
    forme_rows = [ints(r.replace('{', ' ').replace('}', ' ')) for r in forme_rows]
    move_rows = [ints(r.replace('{', ' ').replace('}', ' ')) for r in
                 re.findall(r'^    \{(.*)\},$', block('const dfi_move_data dfi_pool_moves['), re.M)]
    item_rows = [ints(r.replace('DFI_FORME_NONE', '65535u')) for r in
                 re.findall(r'^    \{(.*)\},$', block('const dfi_pool_item_data dfi_pool_items['), re.M)]
    legal_rows = [(m.group(1), m.group(2), int(m.group(3)), m.group(4)) for m in re.finditer(
        r'^    \[DFI_FORME_([A-Z0-9]+)\] = \{\{([^}]*)\}, (\d+)u, \{([^}]*)\}\},$',
        block('const dfi_forme_legal dfi_pool_forme_legal['), re.M)]
    aliases = re.findall(r'^    \{"([^"]+)", DFI_FORME_([A-Z0-9]+)\},$', block('const dfi_pool_alias dfi_pool_forme_aliases['), re.M)


def species():
    return {sp['id']: sp for sp in LEGAL['species']}


def moves_of(sp):
    return set(sp['moves'])


class PoolRows(unittest.TestCase):
    def test_the_tables_have_exactly_the_legal_ids(self):
        sp = species()
        formes = [i for i, s in sp.items() if s['kind'] == 'mega' or
                  (s['kind'] == 'selectable' and s['mechanically_identical_to'] is None)]
        self.assertEqual(sorted(Rows.formes), sorted(formes))
        self.assertEqual(len(Rows.formes), define('DFI_POOL_FORME_COUNT'))
        self.assertEqual(len(Rows.formes), 346)
        self.assertEqual(sorted(Rows.moves), sorted([m['id'] for m in LEGAL['moves']] + ['struggle']))
        self.assertEqual(len(Rows.moves), define('DFI_POOL_MOVE_COUNT'))
        self.assertEqual(sorted(Rows.items), sorted(i['id'] for i in LEGAL['items']))
        self.assertEqual(sorted(Rows.abilities), sorted(a['id'] for a in LEGAL['abilities']))
        self.assertEqual((len(Rows.items), len(Rows.abilities)), (define('DFI_POOL_ITEM_COUNT'), define('DFI_POOL_ABILITY_COUNT')))
        self.assertEqual((len(Rows.items), len(Rows.abilities)), (166, 215))
        for rows in (Rows.formes, Rows.moves, Rows.items, Rows.abilities):
            self.assertEqual(len(set(rows)), len(rows))
        self.assertEqual(len(Rows.forme_rows), len(Rows.formes))
        self.assertEqual(len(Rows.move_rows), len(Rows.moves))
        self.assertEqual(len(Rows.item_rows), len(Rows.items))

    def test_the_bounds_of_the_ids(self):
        self.assertLessEqual(len(Rows.moves), 512)      # DUOFORGE_DATA_MAX_FORME_MOVES
        self.assertLess(len(Rows.items), 255)            # 1 + the id fits a byte and 0xFF is the none
        self.assertLess(len(Rows.abilities), 255)
        self.assertLess(len(Rows.formes), 0xFFFF)
        self.assertEqual(define('DFI_POOL_LEARN_BYTES'), (len(Rows.moves) + 7) // 8)
        self.assertTrue(all(len(t[1].split(',')) == define('DFI_POOL_LEARN_BYTES') for t in Rows.legal_rows))

    def test_the_cosmetic_copies_are_aliases_of_their_base_forme(self):
        want = {s['id']: s['mechanically_identical_to'] for s in LEGAL['species']
                if s['kind'] == 'selectable' and s['mechanically_identical_to'] is not None}
        got = {alias: base.lower() for alias, base in Rows.aliases}
        self.assertEqual(got, want)
        self.assertEqual(len(got), 29)
        self.assertEqual(len(Rows.aliases), define('DFI_POOL_ALIAS_COUNT'))
        for alias, base in got.items():
            self.assertIn(base, Rows.formes)
            self.assertNotIn(alias, Rows.formes)

    def test_a_forme_row_is_its_record(self):
        sp = species()
        for i, name in enumerate(Rows.formes):
            rec, row = sp[name], Rows.forme_rows[i]
            (dex, weight, t0, t1, b0, b1, b2, b3, b4, b5, ability, gender, is_mega, base, mega, mega_item, set_item,
             set_count, *set_moves) = row
            with self.subTest(name):
                self.assertEqual(dex, rec['num'])
                self.assertEqual(weight, int(round(rec['weightkg'] * 10)))
                self.assertEqual([t0, t1], [TYPES.index(t) for t in rec['types']] + [255] * (2 - len(rec['types'])))
                self.assertEqual([b0, b1, b2, b3, b4, b5], [rec['base_stats'][k] for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')])
                self.assertEqual(is_mega, 1 if rec['kind'] == 'mega' else 0)
                if rec['kind'] == 'mega':
                    base_rec = sp[rec['holders'][0]['species']]
                    self.assertEqual(Rows.formes[base], base_rec['id'])
                    self.assertEqual(mega, NONE16)
                    self.assertEqual(Rows.items[mega_item], rec['required_item'])
                    self.assertEqual(set_item, mega_item)
                    self.assertEqual(gender, GENDER[base_rec['gender']])
                else:
                    self.assertEqual(base, i)
                    self.assertEqual(gender, GENDER[rec['gender']])
                    self.assertLessEqual(set_count, 4)
                    # The rows after step G2 have no set of their own.
                    if i >= 28:
                        self.assertEqual((set_item, set_count, set_moves), (255, 0, [0, 0, 0, 0]))
                # The ability is a legal one.
                legal = [a for a in rec['abilities_declared'].values() if a in rec['abilities_legal']]
                self.assertIn(Rows.abilities[ability], legal)

    def test_the_mega_links(self):
        sp = species()
        megas = {}
        for s in LEGAL['species']:
            if s['kind'] == 'mega':
                megas.setdefault(s['holders'][0]['species'], []).append(s['id'])
        for name, row in zip(Rows.formes, Rows.forme_rows):
            if sp[name]['kind'] == 'selectable':
                linked = row[14]
                if name in megas:
                    self.assertNotEqual(linked, NONE16, name)
                    self.assertIn(Rows.formes[linked], megas[name])
                    self.assertEqual(Rows.items[row[15]], sp[Rows.formes[linked]]['required_item'])
                else:
                    self.assertEqual((linked, row[15]), (NONE16, 255), name)
        self.assertEqual(sum(1 for r in Rows.forme_rows if r[14] != NONE16), len(megas))
        self.assertEqual(len(megas), 77)
        self.assertEqual(sum(len(v) for v in megas.values()), 82)
        # A stone's row names a pair that exists: the Mega forme has the stone and the base forme.
        stones = {i['id']: i for i in LEGAL['items'] if i['is_mega_stone']}
        for i, (base, mega) in enumerate(Rows.item_rows):
            if base == NONE16:
                self.assertNotIn(Rows.items[i], stones)
            else:
                pair = (Rows.formes[base], Rows.formes[mega])
                self.assertIn(pair, [tuple(p) for p in stones[Rows.items[i]]['mega_stone'].items()])
        self.assertEqual(len([1 for r in Rows.item_rows if r[0] != NONE16]), 81)

    def test_the_learnable_moves_and_legal_abilities(self):
        sp = species()
        move_index = {m: i for i, m in enumerate(Rows.moves)}
        ability_index = {a: i for i, a in enumerate(Rows.abilities)}
        by_forme = {n.lower(): (bits, int(count), abil) for n, bits, count, abil in Rows.legal_rows}
        for name in Rows.formes:
            rec = sp[name]
            bits, count, abil = by_forme[name]
            data = [int(x.strip().rstrip('u'), 16) for x in bits.split(',')]
            learned = {m for m, i in move_index.items() if data[i // 8] >> (i % 8) & 1}
            slots = [x.strip() for x in abil.split(',')]
            listed = [Rows.abilities[ability_index_of(x)] for x in slots if x != 'DFI_CLOSURE_NONE']
            with self.subTest(name):
                self.assertEqual(count, len(listed))
                self.assertLessEqual(count, 3)
                self.assertEqual(sum(1 for i in range(len(Rows.moves), len(data) * 8) if data[i // 8] >> (i % 8) & 1), 0)
                if rec['kind'] == 'mega':
                    self.assertEqual(learned, set())
                    self.assertEqual(listed, rec['abilities_legal'])
                    self.assertEqual(len(rec['abilities_legal']), 1)
                else:
                    self.assertEqual(learned, moves_of(rec) & set(move_index))
                    self.assertNotIn('struggle', learned)
                    declared = [a for a in rec['abilities_declared'].values() if a in rec['abilities_legal'] and a in ability_index]
                    self.assertEqual(listed, declared)

    def test_a_move_row_is_its_record(self):
        legal = {m['id']: m for m in LEGAL['moves']}
        for i, name in enumerate(Rows.moves):
            if name == 'struggle':
                continue
            rec, row = legal[name], Rows.move_rows[i]
            type_, category, power, accuracy, pp_base, pp_max, priority, target = row[:8]
            with self.subTest(name):
                self.assertEqual(TYPES[type_], rec['type'])
                self.assertEqual(category, CATEGORIES[rec['category']])
                self.assertEqual(power, rec['base_power'])
                self.assertEqual(accuracy, 0 if rec['accuracy'] in (True, 'always') else rec['accuracy'])
                self.assertEqual(priority, rec['priority'] + 8)
                self.assertEqual(target, TARGETS[rec['target']])
                capped = rec['pp']
                # legal_pool.json has the PP after the Champions cap of 20 (data/mods/champions/scripts.ts).
                self.assertEqual(min(pp_base, 20), rec['pp'])
                self.assertEqual(pp_max, capped if rec['pp'] == 1 else (capped // 5 + 1) * 4)

    def test_the_unmodeled_markers(self):
        for kind, array, count in (('MOVE', 'dfi_pool_move_unmodeled', len(Rows.moves)),
                                   ('ITEM', 'dfi_pool_item_unmodeled', len(Rows.items)),
                                   ('ABILITY', 'dfi_pool_ability_unmodeled', len(Rows.abilities))):
            listed = dict(re.findall(r'^\s*\[DFI_%s_([A-Z0-9]+)\] = "([^"]+)",$' % kind, block('const char *const %s[' % array), re.M))
            names_ = {'MOVE': Rows.moves, 'ITEM': Rows.items, 'ABILITY': Rows.abilities}[kind]
            for n in listed:
                self.assertIn(n.lower(), names_)
            if kind == 'MOVE':
                special = {names_[i]: row[28] for i, row in enumerate(Rows.move_rows)}
                unmodeled = define('DFI_SPECIAL_UNMODELED')
                self.assertEqual({n for n, s in special.items() if s == unmodeled}, {n.lower() for n in listed})
                # A target class beyond the closure's is never in a modelled row.
                for i, row in enumerate(Rows.move_rows):
                    if row[7] not in ENGINE_TARGETS and row[7] != 4:
                        self.assertEqual(row[28], unmodeled, names_[i])
                    if row[28] == unmodeled:
                        # An UNMODELED row claims nothing beyond its plain data.
                        self.assertEqual(row[14:18] + row[18:25] + row[25:28], [0] * 4 + [6] * 7 + [0] * 3, names_[i])
            else:
                col = re.findall(r'^\s*\[DFI_%s_([A-Z0-9]+)\] = DFI_HANDLER_(\w+),$' % kind,
                                 block('const uint8_t dfi_pool_%s_handler[' % kind.lower()), re.M)
                self.assertEqual(len(col), count)
                self.assertEqual({n.lower() for n, h in col if h == 'UNMODELED'}, {n.lower() for n in listed})
            for text in listed.values():
                self.assertTrue(all(part.strip() for part in text.split(';')))

    def test_nothing_that_grounds_or_lifts_a_pokemon_is_modelled_but_levitate(self):
        """The engine's isGrounded is "not a Flying type and not a Levitate holder" (dfi_grounded, src/combat/turn.c;
        Levitate since step G23-C), which Expanding Force (step G15) reads for its user. The pin also reads Eelevate, Air
        Balloon and Iron Ball, Gravity, Ingrain, Magnet Rise, Telekinesis, Smack Down and Roost (sim/pokemon.ts:2148-2160):
        every one of them is an UNMODELED row, so no battle has it; Levitate is an engine row."""
        def listed(kind, array):
            return {n.lower() for n in dict(re.findall(r'^\s*\[DFI_%s_([A-Z0-9]+)\] = "([^"]+)",$' % kind,
                                                       block('const char *const %s[' % array), re.M))}
        for kind, array, ids, rows in (('ABILITY', 'dfi_pool_ability_unmodeled', ['eelevate'], Rows.abilities),
                                       ('ITEM', 'dfi_pool_item_unmodeled', ['airballoon', 'ironball'], Rows.items),
                                       ('MOVE', 'dfi_pool_move_unmodeled',
                                        ['gravity', 'ingrain', 'magnetrise', 'telekinesis', 'smackdown', 'roost'],
                                        Rows.moves)):
            # a row of the pool is UNMODELED; an id that the format does not have (Telekinesis) needs no row
            self.assertEqual(sorted(set(ids) & set(rows) - listed(kind, array)), [], kind)
        self.assertIn('[DFI_ABILITY_LEVITATE] = DFI_HANDLER_NONE,', block('const uint8_t dfi_pool_ability_handler['))
        self.assertNotIn('levitate', listed('ABILITY', 'dfi_pool_ability_unmodeled'))

    def test_the_canonical_size(self):
        n_f, n_m, n_i, n_a = len(Rows.formes), len(Rows.moves), len(Rows.items), len(Rows.abilities)
        want = (12 + n_f * 26 + n_m * 29 + n_i * 4 + 18 * 18 + 18 + 25 * 2 + n_i * 2 + n_a * 2 + n_i + n_a +
                n_f * (define('DFI_POOL_LEARN_BYTES') + 1 + 3) + n_m + 2 * n_m + 4 * n_m + 2 * n_m)  # + the second flags byte of every move
        # (step G8), the heal fraction of every move (step G10), then the static flags (4 bytes) and the hit counts
        # (2 bytes) of every move (decision 0020)
        self.assertEqual(define('DFI_POOL_CANONICAL_SIZE'), want)


def ability_index_of(token):
    return Rows.abilities.index(token.replace('DFI_ABILITY_', '').lower())


if __name__ == '__main__':
    unittest.main()
