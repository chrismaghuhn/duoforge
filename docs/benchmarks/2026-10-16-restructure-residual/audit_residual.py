"""Audit of the residual cut: every phase body is the old function's lines; the only edits are the stop returns."""
import re, subprocess, sys, json, hashlib
repo, old_rev, new_rev = sys.argv[1:4]
show = lambda rev: subprocess.check_output(['git', 'show', f'{rev}:src/combat/turn.c'], cwd=repo, text=True).split('\n')
def body(L, sig):
    s = next(i for i, l in enumerate(L) if l.startswith(sig))
    while L[s] != '{': s += 1
    e, d = s, 0
    while True:
        d += L[e].count('{') - L[e].count('}')
        if d == 0: return s + 1, e  # lines inside the braces: L[s+1:e]
        e += 1
O = show(old_rev); N = show(new_rev)
a, b = body(O, 'static duoforge_status dfi_residual_events_run(')
F = O[a:b]                                        # F[k-2] is the function's line k (line 1 is the signature, 2 the brace)
R = lambda x, y: F[x - 3:y - 2]                   # old function lines x..y
phases = [('dfi_residual_collect', 24, 180, 0, 2), ('dfi_residual_order', 181, 226, 1, 4),
          ('dfi_residual_early', 227, 515, 1, 1), ('dfi_residual_durations', 516, 621, 1, 1),
          ('dfi_residual_late', 622, 661, 0, 1), ('dfi_residual_noorder', 662, 765, 1, 0)]
rows, stops = [], 0
for name, x, y, pre, post in phases:
    s, e = body(N, 'static DFI_FORCE_INLINE duoforge_status ' + name + '(')
    got = N[s + pre:e - post] if post else N[s + pre:e]
    want = R(x, y)
    if name == 'dfi_residual_order':
        want = R(181, 210) + R(212, 226)          # `first` is the caller's (its declaration moves there)
    edits = [(w, g) for w, g in zip(want, got) if w != g]
    assert len(got) == len(want), (name, len(got), len(want))
    assert all(re.fullmatch(r'\s*return DUOFORGE_OK;', w) and g == w.replace('return DUOFORGE_OK;', 'return dfi_residual_stop(stop);')
               for w, g in edits), (name, edits[:3])
    stops += len(edits)
    rows.append(dict(phase=name, old_function_lines=[x, y], new_lines=[s + pre + 1, s + pre + len(got)], stop_returns=len(edits),
                     body_sha256=hashlib.sha256('\n'.join(got).encode()).hexdigest()))
s, e = body(N, 'static duoforge_status dfi_residual_events_run(')
assert N[s:s + 21] == R(3, 23), 'prelude'
print(json.dumps(dict(old=old_rev, new=new_rev, old_function_lines=len(F) + 2, stop_returns=stops, phases=rows), indent=1))
