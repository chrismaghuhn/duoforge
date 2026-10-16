import re, subprocess, sys
def funcs(lib):
    out = subprocess.check_output(['objdump', '-d', '--no-show-raw-insn', lib], text=True)
    fs, cur = {}, None
    for line in out.splitlines():
        m = re.match(r'^[0-9a-f]+ <(.+)>:$', line)
        if m:
            cur = m.group(1); fs[cur] = []; continue
        m = re.match(r'^\s+[0-9a-f]+:\s+(.*)$', line)
        if m and cur:
            ins = re.sub(r'\b[0-9a-f]+ <([^>+]+)(\+0x[0-9a-f]+)?>', r'<\1\2>', m.group(1))
            ins = re.sub(r'0x[0-9a-f]+\(%rip\)', 'RIP', ins)
            ins = re.sub(r'CSWTCH\.\d+', 'CSWTCH', ins)
            ins = re.sub(r'\s*#.*$', '', ins)
            fs[cur].append(ins)
    return fs
a, b = funcs(sys.argv[1]), funcs(sys.argv[2])
norm = lambda d: {re.sub(r'\.\d+$', '', k) if k.startswith('CSWTCH') else k: v for k, v in d.items()}
a, b = norm(a), norm(b)
print('functions', len(a), len(b), 'only before', sorted(set(a) - set(b))[:5], 'only after', sorted(set(b) - set(a))[:5])
print('differing', [k for k in a if k in b and a[k] != b[k]])
