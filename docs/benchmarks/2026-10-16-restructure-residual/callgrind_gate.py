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
    def table(inclusive):
        ann = subprocess.check_output(['callgrind_annotate', f'--inclusive={inclusive}', '--threshold=100', str(cg)], text=True)
        rows = {}
        for line in ann.splitlines():
            m = re.match(r'^\s*([\d,]+)\s+\([^)]*\)\s+\S*:((?:dfi_residual|dfi_turn_run)[\w.]*)', line)
            if m:
                rows[m.group(2)] = rows.get(m.group(2), 0) + int(m.group(1).replace(',', ''))
        return rows
    self_ir, incl_ir = table('no'), table('yes')
    clones = sorted(k for k in self_ir if k.startswith('dfi_residual_events_run'))
    funcs = dict(self_ir=self_ir, inclusive_ir=incl_ir, residual_clones=clones,
                 residual_self_ir_sum=sum(self_ir[k] for k in clones))
    import hashlib
    return side, mode, dict(total_ir=total, binary=str(exe), binary_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(), **funcs, record=record)
jobs = [(s, m) for m in ('ipo', 'noipo') for s in ('before', 'after')]
with ThreadPoolExecutor(2) as pool:
    res = list(pool.map(lambda j: run(*j), jobs))
d = {f'{s}-{m}': v for s, m, v in res}
for m in ('ipo', 'noipo'):
    assert d[f'before-{m}']['record'] == d[f'after-{m}']['record'], 'bench record differs'
    d[f'ratio-{m}'] = d[f'after-{m}']['total_ir'] / d[f'before-{m}']['total_ir']
    d[f'gate-{m}'] = d[f'ratio-{m}'] <= 1.01
    d[f'residual-self-ratio-{m}'] = d[f'after-{m}']['residual_self_ir_sum'] / d[f'before-{m}']['residual_self_ir_sum']
    d[f'total-delta-{m}'] = d[f'after-{m}']['total_ir'] - d[f'before-{m}']['total_ir']
    d[f'residual-self-delta-{m}'] = d[f'after-{m}']['residual_self_ir_sum'] - d[f'before-{m}']['residual_self_ir_sum']
(out / 'callgrind.json').write_text(json.dumps(d, indent=1, sort_keys=True) + '\n')
print(json.dumps({k: v for k, v in d.items() if k.startswith(('ratio', 'gate', 'residual-', 'total-'))}, indent=1))
for k in sorted(d):
    if not k.startswith(('ratio', 'gate', 'residual-', 'total-')):
        print(k, d[k]['total_ir'], d[k]['residual_clones'], d[k]['residual_self_ir_sum'], d[k]['binary_sha256'][:12])
