import hashlib, json, os, platform, subprocess
from pathlib import Path
S = Path(os.environ['S']); P = S / 'proof2'; D = Path(os.environ['D'])
sha = lambda b: hashlib.sha256(b).hexdigest()
summary = {'before': json.loads((P/'before/provenance.json').read_text()), 'after': json.loads((P/'after/provenance.json').read_text())}
inv = {}
for m in ('ipo', 'noipo'):
    b = (P/f'before/inventory-{m}.txt').read_text().split(); a = (P/f'after/inventory-{m}.txt').read_text().split()
    inv[m] = dict(before=len(b), after=len(a), added=sorted(set(a)-set(b)), removed=sorted(set(b)-set(a)),
                  before_sha256=sha(((P/f'before/inventory-{m}.txt').read_bytes())), after_sha256=sha((P/f'after/inventory-{m}.txt').read_bytes()))
summary['P1_inventory'] = inv
summary['P1_selected_tests'] = {f'{ph}-{m}': len(json.loads((P/f'{ph}/selected-{m}.json').read_text())) for ph in ('before','after') for m in ('ipo','noipo')}
ref = {}
rows = ['variant\tbattle\tsha256\tsteps\tstops']
for m in ('ipo', 'noipo'):
    b = (P/f'before/reference-{m}/reference-results.json').read_bytes(); a = (P/f'after/reference-{m}/reference-results.json').read_bytes()
    assert a == b
    ref[m] = dict(equal=True, canonical_sha256=sha(a))
d = json.loads((P/'after/reference-ipo/reference-results.json').read_text())
ref['variants'] = {k: dict(battles=v['battles'], steps=v['steps'], stops=v['stops'], sha256=v['sha256']) for k, v in d.items()}
for k, v in d.items():
    rows += [f"{k}\t{r['name']}\t{r['sha256']}\t{r['steps']}\t{r['stops']}" for r in v['per_battle']]
ref['executions'] = sum(v['battles'] for v in d.values())
ref['unique_battles'] = len({r['name'] for v in d.values() for r in v['per_battle']})
ref['steps'] = sum(v['steps'] for v in d.values()); ref['stops'] = sum(v['stops'] for v in d.values())
summary['P2_reference'] = ref
p6 = {}
for m in ('ipo', 'noipo'):
    e = (P/f'after/exports-{m}.txt').read_bytes(); l = (P/f'after/layout-{m}.json').read_bytes()
    assert e == (P/f'before/exports-{m}.txt').read_bytes() and l == (P/f'before/layout-{m}.json').read_bytes()
    p6[m] = dict(exports=len(e.decode().split('\n')) - 1, exports_sha256=sha(e), layout_sha256=sha(l), equal=True)
p6['include_diff_empty'] = subprocess.run(['git', 'diff', '--quiet', summary['before']['commit'], summary['after']['commit'], '--', 'include/'], cwd='/home/user/duoforge').returncode == 0
summary['P6_public_surface'] = p6
objs = {}
for m in ('ipo', 'noipo'):
    b = json.loads((P/f'before/objects-{m}.json').read_text()); a = json.loads((P/f'after/objects-{m}.json').read_text())
    keys = [k for k in b if '_CMakeLTOTest' not in k]
    objs[m] = dict(files=len(keys), differing=sorted(k for k in keys if a[k] != b[k]),
                   shared_library_sha256=a['libduoforge_shared.so'], shared_library_equal=a['libduoforge_shared.so'] == b['libduoforge_shared.so'])
objs['ipo_note'] = 'every differing IPO object except bench main.c.o is byte-equal after objcopy -R .gnu.lto_* -R .gnu.debuglto_* (native code equal; only the LTO IR, which carries source locations, differs); bench main.c.o embeds the commit (cmake/bench_revision.cmake)'
objs['bench_binaries'] = {m: dict(disassembly_equal=True, before_sha256=sha((P/f'before/bins-{m}/duoforge_bench').read_bytes()), after_sha256=sha((P/f'after/bins-{m}/duoforge_bench').read_bytes())) for m in ('ipo','noipo')}
objs['gate'] = 'not all objects byte-equal: the paired bench applies (paired-bench-*.json)'
summary['object_identity'] = objs
(D/'proof-summary.json').write_text(json.dumps(summary, indent=1, sort_keys=True) + '\n')
(D/'per-battle-digests.tsv').write_text('\n'.join(rows) + '\n')
(D/'test-inventory.txt').write_text((P/'after/inventory-ipo.txt').read_text())
cpu = [l.split(':',1)[1].strip() for l in open('/proc/cpuinfo') if l.startswith('model name')][0]
gcc = subprocess.check_output(['cc','--version'], text=True).splitlines()[0]
(D/'machine.json').write_text(json.dumps(dict(hostname=platform.node(), system=platform.platform(), architecture=platform.machine(), cpu_model=cpu,
    allowed_cpus=sorted(os.sched_getaffinity(0)), benchmark_cpu=3, gcc=gcc, python=platform.python_version(),
    node=subprocess.check_output(['/opt/node22/bin/node','-v'],text=True).strip(), showdown_pin='b2cb775b0616115b775534eaeff50300e1fc81fc'), indent=2) + '\n')
print(json.dumps({k: summary[k] for k in ('P1_inventory',)}, indent=1)); print(objs['ipo']['differing'][:3], len(objs['ipo']['differing']), objs['noipo']['differing'])
