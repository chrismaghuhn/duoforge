"""Fixed 32-round Latin rotation of change/control pairs for both IPO modes."""
from pathlib import Path
import hashlib,json,os,random,statistics,subprocess,tempfile,time
out=Path(os.environ['OUT'])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ci(values):
 rng=random.Random(20261012);draws=sorted(statistics.median(rng.choices(values,k=len(values))) for _ in range(20000));return [draws[499],draws[19499]]
jobs=[('ipo','change'),('ipo','control'),('noipo','change'),('noipo','control')]
results={};began=time.time()
provenance={side:json.loads((out/side/'provenance.json').read_text()) for side in ('before','after')}
assert all(not p['dirty'] for p in provenance.values())
for mode,kind in jobs:
 before=out/f'before/bins-{mode}/duoforge_bench';after=before if kind=='control' else out/f'after/bins-{mode}/duoforge_bench'
 results[(mode,kind)]=dict(protocol=dict(rounds=32,repetitions=3,warmup=2,battles_per_pairing=1024,cpu_affinity=[3],ipo='on' if mode=='ipo' else 'off',order='rotate the four change/control/mode pairs through four positions each round; AB odd rounds / BA even rounds; all samples retained',bootstrap='20000 paired-resample medians, seed 20261012, percentile 95% CI',numeric_gate='median after/before time <=1.02; baseline spread and identical-binary control spread reported separately',cgroup_cpu_max='n/a (no cpu.max)'),binaries={s:dict(path=str(p),sha256=sha(p),commit=provenance['before' if s=='before' or kind=='control' else 'after']['commit'],dirty=False) for s,p in [('before',before),('after',after)]},rounds=[],manifests={})
 if kind=='control':assert results[(mode,kind)]['binaries']['before']['sha256']==results[(mode,kind)]['binaries']['after']['sha256']
with tempfile.TemporaryDirectory(prefix='duoforge-matched-',dir=out) as tmp:
 for number in range(1,33):
  shift=(number-1)%4;sequence=jobs[shift:]+jobs[:shift];order=['before','after'] if number%2 else ['after','before']
  for position,(mode,kind) in enumerate(sequence):
   d=results[(mode,kind)];row=dict(round=number,order=order,comparison_position=position,profiles={})
   for side in order:
    output=Path(tmp)/'run.json'
    command=[d['binaries'][side]['path'],'--battles','1024','--repetitions','3','--warmup','2','--max-steps','128','--policy-seed','20261001','--battle-seed','7001','--families','step,events','--out',str(output)]
    subprocess.run(command,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,preexec_fn=lambda:os.sched_setaffinity(0,{3}))
    raw=json.loads(output.read_text());assert not raw['manifest']['dirty'];assert d['binaries'][side]['commit'].startswith(raw['manifest']['revision']),raw['manifest'];assert raw['errors']==raw['skipped_by_time_limit']==raw['record']['errors']==raw['record']['truncations']==0
    if 'record' not in d:d.update(record=raw['record'],choices=raw['choices'])
    assert raw['record']==d['record'] and raw['choices']==d['choices']
    d['manifests'].setdefault(side,raw['manifest']);assert raw['manifest']['ipo']==(mode=='ipo')
    if len(d['manifests'])==2:
     for f in ('compiler','build_type','c_flags','ipo','workload','context_fingerprint','policy_seed','battle_seed','max_steps','battles_per_pairing','pairings','workers'):assert d['manifests']['before'][f]==d['manifests']['after'][f],f
    row.setdefault('provenance',{})[side]={'commit':d['binaries'][side]['commit'],'dirty':raw['manifest']['dirty'],'compiled_revision':raw['manifest']['revision']}
    row['profiles'][side]={r['variant']:dict(wall_ns=r['wall_ns'],cpu_ns=r['cpu_ns'],disturbed=r['disturbed_repetitions'],median_wall_ns=statistics.median(r['wall_ns']),errors=r['errors']) for r in raw['results']}
   row['time_ratios']={v:row['profiles']['after'][v]['median_wall_ns']/row['profiles']['before'][v]['median_wall_ns'] for v in ('plain','events')};d['rounds'].append(row)
   (out/f'matched-{mode}-{kind}.json').write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
   print(number,mode,kind,' '.join(f'{v}={r:.6f}' for v,r in row['time_ratios'].items()),flush=True)
 for mode,kind in jobs:
  d=results[(mode,kind)];summaries={}
  for variant in ('plain','events'):
   values=[r['time_ratios'][variant] for r in d['rounds']];base=[r['profiles']['before'][variant]['median_wall_ns'] for r in d['rounds']];after=[r['profiles']['after'][variant]['median_wall_ns'] for r in d['rounds']];centre=statistics.median(base);ratio=statistics.median(values);spread=[min(base)/centre,max(base)/centre]
   summaries[variant]=dict(median_time_ratio=ratio,change_percent=100*(ratio-1),median_throughput_ratio=1/ratio,paired_bootstrap_95ci=ci(values),ratio_range=[min(values),max(values)],baseline_median_ms=centre/1e6,after_median_ms=statistics.median(after)/1e6,baseline_relative_spread=spread,baseline_sample_ms=[v/1e6 for v in base],after_sample_ms=[v/1e6 for v in after],median_loss_at_most_2_percent=ratio<=1.02,within_baseline_spread=spread[0]<=ratio<=spread[1],disturbed_repetitions={s:sum(r['profiles'][s][variant]['disturbed'] for r in d['rounds']) for s in ('before','after')})
  d.update(summaries=summaries,elapsed_seconds=time.time()-began)
 for mode in ('ipo','noipo'):
  d=results[(mode,'change')];control=results[(mode,'control')]
  for variant,s in d['summaries'].items():
   cc=control['summaries'][variant]['paired_bootstrap_95ci'];adjusted=[r['time_ratios'][variant]/c['time_ratios'][variant] for r,c in zip(d['rounds'],control['rounds'])]
   adj_ci=ci(adjusted);s['gate_adjusted_median_le_1_02_and_ci_upper_lt_1_05']=statistics.median(adjusted)<=1.02 and adj_ci[1]<1.05
   s.update(same_binary_control_median_ratio=control['summaries'][variant]['median_time_ratio'],same_binary_control_95ci=cc,within_control_95ci=cc[0]<=s['median_time_ratio']<=cc[1],round_matched_change_over_control_ratio=statistics.median(adjusted),round_matched_change_over_control_95ci=ci(adjusted))
 for (mode,kind),d in results.items():
  (out/f'matched-{mode}-{kind}.json').write_text(json.dumps(d,indent=2,sort_keys=True)+'\n');print('FINAL',mode,kind,json.dumps(d['summaries']),flush=True)
 assert len({json.dumps(d['record'],sort_keys=True) for d in results.values()})==1
 assert len({json.dumps(d['choices'],sort_keys=True) for d in results.values()})==1
