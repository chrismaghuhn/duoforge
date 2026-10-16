"""Restructure step 4 (residual runner): P1-P6 and object identity, one phase (before|after) per run.

Usage: PHASE=before|after OUT=<dir outside the repo> python proofs.py
Builds build/ipo, build/noipo and build/debug of the checked-out commit (same source and build paths in both phases, so object
bytes compare), then records the CTest inventory, object and library hashes, exports, layouts, selected tests and the
reference digests. The after phase compares with the before phase. Only counts and hashes are retained.
"""
from pathlib import Path
import hashlib, json, os, re, subprocess, time

root = Path(__file__).resolve().parents[0] if os.environ.get('REPO') is None else Path(os.environ['REPO'])
out = Path(os.environ['OUT'])
phase = os.environ['PHASE']
dest = out / phase
dest.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, PATH='/opt/node22/bin:' + os.environ['PATH'], OPENBLAS_NUM_THREADS='1')
git = lambda *a: subprocess.check_output(['git', *a], cwd=root, text=True).strip()
revision = git('rev-parse', 'HEAD')
dirty = bool(git('status', '--porcelain'))
assert not dirty, 'commit before proving'
(dest / 'provenance.json').write_text(json.dumps({'commit': revision, 'dirty': dirty, 'phase': phase}, indent=2) + '\n')
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
NEW_TESTS = set()

for mode in ('ipo', 'noipo', 'debug'):
    build = root / 'build' / mode
    start = time.perf_counter()
    subprocess.run(['cmake', '--build', str(build), '--parallel', '4'], cwd=root, env=env,
                   stdout=(dest / f'build-{mode}.log').open('w'), stderr=subprocess.STDOUT, check=True)
    (dest / f'build-time-{mode}.json').write_text(json.dumps({'seconds': time.perf_counter() - start,
                                                              'scope': 'incremental'}, indent=2) + '\n')
    j = json.loads(subprocess.check_output(['ctest', '--test-dir', str(build), '--show-only=json-v1'], cwd=root,
                                           env=env, text=True))
    (dest / f'ctest-{mode}.json').write_text(json.dumps(j, indent=2) + '\n')
    inventory = '\n'.join(sorted(t['name'] for t in j['tests'])) + '\n'
    (dest / f'inventory-{mode}.txt').write_text(inventory)
    if phase == 'after':
        prior = json.loads((out / f'before/ctest-{mode}.json').read_text())
        norm = lambda x: {t['name']: {k: v for k, v in t.items() if k != 'backtrace'} for t in x['tests']}
        a, b = norm(j), norm(prior)
        assert set(a) - set(b) == NEW_TESTS and not set(b) - set(a), (set(a) ^ set(b))
        assert all(a[n] == b[n] for n in b), [n for n in b if a[n] != b[n]]
    print(phase, mode, 'inventory', len(j['tests']), hashlib.sha256(inventory.encode()).hexdigest(), flush=True)
    # Object identity: every object file and archive of the engine targets, and the shared library.
    objs = {}
    for p in sorted(build.rglob('*.o')) + sorted(build.glob('*.a')) + [build / 'libduoforge_shared.so']:
        objs[str(p.relative_to(build))] = sha(p)
    (dest / f'objects-{mode}.json').write_text(json.dumps(objs, indent=1, sort_keys=True) + '\n')
    # Keep the objects, the library and the bench binary for the native-code comparison (outside the repo).
    keep = dest / f'bins-{mode}'
    keep.mkdir(exist_ok=True)
    for name in ('libduoforge_shared.so', 'bench/duoforge_bench'):
        (keep / Path(name).name).write_bytes((build / name).read_bytes())
    subprocess.run(['tar', 'cf', str(keep / 'objs.tar'),
                    *[k for k in objs if k.endswith('.o') and '_CMakeLTOTest' not in k]], cwd=build, check=True)
    symbols = subprocess.check_output(['nm', '-D', '--defined-only', str(build / 'libduoforge_shared.so')], text=True)
    (dest / f'exports-{mode}.txt').write_text(
        '\n'.join(sorted(' '.join(l.split()[1:]) for l in symbols.splitlines())) + '\n')
    (dest / f'layout-{mode}.json').write_bytes(subprocess.check_output([str(build / 'duoforge_layout_dump')]))
    fp_code = ('import json\nfrom duoforge.context import Context\nfrom duoforge import _layout as L\n'
               'print(json.dumps({n: Context(data_kind=L.CONSTANTS["DUOFORGE_DATA_KIND_" + n]).fingerprint().hex() '
               'for n in ("CLOSURE", "TEAM_C", "POOL")}))')
    fp = subprocess.check_output(['python3', '-c', fp_code],
                                 cwd=root, env=dict(env, DUOFORGE_LIBRARY=str(build / 'libduoforge_shared.so'), PYTHONPATH=str(root / 'python')), text=True)
    (dest / f'fingerprints-{mode}.json').write_text(fp)
    if phase == 'after':
        assert fp == (out / f'before/fingerprints-{mode}.json').read_text(), 'context fingerprints changed'
    # The native reference runners' own reports (counts, checks, digests), before and after.
    native = {}
    for exe in sorted((build / 'tests').glob('duoforge_reference_*')):
        if not exe.name.startswith(('duoforge_reference_conformance', 'duoforge_reference_tiebreak')) or exe.suffix:
            continue
        r = subprocess.run([str(exe)], cwd=build / 'tests', env=env, capture_output=True, text=True)
        native[exe.name] = {'returncode': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}
    (dest / f'native-{mode}.json').write_text(json.dumps(native, indent=1, sort_keys=True) + '\n')
    assert native and all(v['returncode'] == 0 for v in native.values()), {k: v['returncode'] for k, v in native.items()}
    if phase == 'after':
        assert (dest / f'native-{mode}.json').read_text() == (out / f'before/native-{mode}.json').read_text(), 'native reports differ'
    if mode == 'debug':
        print(phase, mode, 'objects, library, exports, layout, fingerprints recorded (no test run)', flush=True)
        continue
    if phase == 'after':
        for n, suffix in (('exports', 'txt'), ('layout', 'json')):
            assert (dest / f'{n}-{mode}.{suffix}').read_bytes() == (out / f'before/{n}-{mode}.{suffix}').read_bytes(), n
    names = []
    for t in j['tests']:
        labels = next((p['value'] for p in t['properties'] if p['name'] == 'LABELS'), [])
        if 'quick' in labels:
            names.append(t['name'])
    names += ['duoforge.python.layout', 'duoforge.python.state_layout', 'duoforge.python.perft', 'duoforge.python.bench']
    if mode == 'ipo':
        names += ['duoforge.data.closure_regen', 'duoforge.data.extended_regen', 'duoforge.data.pool_regen',
                  'duoforge.data.pool_families', 'duoforge.reference.tiebreak_ref', 'duoforge.python.live']
        names += [n for n in NEW_TESTS if any(t['name'] == n for t in j['tests'])]
    names += [t['name'] for t in j['tests'] if t['name'].startswith('duoforge.lint.')]
    names = sorted(set(names))
    (dest / f'selected-{mode}.json').write_text(json.dumps(names, indent=2) + '\n')
    r = subprocess.run(['ctest', '--test-dir', str(build), '-R', '^(' + '|'.join(map(re.escape, names)) + ')$',
                        '--output-on-failure', '--parallel', '4', '--timeout', '900',
                        '--output-junit', str(dest / f'proofs-{mode}.xml')],
                       cwd=root, env=env, stdout=(dest / f'proofs-{mode}.log').open('w'), stderr=subprocess.STDOUT)
    print(phase, mode, len(names), 'selected tests, exit', r.returncode, flush=True)
    subprocess.run(['python3', 'tools/restructure/capture_reference.py', '.', str(build), str(dest / f'reference-{mode}')],
                   cwd=root, env=env, stdout=(dest / f'reference-{mode}.log').open('w'), stderr=subprocess.STDOUT,
                   check=True)
    if phase == 'after':
        assert (dest / f'reference-{mode}/reference-results.json').read_bytes() == \
            (out / f'before/reference-{mode}/reference-results.json').read_bytes()
    print(phase, mode, 'reference digests captured', flush=True)
print(phase, 'done', flush=True)
