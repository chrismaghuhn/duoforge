from pathlib import Path
import collections,ctypes,hashlib,json,subprocess,xml.etree.ElementTree as ET
out=Path('/workspace/duoforge-env/step4-field'); root=Path('/workspace/duoforge')
sha=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:json.loads(p.read_text())
p=read(out/'initial-abb0ade9-proof-summary.json')
p['provenance']={s:read(out/s/'provenance.json') for s in ('before','after')}
assert all(not v['dirty'] for v in p['provenance'].values())
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()==p['provenance']['after']['commit']
assert not subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()
helpers=[r['function'] for r in read(out/'extraction-map.json')]+['dfi_grounded_test','dfi_weather_suppression_scan']
assert len(set(helpers))==17
for mode in ('ipo','noipo'):
 a=read(out/f'before/ctest-{mode}.json');b=read(out/f'after/ctest-{mode}.json')
 norm=lambda x:[{k:v for k,v in t.items() if k!='backtrace'} for t in x['tests']]
 assert norm(a)==norm(b)
 inv=(out/f'after/inventory-{mode}.txt').read_bytes()
 assert inv==(out/f'before/inventory-{mode}.txt').read_bytes()
 tests={s:dict(ET.parse(out/s/f'proofs-{mode}.xml').getroot().attrib) for s in ('before','after')}
 for v in tests.values():
  assert int(v['tests'])==(218 if mode=='ipo' else 213)
  assert all(int(v[k])==0 for k in ('failures','disabled','skipped'))
 tiers=collections.Counter()
 for t in b['tests']:
  labs=next(x['value'] for x in t['properties'] if x['name']=='LABELS')
  tier=set(labs)&{'quick','full','reference','slow'};assert len(tier)==1;tiers.update(tier)
 p['P1'][mode].update(inventory=len(b['tests']),inventory_sha256=sha(inv),runtime_properties_equal=True,tests=tests,tiers=dict(tiers))
 ref=(out/f'after/reference-{mode}/reference-results.json').read_bytes();assert ref==(out/f'before/reference-{mode}/reference-results.json').read_bytes()
 assert sha(ref)==p['P2'][mode]['sha256']
 for kind,suffix in [('exports','txt'),('layout','json')]:
  raw=(out/f'after/{kind}-{mode}.{suffix}').read_bytes();assert raw==(out/f'before/{kind}-{mode}.{suffix}').read_bytes()
  assert sha(raw)==p['P6'][mode]['exports_sha256' if kind=='exports' else 'layout_raw_sha256']
 neg={}
 for side in ('before','after'):
  lib=ctypes.CDLL(str(out/side/f'libduoforge_shared_{mode}'))
  for h in helpers:
   try:getattr(lib,h)
   except AttributeError:pass
   else:raise AssertionError('Exported private helper '+h)
  neg[side]=len(helpers)
 p['P6'][mode]['private_helper_negative_lookups']=neg
 expected=['duoforge.python.perft','duoforge.python.bench','duoforge.python.layout','duoforge.python.state_layout']
 if mode=='ipo':expected+=['duoforge.python.live','duoforge.data.closure_regen','duoforge.data.extended_regen','duoforge.data.pool_regen','duoforge.reference.tiebreak_ref','duoforge.reference.format_pins']
 names={t.attrib['name'] for t in ET.parse(out/f'after/proofs-{mode}.xml').getroot().findall('testcase')}
 assert set(expected)<=names,(set(expected)-names)
 assert 'stale' not in (out/f'after/handlers-check-{mode}.log').read_text().lower()
source=read(out/'before/source-hashes.json')
for path,h in source.items():assert sha((root/path).read_bytes())==h,path
p['P5'].update(sha256=source,unchanged_source_hashes=len(source))
assert subprocess.run(['git','diff','--quiet','aca58173','--','include/duoforge'],cwd=root).returncode==0
p['source']=read(out/'source-audit.json')
p['source'].update(unchanged_original_body_implementations=15,tiny_inline_wrappers=2,private_implementation_aliases={'dfi_grounded':'dfi_grounded_test','dfi_weather_suppressed':'dfi_weather_suppression_scan'})
p['P1']['hosted_ci']='pending PR authorization and opening; not executed locally'
(out/'proof-summary.json').write_text(json.dumps(p,indent=2,sort_keys=True)+'\n')
print('Latest P1-P6 verified',p['provenance'],len(source),'frozen hashes; 68 private symbol lookups')
