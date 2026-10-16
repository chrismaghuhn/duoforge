"""Executed instructions (callgrind Ir) of the bench run, before and after, both IPO modes; deterministic, one run each.

Usage: OUT=<proof dir with before/ and after/ bins-<mode>/duoforge_bench> python3 callgrind_gate.py
Writes OUT/callgrind.json: total Ir per binary, Ir of the library's functions, and the ratio after/before per mode.
"""
import json, os, re, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
out = Path(os.environ['OUT'])
ARGS = ['--battles', '1024', '--repetitions', '3', '--warmup', '2', '--max-steps', '128', '--policy-seed', '20261001',
        '--battle-seed', '7001', '--families', 'step,events']
def run(side, mode):
    exe = out / side / f'bins-{mode}' / 'duoforge_bench'
    cg = out / f'callgrind-{side}-{mode}.out'
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        subprocess.run(['valgrind', '--tool=callgrind', f'--callgrind-out-file={cg}', str(exe), *ARGS, '--out', f'{tmp}/run.json'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        record = json.loads(Path(f'{tmp}/run.json').read_text())['record']
    total = int(re.search(r'^summary: (\d+)', cg.read_text(), re.M).group(1))
    ann = subprocess.check_output(['callgrind_annotate', '--inclusive=yes', '--threshold=100', str(cg)], text=True)
    funcs = {}
    for line in ann.splitlines():
        m = re.match(r'^\s*([\d,]+)\s+\([^)]*\)\s+\S*:(dfi_residual\w*|dfi_turn_run\w*|dfi_residual_events_run\S*)', line)
        if m:
            funcs[m.group(2)] = int(m.group(1).replace(',', ''))
    return side, mode, dict(total_ir=total, inclusive_ir=funcs, record=record)
jobs = [(s, m) for m in ('ipo', 'noipo') for s in ('before', 'after')]
with ThreadPoolExecutor(2) as pool:
    res = list(pool.map(lambda j: run(*j), jobs))
d = {f'{s}-{m}': v for s, m, v in res}
for m in ('ipo', 'noipo'):
    assert d[f'before-{m}']['record'] == d[f'after-{m}']['record'], 'bench record differs'
    d[f'ratio-{m}'] = d[f'after-{m}']['total_ir'] / d[f'before-{m}']['total_ir']
    d[f'gate-{m}'] = d[f'ratio-{m}'] <= 1.01
(out / 'callgrind.json').write_text(json.dumps(d, indent=1, sort_keys=True) + '\n')
print(json.dumps({k: v for k, v in d.items() if k.startswith(('ratio', 'gate'))}, indent=1))
for k in sorted(d):
    if not k.startswith(('ratio', 'gate')):
        print(k, d[k]['total_ir'], d[k]['inclusive_ir'])
