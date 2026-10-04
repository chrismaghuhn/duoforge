"""Public records and hypotheses; all reconstruction rules stay in C."""
import numpy as np

from . import _layout
from ._lib import load_library, ptr, status_name
from .batch import _require
from .errors import DuoforgeError

PUBLIC_STATE = _layout.PUBLIC_STATE
HYPOTHESIS = _layout.HYPOTHESIS


def hypotheses(count):
    """Empty hypothesis records with the correct revision and absent picks."""
    out = np.zeros(count, HYPOTHESIS)
    out["revision"] = _layout.CONSTANTS["DUOFORGE_HYPOTHESIS_REVISION"]
    out["pick_order"] = _layout.CONSTANTS["DUOFORGE_VIEW_PICK_NONE"]
    return out


def queue_mask(ctx, turn_start, view):
    """The foe's turn-start pair mask (32,32), or an explicit engine refusal."""
    if ctx.handle is None:
        raise ValueError("the context is closed")
    _require(turn_start, PUBLIC_STATE, (), "turn_start")
    _require(view, PUBLIC_STATE, (), "view")
    out = np.zeros((_layout.MAX_SLOT_OPTIONS, _layout.MAX_SLOT_OPTIONS), np.uint8)
    st = load_library().duoforge_public_queue_mask(ctx.handle, ptr(turn_start), ptr(view), ptr(out))
    if st:
        raise DuoforgeError(status_name(st))
    return out
