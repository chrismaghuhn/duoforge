"""The data query API of the library (duoforge_data_*): the names and ids of
a context's tables (species, move, item, ability, nature), bound to its data
kind. Names are Showdown ids (to_id: lower-case letters and digits); the
library normalizes nothing, so to_id does it here. Every rule stays in C.
"""
import ctypes
import re

from . import _layout
from ._lib import check, load_library, uint

TABLES = {t: _layout.CONSTANTS[f"DUOFORGE_DATA_TABLE_{t.upper()}"]
          for t in ("species", "move", "item", "ability", "nature")}


def to_id(name):
    """Showdown's toID: lower-case letters and digits ("Indeedee-F" -> "indeedeef")."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _table(table):
    if table not in TABLES:
        raise ValueError(f"unknown table {table!r}: one of {sorted(TABLES)}")
    return TABLES[table]


def _handle(context):
    if context.handle is None:
        raise ValueError("the context is closed")
    return context.handle


def count(context, table):
    """The number of ids of a table under the context's data kind."""
    out = ctypes.c_uint32()
    check(load_library().duoforge_data_count(_handle(context), _table(table), ctypes.byref(out)))
    return out.value


def name(context, table, id_):
    """The Showdown id of an id."""
    out = ctypes.c_char_p()
    check(load_library().duoforge_data_name(_handle(context), _table(table), uint(id_, 32, "id"), ctypes.byref(out)))
    return out.value.decode("ascii")


def find(context, table, showdown_id):
    """The id of a Showdown id; DuoforgeError (E_INVALID_ARGUMENT) when the
    context's data kind has no such name."""
    raw = showdown_id.encode("ascii")
    out = ctypes.c_uint32()
    check(load_library().duoforge_data_find(_handle(context), _table(table), raw, len(raw), ctypes.byref(out)))
    return out.value
