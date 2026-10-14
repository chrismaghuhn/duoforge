from pathlib import Path
import json,re,collections,hashlib,os
out=Path('/workspace/duoforge-env/step4-field-2026-10-14')
helpers=[r['function'] for r in json.loads((out/'extraction-map.json').read_text())]
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
            if op.startswith('call'):funcs[name]['calls'].append(target)
            elif target!=name:funcs[name]['jumps'].append(target)
        elif op.startswith('call'):funcs[name]['indirect_calls'].append(line.strip())
    return funcs
def graph(funcs,roots):
    todo=[n for n in funcs if norm(n) in roots];seen=set()
    while todo:
        n=todo.pop()
        if n.endswith('@plt') and n[:-4] in funcs:n=n[:-4]
        if n in seen or n not in funcs:continue
        seen.add(n);todo.extend(funcs[n]['calls']+funcs[n]['jumps'])
    return seen
def norm(n):
    name=re.sub(r'\.(?:constprop|isra|part|cold|lto_priv)(?:\.\d+)?','',n).removesuffix('@plt')
    return {'dfi_grounded_test':'dfi_grounded','dfi_weather_suppression_scan':'dfi_weather_suppressed'}.get(name,name)
result={'method':'objdump -d conservative static reachable graphs, direct call instructions including calls to external functions; tail jumps/cold branches traversed; same-library PLT targets resolved; indirect calls reported separately; public entry points and their compiler clones are roots; IPO may fold plain/events wrappers into their common internal implementation; predicate implementation aliases grounded_test→grounded and weather_suppression_scan→weather_suppressed retain their old body identities; actual artifact names are retained in definition lists; these are not dynamic invocation counts','provenance':{s:json.loads((out/s/'provenance.json').read_text()) for s in ('before','after')},'profiles':{}}
for mode in ('ipo','noipo'):
    if os.environ.get('ONLY_MODE') and mode != os.environ['ONLY_MODE']:continue
    for kind,base in [('bench','duoforge_bench'),('shared','libduoforge_shared')]:
        parsed={side:parse(out/f'{side}/{base}-{mode}-objdump.txt') for side in ('before','after')}
        detail={'artifacts':{s:{'sha256':hashlib.sha256((out/s/f'{base}_{mode}').read_bytes()).hexdigest(),'commit':result['provenance'][s]['commit'],'dirty':result['provenance'][s]['dirty']} for s in parsed},'workloads':{},'helpers':[]}
        for helper in helpers:
            h={'name':helper}
            for side,f in parsed.items():
                definitions=[n for n in f if norm(n)==helper]
                h[side]={'out_of_line_definitions':definitions,'direct_calls':sum(norm(c)==helper for data in f.values() for c in data['calls']),'tail_jumps':sum(norm(c)==helper for data in f.values() for c in data['jumps'])}
            detail['helpers'].append(h)
        for workload,roots in [('common_step',['duoforge_battle_step','duoforge_battle_step_events','dfi_battle_step_tape','dfi_battle_step_events_tape']),('events',['duoforge_battle_step_events','dfi_battle_step_events_tape'])]:
            graphs={s:graph(f,roots) for s,f in parsed.items()}
            assert all(graphs.values()),(mode,kind,workload)
            counts={};edges={}
            for side,f in parsed.items():
                counts[side]=collections.Counter(norm(c) for n in graphs[side] for c in f[n]['calls'])
                edges[side]=collections.Counter((norm(n),norm(c)) for n in graphs[side] for c in f[n]['calls'])
            rows=[{'callee':n,'before':counts['before'][n],'after':counts['after'][n]} for n in sorted(set(counts['before'])|set(counts['after'])) if counts['before'][n]!=counts['after'][n]]
            edge_delta=[{'caller':a,'callee':b,'before':edges['before'][(a,b)],'after':edges['after'][(a,b)]} for a,b in sorted(set(edges['before'])|set(edges['after'])) if edges['before'][(a,b)]!=edges['after'][(a,b)]]
            detail['workloads'][workload]={'roots':roots,'direct_call_instructions':{s:sum(c.values()) for s,c in counts.items()},'indirect_call_instructions':{s:sum(len(parsed[s][n]['indirect_calls']) for n in graphs[s]) for s in parsed},'reachable_functions':{s:len(g) for s,g in graphs.items()},'changed_callee_counts':rows,'changed_edges':edge_delta}
            print(mode,kind,workload,detail['workloads'][workload]['direct_call_instructions'],'changed edges',len(edge_delta),flush=True)
        result['profiles'][mode+'-'+kind]=detail
(out/('call-audit-'+os.environ['ONLY_MODE']+'.json' if os.environ.get('ONLY_MODE') else 'call-audit.json')).write_text(json.dumps(result,indent=2)+'\n')
