"""Restructure step 5a: every top-level statement of tools/datagen/gen_closure.py at the base commit is, verbatim, in
exactly one of the split files, and each file keeps the statements in their old order.

Usage: python3 verify_split.py <repo> <base commit>
Imports are left out (each module imports what it uses); the docstring of gen_closure.py must be unchanged.
"""
import ast
import os
import subprocess
import sys

repo, base = sys.argv[1], sys.argv[2]
old_src = subprocess.check_output(['git', 'show', '%s:tools/datagen/gen_closure.py' % base], cwd=repo, text=True)


def segments(src):
    tree = ast.parse(src)
    out = []
    for i, n in enumerate(tree.body):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        if i == 0 and isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
            continue  # a module docstring
        out.append(ast.get_source_segment(src, n))
    return out, ast.get_docstring(tree, clean=False)


old, old_doc = segments(old_src)
files = ['tools/datagen/gen_closure.py'] + sorted(
    os.path.join('tools/datagen/tablegen', f) for f in os.listdir(os.path.join(repo, 'tools/datagen/tablegen'))
    if f.endswith('.py') and f != '__init__.py')
pos = {s: k for k, s in enumerate(old)}
assert len(pos) == len(old), 'two old statements have the same text'
seen = []
for f in files:
    segs, doc = segments(open(os.path.join(repo, f)).read())
    if f.endswith('gen_closure.py'):
        assert doc == old_doc, 'the docstring of gen_closure.py changed'
        # the re-export loop and its del are the only new statements of gen_closure.py
        segs = [s for s in segs if not s.startswith(('for _area in', 'del _area'))]
    idx = []
    for s in segs:
        assert s in pos, '%s: a statement that is not in the old file:\n%s' % (f, s[:200])
        idx.append(pos[s])
    assert idx == sorted(idx), '%s: the statements are not in their old order' % f
    seen += idx
    print('%-40s %4d statements' % (f, len(segs)))
assert sorted(seen) == list(range(len(old))), 'missing or doubled statements: %s' % sorted(
    set(range(len(old))) ^ set(seen))
print('all %d top-level statements of gen_closure.py@%s are unchanged, each in exactly one file, in order' % (
    len(old), base[:8]))
