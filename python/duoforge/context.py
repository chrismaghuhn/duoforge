"""A DuoForge context and the reference setups."""
import ctypes
import weakref

import numpy as np

from . import _layout
from ._lib import check, load_library, ptr


class Context:
    """A context of the library (duoforge_context_create).

    The defaults are the certified profile: CLOSURE data, a roster of six,
    four brought. close() releases it; a closed context has handle None.
    Its batches must be closed first: they point into it.
    """

    def __init__(self, data_kind=_layout.DATA_KIND_CLOSURE, max_roster=6, brought_count=4):
        self.handle = None  # set only after a successful create, so __del__ is safe
        self._batches = weakref.WeakSet()
        self._lib = load_library()
        config = np.zeros((), dtype=_layout.CONTEXT_CONFIG)
        config["data_kind"] = data_kind
        config["max_roster"] = max_roster
        config["brought_count"] = brought_count
        handle = ctypes.c_void_p()
        check(self._lib.duoforge_context_create(ptr(config), ctypes.byref(handle)))
        self.handle = handle

    def close(self):
        """Destroys the context; a second close is a no-op. RuntimeError while
        one of its batches is open."""
        if self.handle is not None:
            if len(self._batches) != 0:
                raise RuntimeError("close the context's batches first")
            self._lib.duoforge_context_destroy(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        if self.handle is not None and len(self._batches) == 0:
            self.close()


def reference_setups(pairings):
    """The setups of the reference pairings (duoforge_reference_setup):
    0 A-B, 1 B-A, 2 A-A, 3 B-B (decisions 0004 and 0010)."""
    lib = load_library()
    setups = np.zeros(len(pairings), dtype=_layout.SETUP)
    for i, pairing in enumerate(pairings):
        check(lib.duoforge_reference_setup(int(pairing), ptr(setups[i:i + 1])))
    return setups
