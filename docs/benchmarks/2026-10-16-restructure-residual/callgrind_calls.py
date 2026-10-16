import re,sys,collections
def parse(path):
    names={}; fn=None; cfn=None; calls=collections.Counter(); self_ir=collections.Counter(); pending=False
    def name(tok):
        m=re.match(r'\((\d+)\)(?:\s+(.*))?',tok)
        if m:
            if m.group(2): names[m.group(1)]=m.group(2)
            return names[m.group(1)]
        return tok
    for line in open(path):
        line=line.rstrip('\n')
        if line.startswith('fn='): fn=name(line[3:]); continue
        if line.startswith('cfn='): cfn=name(line[4:]); continue
        if line.startswith(('cfi=','cfl=','fi=','fe=','fl=','ob=','cob=')):
            if line.startswith(('fi=','fe=','fl=','cfi=','cfl=')):
                tok=line.split('=',1)[1]; m=re.match(r'\((\d+)\)(?:\s+(.*))?',tok)
            continue
        if line.startswith('calls='):
            n=int(line[6:].split()[0]); calls[(fn,cfn)]+=n; pending=True; continue
        if pending: pending=False; continue   # the cost line of the call: inclusive, not self
        if line and (line[0].isdigit() or line[0] in '+-*'):
            parts=line.split()
            if len(parts)>=2: self_ir[fn]+=int(parts[1])
    return calls,self_ir
for p in sys.argv[1:]:
    calls,self_ir=parse(p)
    res={k:v for k,v in calls.items() if k[0] and k[0].startswith('dfi_residual_events_run')}
    em=sum(v for (f,c),v in res.items() if c and c.startswith('dfi_event_make'))
    out=sum(v for (f,c),v in calls.items() if c and c.startswith('dfi_event_make'))
    print(p.split('/')[-1],'calls residual->dfi_event_make*',em,'all callers->dfi_event_make*',out,'self residual',sum(v for k,v in self_ir.items() if k and k.startswith('dfi_residual_events_run')))
