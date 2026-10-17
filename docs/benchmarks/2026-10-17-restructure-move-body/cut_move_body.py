"""Cut dfi_run_move_body (src/combat/turn.c) into named phase functions; bodies are the original lines.

Usage: python3 cut_move_body.py <repo> [--plan]   (--plan prints the variable plan and writes nothing)
"""
from pathlib import Path
import re, sys
root = Path(sys.argv[1]); plan_only = '--plan' in sys.argv
turn = root / 'src/combat/turn.c'
L = turn.read_text().split('\n')
s = next(i for i, l in enumerate(L) if l.startswith('static duoforge_status dfi_run_move_body('))
e = s
while L[e] != '}':
    e += 1
F = L[s:e + 1]                  # F[k-1] = function line k
N = len(F)
PHASES = [  # name, first, last (function lines), comment
    ('dfi_move_body_prepare', 10, 108, 'the actor and its targets, getTarget, BeforeMove, Mega Sol'),
    ('dfi_move_body_announce', 109, 218, 'the PP, ModifyMove, Stance Change and the move line'),
    ('dfi_move_body_try_move', 219, 404, 'the redirections, Dragon Darts, Pressure, the charge turn and TryMove'),
    ('dfi_move_body_status_handlers', 405, 615, 'the status moves with their own handler'),
    ('dfi_move_body_hit_steps', 616, 1028, 'onTry, the accuracy modifiers and the hit steps, the status hit'),
    ('dfi_move_body_hit_loop', 1029, 1843, 'the hit loop'),
    ('dfi_move_body_after_loop', 1844, N - 1, 'recoil, MoveFail, selfBoost and Life Orb (the last phase)'),
]
PRELUDE = (3, 9)

# code text without comments and strings, per line
def code_lines(lines):
    out, inc = [], False
    for l in lines:
        t = re.sub(r'"(\\.|[^"\\])*"', '""', l)
        res = ''
        i = 0
        while i < len(t):
            if inc:
                j = t.find('*/', i)
                if j < 0: i = len(t); break
                inc = False; i = j + 2; continue
            if t.startswith('/*', i): inc = True; i += 2; continue
            if t.startswith('//', i): break
            res += t[i]; i += 1
        out.append(res)
    return out
C = code_lines(F)
depth, d = [0] * (N + 2), 0
for k, c in enumerate(C, 1):
    depth[k] = d
    d += c.count('{') - c.count('}')
DECL = re.compile(r'^    ((?:const\s+)?(?:struct\s+)?[A-Za-z_]\w*(?:\s*\*\s*|\s+)(?:const\s+)?)([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*(=|;)')
decls = {}
for k in range(2, N):
    if depth[k] != 1: continue
    m = DECL.match(F[k - 1])
    if m and m.group(1).split()[0] not in ('return', 'else', 'goto', 'case'):
        decls[m.group(2)] = dict(line=k, type=m.group(1).strip(), array=m.group(3), const=m.group(1).startswith('const'))
def phase_of(k):
    if PRELUDE[0] <= k <= PRELUDE[1]: return -1
    return next(i for i, p in enumerate(PHASES) if p[1] <= k <= p[2])
used = {v: set() for v in decls}
for k in range(2, N):
    for v in decls:
        if k != decls[v]['line'] and re.search(r'(?<![\w.])(?<!->)' + v + r'\b', C[k - 1]):
            used[v].add(phase_of(k))
for v, dd in decls.items():
    dd['phase'] = phase_of(dd['line'])
cross = {v for v in decls if any(p != decls[v]['phase'] for p in used[v])}
arrays = {v for v in cross if decls[v]['array']}
ARRAYS = {decls[v]['line']: v for v in arrays}   # array declarations that move to the caller
scalars = sorted(cross - arrays, key=lambda v: decls[v]['line'])
plan = []
for i, (name, a, b, what) in enumerate(PHASES):
    unpack = [v for v in scalars if decls[v]['phase'] < i and i in used[v]]
    later = lambda v: any(p > i for p in used[v])
    back = [v for v in scalars if later(v) and (decls[v]['phase'] == i or (decls[v]['phase'] < i and i in used[v] and not decls[v]['const']))]
    arr = [v for v in sorted(arrays, key=lambda v: decls[v]['line']) if i in used[v]]
    plan.append((name, a, b, what, unpack, back, arr))
if plan_only:
    for v in scalars: print(f"{v:22s} {decls[v]['type']:28s} line {decls[v]['line']:5d} phase {decls[v]['phase']} used {sorted(used[v])}")
    for p in plan: print(p[0], p[1], p[2], 'unpack', p[4], 'back', p[5], 'arrays', p[6])
    sys.exit(0)
# the context of the scalars that cross phases
ctx = ['/* The locals of dfi_run_move_body that more than one phase uses (restructure step 4, move body), on the caller\'s',
       ' * stack: each phase starts from them and leaves its changes in them. The arrays (targets, hit) stay the caller\'s. */',
       'typedef struct dfi_move_body_state {']
for v in scalars:
    t = decls[v]['type']
    if t.startswith('const ') and '*' not in t:
        t = t[len('const '):]  # a const value: the state's field is written once, by the phase that declares it
    t = re.sub(r'\s*\*\s*const\s*$', ' *', t)
    sep = '' if t.endswith('*') else ' '
    ctx.append(f'    {t}{sep}{v};')
ctx += ['} dfi_move_body_state;', '']
stop = ['/* A return of dfi_run_move_body inside a phase: the move ends there with `value`, as the one function returned it. */',
        'static DFI_ALWAYS_INLINE duoforge_status dfi_move_body_stop(bool *stop, duoforge_status value)',
        '{', '    *stop = true;', '    return value;', '}', '']
RET = re.compile(r'^(\s*)return (.*);(\s*/\*.*\*/)?$')
def body(a, b, last):
    out = []
    for k in range(a, b + 1):
        l = F[k - 1]
        if k in ARRAYS:
            continue
        mm = RET.match(l) if depth[k] >= 1 and C[k - 1].strip().startswith('return') else None
        if not last and C[k - 1].strip().startswith('return'):
            assert mm and C[k - 1].strip().endswith(';'), (k, l)
            l = f'{mm.group(1)}return dfi_move_body_stop(stop, {mm.group(2)});' + (mm.group(3) or '')
        out.append(l)
    return out
def sig(name, arr, last):
    params = ['dfi_run *r', 'const dfi_queue_record *q', 'bool *ran', 'dfi_move_body_state *c']
    params += [f"{decls[v]['type'].replace('const ', '')} *{v}" for v in arr]
    if not last: params.append('bool *stop')
    head = f'static DFI_ALWAYS_INLINE duoforge_status {name}('
    lines, cur = [], head
    for i, p in enumerate(params):
        piece = p + (', ' if i < len(params) - 1 else ')')
        if len(cur) + len(piece) > 120:
            lines.append(cur.rstrip()); cur = ' ' * len(head) + piece
        else:
            cur += piece
    return lines + [cur]
new = ctx + stop
for i, (name, a, b, what, unpack, back, arr) in enumerate(plan):
    last = i == len(plan) - 1
    new += [f'/* Phase {i + 1} of dfi_run_move_body: {what}. */'] + sig(name, arr, last) + ['{']
    for v in unpack:
        t = decls[v]['type']
        sep = '' if t.endswith('*') else ' '
        new.append(f'    {t}{sep}{v} = c->{v};')
    uses_any = lambda w: any(re.search(r'(?<![\w.])(?<!->)' + w + r'\b', C[k - 1]) for k in range(a, b + 1))
    for w in ('ran', 'q', 'r'):
        if not uses_any(w) and not (w == 'r' and unpack):
            new.append(f'    (void){w};')
    if not unpack and not uses_any('c'):
        pass
    new += body(a, b, last)
    if not last:
        new += [f'    c->{v} = {v};' for v in back] + ['    return DUOFORGE_OK;']
    new += ['}', '']
# the caller: the prelude, the arrays, the state and the phases in order
caller = [F[0], F[1]] + F[PRELUDE[0] - 1:PRELUDE[1]]
caller += [F[k - 1] for k in sorted(ARRAYS)]
caller += ['    dfi_move_body_state c;', '    bool stop = false;', '    duoforge_status st = DUOFORGE_OK;']
init = {'b': 'b', 'side': 'side', 'user': 'user', 'pos': 'pos', 'm': 'm'}
for v in scalars:
    if v in init: caller.append(f'    c.{v} = {init[v]};')
for i, (name, a, b, what, unpack, back, arr) in enumerate(plan):
    args = ['r', 'q', 'ran', '&c'] + list(arr)
    if i == len(plan) - 1:
        caller.append(f"    return {name}({', '.join(args)});")
    else:
        caller += [f"    st = {name}({', '.join(args + ['&stop'])});", '    if (stop) {', '        return st;', '    }']
caller.append('}')
L[s:e + 1] = new + caller
turn.write_text('\n'.join(L))
print('ok', len(F), '->', len(new) + len(caller))
