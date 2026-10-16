"""Evaluation runs: arenas, A/B comparisons, ladders and expert evaluations (restructure step 8, plan "Runs").

The entry points moved here from duoforge_learn and duoforge_search, which keep only learning and search code;
each old module is a forwarder (_forward) until no session uses the old names. Run outputs go through
duoforge.runs: --out or $DUOFORGE_RUNS/eval/<date>-<name>/, never inside the repository.

JAX takes GPU memory as it needs it, as under duoforge_learn (whose package the learning-side tools were imported
through): the GPU also drives the desktop.
"""
import os

os.environ.setdefault("XLA_PYTHON_CLIENT_PREALLOCATE", "false")
