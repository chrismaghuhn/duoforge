"""The data API over ctypes: names, legality, support and the static features of the rows (decisions 0015 and 0020).

Plain wrappers. Every function calls the C function of the same name (duoforge_data_*) with a Context and copies the
struct it fills into a dict of Python ints (an array field becomes a tuple); an error status raises DuoforgeError with
the C status name, as everywhere in the package. Nothing is computed, derived or normalised here: the numbers are the
generated tables' (decision 0020), and what a row means is the C header's. A learner calls each function once per id at
start-up and builds its own arrays.

The table arguments are the DUOFORGE_DATA_TABLE_* values (TABLE_SPECIES ... TABLE_NATURE, below, from _layout.CONSTANTS).
"""
import ctypes

import numpy as np

from . import _layout
from ._lib import check, load_library, ptr, uint

TABLE_SPECIES = _layout.CONSTANTS["DUOFORGE_DATA_TABLE_SPECIES"]
TABLE_MOVE = _layout.CONSTANTS["DUOFORGE_DATA_TABLE_MOVE"]
TABLE_ITEM = _layout.CONSTANTS["DUOFORGE_DATA_TABLE_ITEM"]
TABLE_ABILITY = _layout.CONSTANTS["DUOFORGE_DATA_TABLE_ABILITY"]
TABLE_NATURE = _layout.CONSTANTS["DUOFORGE_DATA_TABLE_NATURE"]
NONE = _layout.CONSTANTS["DUOFORGE_DATA_NONE"]
MAX_FORME_MOVES = _layout.CONSTANTS["DUOFORGE_DATA_MAX_FORME_MOVES"]


def _handle(ctx):
    """The C handle of a Context; ValueError for a closed one."""
    if ctx.handle is None:
        raise ValueError("the context is closed")
    return ctx.handle


def _as_dict(record):
    """A filled zero-dimensional structured array as {field: int or tuple of ints}."""
    out = {}
    for name in record.dtype.names:
        value = record[name]
        out[name] = tuple(int(x) for x in value) if value.ndim else int(value)
    return out


def _read(call, ctx, ident, dtype, name):
    """One struct read: call(handle, id, pointer) -> status."""
    record = np.zeros((), dtype=dtype)
    check(call(_handle(ctx), uint(ident, 32, name), ptr(record)))
    return _as_dict(record)


def count(ctx, table):
    """duoforge_data_count: the number of ids of a table under the context's kind."""
    out = ctypes.c_uint32()
    check(load_library().duoforge_data_count(_handle(ctx), uint(table, 32, "table"), ctypes.byref(out)))
    return out.value


def name(ctx, table, ident):
    """duoforge_data_name: the Showdown id of a row (for example "closecombat")."""
    out = ctypes.c_char_p()
    check(load_library().duoforge_data_name(_handle(ctx), uint(table, 32, "table"), uint(ident, 32, "id"),
                                            ctypes.byref(out)))
    return out.value.decode("ascii")


def find(ctx, table, row_name):
    """duoforge_data_find: the id of a name as duoforge_data_name writes it (exact, nothing normalised)."""
    data = row_name.encode("ascii")
    out = ctypes.c_uint32()
    check(load_library().duoforge_data_find(_handle(ctx), uint(table, 32, "table"), data, len(data), ctypes.byref(out)))
    return out.value


def supported(ctx, table, ident):
    """duoforge_data_supported: whether a battle that uses the row passes the support gate."""
    out = ctypes.c_bool()
    check(load_library().duoforge_data_supported(_handle(ctx), uint(table, 32, "table"), uint(ident, 32, "id"),
                                                 ctypes.byref(out)))
    return bool(out.value)


def forme_info(ctx, species_id):
    """duoforge_data_forme_info as a dict (abilities is the full 3-entry array; ability_count says how many are set)."""
    return _read(load_library().duoforge_data_forme_info, ctx, species_id, _layout.FORME_INFO, "species_id")


def forme_moves(ctx, species_id):
    """duoforge_data_forme_moves: the legal move ids of a species, ascending, as a list."""
    buffer = (ctypes.c_uint32 * MAX_FORME_MOVES)()
    out = ctypes.c_uint32()
    check(load_library().duoforge_data_forme_moves(_handle(ctx), uint(species_id, 32, "species_id"), buffer,
                                                   MAX_FORME_MOVES, ctypes.byref(out)))
    return list(buffer[:out.value])


def mega_count(ctx, species_id):
    """duoforge_data_mega_count: how many Mega Stones take the species to a Mega forme under the context's kind."""
    out = ctypes.c_uint32()
    check(load_library().duoforge_data_mega_count(_handle(ctx), uint(species_id, 32, "species_id"), ctypes.byref(out)))
    return out.value


def mega_at(ctx, species_id, index):
    """duoforge_data_mega_at as a dict: the index-th Mega Stone of the species, in ascending item id."""
    record = np.zeros((), dtype=_layout.MEGA_INFO)
    check(load_library().duoforge_data_mega_at(_handle(ctx), uint(species_id, 32, "species_id"),
                                               uint(index, 32, "index"), ptr(record)))
    return _as_dict(record)


def forme_static(ctx, species_id):
    """duoforge_data_forme_static as a dict: types, base_stats, weight_hg, default_ability, is_mega."""
    return _read(load_library().duoforge_data_forme_static, ctx, species_id, _layout.FORME_STATIC, "species_id")


def move_static(ctx, move_id):
    """duoforge_data_move_static as a dict (priority is signed)."""
    return _read(load_library().duoforge_data_move_static, ctx, move_id, _layout.MOVE_STATIC, "move_id")


def item_static(ctx, item_id):
    """duoforge_data_item_static as a dict."""
    return _read(load_library().duoforge_data_item_static, ctx, item_id, _layout.ITEM_STATIC, "item_id")


def ability_static(ctx, ability_id):
    """duoforge_data_ability_static as a dict."""
    return _read(load_library().duoforge_data_ability_static, ctx, ability_id, _layout.ABILITY_STATIC, "ability_id")


def nature_static(ctx, nature_id):
    """duoforge_data_nature_static as a dict: raised_stat and lowered_stat (NONE for both of a neutral nature)."""
    return _read(load_library().duoforge_data_nature_static, ctx, nature_id, _layout.NATURE_STATIC, "nature_id")


def type_effect(ctx, attack_type, defend_type):
    """duoforge_data_type_effect: the multiplier of an attack type on a defending type as (numerator, denominator)."""
    num = ctypes.c_uint32()
    den = ctypes.c_uint32()
    check(load_library().duoforge_data_type_effect(_handle(ctx), uint(attack_type, 32, "attack_type"),
                                                   uint(defend_type, 32, "defend_type"), ctypes.byref(num),
                                                   ctypes.byref(den)))
    return num.value, den.value
