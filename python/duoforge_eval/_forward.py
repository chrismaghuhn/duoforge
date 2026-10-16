"""The forwarders at the old paths of moved entry points (restructure step 8).

An old module calls alias() when it is imported: its sys.modules entry becomes the new module itself, so
`from duoforge_search import arena`, `duoforge_search.arena.X` and mock.patch("duoforge_search.arena.X") reach the
very module the new name does. Run as a program (python -m OLD), it calls run(): the new name is printed on stderr
and the new module runs as __main__ with the same arguments.
"""
import importlib
import runpy
import sys


def alias(old, new):
    """Makes the module named old (being imported) the module named new."""
    sys.modules[old] = importlib.import_module(new)


def run(old, new):
    """Runs the module named new as python -m new would, after naming it on stderr."""
    print(f"{old} moved to {new}: run python -m {new} (this forwarder will be removed)", file=sys.stderr, flush=True)
    runpy.run_module(new, run_name="__main__", alter_sys=True)
