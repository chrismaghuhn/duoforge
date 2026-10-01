"""DuoForge from Python: a ctypes binding over the shared library (M7).

Python allocates, calls and views; every rule stays in the C engine.
"""
from ._lib import load_library, version
from .context import Context, reference_setups
from .errors import DuoforgeError, DuoforgeLibraryError

__all__ = [
    "Context",
    "DuoforgeError",
    "DuoforgeLibraryError",
    "load_library",
    "reference_setups",
    "version",
]
