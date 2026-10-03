"""DuoForge from Python: a ctypes binding over the shared library (M7).

Python allocates, calls and views; every rule stays in the C engine.
"""
from . import data
from ._lib import library_path, load_library, status_name, version
from .batch import Batch, factored_choice, factored_choices, joint_counts, joint_index, joint_indices, search_seeds
from .context import Context, reference_setups
from .errors import DuoforgeError, DuoforgeLibraryError
from .policies import RandomPolicy, ScriptedPolicy, seeds
from . import data, teams

__all__ = [
    "Batch",
    "Context",
    "DuoforgeError",
    "DuoforgeLibraryError",
    "RandomPolicy",
    "data",
    "ScriptedPolicy",
    "factored_choice",
    "factored_choices",
    "joint_counts",
    "joint_index",
    "joint_indices",
    "library_path",
    "load_library",
    "reference_setups",
    "search_seeds",
    "seeds",
    "status_name",
    "version",
]
