"""Top-level statements of gen_closure.py, the names each defines and uses (load), for the area split."""
import ast
import json
import sys

src = open(sys.argv[1]).read()
tree = ast.parse(src)
lines = src.split('\n')
stmts = []
defined_at = {}
for i, node in enumerate(tree.body):
    names = set()
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        names.add(node.name)
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    names.add(n.id)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        names.add(node.target.id)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        for a in node.names:
            names.add((a.asname or a.name).split('.')[0])
    uses = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            uses.add(n.id)
    # module-level (import-time) uses: everything outside function bodies
    now = set()
    def walk_now(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and n is not node:
            # decorators and defaults run now
            for d in getattr(n, 'decorator_list', []):
                walk_now(d)
            return
        if isinstance(n, ast.FunctionDef) and n is node:
            for d in n.decorator_list:
                walk_now(d)
            for d in n.args.defaults + n.args.kw_defaults:
                if d is not None:
                    walk_now(d)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            now.add(n.id)
        for c in ast.iter_child_nodes(n):
            walk_now(c)
    walk_now(node)
    kind = type(node).__name__
    stmts.append({'i': i, 'line': node.lineno, 'end': node.end_lineno, 'kind': kind, 'defines': sorted(names),
                  'uses': sorted(uses), 'uses_now': sorted(now)})
    for nm in names:
        defined_at.setdefault(nm, []).append(i)
redef = {k: v for k, v in defined_at.items() if len(v) > 1}
json.dump({'stmts': stmts, 'redefined': redef}, open(sys.argv[2], 'w'), indent=0)
print(len(stmts), 'statements;', len(defined_at), 'names; redefined:', redef)
