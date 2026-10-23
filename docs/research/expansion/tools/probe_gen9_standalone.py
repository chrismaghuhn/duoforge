#!/usr/bin/env python3
"""Scope probe of a standalone Gen 9 table set (O8, docs/research/expansion/gen9-standalone-tables.md): which fact
checks, move rows and family columns of tools/datagen/tablegen hold on the base data alone (an empty override file for
every Champions file, no PP cap). Research only, not part of the build; written against main 80bb7524 plus O8.

usage: python3 -I docs/research/expansion/tools/probe_gen9_standalone.py <repo> <pinned checkout>
"""
import sys, os, io, inspect
repo, root = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(repo, 'tools', 'datagen'))
import gen_closure as g
from tablegen import tables as T

class Empty:
    """An override file that has no entries (the gen9 rule set has none)."""
    rel = '(none)'; lines = []
    def entry(self, key): return None
    def first_lines(self): return {}
    def ref(self, key): raise SystemExit('ref of empty override')

S = lambda rel, pins=None: g.Source(root, rel, pins)
R = g.READER_INPUTS
moves_ts, items_ts, abil_ts = S('data/moves.ts'), S('data/items.ts'), S('data/abilities.ts')
E = Empty()
calls = [
 ('g8_conditions', lambda: g.check_g8_conditions(moves_ts)),
 ('c4', lambda: g.check_c4_facts(moves_ts, E)), ('c5', lambda: g.check_c5_facts(moves_ts, E)),
 ('c1', lambda: g.check_c1_facts(moves_ts, E)), ('a0', lambda: g.check_a0_facts(moves_ts, E)),
 ('g15', lambda: g.check_g15_facts(moves_ts, items_ts)),
 ('g30', lambda: g.check_g30_facts(abil_ts, E)),
 ('a2a', lambda: g.check_a2a_facts(abil_ts, E, {r: S(r, R) for r in ('sim/pokemon.ts', 'data/conditions.ts')})),
 ('g28_items', lambda: g.check_g28_items(items_ts)),
 ('g34', lambda: g.check_g34_facts(abil_ts, E, items_ts, E)),
 ('g61', lambda: g.check_g61_facts(root, abil_ts, E)),
 ('g49', lambda: g.check_g49_facts(items_ts, E)),
 ('g59', lambda: g.check_g59_facts(abil_ts, E, S('sim/pokemon.ts', R), S('data/conditions.ts', R))),
 ('g79', lambda: g.check_g79_facts(S('sim/field.ts', R), S('sim/battle.ts', R), S('sim/battle-actions.ts', R), S('data/conditions.ts', R))),
 ('g55_items', lambda: g.check_g55_items(items_ts, E)),
 ('g37', lambda: g.check_g37_facts(abil_ts, E)), ('g57', lambda: g.check_g57_facts(abil_ts, E)),
 ('i2', lambda: g.check_i2_facts(abil_ts, E)),
 ('g32_entries', lambda: g.check_g32_entries(items_ts, E, abil_ts, E)),
 ('weather', lambda: g.check_weather_facts(S('data/conditions.ts', R), moves_ts)),
 ('g56', lambda: g.check_g56_facts(S('data/conditions.ts', R), moves_ts)),
 ('g58', lambda: g.check_g58_facts(moves_ts)), ('g72b', lambda: g.check_g72b_facts(moves_ts)),
 ('g84', lambda: g.check_g84_facts(moves_ts)), ('g82', lambda: g.check_g82_facts(moves_ts)),
 ('g80', lambda: g.check_g80_facts(moves_ts)), ('g76', lambda: g.check_g76_facts(moves_ts)),
 ('g78', lambda: g.check_g78_facts(moves_ts)), ('g96', lambda: g.check_g96_facts(moves_ts)),
 ('g88', lambda: g.check_g88_facts(moves_ts)),
 ('c2', lambda: g.check_c2_facts(moves_ts, E)),
 ('c2_part4', lambda: g.check_c2_facts(moves_ts, E, only=g.C1_PART4_FACTS)),
 ('g86', lambda: g.check_g86_facts(moves_ts)), ('g92', lambda: g.check_g92_facts(moves_ts)),
 ('g90', lambda: g.check_g90_facts(S('data/conditions.ts', R), moves_ts)),
]
ok, bad = [], []
for name, fn in calls:
    try:
        fn(); ok.append(name)
    except SystemExit as e:
        bad.append((name, str(e.code)[:160]))
    except Exception as e:
        bad.append((name, '%s: %s' % (type(e).__name__, str(e)[:140])))
print('hold on the base data:', len(ok), ok)
print('fail:', len(bad))
for n, m in bad: print('  ', n, '--', m)
# Moves: parse every gen9ou pool move without overrides and without a PP cap.
import json
pool = json.load(open(os.path.join(repo, 'data/formats/pools/gen9ou.json')))
pm_bad = []
for m in pool['moves']:
    try:
        g.parse_pool_move(m['id'], moves_ts, E, pp_cap=None)
    except SystemExit as e:
        pm_bad.append((m['id'], str(e.code)[:120]))
    except Exception as e:
        pm_bad.append((m['id'], type(e).__name__ + ' ' + str(e)[:100]))
print('pool moves that fail parse_pool_move without overrides:', len(pm_bad), 'of', len(pool['moves']))
for x in pm_bad[:15]: print('  ', x)
# Families: derive the item and ability families on the base entries alone.
from tablegen import families as F, items as I, abilities as A
item_of = {i: f for f, ids in I.ITEM_MEMBERS.items() for i in ids}
ab_of = {a: f for f, ids in A.ABILITY_MEMBERS.items() for a in ids}
fb = []
for it in pool['items']:
    try:
        F.derive_family(items_ts, E, it['id'], item_of.get(it['id'], 'NONE'), I.ITEM_MATCHERS, 'item')
    except SystemExit as e:
        fb.append(('item', it['id'], str(e.code)[:120]))
for ab in pool['abilities']:
    try:
        F.derive_family(abil_ts, E, ab['id'], ab_of.get(ab['id'], 'NONE'), A.ABILITY_MATCHERS, 'ability')
    except SystemExit as e:
        fb.append(('ability', ab['id'], str(e.code)[:120]))
print('family derivations that fail on base entries:', len(fb))
for x in fb[:15]: print('  ', x)
