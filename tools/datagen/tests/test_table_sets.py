#!/usr/bin/env python3
"""The table set of a format (restructure step 5): gen_closure.py --pool --format <id> reads the pool, the rule set,
the writer's names, the learnset bytes, the id bounds and the excluded formes from data/formats/<id>.json. Reg M-C's
values reproduce today's tables byte for byte (duoforge.data.pool_regen); these cases play the parameters through
with a second, made-up format, and every missing or unknown input is refused by name.

usage: python3 tools/datagen/tests/test_table_sets.py [<pinned checkout>]
CTest runs it without a checkout as duoforge.data.table_sets (the offline cases) and, with
-DDUOFORGE_PS_REFERENCE_DIR, with the checkout as duoforge.data.table_sets_pinned, which builds the whole pool
tables of the made-up format (the PinnedDummyFormat cases need the checkout and run only then).
"""
import copy
import io
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.dirname(HERE))
import gen_closure  # noqa: E402
import gen_format  # noqa: E402

CHECKOUT = sys.argv.pop(1) if len(sys.argv) > 1 else None

with io.open(os.path.join(ROOT, 'data', 'formats', 'reg-mc.json'), encoding='utf-8') as _fh:
    REG_MC = json.load(_fh)


def refused(test, message, fn, *args):
    with test.assertRaises(SystemExit) as cm:
        fn(*args)
    test.assertIn(message, str(cm.exception.code))


def dummy_tables(**changes):
    """The tables section of a made-up second format: other names, a wider learnset, smaller bounds."""
    t = {'comment': 'a made-up format of the tests', 'rule_set': 'champions', 'symbol_prefix': 'dummy',
         'include_guard': 'DUOFORGE_DATA_DUMMY_TABLES_H', 'stem': 'dummy_tables', 'learnset_bytes': 65,
         'bounds': {'formes': 400, 'moves': 600, 'moves_per_forme': 300, 'items': 200, 'abilities': 230},
         'excluded_formes': []}
    t.update(changes)
    return t


def dummy_format(pool_source='data/formats/pools/reg-mc.json', **changes):
    fmt = copy.deepcopy(REG_MC)
    fmt['id'] = 'dummy'
    fmt['pool']['source'] = pool_source
    fmt['tables'] = dummy_tables(**changes)
    gen_format.check_tables(fmt['tables'], 'data/formats/dummy.json')
    return gen_closure.TableSet(fmt, os.path.join('data', 'formats', 'dummy.json'))


class TablesSection(unittest.TestCase):
    """gen_format.check_tables: every key is required, none is unknown, every value has its shape."""

    def check(self, tables):
        gen_format.check_tables(tables, 'data/formats/dummy.json')

    def test_reg_mc_and_the_dummy_are_valid(self):
        self.check(REG_MC['tables'])
        self.check(dummy_tables())

    def test_a_missing_or_unknown_key_is_refused_by_name(self):
        t = dummy_tables()
        del t['learnset_bytes']
        refused(self, "tables: missing ['learnset_bytes'], unknown none", self.check, t)
        refused(self, "unknown ['width']", self.check, dict(dummy_tables(), width=64))
        bounds = dict(dummy_tables()['bounds'])
        del bounds['moves_per_forme']
        refused(self, "tables.bounds: missing ['moves_per_forme']", self.check, dummy_tables(bounds=bounds))

    def test_values_have_their_shape(self):
        refused(self, 'symbol_prefix', self.check, dummy_tables(symbol_prefix='Dummy'))
        refused(self, 'include_guard', self.check, dummy_tables(include_guard='DUMMY_H'))
        refused(self, 'stem', self.check, dummy_tables(stem='dummy.tables'))
        refused(self, 'learnset_bytes must be a positive int', self.check, dummy_tables(learnset_bytes=0))
        refused(self, 'tables.bounds.items must be a positive int', self.check,
                dummy_tables(bounds=dict(dummy_tables()['bounds'], items='254')))

    def test_an_excluded_forme_needs_an_id_and_a_reason(self):
        refused(self, 'has no reason', self.check, dummy_tables(excluded_formes=[{'id': 'smeargle', 'reason': ' '}]))
        refused(self, "excluded_formes[0]: missing ['reason']", self.check,
                dummy_tables(excluded_formes=[{'id': 'smeargle'}]))
        refused(self, 'names smeargle twice', self.check, dummy_tables(excluded_formes=[
            {'id': 'smeargle', 'reason': 'a'}, {'id': 'smeargle', 'reason': 'b'}]))


class RuleSetsAndDefinitions(unittest.TestCase):
    def test_the_champions_rule_set(self):
        rs = gen_closure.rule_set('champions')
        self.assertEqual(rs['pp_cap'], 20)
        self.assertEqual(rs['files']['learnsets'], 'data/mods/champions/learnsets.ts')
        for rel, sha in rs['inputs'].items():
            self.assertEqual(gen_closure.INPUTS[rel], sha)

    def test_an_unknown_rule_set_is_refused(self):
        refused(self, "rule set 'gen9' is not defined", gen_closure.rule_set, 'gen9')
        refused(self, "rule set 'gen9' is not defined", lambda: dummy_format(rule_set='gen9'))

    def test_reg_mc_keeps_todays_names_and_widths(self):
        ts = gen_closure.load_table_set(ROOT, 'reg-mc')
        self.assertEqual((ts.symbol_prefix, ts.include_guard, ts.stem, ts.learnset_bytes, ts.rule_set_name, ts.pp_cap),
                         ('pool', 'DUOFORGE_DATA_POOL_TABLES_H', 'pool_tables', 64, 'champions', 20))
        self.assertEqual(ts.excluded, {})
        self.assertEqual(ts.showdown_format_id, 'gen9championsvgc2026regmc')

    def test_a_definition_without_tables_builds_none(self):
        refused(self, 'champions-ou.json builds no tables', gen_closure.load_table_set, ROOT, 'champions-ou')

    def test_an_unknown_format_is_refused(self):
        refused(self, "no format definition 'dummy'", gen_closure.load_table_set, ROOT, 'dummy')


class LegalPool(unittest.TestCase):
    """load_legal_pool: the pool must be the definition's format at the pin; exclusions are named and checked."""

    def pool(self, species, format_id='gen9championsvgc2026regmc'):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        os.makedirs(os.path.join(d.name, 'data', 'formats', 'pools'))
        with io.open(os.path.join(d.name, 'data', 'formats', 'pools', 'dummy.json'), 'w', encoding='utf-8') as fh:
            json.dump({'meta': {'showdown_commit': gen_closure.PIN, 'format_id': format_id}, 'items': [],
                       'abilities': [], 'moves': [], 'counts': {}, 'species': species}, fh)
        return d.name

    SPECIES = [{'id': 'aaa', 'kind': 'selectable', 'mechanically_identical_to': None},
               {'id': 'bbb', 'kind': 'selectable', 'mechanically_identical_to': None},
               {'id': 'bbbmega', 'kind': 'mega', 'holders': [{'species': 'bbb'}]},
               {'id': 'ccc', 'kind': 'selectable', 'mechanically_identical_to': None},
               {'id': 'cccstar', 'kind': 'selectable', 'mechanically_identical_to': 'ccc'}]

    def load(self, repo, excluded):
        ts = dummy_format('data/formats/pools/dummy.json', excluded_formes=excluded)
        return gen_closure.load_legal_pool(repo, ts)

    def test_an_excluded_forme_leaves_the_pool(self):
        legal = self.load(self.pool(self.SPECIES), [{'id': 'aaa', 'reason': 'Smeargle-like: refused in O8'}])
        self.assertEqual(legal['species_order'], ['bbb', 'bbbmega', 'ccc', 'cccstar'])
        self.assertNotIn('aaa', legal['species'])

    def test_an_excluded_forme_that_is_not_in_the_pool_fails(self):
        refused(self, 'excludes zzz, which is not a forme of', self.load, self.pool(self.SPECIES),
                [{'id': 'zzz', 'reason': 'gone'}])

    def test_an_excluded_forme_that_another_row_needs_fails(self):
        refused(self, 'excludes bbb, which bbbmega of the pool need', self.load, self.pool(self.SPECIES),
                [{'id': 'bbb', 'reason': 'r'}])
        refused(self, 'excludes ccc, which cccstar of the pool need', self.load, self.pool(self.SPECIES),
                [{'id': 'ccc', 'reason': 'r'}])

    def test_a_pool_of_another_format_fails(self):
        refused(self, 'was not made at the pin for gen9championsvgc2026regmc', self.load,
                self.pool(self.SPECIES, format_id='gen9ou'), [])


class Widths(unittest.TestCase):
    def test_a_learnset_narrower_than_the_moves_fails(self):
        refused(self, 'learnset_bytes 1 holds 8 moves, the pool has 9', gen_closure.forme_legal, [], ['m'] * 9, [],
                None, {}, None, None, 1, 'the test pool')

    def bounds(self, d, bounds):
        repo = ROOT
        gen_closure.check_bounds(d, repo, bounds)

    def data(self, formes=3, moves=5, items=4, abilities=6, legal_moves=0):
        row = {'set_moves': [], 'set_item': 0xFF, 'dex_num': 1, 'weight_hg': 1, 'base': [1] * 6, 'id': 'x'}
        return {'formes': [dict(row, id='f%d' % i) for i in range(formes)], 'moves': [{}] * moves, 'items': [{}] * items,
                'abilities': [{}] * abilities,
                'forme_legal': [{'learnable': [0] * ((moves + 7) // 8), 'moves': ['m'] * legal_moves}] * formes}

    def test_the_set_bounds_are_the_limits(self):
        b = dummy_tables()['bounds']
        self.bounds(self.data(items=200, abilities=230), b)
        refused(self, 'the table set holds at most 230 and 200', self.bounds, self.data(items=201), b)
        refused(self, 'exceed the table set\'s 400 and 600', self.bounds, self.data(formes=401), b)
        refused(self, 'a forme has 301 legal moves, the bound moves_per_forme is 300', self.bounds,
                self.data(moves=400, legal_moves=301), b)

    def test_a_bound_past_the_row_fields_fails(self):
        refused(self, 'exceed the row fields', self.bounds, self.data(), dict(dummy_tables()['bounds'], items=255))
        refused(self, 'exceeds DUOFORGE_DATA_MAX_FORME_MOVES', self.bounds, self.data(),
                dict(dummy_tables()['bounds'], moves_per_forme=513))


class WriterNames(unittest.TestCase):
    def committed(self):
        out = []
        for ext in ('h', 'c'):
            with io.open(os.path.join(ROOT, 'src', 'data', 'pool_tables.' + ext), encoding='ascii') as fh:
                out.append(fh.read().replace('\r\n', '\n'))
        return out

    def test_reg_mc_names_change_nothing(self):
        ts = gen_closure.load_table_set(ROOT, 'reg-mc')
        for text in self.committed():
            self.assertEqual(gen_closure.table_set_names(text, ts), text)

    def test_the_dummy_names_replace_every_pool_name(self):
        ts = dummy_format(excluded_formes=[{'id': 'smeargle', 'reason': 'Sketch is not modelled'}])
        h, c = (gen_closure.table_set_names(t, ts) for t in self.committed())
        for text in (h, c):
            self.assertIsNone(re.search(r'\b(dfi_pool_|DFI_POOL_|DUOFORGE_DATA_POOL_TABLES_H)', text))
        self.assertTrue(h.startswith('#ifndef DUOFORGE_DATA_DUMMY_TABLES_H\n#define DUOFORGE_DATA_DUMMY_TABLES_H\n'))
        self.assertIn(' *   smeargle: Sketch is not modelled\n', h)
        self.assertIn('#include "data/dummy_tables.h"', c)
        self.assertIn('extern const dfi_dummy_forme_data dfi_dummy_formes[DFI_DUMMY_FORME_COUNT];', h)


@unittest.skipUnless(CHECKOUT, 'needs the pinned checkout (duoforge.data.table_sets_pinned)')
class PinnedDummyFormat(unittest.TestCase):
    """The whole pool tables of the made-up format, built from the pinned checkout: Reg M-C's pool with one forme
    excluded, another prefix, guard and stem, and a wider learnset."""

    @classmethod
    def setUpClass(cls):
        cls.reg = gen_closure.load_table_set(ROOT, 'reg-mc')
        with io.open(os.path.join(ROOT, cls.reg.legal_pool), encoding='utf-8') as fh:
            pool = json.load(fh)
        needed = {sp.get('mechanically_identical_to') for sp in pool['species']}
        needed |= {h['species'] for sp in pool['species'] for h in sp.get('holders', ())}
        prefix = {s[0] for g in (gen_closure.SETS, gen_closure.SETS_C, gen_closure.SETS_G2) for s in g}
        cls.out = [sp['id'] for sp in pool['species'] if sp['kind'] == 'selectable' and sp['id'] not in needed
                   and sp['id'] not in prefix and sp['mechanically_identical_to'] is None][-1]
        cls.ts = dummy_format(excluded_formes=[{'id': cls.out, 'reason': 'left out by the test'}])
        dc = gen_closure.build(CHECKOUT, cls.reg)
        dx = gen_closure.build(CHECKOUT, cls.reg, ext=True)
        cls.d_reg = gen_closure.build_pool(CHECKOUT, ROOT, dx, cls.reg)
        cls.h_reg = gen_closure.render_pool(cls.d_reg, dx, cls.reg)[0]
        cls.d = gen_closure.build_pool(CHECKOUT, ROOT, dx, cls.ts)
        cls.h, cls.c = gen_closure.render_pool(cls.d, dx, cls.ts)[:2]
        del dc

    def test_reg_mc_is_the_committed_header(self):
        with io.open(os.path.join(ROOT, 'src', 'data', 'pool_tables.h'), encoding='ascii') as fh:
            self.assertEqual(self.h_reg, fh.read().replace('\r\n', '\n'))

    def test_the_excluded_forme_has_no_row(self):
        self.assertEqual(len(self.d['formes']), len(self.d_reg['formes']) - 1)
        self.assertNotIn(self.out, [f['id'] for f in self.d['formes']])
        self.assertNotIn('#define DFI_FORME_%s ' % self.out.upper(), self.h)
        self.assertIn(' *   %s: left out by the test\n' % self.out, self.h)

    def test_the_names_and_the_learnset_width_are_the_sets(self):
        self.assertIn('#define DFI_DUMMY_LEARN_BYTES 65u', self.h)
        self.assertTrue(all(len(fl['learnable']) == 65 for fl in self.d['forme_legal']))
        for text in (self.h, self.c):
            self.assertIsNone(re.search(r'\b(dfi_pool_|DFI_POOL_)', text))

    def test_the_pp_cap_is_the_rule_sets(self):
        moves_ts = gen_closure.Source(CHECKOUT, 'data/moves.ts')
        champ = gen_closure.Source(CHECKOUT, self.reg.file('moves'))
        capped = gen_closure.parse_pool_move('growl', moves_ts, champ, pp_cap=self.reg.pp_cap)
        uncapped = gen_closure.parse_pool_move('growl', moves_ts, champ, pp_cap=None)
        self.assertEqual((capped['pp_base'], uncapped['pp_base']), (40, 40))
        self.assertLess(capped['pp_max'], uncapped['pp_max'])


if __name__ == '__main__':
    unittest.main()
