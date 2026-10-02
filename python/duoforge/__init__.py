"""DuoForge from Python: a ctypes binding over the shared library (M7).

Python allocates, calls and views; every rule stays in the C engine.
"""
from ._lib import library_path, load_library, status_name, version
from .batch import Batch, factored_choice, factored_choices, joint_counts, joint_index, joint_indices
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
    "ScriptedPolicy",
    "factored_choice",
    "factored_choices",
    "joint_counts",
    "joint_index",
    "joint_indices",
    "library_path",
    "load_library",
    "reference_setups",
    "seeds",
    "status_name",
    "version",
]
