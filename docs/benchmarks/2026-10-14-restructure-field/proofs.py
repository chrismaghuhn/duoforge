from pathlib import Path
import hashlib, json, os, re, shutil, subprocess, time
root=Path('/workspace/duoforge');out=Path('/workspace/duoforge-env/step4-field-2026-10-14')
phase=os.environ['PHASE']; dest=out/phase;dest.mkdir(exist_ok=True)
env=dict(os.environ,PATH='/workspace/duoforge-env/venv/bin:/workspace/duoforge-env/node-v22.23.3-linux-x64/bin:'+os.environ['PATH'],OPENBLAS_NUM_THREADS='1')
revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip())
assert not dirty, 'Commit changes before measuring or proving this phase'
(dest/'provenance.json').write_text(json.dumps({'commit':revision,'dirty':dirty,'phase':phase,'machine':json.loads((out/'machine.json').read_text())},indent=2)+'\n')
for mode,build in {'ipo':'build/restructure','noipo':'build/restructure3-noipo'}.items():
    if os.environ.get('ONLY_MODE') and mode!=os.environ['ONLY_MODE']:continue
    subprocess.run(['cmake','-S','.', '-B',build],cwd=root,env=env,stdout=(dest/f'configure-{mode}.log').open('w'),stderr=subprocess.STDOUT,check=True)
    start=time.perf_counter()
    subprocess.run(['cmake','--build',build,'--parallel','2'],cwd=root,env=env,stdout=(dest/f'build-{mode}.log').open('w'),stderr=subprocess.STDOUT,check=True)
    (dest/f'build-time-{mode}.json').write_text(json.dumps({'commit':revision,'dirty':dirty,'seconds':time.perf_counter()-start,'scope':'incremental full build, reusing build directory; not a clean build'},indent=2)+'\n')
    j=json.loads(subprocess.check_output(['ctest','--test-dir',build,'--show-only=json-v1'],cwd=root,env=env,text=True))
    (dest/f'ctest-{mode}.json').write_text(json.dumps(j,indent=2)+'\n')
    inventory='\n'.join(sorted(t['name'] for t in j['tests']))+'\n'
    (dest/f'inventory-{mode}.txt').write_text(inventory)
    if phase=='after':
        prior=json.loads((out/f'before/ctest-{mode}.json').read_text())
        norm=lambda x:[{k:v for k,v in t.items() if k!='backtrace'} for t in x['tests']]
        assert norm(j)==norm(prior),'test registrations or runtime properties drift'
    print(phase,mode,'inventory',len(j['tests']),hashlib.sha256(inventory.encode()).hexdigest(),flush=True)
    for name,p in [('duoforge_bench',root/build/'bench/duoforge_bench'),('libduoforge_shared',root/build/'libduoforge_shared.so')]:
        target=dest/f'{name}_{mode}'
        shutil.copy2(p,target)
        (dest/f'{name}-{mode}-objdump.txt').write_text(subprocess.check_output(['objdump','-d',str(p)],text=True))
    symbols=subprocess.check_output(['nm','-D','--defined-only',str(root/build/'libduoforge_shared.so')],text=True)
    (dest/f'exports-{mode}.txt').write_text('\n'.join(sorted(' '.join(l.split()[1:]) for l in symbols.splitlines()))+'\n')
    (dest/f'layout-{mode}.json').write_bytes(subprocess.check_output([str(root/build/'duoforge_layout_dump')]))
    if phase=='after':
        for n in ('exports','layout'):
            suffix='txt' if n=='exports' else 'json'
            assert (dest/f'{n}-{mode}.{suffix}').read_bytes()==(out/f'before/{n}-{mode}.{suffix}').read_bytes()
    names=[]
    for t in j['tests']:
        labels=next((p['value'] for p in t['properties'] if p['name']=='LABELS'),[])
        if 'quick' in labels:names.append(t['name'])
    names += ['duoforge.python.layout','duoforge.python.state_layout','duoforge.python.perft','duoforge.python.bench']
    if mode=='ipo':names+=['duoforge.data.closure_regen','duoforge.data.extended_regen','duoforge.data.pool_regen','duoforge.reference.tiebreak_ref','duoforge.python.live']
    names += [t['name'] for t in j['tests'] if t['name'].startswith('duoforge.lint.')]
    names=sorted(set(names)); assert names
    (dest/f'selected-{mode}.json').write_text(json.dumps(names,indent=2)+'\n')
    subprocess.run(['ctest','--test-dir',build,'-R','^('+'|'.join(map(re.escape,names))+')$','--output-on-failure','--parallel','2','--output-junit',str(dest/f'proofs-{mode}.xml')],cwd=root,env=env,stdout=(dest/f'proofs-{mode}.log').open('w'),stderr=subprocess.STDOUT,check=True)
    subprocess.run(['python','tools/restructure/capture_reference.py','.',build,str(dest/f'reference-{mode}')],cwd=root,env=env,stdout=(dest/f'reference-{mode}.log').open('w'),stderr=subprocess.STDOUT,check=True)
    if phase=='after':assert (dest/f'reference-{mode}/reference-results.json').read_bytes()==(out/f'before/reference-{mode}/reference-results.json').read_bytes()
    print(phase,mode,len(names),'selected tests and 10 reference variants pass',flush=True)
    subprocess.run(['python','tools/datagen/gen_move_handlers.py','--check'],cwd=root,env=env,stdout=(dest/f'handlers-check-{mode}.log').open('w'),stderr=subprocess.STDOUT,check=True)
print(phase,'all proofs complete',flush=True)
