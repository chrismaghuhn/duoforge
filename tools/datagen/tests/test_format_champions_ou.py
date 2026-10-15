#!/usr/bin/env python3
"""The format definition data/formats/champions-ou.json
(step O1 of docs/superpowers/specs/2026-10-15-gen9-ou-design.md).

Without a checkout, with code of its own, this test checks that:
  - the definition loads: its id, its keys, its facts, the pool source it names (sha256, Showdown commit, format id);
  - the facts agree with the rules block of the pool source (what the pinned rule table said when the pool was made):
    singles, six of six with no pick, level 50, four moves, 66 Stat Points, the clauses, the banlist;
  - the definition is not the engine's format: it writes no header and src/data/format_tables.h stays Reg M-C's;
  - the pool lies inside today's pool tables: every forme (a row or a cosmetic alias), move, item and ability of the
    pool is a row of src/data/pool_tables.c, except the battle-only formes named here, which are not rows for Reg
    M-C either;
  - the pool differs from Reg M-C's only by entries that the format's banlist, clauses or tiers remove: no entry is
    in Champions OU that Reg M-C lacks.
tools/datagen/gen_format.py --format champions-ou --pin (duoforge.data.format_pin_champions_ou) compares every quote
with the pinned checkout; tools/datagen/tests/check_format_pool.py (duoforge.data.format_pool_champions_ou) makes the
pool again with the pinned validator.

usage: python3 tools/datagen/tests/test_format_champions_ou.py
"""
import io
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import gen_format  # noqa: E402

ROOT = gen_format.REPO
FMT = gen_format.load_format(format_id='champions-ou')
REG_MC = gen_format.load_format()
# The battle-only formes of the pool that are no rows of the tables (the tables carry only Aegislash-Blade, step G66).
BATTLE_ONLY_NOT_ROWS = ['castformrainy', 'castformsnowy', 'castformsunny', 'mimikyubusted', 'morpekohangry']


def read(rel):
    with io.open(os.path.join(ROOT, rel), 'rb') as fh:
        return fh.read().decode('utf-8').replace('\r\n', '\n')


def pool(fmt):
    return json.loads(read(fmt['pool']['source']))


def table_names(source, array):
    a = source.index('const char *const %s[' % array)
    return set(re.findall(r'^\s*\[DFI_[A-Z]+_[A-Z0-9]+\] = "([^"]*)",$', source[a:source.index('\n};', a)], re.M))


def to_id(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())


class ChampionsOuDefinition(unittest.TestCase):
    def test_the_definition_names_the_pool_source(self):
        self.assertEqual((FMT['id'], FMT['showdown_format_id']), ('champions-ou', 'gen9championsou'))
        self.assertEqual(FMT['showdown_commit'], REG_MC['showdown_commit'])
        meta = pool(FMT)['meta']
        self.assertEqual((meta['showdown_commit'], meta['format_id']),
                         (FMT['showdown_commit'], FMT['showdown_format_id']))
        self.assertEqual(gen_format.file_sha256(os.path.join(ROOT, FMT['pool']['source'])), FMT['pool']['sha256'])

    def test_the_facts_agree_with_the_rule_table(self):
        facts = {k: v['value'] for k, v in FMT['facts'].items()}
        rules = pool(FMT)['rules']
        self.assertEqual((rules['format_name'], rules['mod'], rules['game_type']),
                         (facts['name'], facts['mod'], facts['game_type_default']))
        self.assertEqual(FMT['engine']['active_per_side'], 1)
        self.assertEqual(rules['team_size'], {'min': facts['team_size'], 'max': facts['max_team_size'], 'picked': None})
        self.assertTrue(facts['lead_only_preview'])
        self.assertEqual(rules['level']['adjust_level_to'], facts['level'])
        self.assertEqual(rules['moves_per_set'], facts['moves_per_set'])
        self.assertEqual(rules['stat_points']['total_limit'], facts['stat_points_total_max'])
        self.assertEqual(rules['ruleset_as_declared'], facts['ruleset'])
        keys = set(rules['rule_table_keys'])
        for fact, key in (('team_preview', 'teampreview'), ('endless_battle_clause', 'endlessbattleclause'),
                          ('species_clause', 'speciesclause'), ('nickname_clause', 'nicknameclause'),
                          ('sleep_moves_clause', 'sleepmovesclause'), ('ohko_clause', 'ohkoclause'),
                          ('evasion_clause', 'evasionclause'), ('item_clause', 'itemclause')):
            self.assertTrue(facts[fact], fact)
            self.assertIn(key, keys, fact)
        self.assertNotIn('sleepclausemod', keys)
        banned = set(rules['banlist_effective'])
        for entry in facts['banlist']:
            kinds = [prefix + to_id(entry) for prefix in ('-tag:', '-ability:', '-item:', '-move:')]
            self.assertEqual(sum(k in banned for k in kinds), 1, entry)
        self.assertFalse(facts['terastallization'])

    def test_the_engine_format_stays_reg_mc(self):
        self.assertEqual(gen_format.ENGINE_FORMAT, 'reg-mc')
        self.assertEqual(read(gen_format.HEADER), gen_format.render(REG_MC))
        self.assertNotIn('champions-ou', read(gen_format.HEADER))

    def test_the_pool_lies_inside_the_pool_tables(self):
        source = read('src/data/pool_tables.c')
        a = source.index('dfi_pool_forme_aliases[')
        aliases = set(re.findall(r'\{"([a-z0-9]+)",', source[a:source.index('\n};', a)]))
        rows = {'species': table_names(source, 'dfi_pool_forme_names') | aliases,
                'moves': table_names(source, 'dfi_pool_move_names'),
                'items': table_names(source, 'dfi_pool_item_names'),
                'abilities': table_names(source, 'dfi_pool_ability_names')}
        legal = pool(FMT)
        for kind, have in rows.items():
            outside = sorted({rec['id'] for rec in legal[kind]} - have)
            self.assertEqual(outside, BATTLE_ONLY_NOT_ROWS if kind == 'species' else [], kind)
        kinds = {rec['id']: rec['kind'] for rec in legal['species']}
        self.assertEqual({kinds[i] for i in BATTLE_ONLY_NOT_ROWS}, {'battle_only'})

    def test_the_pool_is_a_subset_of_reg_mc(self):
        ours, theirs = pool(FMT), pool(REG_MC)
        for kind in ('species', 'moves', 'items', 'abilities'):
            self.assertEqual(sorted({r['id'] for r in ours[kind]} - {r['id'] for r in theirs[kind]}), [], kind)
        banned_items = {to_id(e) for e in FMT['facts']['banlist']['value']}
        removed = {r['id'] for r in theirs['items']} - {r['id'] for r in ours['items']}
        # Light Clay, Quick Claw, Damp Rock and King's Rock are banned; Bright Powder falls to Evasion Items Clause.
        self.assertEqual(removed - banned_items, {'brightpowder'})


if __name__ == '__main__':
    unittest.main()
