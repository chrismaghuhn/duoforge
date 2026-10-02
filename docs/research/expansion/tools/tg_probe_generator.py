#!/usr/bin/env python3
"""Runs tools/datagen/gen_closure.py's parse_move (the extended-table mode of
decision 0009) over a list of move ids and reports, per move, whether the
generator encodes it or rejects it, and with which message. Read-only research
tooling for docs/research/expansion/team-gaps.md: it imports the generator
unchanged, so the answer is what `gen_closure.py --team-c` would do today.

usage: python tg_probe_generator.py <pinned checkout> [move id ...]

Without move ids it probes the 22 gap moves of the team-gaps note. The output
is one JSON object per line: {"move", "result": "encoded"|"rejected",
"message"|"fields"}.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tools', 'datagen'))
import gen_closure as g  # noqa: E402

GAP_MOVES = ['uturn', 'rockslide', 'throatchop', 'encore', 'doubleedge', 'thunderbolt', 'scald', 'wideguard',
             'flashcannon', 'extremespeed', 'headsmash', 'firstimpression', 'bulkup', 'liquidation', 'icepunch',
             'shadowclaw', 'recover', 'soak', 'psychicnoise', 'drumbeating', 'lowkick', 'dazzlinggleam']


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    root = sys.argv[1]
    moves = sys.argv[2:] or GAP_MOVES
    base = g.Source(root, 'data/moves.ts')
    champ = g.Source(root, 'data/mods/champions/moves.ts')
    for mid in moves:
        out = {'move': mid}
        try:
            rec = g.parse_move(mid, base, champ, ext=True)
            out['result'] = 'encoded'
            out['fields'] = {k: rec[k] for k in ('type', 'category', 'base_power', 'accuracy', 'pp_base', 'pp_max',
                                                 'priority', 'target_class', 'crit_ratio', 'flags', 'recoil', 'drain',
                                                 'sec_chance', 'sec_kind', 'sec_param', 'boost_role', 'boosts',
                                                 'primary_status', 'side_condition', 'pseudo_weather', 'special')}
            out['refs'] = rec['refs']
        except SystemExit as e:  # the generator's fail(): never a silent encoding
            out['result'] = 'rejected'
            out['message'] = str(e)
        except KeyError as e:  # a table lookup that has no entry: still a loud stop
            out['result'] = 'rejected'
            out['message'] = 'KeyError %s (an encoding table has no entry)' % e
        print(json.dumps(out))


if __name__ == '__main__':
    main()
