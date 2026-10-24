#!/usr/bin/env python3
"""The format definition data/formats/reg-mc.json against the committed tables (restructure step 10).

Without a checkout, with code of its own, this test checks that:
  - the definition loads: its keys, the facts' shapes, the pool source it names (sha256, Showdown commit, format id);
  - src/data/formats/reg-mc/format_tables.h is what tools/datagen/gen_format.py makes of it;
  - the definition reproduces today's pool tables exactly: after the rows of the content steps (28 formes, 72 moves,
    52 items, 29 abilities: the closure, Team C and G2 prefix), the forme, move, item and ability rows of
    src/data/formats/reg-mc/pool_tables.c are the pool source's ids in its own order (a forme followed by its Mega formes, the
    cosmetic copies left out, then the battle-only Blade row of step G66), and the counts are 347, 511, 166 and 215;
  - the format facts in code are named: the engine's level, brought count and Stat Point limits are the
    DFI_FORMAT_* constants, and the Python context's defaults are the layout's roster and the definition's pick.
tools/datagen/gen_format.py --pin (duoforge.data.format_pin) compares every quote with the pinned checkout.

usage: python3 tools/datagen/tests/test_format.py
"""
import ast
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import gen_format  # noqa: E402
import test_pool_rows as pool  # noqa: E402

ROOT = gen_format.REPO
FMT = gen_format.load_format()
# The rows of the content steps that the whole-pool rows follow (decision 0015 section 4.2).
STEP_ROWS = {'formes': 28, 'moves': 72, 'items': 52, 'abilities': 29}
BATTLE_ONLY_ROWS = ['aegislashblade']  # step G66


def read(rel):
    with io.open(os.path.join(ROOT, rel), 'rb') as fh:
        return fh.read().decode('utf-8').replace('\r\n', '\n')


def legal():
    with io.open(os.path.join(ROOT, FMT['pool']['source']), encoding='utf-8') as fh:
        return json.load(fh)


def expected_formes(source, prefix):
    seen = set(prefix)
    megas = {}
    for rec in source['species']:
        if rec['kind'] == 'mega':
            megas.setdefault(rec['holders'][0]['species'], []).append(rec['id'])
    out = list(prefix)
    for rec in source['species']:
        if rec['kind'] != 'selectable' or rec['mechanically_identical_to'] is not None:
            continue
        out += [rec['id']] if rec['id'] not in seen else []
        out += [m for m in megas.get(rec['id'], []) if m not in seen]
    return out + BATTLE_ONLY_ROWS


def expected_rows(order, prefix):
    seen = set(prefix)
    return list(prefix) + [i for i in order if i not in seen]


class FormatDefinition(unittest.TestCase):
    def test_the_definition_names_the_pool_source(self):
        self.assertEqual(FMT['id'], 'reg-mc')
        self.assertEqual(FMT['showdown_format_id'], 'gen9championsvgc2026regmc')
        meta = legal()['meta']
        self.assertEqual((meta['showdown_commit'], meta['format_id']), (FMT['showdown_commit'], FMT['showdown_format_id']))
        self.assertEqual(gen_format.file_sha256(os.path.join(ROOT, FMT['pool']['source'])), FMT['pool']['sha256'])

    def test_the_header_is_generated_from_the_definition(self):
        self.assertEqual(read(gen_format.HEADER), gen_format.render(FMT))

    def test_the_definition_reproduces_the_pool_tables(self):
        source = legal()
        rows = {'formes': pool.Rows.formes, 'moves': pool.Rows.moves, 'items': pool.Rows.items,
                'abilities': pool.Rows.abilities}
        orders = {'moves': [m['id'] for m in source['moves']], 'items': [i['id'] for i in source['items']],
                  'abilities': [a['id'] for a in source['abilities']]}
        for kind, have in rows.items():
            prefix = have[:STEP_ROWS[kind]]
            want = expected_formes(source, prefix) if kind == 'formes' else expected_rows(orders[kind], prefix)
            self.assertEqual(have, want, kind)
            # No shorter prefix gives the same rows: the step rows end exactly there.
            shorter = have[:STEP_ROWS[kind] - 1]
            again = expected_formes(source, shorter) if kind == 'formes' else expected_rows(orders[kind], shorter)
            self.assertNotEqual(have, again, kind)
        self.assertEqual([len(rows[k]) for k in ('formes', 'moves', 'items', 'abilities')], [347, 511, 166, 215])
        self.assertEqual([len(rows[k]) for k in ('formes', 'moves', 'items', 'abilities')],
                         [pool.define('DFI_POOL_%s_COUNT' % k) for k in ('FORME', 'MOVE', 'ITEM', 'ABILITY')])
        self.assertEqual(rows['moves'][STEP_ROWS['moves']:].count('struggle'), 0)
        self.assertIn('struggle', rows['moves'][:STEP_ROWS['moves']])

    def test_the_format_facts_in_code_are_named(self):
        self.assertIn('\n#define DFI_LEVEL DFI_FORMAT_LEVEL\n', read('src/combat/turn.c'))
        self.assertIn('\n#define DFI_CLOSURE_BROUGHT_COUNT DFI_FORMAT_BROUGHT_COUNT\n',
                      read('src/state/context_internal.h'))
        formulas = read('src/data/formulas.h')
        self.assertIn('\n#define DFI_STAT_POINTS_MAX DFI_FORMAT_STAT_POINTS_MAX ', formulas)
        self.assertIn('\n#define DFI_STAT_POINTS_TOTAL_MAX DFI_FORMAT_STAT_POINTS_TOTAL_MAX ', formulas)
        for rel in ('src/state/context_internal.h', 'src/data/formulas.h'):
            self.assertIn('\n#include "data/formats/reg-mc/format_tables.h" /* the format facts (restructure step 10) */\n', read(rel), rel)
        tree = ast.parse(read('python/duoforge/context.py'))
        consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                  if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
        self.assertEqual(consts['_FORMAT_BROUGHT_COUNT'], FMT['facts']['picked_team_size']['value'])
        init = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '__init__'][0]
        self.assertEqual([ast.unparse(d) for d in init.args.defaults],
                         ['_layout.DATA_KIND_CLOSURE', '_layout.MAX_ROSTER', '_FORMAT_BROUGHT_COUNT'])


if __name__ == '__main__':
    unittest.main()
