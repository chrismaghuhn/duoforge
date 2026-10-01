#!/usr/bin/env python3
"""Read-only probe: what does tools/datagen/gen_closure.py say about the Team C moves and formes today?

usage: python docs/research/third-team/probe-generator.py [pinned checkout]

It imports the generator and calls its own parsers one entry at a time; it
writes nothing and changes nothing. A move that fails prints the generator's
own explicit message (the gate decision 0006 asks for); a move that parses is
only data-complete: it still needs a handler in C and an entry in
src/data/support_manifest.c before a battle may use it.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'tools', 'datagen'))
import gen_closure as g  # noqa: E402

ROOT = sys.argv[1] if len(sys.argv) > 1 else 'C:/Dev/src/pokemon-showdown'
src = {rel: g.Source(ROOT, rel) for rel in g.INPUTS}  # also checks the input hashes against the pin
base, champ = src['data/moves.ts'], src['data/mods/champions/moves.ts']

SETS = [  # as in team-c.txt: forme, ability, item, moves
    ('sneasler', 'unburden', 'whiteherb', ['closecombat', 'direclaw', 'protect', 'fakeout']),
    ('incineroar', 'intimidate', 'sitrusberry', ['fakeout', 'flareblitz', 'partingshot', 'darkestlariat']),
    ('salamence', 'intimidate', 'salamencite', ['protect', 'hypervoice', 'dracometeor', 'tailwind']),
    ('indeedeef', 'psychicsurge', 'colburberry', ['followme', 'trickroom', 'helpinghand', 'psychic']),
    ('kingambit', 'defiant', 'chopleberry', ['kowtowcleave', 'suckerpunch', 'ironhead', 'protect']),
    ('basculegion', 'adaptability', 'choicescarf', ['lastrespects', 'wavecrash', 'aquajet', 'protect']),
]
VARIANT_MOVES = ['flipturn']  # the Basculegion variant of README.md

print('== moves')
seen = []
for _sp, _ab, _it, mv in SETS:
    seen += [m for m in mv if m not in seen]
for m in seen + VARIANT_MOVES:
    try:
        rec = g.parse_move(m, base, champ)
        print('%-14s parses  special=%-13s flags=%-3d secondary=(%d%%, kind %d) boost_role=%d' % (
            m, g.SPECIAL_IDS[rec['special']], rec['flags'], rec['sec_chance'], rec['sec_kind'], rec['boost_role']))
    except SystemExit as e:
        print('%-14s FAILS   %s' % (m, e))

print('== formes, learnsets, abilities, items')
dex, formats, learn = src['data/pokedex.ts'], src['data/mods/champions/formats-data.ts'], src['data/mods/champions/learnsets.ts']
for sp, ab, it, mv in SETS:
    try:
        fo = g.parse_forme(sp, dex, formats)
        problems = []
        if ab not in fo['abilities']:
            problems.append('ability %s not among %s' % (ab, fo['abilities']))
        le = learn.entry(sp)
        if le is None:
            problems.append('no champions learnset entry')
        else:
            text = '\n'.join(le[2])
            problems += ['learnset lacks %s' % m for m in mv if not re.search(r'\b%s: \[' % m, text)]
        if src['data/abilities.ts'].entry(ab) is None:
            problems.append('ability entry missing')
        e = src['data/items.ts'].entry(it)
        if e is None:
            problems.append('item entry missing')
        elif 'isNonstandard' in '\n'.join(e[2]) and src['data/mods/champions/items.ts'].entry(it) is None:
            problems.append('item nonstandard without a champions override')
        print('%-12s gender_rule=%d weight_hg=%-5d %s' % (sp, fo['gender_rule'], fo['weight_hg'],
                                                          ('PROBLEMS: ' + '; '.join(problems)) if problems else 'lookups ok'))
    except SystemExit as e:
        print('%-12s FAILS %s' % (sp, e))
mega = g.parse_forme('salamencemega', dex, formats)
print('%-12s abilities=%s required_item=%s weight_hg=%d' % ('salamencemega', mega['abilities'], mega['required_item'], mega['weight_hg']))
print('type chart keys without a consumer:', sorted(g.IGNORED_TYPE_KEYS), '(psn and tox matter for Dire Claw)')
