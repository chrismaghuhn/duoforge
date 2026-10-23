"""Collect the proof of restructure 5c (number spaces) into the committed proof dir: counts and hashes only.

Usage: OUT=<proof dir outside the repo> DEST=<docs/benchmarks/...> REPO=<repo> python3 summarize.py
"""
from pathlib import Path
import hashlib, json, os, re, subprocess, xml.etree.ElementTree as ET

out, dest, repo = Path(os.environ['OUT']), Path(os.environ['DEST']), Path(os.environ['REPO'])
sha = lambda b: hashlib.sha256(b).hexdigest()
rd = lambda p: (out / p).read_bytes()
s = {'before': json.loads(rd('before/provenance.json')), 'after': json.loads(rd('after/provenance.json'))}
assert not s['before']['dirty'] and not s['after']['dirty']

inv = {}
for m in ('ipo', 'noipo', 'debug'):
    a, b = rd(f'after/inventory-{m}.txt'), rd(f'before/inventory-{m}.txt')
    inv[m] = {'equal': a == b, 'names': a.decode().count('\n'), 'sha256': sha(a)}
s['P1_inventory'] = inv
norm = lambda x: {t['name']: {k: v for k, v in t.items() if k != 'backtrace'} for t in x['tests']}
COMMAND_CHANGES = set()
strip = lambda t: {k: v for k, v in t.items() if k != 'command'}
eq, changed = True, set()
for m in ('ipo', 'noipo', 'debug'):
    a_, b_ = norm(json.loads(rd(f'after/ctest-{m}.json'))), norm(json.loads(rd(f'before/ctest-{m}.json')))
    for n in b_:
        if a_[n] != b_[n]:
            changed.add(n)
            eq = eq and n in COMMAND_CHANGES and strip(a_[n]) == strip(b_[n])
s['P1_properties_equal'] = eq
s['P1_command_changed'] = sorted(changed)
sel = {}
for p in ('before', 'after'):
    for m in ('ipo', 'noipo'):
        root = ET.parse(out / p / f'proofs-{m}.xml').getroot()
        cases = root.iter('testcase')
        stat = [c.get('status') for c in cases]
        sel[f'{p}-{m}'] = {'tests': len(stat), 'passed': stat.count('run'), 'names_sha256': sha(rd(f'{p}/selected-{m}.json'))}
s['P1_selected_tests'] = sel

ref = {}
for m in ('ipo', 'noipo'):
    a, b = rd(f'after/reference-{m}/reference-results.json'), rd(f'before/reference-{m}/reference-results.json')
    ref[m] = {'equal': a == b, 'sha256': sha(a)}
res = json.loads(rd('after/reference-ipo/reference-results.json'))
rows = [(v, r['name'], r['sha256'], r['steps'], r['stops']) for v, d in sorted(res.items()) for r in d['per_battle']]
ref['variants'] = len(res)
ref['executions'] = len(rows)
ref['unique_battles'] = len({r[1] for r in rows})
ref['steps'] = sum(r[3] for r in rows)
ref['stops'] = sum(r[4] for r in rows)
ref['checks'] = {v: d['checks'] for v, d in sorted(res.items())}
ref['native_reports_equal'] = {m: rd(f'after/native-{m}.json') == rd(f'before/native-{m}.json') for m in ('ipo', 'noipo', 'debug')}
s['P2_reference'] = ref
(dest / 'per-battle-digests.tsv').write_text('variant\tbattle\tsha256\tsteps\tstops\n' +
                                             ''.join('\t'.join(map(str, r)) + '\n' for r in rows))
(dest / 'test-inventory.txt').write_bytes(rd('after/inventory-ipo.txt'))

git = lambda *a: subprocess.check_output(['git', *a], cwd=repo, text=True)
s['P3_perft_pins_sha256'] = sha((repo / 'tests/perft/pins.json').read_bytes())
s['P3_perft_pins_unchanged'] = git('diff', '--stat', s['before']['commit'], s['after']['commit'], '--', 'tests/perft') == ''
bench_sha = re.findall(r'BENCH_SHA256\s*=\s*[\'"]([0-9a-f]{64})', (repo / 'python/tests/test_bench.py').read_text()) \
    if (repo / 'python/tests/test_bench.py').exists() else []
s['P4_bench_sha256_unchanged'] = git('diff', '--stat', s['before']['commit'], s['after']['commit'], '--', 'python') == ''
s['P5_generated_unchanged'] = git('diff', '--stat', s['before']['commit'], s['after']['commit'], '--', 'src/data',
                                  'tools/datagen', 'tests/reference') == ''
s['P5_fingerprints'] = {m: json.loads(rd(f'after/fingerprints-{m}.json')) for m in ('ipo', 'noipo', 'debug')}
s['P5_fingerprints_equal'] = all(rd(f'after/fingerprints-{m}.json') == rd(f'before/fingerprints-{m}.json')
                                 for m in ('ipo', 'noipo', 'debug'))
pub = {'include_diff_empty': git('diff', '--stat', s['before']['commit'], s['after']['commit'], '--', 'include') == ''}
for m in ('ipo', 'noipo', 'debug'):
    e, l = rd(f'after/exports-{m}.txt'), rd(f'after/layout-{m}.json')
    pub[m] = {'equal': e == rd(f'before/exports-{m}.txt') and l == rd(f'before/layout-{m}.json'),
              'exports': e.decode().count('\n'), 'exports_sha256': sha(e), 'layout_sha256': sha(l)}
s['P6_public_surface'] = pub

obj = {}
for m in ('ipo', 'noipo', 'debug'):
    a, b = json.loads(rd(f'after/objects-{m}.json')), json.loads(rd(f'before/objects-{m}.json'))
    obj[m] = {'compared': len(b), 'differing': sorted(k for k in b if a.get(k) != b[k]),
              'library_before': b['libduoforge_shared.so'], 'library_after': a['libduoforge_shared.so']}
s['object_identity'] = obj
s['changed_files'] = git('diff', '--name-only', s['before']['commit'], s['after']['commit']).split()
(dest / 'proof-summary.json').write_text(json.dumps(s, indent=1, sort_keys=True) + '\n')
print(json.dumps({k: s[k] for k in ('P1_inventory', 'P1_properties_equal', 'P1_command_changed', 'P1_selected_tests', 'P5_fingerprints_equal',
                                    'P6_public_surface')}, indent=1))
print({k: v for k, v in ref.items() if k != 'checks'}, bench_sha)
