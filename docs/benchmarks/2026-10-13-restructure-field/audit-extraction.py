from pathlib import Path
import hashlib,json,re
root=Path('/workspace/duoforge');out=Path('/workspace/duoforge-env/step4-field')
def mask(s):
    return re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:re.sub(r'[^\n]',' ',m.group()),s,flags=re.S)
def funcs(s):
    masked=mask(s);result={}
    for m in re.finditer(r'^static[^;{}]*?\b(dfi_\w+)\s*\([^;{}]*?\)\s*\{',masked,re.M):
        depth=1;end=m.end()
        while depth:depth+=(masked[end]=='{')-(masked[end]=='}');end+=1
        result[m.group(1)]=(m.start(),m.end()-1,end)
    return result
before=(out/'before/turn.c').read_text();after=(root/'src/combat/turn.c').read_text()
beforedefs=funcs(before);afterdefs=funcs(after)
rows=json.loads((out/'extraction-map.json').read_text());moved={r['function'] for r in rows}
assert set(beforedefs)-set(afterdefs)==moved
assert not set(afterdefs)-set(beforedefs)
for name in afterdefs:
    a,_,b=beforedefs[name];c,_,d=afterdefs[name]
    assert before[a:b]==after[c:d],name
for r in rows:
    new=(root/r['to']).read_text();a,b,c=funcs(new)[r.get('implementation_function',r['function'])]
    if 'implementation_function' not in r:assert new[a:b].startswith('static inline '),r['function']
    assert hashlib.sha256(new[b:c].encode()).hexdigest()==r['body_sha256'],r['function']
    r['new_first_line']=new[:a].count('\n')+1;r['new_last_line']=new[:c].count('\n')+1
# Verify everything outside the removed definitions/macros/includes, preserving C literals.
def remaining(s,definitions):
    for a,_,b in sorted(definitions,reverse=True):s=s[:a]+s[b:]
    s=re.sub(r'^\s*#include[^\n]*|^#define DFI_SIDE_KINDS 4u', '', s,flags=re.M)
    tokens=re.findall(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_]\w*|\d+|[^\s]',s,re.S)
    return [t for t in tokens if not t.startswith(('/*','//'))]
assert remaining(before,[beforedefs[n] for n in moved])==remaining(after,[])
(out/'extraction-map.json').write_text(json.dumps(rows,indent=2)+'\n')
summary={'baseline_commit':'aca58173d389613b6b4a89a95d8b1b5e3fe7b2fa','moved_functions':len(rows),'unchanged_remaining_function_bodies':len(afterdefs),'unchanged_whole_turn_tokens_except_declared_extractions_and_includes':True,'byte_equal_big_functions':[n for n in afterdefs if any(x in n for x in ('get_damage','run_move_body','residual'))],'old_turn_lines':len(before.splitlines()),'new_turn_lines':len(after.splitlines()),'file_renames':0}
(out/'source-audit.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary))
