"""The DuoForge shared library over ctypes (M7, decision 0013).

The path comes from DUOFORGE_LIBRARY; without it the package looks next to
itself, then in build/*/ and build/*/Release of the repository. An explicit
DUOFORGE_LIBRARY is the only candidate: a wrong path fails and never falls
back to another build. Among the build directories exactly one library may
report EXPECTED_VERSION; two raise, naming both, so a stale build of the
same version cannot load unnoticed (set DUOFORGE_LIBRARY to choose).
library_path() names the loaded file. ctypes.CDLL releases the GIL for every
foreign call. Struct pointers travel as c_void_p into NumPy buffers
(_layout.py).
"""
import ctypes
import functools
import glob
import operator
import os

from .errors import DuoforgeError, DuoforgeLibraryError

EXPECTED_VERSION = "0.22.0"

_NAMES = ("duoforge_shared.dll", "libduoforge_shared.dll", "libduoforge_shared.so", "libduoforge_shared.dylib")

_P = ctypes.c_void_p
_U32 = ctypes.c_uint32
_U64 = ctypes.c_uint64
_STATUS = ctypes.c_uint32

# restype, argtypes of every function the package calls.
_SIGNATURES = {
    "duoforge_version_string": (ctypes.c_char_p, ()),
    "duoforge_status_name": (ctypes.c_char_p, (_STATUS,)),
    "duoforge_context_create": (_STATUS, (_P, ctypes.POINTER(_P))),
    "duoforge_context_destroy": (None, (_P,)),
    "duoforge_context_fingerprint": (_STATUS, (_P, _P)),
    "duoforge_reference_setup": (_STATUS, (_U32, _P)),
    "duoforge_battle_create": (_STATUS, (_P, _P, ctypes.POINTER(_P))),
    "duoforge_battle_destroy": (None, (_P,)),
    "duoforge_data_count": (_STATUS, (_P, _U32, ctypes.POINTER(_U32))),
    "duoforge_data_name": (_STATUS, (_P, _U32, _U32, ctypes.POINTER(ctypes.c_char_p))),
    "duoforge_data_find": (_STATUS, (_P, _U32, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(_U32))),
    "duoforge_battle_result": (_STATUS, (_P, _P, ctypes.POINTER(_U32))),
    "duoforge_battle_tiebreak": (_STATUS, (_P, _P, ctypes.POINTER(_U32))),
    "duoforge_battle_digest": (_STATUS, (_P, _P, _P)),
    "duoforge_batch_seeds": (None, (_U64, _U32, _U32, ctypes.POINTER(_U64), ctypes.POINTER(_U64),
                                    ctypes.POINTER(_U64))),
    "duoforge_batch_create": (_STATUS, (_P, _P, ctypes.POINTER(_P))),
    "duoforge_batch_destroy": (None, (_P,)),
    "duoforge_batch_env": (_P, (_P, _U32)),
    "duoforge_batch_env_episode": (_U32, (_P, _U32)),
    "duoforge_batch_query": (_STATUS, (_P, _P, _P, _P, _P)),
    "duoforge_batch_query_factored": (_STATUS, (_P, _P, _P, _P)),
    "duoforge_batch_step_indices": (_STATUS, (_P, _P, _P, _P, _P, _P, _P)),
    "duoforge_batch_step_factored": (_STATUS, (_P, _P, _P, _P, _P, _P)),
    "duoforge_batch_step_query": (_STATUS, (_P, _U32, _P, _P, _P, _P, _P, _P, _P, _P)),
    "duoforge_batch_reset": (_STATUS, (_P, _U32, _U32)),
    "duoforge_batch_reset_terminal": (_STATUS, (_P,)),
    "duoforge_batch_reset_setups": (_STATUS, (_P, _U32, _P, _P, _P, _P)),
    "duoforge_batch_play_random": (_STATUS, (_P, _U32, _U32, _P)),
}


def _candidates():
    """Candidate groups in order: DUOFORGE_LIBRARY alone, or the package
    directory, then the build directories."""
    explicit = os.environ.get("DUOFORGE_LIBRARY")
    if explicit:
        return ((explicit,),)
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    builds = []
    for pattern in ("build/*", "build/*/Release"):
        builds.extend(sorted(d for d in glob.glob(os.path.join(root, pattern)) if os.path.isdir(d)))
    return (tuple(os.path.join(here, n) for n in _NAMES), tuple(os.path.join(d, n) for d in builds for n in _NAMES))


def _open(path, expected, tried):
    """The library at path if it loads and reports the expected version."""
    if not os.path.isfile(path):
        tried.append(f"{path}: not found")
        return None
    try:
        lib = ctypes.CDLL(os.path.abspath(path))
    except OSError as err:
        tried.append(f"{path}: {err}")
        return None
    lib.duoforge_version_string.restype = ctypes.c_char_p
    lib.duoforge_version_string.argtypes = ()
    found = lib.duoforge_version_string().decode("ascii")
    if found != expected:
        tried.append(f"{path}: version {found}")
        return None
    return lib


@functools.lru_cache(maxsize=None)
def _load(groups, expected):
    """The library of the first group with a match; a group with two
    matches raises instead of choosing one silently."""
    tried = []
    for group in groups:
        matches = [(path, lib) for path in group for lib in [_open(path, expected, tried)] if lib is not None]
        if len(matches) > 1:
            raise DuoforgeLibraryError(f"more than one DuoForge library {expected}: "
                                       + ", ".join(p for p, _ in matches) + "; set DUOFORGE_LIBRARY to choose one")
        if matches:
            path, lib = matches[0]
            for name, (restype, argtypes) in _SIGNATURES.items():
                fn = getattr(lib, name)
                fn.restype = restype
                fn.argtypes = argtypes
            lib._duoforge_path = os.path.abspath(path)
            return lib
    shown = tried if len(tried) <= 8 else tried[:8] + [f"... {len(tried) - 8} more"]
    raise DuoforgeLibraryError(f"no DuoForge library {expected} found; tried: " + "; ".join(shown))


def load_library():
    """The loaded library (cached per search path and expected version)."""
    return _load(_candidates(), EXPECTED_VERSION)


def library_path():
    """The absolute path of the loaded library."""
    return load_library()._duoforge_path


def version():
    """The library's version string."""
    return load_library().duoforge_version_string().decode("ascii")


def status_name(status):
    """The C name of a status, for example "DUOFORGE_E_STALE_EPOCH"."""
    return load_library().duoforge_status_name(int(status)).decode("ascii")


def check(status):
    """Raises DuoforgeError unless status is DUOFORGE_OK."""
    if status != 0:
        raise DuoforgeError(status_name(status))


def uint(value, bits, name):
    """value as an unsigned integer of `bits` bits: TypeError for a
    non-integer (a float is not truncated), ValueError outside the range
    (ctypes would wrap it silently)."""
    value = operator.index(value)
    if not 0 <= value < 1 << bits:
        raise ValueError(f"{name} {value} is outside uint{bits}")
    return value


def ptr(array):
    """A c_void_p to the first byte of a C-contiguous NumPy array."""
    if not array.flags["C_CONTIGUOUS"]:
        raise ValueError("the array must be C-contiguous")
    return array.ctypes.data_as(ctypes.c_void_p)
