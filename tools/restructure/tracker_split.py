"""Restructure step 7: split the former python/duoforge_live/tracker.py into a package by fold family.

    git show c02189e7:python/duoforge_live/tracker.py > OLD.py
    python3 tools/restructure/tracker_split.py OLD.py python/duoforge_live/tracker

Pure move: every statement keeps its text (a method's relative import goes one package level up); Tracker's methods
go to one mixin class per family, the module's names to their own modules, and __init__ re-exports every name the
former module had. Prints the old-line -> new-file map. tracker_split_check.py proves the result equal.
"""
import ast
import builtins
import dis
import sys
import types
from pathlib import Path

SRC = Path(sys.argv[1]).read_text(encoding="utf-8")
OUT = Path(sys.argv[2])
L = SRC.splitlines(keepends=True)
tree = ast.parse(SRC)

FAMILIES = {  # module: (mixin class, docstring, methods)
    "conditions": ("_ConditionFolds", "Boosts, Attract, Throat Chop, the partial trap and the extended field turns that lines set",
                   ["_set_boost", "_silent_attract_end", "_throat_chop", "_trap_move_id", "_trap_clear", "_trap_start",
                    "_trap_end", "_trap_silent_end", "_trap_residual", "_trap_source_left", "_extended_field"]),
    "sheets": ("_SheetReads", "What lines.check reads: sheets, abilities and items of the members",
               ["sheet_of", "known_sheet", "side_sheets", "ability_now", "_ability_at", "item_now", "_item_of", "_holds",
                "_holds_id", "_item_received", "_member_of"]),
    "requests": ("_RequestFolds", "Own choices, requests and the |showteam| sheets",
                 ["accepted", "ready", "_on_request", "_on_updated_request", "_on_showteam", "_foe_sheet", "_member"]),
    "events": ("_EventFolds", "Lines into events, and the move action an event belongs to",
               ["_register", "_fold", "_at", "current_types", "_occupant", "_event", "_residual_end", "_segment",
                "_bounce_cant", "_pre_action", "_end_action"]),
    "fold_event": ("_EventFold", "One event into the tracker's fields",
                   ["_fold_event"]),
    "actions": ("_ActionFolds", "Switch rights, own displays, Ally Switch, Baton Pass, the residual, damage and Pressure",
                ["_can_switch", "_move_action", "_own_display", "_own_target", "_swap_positions", "_ally_pass", "_upkeep",
                 "_hurt", "_pressure_extra"]),
    "views": ("_Views", "The output at a decision point: observation, its extension, the domain and the public parts",
              ["boundary", "_requested", "_occupied", "_foe_switch_slots", "observation", "_shown_locked_slot", "_view_side",
               "_view_member", "request_record", "public_parts", "observation_ext", "domain"]),
}
CORE = ["__init__", "feed", "_battle_line", "_turn_scoped_stop"]
STATE_NAMES = ["_condition", "_Position", "_SWAP_MOVES", "_SWAP_SLOT", "_Member", "SheetContradiction"]
MODULE_IMPORTS = {  # names the old module imported, and how a package module imports them
    "collections": "import collections", "json": "import json", "np": "import numpy as np",
    "_layout": "from duoforge import _layout", "_ENC": "from duoforge._state_layout import VALUES as _ENC",
    "lines": "from .. import lines", "options": "from .. import options", "teams": "from .. import teams",
    "trace_to_c": "from ..data import trace_to_c",
}

body = tree.body
doc = body[0]
assert isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)
cls = next(n for n in body if isinstance(n, ast.ClassDef) and n.name == "Tracker")
restrict = next(n for n in body if isinstance(n, ast.FunctionDef) and n.name == "restrict_ext")
first_state = next(n for n in body if getattr(n, "name", None) == "_condition")
sheet_exc = next(n for n in body if getattr(n, "name", None) == "SheetContradiction")
last_import = max(n.end_lineno for n in body if isinstance(n, (ast.Import, ast.ImportFrom)))


def start(node):
    return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])


def text(a, b):  # 1-based inclusive
    """The lines, with a function's relative import one package level up (the package sits one level deeper)."""
    out = []
    for line in L[a - 1:b]:
        stripped = line.lstrip()
        if line[:1] == " " and stripped.startswith("from ."):
            line = line[:len(line) - len(stripped)] + "from .." + stripped[len("from ."):]
        out.append(line)
    return "".join(out)


def trimmed(a, b):
    """Lines a..b without leading and trailing blank lines."""
    while a <= b and not L[a - 1].strip():
        a += 1
    while b >= a and not L[b - 1].strip():
        b -= 1
    return a, b


mapping = []  # (old a, old b, new file)

# Tracker's members: each method's segment runs from the line after the previous member to its end, so the comments
# and section headers before it go with it.
methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef,))]
first_method = methods[0]
head_a, head_b = cls.lineno, start(first_method) - 1  # class line, docstring, class defaults
segments = {}
prev_end = head_b
for m in methods:
    a, b = trimmed(prev_end + 1, m.end_lineno)
    segments[m.name] = (a, b)
    prev_end = m.end_lineno
assigned = set(CORE) | {n for _, _, ms in FAMILIES.values() for n in ms}
names = [m.name for m in methods]
assert sorted(assigned) == sorted(names), (set(names) - assigned, assigned - set(names))
assert len(set(names)) == len(names)

# module-level definitions of the old module (for the import headers)
defined = {}  # name -> package module
for n in body:
    if isinstance(n, (ast.Assign,)):
        for t in n.targets:
            for e in ast.walk(t):
                if isinstance(e, ast.Name):
                    defined[e.id] = "constants"
for n in STATE_NAMES:
    defined[n] = "state"
defined["Tracker"] = "core"
defined["restrict_ext"] = "views"
for k in MODULE_IMPORTS:
    defined[k] = "import"


def global_names(source, filename):
    """Every global a piece of code loads (LOAD_GLOBAL / LOAD_NAME at module level, recursively)."""
    code = compile(source, filename, "exec")
    out = set()

    def walk(co, top):
        for ins in dis.get_instructions(co):
            if ins.opname == "LOAD_GLOBAL" or (top and ins.opname in ("LOAD_NAME",)):
                out.add(ins.argval)
        for c in co.co_consts:
            if isinstance(c, types.CodeType):
                walk(c, False)
    walk(code, True)
    return out


def header(module, doc_line, source, own):
    """The module's docstring and the imports of every global its code uses that it does not define itself."""
    used = global_names(source, module) - set(dir(builtins)) - own
    imports = sorted(MODULE_IMPORTS[n] for n in used if defined.get(n) == "import")
    std = [i for i in imports if i.startswith("import ")]
    third = [i for i in imports if i.startswith("from duoforge")]
    rel = merge_rel([i for i in imports if i.startswith("from ..")])
    by_module = {}
    for n in used:
        where = defined.get(n)
        if where is None:
            raise SystemExit(f"{module}: global {n!r} is defined nowhere")
        if where not in ("import",):
            by_module.setdefault(where, []).append(n)
    local = [f"from .{m} import {', '.join(sorted(ns, key=lambda s: (s.lstrip('_').lower(), s)))}"
             for m, ns in sorted(by_module.items())]
    parts = [f'"""{doc_line}.\n\nPart of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure\nstep 7); the package re-exports every name of the former module.\n"""\n']
    blocks = []
    std_only = [i for i in std if "numpy" not in i]
    if std_only:
        blocks.append("".join(i + "\n" for i in std_only))
    if "import numpy as np" in imports:
        blocks.append("import numpy as np\n")
    if third:
        blocks.append("".join(i + "\n" for i in third))
    if rel or local:
        blocks.append("".join(i + "\n" for i in rel + wrap(local)))
    return parts[0] + ("\n" + "\n".join(blocks) if blocks else "")


def merge_rel(stmts):
    """`from .. import a` and `from .. import b` as one `from .. import a, b`, as the former module wrote them."""
    plain = sorted(i[len("from .. import "):] for i in stmts if i.startswith("from .. import "))
    rest = [i for i in stmts if not i.startswith("from .. import ")]
    return ([f"from .. import {', '.join(plain)}"] if plain else []) + rest


def wrap(stmts, width=120):
    out = []
    for s in stmts:
        if len(s) <= width:
            out.append(s)
            continue
        head, rest = s.split(" import ", 1)
        items = rest.split(", ")
        line = head + " import ("
        lines_ = []
        cur = line
        indent = " " * len(line)
        for i, it in enumerate(items):
            piece = it + ("," if i < len(items) - 1 else ")")
            if len(cur) + len(piece) + (1 if cur != line else 0) > width:
                lines_.append(cur.rstrip())
                cur = indent + piece
            else:
                cur = cur + ("" if cur == line else " ") + piece
        lines_.append(cur)
        out.append("\n".join(lines_))
    return out


OUT.mkdir(parents=True, exist_ok=True)
files = {}

# constants: the old imports' lines are dropped (each module imports its own); the constants keep their text
const_a, const_b = trimmed(last_import + 1, start(first_state) - 1)
const_src = text(const_a, const_b)
mapping.append((const_a, const_b, "constants.py"))
own = {k for k, v in defined.items() if v == "constants"}
files["constants.py"] = header("constants", "The constants and tables the tracker folds with", const_src, own) + "\n" + const_src

# state
st_a, st_b = trimmed(start(first_state), sheet_exc.end_lineno)
st_src = text(st_a, st_b)
mapping.append((st_a, st_b, "state.py"))
files["state.py"] = header("state", "A position's and a member's folded state, and the closed-sheet contradiction", st_src,
                           set(STATE_NAMES)) + "\n\n" + st_src

# mixins
for module, (mixin, docline, ms) in FAMILIES.items():
    chunks = []
    for name in ms:
        a, b = segments[name]
        chunks.append(text(a, b))
        mapping.append((a, b, f"{module}.py"))
    src = f"class {mixin}:\n" + "\n".join(chunks)
    extra = ""
    if module == "views":
        ra, rb = trimmed(cls.end_lineno + 1, restrict.end_lineno)
        extra = "\n\n" + text(ra, rb)
        mapping.append((ra, rb, "views.py"))
        src += extra
    own = {"restrict_ext"} if module == "views" else set()
    files[f"{module}.py"] = header(module, docline, src, own | {mixin}) + "\n\n" + src

# core: the class line gets the mixins, then the class head and the core methods
core_chunks = []
for name in CORE:
    a, b = segments[name]
    core_chunks.append(text(a, b))
    mapping.append((a, b, "core.py"))
mixins = [m for m, _, _ in FAMILIES.values()]
class_line = L[cls.lineno - 1]
assert class_line == "class Tracker:\n", class_line
bases = ", ".join(mixins)
new_class_line = f"class Tracker({bases}):\n"
if len(new_class_line) > 121:
    new_class_line = "class Tracker(" + ",\n              ".join(mixins) + "):\n"
head = text(cls.lineno + 1, head_b)
while head.endswith("\n\n"):
    head = head[:-1]
mapping.append((cls.lineno, head_b, "core.py"))
core_src = new_class_line + head + "\n" + "\n".join(core_chunks)
mix_imports = "".join(f"from .{m} import {FAMILIES[m][0]}\n" for m in FAMILIES)
core_hdr = header("core", "The tracker: one battle room as one player sees it", core_src, set(mixins) | {"Tracker"})
core_hdr = core_hdr.rstrip("\n") + "\n" + mix_imports
files["core.py"] = core_hdr + "\n\n" + core_src

# __init__: the old docstring, then every old module-level name re-exported
old_names = set()
for n in body:
    if isinstance(n, ast.Assign):
        for t in n.targets:
            for e in ast.walk(t):
                if isinstance(e, ast.Name):
                    old_names.add(e.id)
    elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
        old_names.add(n.name)
    elif isinstance(n, ast.Import):
        old_names.update((a.asname or a.name) for a in n.names)
    elif isinstance(n, ast.ImportFrom):
        old_names.update((a.asname or a.name) for a in n.names)
init = text(doc.lineno, doc.end_lineno - 1)  # the docstring without its closing quotes
init += ("\nThe package (restructure step 7) splits the former tracker.py by fold family: constants (the constants and\n"
         "tables), state (_Position, _Member), core (Tracker: input and the battle line), conditions, sheets, requests,\n"
         "events, fold_event (_fold_event), actions and views (the output), each family a mixin of Tracker. This module\n"
         "re-exports every name the former module had, so `from duoforge_live.tracker import X` and `tracker.X` keep\n"
         "working.\n\"\"\"\n")
mods = [i for k, i in MODULE_IMPORTS.items() if k in old_names]
std = sorted(i for i in mods if i.startswith("import ") and "numpy" not in i)
blocks = ["".join(i + "\n" for i in std), "import numpy as np\n",
          "".join(sorted(i + "\n" for i in mods if i.startswith("from duoforge")))]
reexp = {}
for nm in sorted(old_names - set(MODULE_IMPORTS)):
    reexp.setdefault(defined[nm], []).append(nm)
rel = merge_rel(sorted(i for i in mods if i.startswith("from ..")))
loc = wrap([f"from .{m} import {', '.join(sorted(ns, key=lambda s: (s.lstrip('_').lower(), s)))}"
            for m, ns in sorted(reexp.items())])
blocks.append("".join(i + "\n" for i in rel + loc))
files["__init__.py"] = init + "\n" + "\n".join(blocks)

for name, content in files.items():
    (OUT / name).write_text(content, encoding="utf-8")

covered = set()
for a, b, f in sorted(mapping):
    print(f"{a}-{b}\t{f}")
    covered.update(range(a, b + 1))
rest = [i for i in range(1, len(L) + 1) if i not in covered and L[i - 1].strip()
        and not (doc.lineno <= i <= doc.end_lineno) and not (1 <= i <= last_import)]
print("uncovered non-blank lines:", rest, file=sys.stderr)
