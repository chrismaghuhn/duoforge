"""NumPy's SIMD dispatch on the ladder box, checked (#484, HauptSession 2026-10-15): the box runs NumPy on the local
machine's targets (X86_V3, AVX2), never on AVX-512.

    NPY_DISABLE_CPU_FEATURES="X86_V4 AVX512_ICL AVX512_SPR" python numpy_dispatch.py OUT.json

NumPy picks its exp, log and sum routines at run time; the first AWS equality proof (2026-10-14) differed in its
decisions with every result equal, the c7a's EPYC on AVX-512, the local Ryzen on AVX2. NPY_DISABLE_CPU_FEATURES turns
NumPy's AVX-512 targets off. This tool checks, with the NumPy the box runs (ladder_requirements.txt):
- every name in NPY_DISABLE_CPU_FEATURES is one of NumPy's dispatch targets (read in a child process without the
  variable: a misspelt or a baseline name would disable nothing);
- with the variable set, no AVX-512 target (X86_V4, AVX512_*) is enabled.
It writes the record (the names disabled, NumPy's baseline, the targets found and not found) to OUT.json either way,
and exits 0 when the check passes, 3 with the reason on stderr when it does not (the box then refuses by name,
numpy_dispatch, and runs nothing). Exit 2: a usage error.
"""
import json
import os
import subprocess
import sys

READ = ("from numpy._core import _multiarray_umath as m; import json; "
        "print(json.dumps([list(m.__cpu_baseline__), list(m.__cpu_dispatch__), dict(m.__cpu_features__)]))")


def avx512(target):
    """Whether a NumPy dispatch target is an AVX-512 one."""
    return target == "X86_V4" or target.startswith("AVX512")


def check(disabled_text, baseline, dispatch, known, features):
    """(problem or None, record). disabled_text: NPY_DISABLE_CPU_FEATURES; baseline: NumPy's baseline targets; dispatch:
    its dispatch targets with the variable set; known: its dispatch targets without the variable (the names the variable
    may hold); features: target -> enabled, with the variable set."""
    names = disabled_text.split()
    found = [t for t in dispatch if features.get(t)]
    record = {"disabled": names, "baseline": list(baseline), "found": found,
              "not_found": [t for t in dispatch if not features.get(t)]}
    if not names:
        return "NPY_DISABLE_CPU_FEATURES is not set", record
    unknown = [n for n in names if n not in known]
    if unknown:
        return (f"NPY_DISABLE_CPU_FEATURES names {unknown}, which are not among NumPy's dispatch targets {list(known)}: "
                "they would disable nothing"), record
    on = [t for t in found if avx512(t)]
    if on:
        return f"NumPy still enables the AVX-512 target(s) {on} with NPY_DISABLE_CPU_FEATURES={disabled_text!r}", record
    return None, record


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    env = {k: v for k, v in os.environ.items() if k != "NPY_DISABLE_CPU_FEATURES"}
    child = subprocess.run([sys.executable, "-c", READ], capture_output=True, text=True, env=env)
    if child.returncode != 0:
        print(f"numpy_dispatch: NumPy did not load without NPY_DISABLE_CPU_FEATURES: {child.stderr.strip()}",
              file=sys.stderr)
        return 3
    _, known, _ = json.loads(child.stdout)
    try:
        from numpy._core import _multiarray_umath as m  # with the variable set
    except Exception as err:  # NumPy refuses some names itself (a baseline target): a refusal, named
        print(f"numpy_dispatch: NumPy did not load with NPY_DISABLE_CPU_FEATURES="
              f"{os.environ.get('NPY_DISABLE_CPU_FEATURES', '')!r}: {err}", file=sys.stderr)
        return 3
    problem, record = check(os.environ.get("NPY_DISABLE_CPU_FEATURES", ""), m.__cpu_baseline__, m.__cpu_dispatch__,
                            known, dict(m.__cpu_features__))
    record["ok"] = problem is None
    with open(args[0], "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1)
    if problem:
        print(f"numpy_dispatch: {problem}", file=sys.stderr)
        return 3
    print(json.dumps(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
