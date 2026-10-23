"""Audit of the move-body cut: every phase body is dfi_run_move_body's lines; the only edits are the returns.

Usage: python3 audit_move_body.py <repo> <old rev> <new rev>
"""
import hashlib, json, re, subprocess, sys
repo, old_rev, new_rev = sys.argv[1:4]
show = lambda rev: subprocess.check_output(['git', 'show', f'{rev}:src/combat/turn.c'], cwd=repo, text=True).split('\n')
def span(L, sig):
    s = next(i for i, l in enumerate(L) if l.startswith(sig))
    while L[s] != '{': s += 1
    e = s
    while L[e] != '}': e += 1
    return s + 1, e          # lines strictly inside the braces
O, N = show(old_rev), show(new_rev)
a, b = span(O, 'static duoforge_status dfi_run_move_body(')
F = O[a - 2:b + 1]            # F[k-1] = old function line k (k=1 signature)
PHASES = [('dfi_move_body_prepare', 10, 108), ('dfi_move_body_announce', 109, 218), ('dfi_move_body_try_move', 219, 404),
          ('dfi_move_body_status_handlers', 405, 615), ('dfi_move_body_hit_steps', 616, 1028),
          ('dfi_move_body_hit_loop', 1029, 1843), ('dfi_move_body_after_loop', 1844, len(F) - 1)]
UNPACK = re.compile(r'^    [^=]*\b(\w+) = c->\1;$')
BACK = re.compile(r'^    c->(\w+) = \1;$')
moved, rows, edits_total = [], [], 0
caller_s, caller_e = span(N, 'static duoforge_status dfi_run_move_body(')
caller = N[caller_s:caller_e]
assert caller[:7] == F[2:9], 'prelude'
for i, (name, x, y) in enumerate(PHASES):
    s, e = span(N, 'static DFI_ALWAYS_INLINE duoforge_status ' + name + '(')
    body = N[s:e]
    k = 0
    while k < len(body) and (UNPACK.match(body[k]) or re.fullmatch(r'    \(void\)\w+;', body[k])): k += 1
    j = len(body)
    if i < len(PHASES) - 1:
        assert body[j - 1] == '    return DUOFORGE_OK;'; j -= 1
        while BACK.match(body[j - 1]): j -= 1
    got = body[k:j]
    want = [l for n, l in zip(range(x, y + 1), F[x - 1:y]) if not (l in caller and re.match(r'^    (uint32_t|bool) \w+\[DFI_POSITIONS\] = ', l) and not moved.append((n, l)))]
    assert len(got) == len(want), (name, len(got), len(want))
    edits = [(w, g) for w, g in zip(want, got) if w != g]
    for w, g in edits:
        m = re.fullmatch(r'(\s*)return (.*);(\s*/\*.*\*/)?', w)
        assert m and g == f'{m.group(1)}return dfi_move_body_stop(stop, {m.group(2)});' + (m.group(3) or ''), (name, w, g)
    assert i < len(PHASES) - 1 or not edits
    edits_total += len(edits)
    rows.append(dict(phase=name, old_function_lines=[x, y], new_lines=[s + k + 1, s + j], stop_returns=len(edits),
                     body_sha256=hashlib.sha256('\n'.join(got).encode()).hexdigest()))
assert all(l in caller for n, l in moved)
print(json.dumps(dict(old=old_rev, new=new_rev, old_function_lines=len(F), stop_returns=edits_total,
                      arrays_moved_to_caller=[dict(old_function_line=n, line=l.strip()) for n, l in moved], phases=rows), indent=1))
