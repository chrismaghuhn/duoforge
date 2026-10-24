#!/usr/bin/env python3
"""The format definition data/formats/gen9ou.json (step O8 of docs/superpowers/specs/2026-10-15-gen9-ou-design.md).

Without a checkout, with code of its own, this test checks that:
  - the definition loads: its id, its keys, its facts, its tables section, the pool source it names (sha256, Showdown
    commit, format id);
  - the facts agree with the rules block of the pool source (what the pinned rule table said when the pool was made):
    singles, a team of 1 to 6 with no pick, sets up to level 100, four moves, 510 EVs and 255 in a stat, the clauses
    and no Item Clause, the banlist, Terastallization;
  - the tables section fits the pool: W1, the learnset bytes are the fewest that hold a bit for every move row (the
    pool's moves and Struggle); W2, no forme left in the pool has more legal moves than moves_per_forme, while the
    moves in total exceed it; Smeargle, the one forme above it, is excluded by name with its reason; the formes, items,
    abilities and abilities per forme fit their bounds;
  - the gen9 rule set the section names is refused by name (no table set builds it before the Gen 9 design), no
    gen9ou tables are committed, and the engine's header stays Reg M-C's.
tools/datagen/gen_format.py --format gen9ou --pin (duoforge.data.format_pin_gen9ou) compares every quote with the pinned
checkout; tools/datagen/tests/check_format_pool.py (duoforge.data.format_pool_gen9ou) makes the pool again with the
pinned validator.

usage: python3 tools/datagen/tests/test_format_gen9ou.py
"""
import io
import json
import os
import re
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import gen_closure  # noqa: E402
import gen_format  # noqa: E402

ROOT = gen_format.REPO
FMT = gen_format.load_format(format_id='gen9ou')
REG_MC = gen_format.load_format()
TABLES = FMT['tables']
# The bound of the public API: a buffer of DUOFORGE_DATA_MAX_FORME_MOVES entries holds the legal moves of any forme.
MAX_FORME_MOVES = 512


def read(rel):
    with io.open(os.path.join(ROOT, rel), 'rb') as fh:
        return fh.read().decode('utf-8').replace('\r\n', '\n')


POOL = json.loads(read(FMT['pool']['source']))


def to_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())


def refused(test, message, fn, *args):
    with test.assertRaises(SystemExit) as cm:
        fn(*args)
    test.assertIn(message, str(cm.exception.code))


def legal_pool():
    """The pool as the generator reads it, with the definition's exclusions (load_legal_pool reads only these fields of
    a table set; the table set itself is refused, see RuleSet)."""
    ts = types.SimpleNamespace(format_id=FMT['id'], definition='data/formats/gen9ou.json',
                               legal_pool=os.path.join(*FMT['pool']['source'].split('/')),
                               showdown_format_id=FMT['showdown_format_id'],
                               excluded={e['id']: e['reason'] for e in TABLES['excluded_formes']})
    return gen_closure.load_legal_pool(ROOT, ts)


class Gen9OuDefinition(unittest.TestCase):
    def test_the_definition_names_the_pool_source(self):
        self.assertEqual((FMT['id'], FMT['showdown_format_id']), ('gen9ou', 'gen9ou'))
        self.assertEqual(FMT['showdown_commit'], REG_MC['showdown_commit'])
        meta = POOL['meta']
        self.assertEqual((meta['showdown_commit'], meta['format_id']),
                         (FMT['showdown_commit'], FMT['showdown_format_id']))
        self.assertEqual(gen_format.file_sha256(os.path.join(ROOT, FMT['pool']['source'])), FMT['pool']['sha256'])

    def test_the_facts_agree_with_the_rule_table(self):
        facts = {k: v['value'] for k, v in FMT['facts'].items()}
        rules = POOL['rules']
        self.assertEqual((rules['format_name'], rules['mod'], rules['game_type']),
                         (facts['name'], facts['mod'], facts['game_type_default']))
        self.assertEqual(FMT['engine']['active_per_side'], 1)
        self.assertEqual(rules['team_size'],
                         {'min': facts['min_team_size_singles'], 'max': facts['max_team_size'], 'picked': None})
        self.assertTrue(facts['lead_only_preview'])
        self.assertEqual(rules['level'], {'adjust_level_to': None, 'validator_max_level': facts['max_level']})
        self.assertEqual(rules['moves_per_set'], facts['moves_per_set'])
        self.assertEqual((rules['evs']['total_limit'], rules['evs']['per_stat_max']),
                         (facts['ev_total_max'], facts['ev_max']))
        self.assertEqual(rules['ruleset_as_declared'], facts['ruleset'])
        keys = set(rules['rule_table_keys'])
        for fact, key in (('team_preview', 'teampreview'), ('endless_battle_clause', 'endlessbattleclause'),
                          ('species_clause', 'speciesclause'), ('nickname_clause', 'nicknameclause'),
                          ('ohko_clause', 'ohkoclause'), ('evasion_items_clause', 'evasionitemsclause'),
                          ('evasion_moves_clause', 'evasionmovesclause'),
                          ('evasion_abilities_clause', 'evasionabilitiesclause'),
                          ('sleep_moves_clause', 'sleepmovesclause')):
            self.assertTrue(facts[fact], fact)
            self.assertIn(key, keys, fact)
        # '!Sleep Clause Mod' takes the Standard's Sleep Clause Mod out; no rule of the format is an Item Clause.
        self.assertTrue(facts['sleep_clause_mod_removed'])
        self.assertIn('Sleep Clause Mod', facts['standard_clauses'])
        self.assertNotIn('sleepclausemod', keys)
        self.assertNotIn('itemclause', keys)
        self.assertEqual(rules['clauses_team_level'], ['Species Clause', 'Nickname Clause'])
        banned = set(rules['banlist_effective'])
        for entry in facts['banlist']:
            kinds = [prefix + to_id(entry) for prefix in ('-tag:', '-ability:', '-item:', '-move:')]
            self.assertEqual(sum(k in banned for k in kinds), 1, entry)
        self.assertTrue(facts['terastallization'])
        self.assertEqual(rules['terastallization'], 'enabled (every set has a Tera type)')

    def test_the_engine_format_stays_reg_mc(self):
        self.assertEqual(gen_format.ENGINE_FORMAT, 'reg-mc')
        self.assertEqual(read(gen_format.HEADER), gen_format.render(REG_MC))
        self.assertNotIn('gen9ou', read(gen_format.HEADER))


class RuleSet(unittest.TestCase):
    def test_the_tables_name_the_gen9_set_and_its_writer_names(self):
        self.assertEqual((TABLES['rule_set'], TABLES['symbol_prefix'], TABLES['include_guard'], TABLES['stem']),
                         ('gen9', 'gen9ou', 'DUOFORGE_DATA_FORMATS_GEN9OU_POOL_TABLES_H', 'pool_tables'))

    def test_the_gen9_rule_set_is_refused_by_name(self):
        refused(self, 'rule set gen9 is refused: standalone table sets come with the Gen 9 design',
                gen_closure.load_table_set, ROOT, 'gen9ou')

    def test_no_gen9ou_tables_are_committed(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, 'src', 'data', 'formats', 'gen9ou')))


class TablesFitThePool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legal = legal_pool()
        cls.raw = {sp['id']: sp for sp in POOL['species']}
        # The selectable formes carry their legal moves; a battle-only forme is reached in battle and learns none.
        cls.selectable = [sp for sp in cls.legal['species'].values() if sp['kind'] == 'selectable']
        cls.battle_only = [sp for sp in cls.legal['species'].values() if sp['kind'] == 'battle_only']
        assert len(cls.selectable) + len(cls.battle_only) == len(cls.legal['species'])

    def test_w1_the_learnset_bytes_hold_every_move_row(self):
        # The move rows are the pool's moves and Struggle, which no forme learns (build_pool).
        rows = len(POOL['moves']) + 1
        self.assertNotIn('struggle', {m['id'] for m in POOL['moves']})
        self.assertEqual((len(POOL['moves']), rows), (666, 667))
        self.assertGreaterEqual(TABLES['learnset_bytes'] * 8, rows)
        self.assertLess((TABLES['learnset_bytes'] - 1) * 8, rows)
        self.assertEqual(TABLES['learnset_bytes'], 84)
        self.assertEqual(REG_MC['tables']['learnset_bytes'], 64)

    def test_w2_the_bound_is_per_forme_and_holds_without_smeargle(self):
        bound = TABLES['bounds']['moves_per_forme']
        self.assertEqual(bound, MAX_FORME_MOVES)
        self.assertGreater(len(POOL['moves']), bound)  # the total would not fit: the bound must be per forme
        most = max(len(sp['moves']) for sp in self.selectable)
        self.assertLessEqual(most, bound)
        self.assertEqual(most, len(self.raw['mew']['moves']))
        above = sorted(sid for sid, sp in self.raw.items() if len(sp.get('moves', ())) > bound)
        self.assertEqual(above, ['smeargle'])
        self.assertEqual(len(self.raw['smeargle']['moves']), 664)

    def test_smeargle_is_excluded_by_name_with_its_reason(self):
        excluded = {e['id']: e['reason'] for e in TABLES['excluded_formes']}
        self.assertEqual(sorted(excluded), ['smeargle'])
        self.assertIn('Sketch', excluded['smeargle'])
        self.assertIn('664', excluded['smeargle'])
        self.assertNotIn('smeargle', self.legal['species'])
        self.assertNotIn('smeargle', self.legal['species_order'])

    def test_the_ids_fit_the_bounds(self):
        b = TABLES['bounds']
        self.assertEqual(b, {'formes': 65534, 'moves': 65535, 'moves_per_forme': 512, 'items': 254, 'abilities': 254})
        rows = [sp for sp in self.selectable if sp['mechanically_identical_to'] is None] + self.battle_only
        self.assertLessEqual(len(rows), b['formes'])
        self.assertLessEqual(len(POOL['moves']) + 1, b['moves'])
        self.assertLessEqual(len(self.legal['items']), b['items'])
        self.assertLessEqual(len(self.legal['abilities']), b['abilities'])
        # W3, open before O11: 246 of the 254 u8 item ids.
        self.assertEqual((len(self.legal['items']), len(self.legal['abilities'])), (246, 224))
        self.assertLessEqual(max(len(sp['abilities_legal']) for sp in self.selectable),
                             gen_closure.FORME_ABILITIES_MAX)


if __name__ == '__main__':
    unittest.main()
