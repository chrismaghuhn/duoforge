from pathlib import Path
import collections,hashlib,json,statistics
out=Path('/workspace/duoforge-env/step4-field')
source={s:json.loads((out/s/'provenance.json').read_text()) for s in ('before','after')}
records=set();choices=set();gates=[]
for mode in ('ipo','noipo'):
 for kind in ('change','control'):
  j=json.loads((out/f'matched-{mode}-{kind}.json').read_text())
  assert len(j['rounds'])==32 and 'summaries' in j
  assert [r['round'] for r in j['rounds']]==list(range(1,33))
  assert collections.Counter(r['comparison_position'] for r in j['rounds'])=={0:8,1:8,2:8,3:8}
  records.add(json.dumps(j['record'],sort_keys=True));choices.add(json.dumps(j['choices'],sort_keys=True))
  assert j['record']['errors']==j['record']['truncations']==0
  if kind=='control':assert j['binaries']['before']['sha256']==j['binaries']['after']['sha256']
  for side,b in j['binaries'].items():
   assert not b['dirty'] and b['commit']==source['before' if side=='before' or kind=='control' else 'after']['commit']
   assert hashlib.sha256(Path(b['path']).read_bytes()).hexdigest()==b['sha256']
  for r in j['rounds']:
   assert r['order']==(['before','after'] if r['round']%2 else ['after','before'])
   for side,p in r['provenance'].items():assert not p['dirty'] and p['commit']==j['binaries'][side]['commit'] and p['commit'].startswith(p['compiled_revision'])
   for side,p in r['profiles'].items():
    for work,w in p.items():
     assert len(w['wall_ns'])==len(w['cpu_ns'])==3
     assert w['errors']==0 and all(t>0 for t in w['wall_ns']+w['cpu_ns'])
     assert w['median_wall_ns']==statistics.median(w['wall_ns'])
   for work,ratio in r['time_ratios'].items():assert ratio==r['profiles']['after'][work]['median_wall_ns']/r['profiles']['before'][work]['median_wall_ns']
  for work,s in j['summaries'].items():
   assert s['median_time_ratio']==statistics.median(r['time_ratios'][work] for r in j['rounds'])
   if kind=='change':gates.append(dict(profile=mode,workload=work,change_percent=s['change_percent'],change_95ci=s['paired_bootstrap_95ci'],control_95ci=s['same_binary_control_95ci'],numeric_pass=s['median_loss_at_most_2_percent'],own_scatter_pass=s['within_control_95ci']))
assert len(records)==len(choices)==1
log=(out/'repaired-matched-bench.log').read_text();assert 'Traceback' not in log and log.count('FINAL ')==4
result={'provenance':source,'completed_series':4,'pairs_per_series':32,'total_pairs':128,'all_samples_retained':True,'same_binary_control_sha_matches':True,'records_and_choices_identical':True,'gates':gates,'gate_pass':all(g['numeric_pass'] or g['own_scatter_pass'] for g in gates)}
(out/'bench-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
