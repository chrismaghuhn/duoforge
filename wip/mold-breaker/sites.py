import re,sys,subprocess
import os; R=os.environ['DUOFORGE_ROOT'] + '/'
ab=open(os.environ['DUOFORGE_PS_REFERENCE_DIR'] + '/data/abilities.ts',encoding='utf8').read().split('\n')
br={};cur=None
for i,l in enumerate(ab,1):
    m=re.match(r'^\t(\w+): \{',l)
    if m: cur=m.group(1)
    if re.search(r'breakable: 1',l) and cur: br[cur]=i
sm=open(R+'src/data/support_manifest.c',encoding='utf8').read().split('\n')
st=[i for i,l in enumerate(sm) if l.strip().startswith('.abilities')][0]
marked={}
for i in range(st,len(sm)):
    m=re.search(r'\[DFI_ABILITY_(\w+)\]\s*=\s*1u',sm[i])
    if m: marked[m.group(1).lower()]=i+1
    if sm[i].startswith('        }') and i>st+3: break
inter=sorted(k for k in br if k in marked)
print(len(br),len(marked),len(inter),file=sys.stderr)
open(R.replace('.claude/worktrees/content-mb/','')+'x','w') if False else None
print('\n'.join(inter))
