"""Restructure step 7: proof that the tracker package equals the former tracker.py.

    git show c02189e7:python/duoforge_live/tracker.py > OLD.py
    PYTHONPATH=python python3 tools/restructure/tracker_split_check.py OLD.py

Compares every module-level name (values; classes member by member through the MRO), the bytecode of every function
and method, their defaults, docstrings and the modules they import, and checks that every global each function of the
package loads resolves to the same value as in the former module. Exit status 1 and the differences otherwise.
"""
import builtins
import dis
import importlib
import importlib.util
import sys
import types

import numpy as np

old_path = sys.argv[1]
import duoforge_live  # noqa: E402

spec = importlib.util.spec_from_file_location("duoforge_live._tracker_old", old_path)
old = importlib.util.module_from_spec(spec)
old.__package__ = "duoforge_live"
sys.modules[spec.name] = old
spec.loader.exec_module(old)
new = importlib.import_module("duoforge_live.tracker")
SUBMODULES = {"constants", "state", "core", "conditions", "sheets", "requests", "events", "fold_event", "actions",
              "views"}

problems = []


def code_key(co):
    # constants are compared where they are loaded; nested code objects in full. The level of a relative import is
    # compared by imports() as the module it resolves to (the package sits one level deeper than the former module).
    consts = tuple(code_key(c) for c in co.co_consts if isinstance(c, types.CodeType))
    # The instructions by name and argument value: CPython 3.12 marks a call on a name bound by an import as a plain
    # attribute load (LOAD_GLOBAL's NULL bit, LOAD_ATTR's method bit), and the package imports the former module's
    # constants, so those two flags may differ; the names, the order and every other argument may not.
    raw = list(dis.get_instructions(co))
    ins = tuple((i.opname, "<import level>" if k + 2 < len(raw) and raw[k + 2].opname == "IMPORT_NAME"
                 and i.opname == "LOAD_CONST" else (repr(i.argval) if not isinstance(i.argval, types.CodeType) else None))
                for k, i in enumerate(raw))
    return (co.co_name, co.co_qualname.split(".")[-1], ins, consts, co.co_names, co.co_varnames,
            co.co_freevars, co.co_cellvars, co.co_argcount, co.co_kwonlyargcount, co.co_posonlyargcount, co.co_flags)


def same_function(a, b, where):
    if code_key(a.__code__) != code_key(b.__code__):
        problems.append(f"{where}: bytecode differs")
    if a.__defaults__ != b.__defaults__ or a.__kwdefaults__ != b.__kwdefaults__:
        problems.append(f"{where}: defaults differ")
    if a.__doc__ != b.__doc__:
        problems.append(f"{where}: docstring differs")
    if imports(a) != imports(b):
        problems.append(f"{where}: imports differ: {imports(a)} != {imports(b)}")
    check_globals(b, where)


def imports(fn):
    """The absolute module names a function imports (its relative imports resolved against its own package)."""
    out = []

    def walk(co):
        ins = list(dis.get_instructions(co))
        for k, i in enumerate(ins):
            if i.opname == "IMPORT_NAME":
                level = ins[k - 2].argval
                name = i.argval
                pkg = fn.__globals__["__package__"]
                out.append(importlib.util.resolve_name("." * level + name, pkg) if level else name)
        for c in co.co_consts:
            if isinstance(c, types.CodeType):
                walk(c)
    walk(fn.__code__)
    return out


def check_globals(fn, where):
    def walk(co):
        for ins in dis.get_instructions(co):
            if ins.opname == "LOAD_GLOBAL":
                n = ins.argval
                if n not in fn.__globals__ and not hasattr(builtins, n):
                    problems.append(f"{where}: global {n} unresolved in {fn.__module__}")
                elif n in fn.__globals__ and n in vars(old) and fn.__globals__[n] is not vars(old)[n] \
                        and not same_value(fn.__globals__[n], vars(old)[n]):
                    problems.append(f"{where}: global {n} resolves to another value")
        for c in co.co_consts:
            if isinstance(c, types.CodeType):
                walk(c)
    walk(fn.__code__)


def same_value(a, b):
    if isinstance(a, np.ndarray):
        return isinstance(b, np.ndarray) and a.dtype == b.dtype and np.array_equal(a, b)
    if isinstance(a, type) and isinstance(b, type):
        return a.__name__ == b.__name__  # compared member by member below
    if isinstance(a, types.FunctionType) and isinstance(b, types.FunctionType):
        return code_key(a.__code__) == code_key(b.__code__)
    try:
        return type(a) is type(b) and a == b
    except Exception:
        return a is b


def unwrap(v):
    if isinstance(v, (staticmethod, classmethod)):
        return type(v).__name__, v.__func__
    if isinstance(v, property):
        return "property", v.fget
    return None, v


def compare_class(a, b, where):
    names_a = {n for k in a.__mro__ if k is not object for n in vars(k)} - {"__dict__", "__weakref__", "__module__",
                                                                              "__qualname__", "__firstlineno__",
                                                                              "__static_attributes__"}
    names_b = {n for k in b.__mro__ if k is not object for n in vars(k)} - {"__dict__", "__weakref__", "__module__",
                                                                              "__qualname__", "__firstlineno__",
                                                                              "__static_attributes__"}
    if names_a != names_b:
        problems.append(f"{where}: members differ: {sorted(names_a ^ names_b)}")
    for n in sorted(names_a & names_b):
        va = next(vars(k)[n] for k in a.__mro__ if n in vars(k))
        vb = next(vars(k)[n] for k in b.__mro__ if n in vars(k))
        ka, fa = unwrap(va)
        kb, fb = unwrap(vb)
        if ka != kb:
            problems.append(f"{where}.{n}: kind {ka} != {kb}")
        elif isinstance(fa, types.FunctionType):
            same_function(fa, fb, f"{where}.{n}")
        elif not same_value(fa, fb):
            problems.append(f"{where}.{n}: value differs")
    # the old classes have no base but object (and Exception); a member defined twice in the new MRO could shadow
    defined = [n for k in b.__mro__ if k not in (object, Exception, BaseException) for n in vars(k)
               if not n.startswith("__")]
    if len(defined) != len(set(defined)):
        problems.append(f"{where}: members defined in more than one class of the MRO")
    if [k for k in a.__mro__ if k not in (a, object, Exception, BaseException)]:
        problems.append(f"{where}: the former class has bases the check does not compare")
    if a.__name__ == "SheetContradiction" and not issubclass(b, Exception):
        problems.append("SheetContradiction is no Exception")


old_names = {n for n in vars(old) if not n.startswith("__")}
new_names = {n for n in vars(new) if not n.startswith("__")} - SUBMODULES
if old_names != new_names:
    problems.append(f"module names differ: old only {sorted(old_names - new_names)}, new only "
                    f"{sorted(new_names - old_names)}")
for n in sorted(old_names & new_names):
    a, b = vars(old)[n], vars(new)[n]
    if isinstance(a, types.ModuleType):
        if a is not b:
            problems.append(f"{n}: another module")
    elif isinstance(a, type):
        compare_class(a, b, n)
    elif isinstance(a, types.FunctionType):
        same_function(a, b, n)
    elif not same_value(a, b):
        problems.append(f"{n}: value differs")
# every function of every submodule resolves its globals
for sub in sorted(SUBMODULES):
    m = importlib.import_module(f"duoforge_live.tracker.{sub}")
    for n, v in vars(m).items():
        if isinstance(v, types.FunctionType) and v.__module__ == m.__name__:
            check_globals(v, f"{sub}.{n}")
        if isinstance(v, type) and v.__module__ == m.__name__:
            for k, w in vars(v).items():
                _, f = unwrap(w)
                if isinstance(f, types.FunctionType):
                    check_globals(f, f"{sub}.{n}.{k}")
print("\n".join(problems) if problems else f"identical: {len(old_names)} names, Tracker "
      f"{sum(1 for k in new.Tracker.__mro__ for v in vars(k).values() if isinstance(unwrap(v)[1], types.FunctionType))}"
      " functions")
sys.exit(1 if problems else 0)
