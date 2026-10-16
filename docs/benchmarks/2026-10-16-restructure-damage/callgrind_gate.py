"""Gate (b) of a phase cut: executed instructions (valgrind --tool=callgrind) of one bench run, before vs after.

Usage: OUT=<proof dir> python3 callgrind_gate.py
Runs bins-<mode>/duoforge_bench of the before and after phases (IPO on and off) on the same workload under callgrind,
records the total Ir and the inclusive Ir of dfi_get_damage, and checks after/before <= 1.010 per profile.
"""
from pathlib import Path
import json, os, re, subprocess

out = Path(os.environ['OUT'])
dest = out / 'callgrind'
dest.mkdir(exist_ok=True)
ARGS = ['--battles', '128', '--repetitions', '1', '--warmup', '0', '--max-steps', '128', '--policy-seed', '20261001',
        '--battle-seed', '7001', '--families', 'step,events', '--workers', '1']
LIMIT = 1.010
result = {'workload': ARGS, 'limit': LIMIT, 'profiles': {}}
for mode in ('ipo', 'noipo'):
    row = {}
    for phase in ('before', 'after'):
        exe = out / phase / f'bins-{mode}' / 'duoforge_bench'
        cg = dest / f'{mode}-{phase}.callgrind'
        run = dest / f'{mode}-{phase}.json'
        subprocess.run(['valgrind', '--tool=callgrind', f'--callgrind-out-file={cg}', str(exe), *ARGS, '--out', str(run)],
                       check=True, stdout=subprocess.DEVNULL, stderr=(dest / f'{mode}-{phase}.log').open('w'))
        summary = next(l for l in cg.read_text().splitlines() if l.startswith('summary:') or l.startswith('totals:'))
        total = int(summary.split()[1])
        ann = subprocess.check_output(['callgrind_annotate', '--inclusive=yes', '--threshold=100', str(cg)], text=True)
        m = re.search(r'^\s*([\d,]+)\s.*\bdfi_get_damage\b', ann, re.M)
        incl = int(m.group(1).replace(',', '')) if m else None
        rec = json.loads(run.read_text())['record']
        row[phase] = {'ir_total': total, 'ir_dfi_get_damage_inclusive': incl, 'record': rec}
    assert row['before']['record'] == row['after']['record'], 'bench record differs'
    for k in ('ir_total', 'ir_dfi_get_damage_inclusive'):
        if row['before'][k]:
            row[k + '_ratio'] = row['after'][k] / row['before'][k]
    row['pass'] = row['ir_total_ratio'] <= LIMIT
    for p in ('before', 'after'):
        del row[p]['record']
    result['profiles'][mode] = row
    print(mode, json.dumps(row), flush=True)
(dest / 'callgrind-gate.json').write_text(json.dumps(result, indent=2) + '\n')
assert all(r['pass'] for r in result['profiles'].values()), 'callgrind gate failed'
print('callgrind gate pass', flush=True)
