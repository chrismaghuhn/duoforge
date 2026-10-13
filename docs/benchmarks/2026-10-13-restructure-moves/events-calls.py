from pathlib import Path
import json,re,collections
previous=Path('/workspace/duoforge-env/step4-moves-call-audit');out=Path('/workspace/duoforge-env/step4-moves-call-audit')
helpers=[r['function'] for r in json.loads((previous/'function-extractions.json').read_text())]+['dfi_move_special_has_handler','dfi_move_special_status_hit']
def parse(path):
 funcs={};name=None
 for line in path.read_text().splitlines():
  m=re.match(r'^([0-9a-f]+) <([^>]+)>:',line)
  if m:name=m[2];funcs.setdefault(name,dict(calls=[],jumps=[],indirect_calls=[]));continue
  if name is None:continue
  m=re.search(r'\b(call\w*|jmp\w*|j[a-z]+)\s+([^\n]+)',line)
  if not m:continue
  op,arg=m.groups();target=re.search(r'<([^>]+)>',arg)
  if target:
   target=target[1].split('+0x')[0]
   if op.startswith('call'):funcs[name]['calls'].append(dict(callee=target,instruction=line.strip()))
   elif target!=name:funcs[name]['jumps'].append(target)
  elif op.startswith('call'):funcs[name]['indirect_calls'].append(line.strip())
 return funcs
def graph(funcs):
 roots=['duoforge_battle_step_events','dfi_battle_step_events_tape']
 todo=list(roots);seen=set()
 while todo:
  n=todo.pop()
  if n.endswith('@plt') and n[:-4] in funcs:n=n[:-4]
  if n in seen or n not in funcs:continue
  seen.add(n);todo.extend([r['callee'] for r in funcs[n]['calls']]+funcs[n]['jumps'])
 return seen
def norm(n):return re.sub(r'\.(?:constprop|isra|part)\.\d+','',n).removesuffix('.cold')
result=dict(method='objdump -d: static call instructions; reachable graph includes direct calls, tail jumps, cold blocks and branch edges; same-library PLT calls resolve to their definitions, indirect calls are reported separately; not dynamic invocation counts',roots=['duoforge_battle_step_events','dfi_battle_step_events_tape'],profiles={})
for kind in ['bench','shared']:
 parsed={side:parse(previous/f'{side}/{kind}-noipo-objdump.txt') for side in ['baseline','after']}
 graphs={side:graph(f) for side,f in parsed.items()}
 counts={};edgecounts={};details={}
 for side in ['baseline','after']:
  f=parsed[side];g=graphs[side];c=collections.Counter();e=collections.Counter();d=[]
  for caller in sorted(g):
   for call in f[caller]['calls']:
    c[norm(call['callee'])]+=1;e[(norm(caller),norm(call['callee']))]+=1
    if call['callee'].startswith('dfi_'):d.append(dict(caller=caller,**call))
  counts[side]=c;edgecounts[side]=e;details[side]=d
 rows=[dict(callee=n,before=counts['baseline'][n],after=counts['after'][n],delta=counts['after'][n]-counts['baseline'][n]) for n in sorted(set(counts['baseline'])|set(counts['after']))]
 edges=[dict(caller=e[0],callee=e[1],before=edgecounts['baseline'][e],after=edgecounts['after'][e]) for e in sorted(set(edgecounts['baseline'])|set(edgecounts['after'])) if edgecounts['baseline'][e]!=edgecounts['after'][e]]
 helperrows=[dict(helper=n,before=sum(counts['baseline'][k] for k in counts['baseline'] if k==n or k.startswith(n+'.')),after=sum(counts['after'][k] for k in counts['after'] if k==n or k.startswith(n+'.'))) for n in helpers]
 result['profiles'][kind]=dict(reachable_functions={s:len(g) for s,g in graphs.items()},direct_call_instructions={s:sum(c.values()) for s,c in counts.items()},indirect_calls={s:[dict(caller=n,instruction=i) for n in sorted(graphs[s]) for i in parsed[s][n]['indirect_calls']] for s in parsed},callee_counts=rows,changed_edges=edges,moved_helpers=helperrows,internal_call_sites=details)
 print(kind,'direct calls',result['profiles'][kind]['direct_call_instructions'],'reachable',result['profiles'][kind]['reachable_functions'])
 print('Changed callee counts:',[r for r in rows if r['delta']]);print('Changed edges:',edges)
 print('Moved helpers:',helperrows)
(out/'events-call-audit.json').write_text(json.dumps(result,indent=2)+'\n')
