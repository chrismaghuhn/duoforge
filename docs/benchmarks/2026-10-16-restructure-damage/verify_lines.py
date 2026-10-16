"""Check that every line of dfi_get_damage at main is unchanged in the cut, in order.

Usage: python3 verify_lines.py <repo> <base sha>
Each phase header must contain its original line range contiguously; the orchestrator in turn.c must contain the
remaining lines (head and tail); the one moved line is crit_mult (into the crit phase, its only reader).
"""
import subprocess, sys
from pathlib import Path
repo, base = Path(sys.argv[1]), sys.argv[2]
old = subprocess.check_output(['git', 'show', f'{base}:src/combat/turn.c'], cwd=repo, text=True).split('\n')
new_turn = (repo / 'src/combat/turn.c').read_text().split('\n')
seg = lambda a, b: old[a - 1:b]
def contains(hay, needle):
    return any(hay[i:i + len(needle)] == needle for i in range(len(hay) - len(needle) + 1))
phases = {'crit': (1147, 1180), 'stats': (1181, 1267), 'base_power': (1268, 1490), 'attack': (1491, 1543),
          'base_damage': (1544, 1605), 'modify_damage': (1606, 1756)}
covered = set()
for name, (a, b) in phases.items():
    h = (repo / f'src/combat/mechanics/damage/{name}.h').read_text().split('\n')
    assert contains(h, seg(a, b)), name
    covered |= set(range(a, b + 1))
crit_h = (repo / 'src/combat/mechanics/damage/crit.h').read_text().split('\n')
assert old[1097] in crit_h; covered.add(1098)
assert contains(new_turn, seg(1095, 1097)) and contains(new_turn, seg(1099, 1146)) and contains(new_turn, seg(1757, 1760))
covered |= set(range(1095, 1098)) | set(range(1099, 1147)) | set(range(1757, 1761))
assert covered == set(range(1095, 1761)), sorted(set(range(1095, 1761)) - covered)
# Everything outside the function is unchanged: turn.c before 1095 and after 1760.
assert new_turn[:1094] == old[:1094]
assert new_turn[-(len(old) - 1760):] == old[1760:]
print('all 666 lines of dfi_get_damage unchanged and in order; turn.c outside the function unchanged')
