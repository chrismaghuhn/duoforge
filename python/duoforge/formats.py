"""The format a run plays, as metadata (restructure step 8, plan "Format axis": arena and coverage runs record the
format in their manifest).

A format is its definition file, data/formats/<id>.json (restructure step 10, docs/architecture/formats.md); this module
reads its id and Showdown format id and nothing else. No rule of the game lives here (AGENTS.md): what a format allows
is the engine's, generated from the same definitions.

A run names its format by the definition's Showdown format id (by_showdown_id: exactly, never by a prefix or a suffix
such as a "...bo3" replay format) or by the data kind it plays (of_data_kind). A format that cannot be told is refused
by name (FormatError), never guessed and never left out.

This module imports nothing but the standard library, so that a tool may load it as a file of its own (as
tools/coverage/champions_coverage.py does when --package names another commit's duoforge package).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMATS = ROOT / "data" / "formats"
HEADER = ROOT / "include" / "duoforge" / "duoforge.h"  # the data kinds' names and values (the generated layout lacks some)

# The format of each data kind (the DUOFORGE_DATA_KIND_* constants of include/duoforge/duoforge.h), by constant name.
# A TRANSITIONAL table (HauptSession, 2026-10-16): the engine and the definitions do not name the format of a data kind
# yet; the assignment moves into the format definitions or the engine with restructure step 5 and the Gen 9 design
# (Champions and SV as rule sets), and this table goes then. duoforge.python.formats checks it against the header,
# the generated layout and the definition files.
DATA_KIND_FORMATS = {
    "DUOFORGE_DATA_KIND_CLOSURE": "reg-mc",
    "DUOFORGE_DATA_KIND_CLOSURE_DEV": "reg-mc",
    "DUOFORGE_DATA_KIND_TEAM_C": "reg-mc",
    "DUOFORGE_DATA_KIND_TEAM_C_DEV": "reg-mc",
    "DUOFORGE_DATA_KIND_POOL": "reg-mc",
    "DUOFORGE_DATA_KIND_POOL_DEV": "reg-mc",
    "DUOFORGE_DATA_KIND_POOL_SINGLES_DEV": "champions-ou",  # [Gen 9 Champions] OU in singles (decision 0083)
}
# The data kinds that play no format: a run over them has none to record and is refused by name.
NO_FORMAT = {"DUOFORGE_DATA_KIND_SYNTHETIC": "synthetic ids and target classes, no combat"}


class FormatError(ValueError):
    """The format of a run cannot be told: an unknown definition, Showdown format id or data kind."""


def known():
    """The ids of the format definitions, sorted."""
    return sorted(p.stem for p in FORMATS.glob("*.json"))


def definition(format_id):
    """The definition data/formats/<format_id>.json, whose id must be its file name."""
    path = FORMATS / f"{format_id}.json"
    if not path.is_file():
        raise FormatError(f"no format definition {format_id!r} (known: {', '.join(known())})")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("id") != format_id:
        raise FormatError(f"{path.name} names the id {data.get('id')!r}, not its file name {format_id!r}")
    return data


def record(format_id):
    """The manifest's "format" field: {"id", "showdown_format_id"} of the definition."""
    data = definition(format_id)
    return {"id": data["id"], "showdown_format_id": data["showdown_format_id"]}


def by_showdown_id(showdown_format_id):
    """The format whose definition has exactly this Showdown format id."""
    found = [f for f in known() if definition(f).get("showdown_format_id") == showdown_format_id]
    if len(found) != 1:
        raise FormatError(f"{len(found) or 'no'} format definition(s) with the Showdown format id "
                          f"{showdown_format_id!r} (known: "
                          f"{', '.join(definition(f)['showdown_format_id'] for f in known())})")
    return record(found[0])


def data_kinds():
    """The DUOFORGE_DATA_KIND_* constants of the public header, by name."""
    text = HEADER.read_text(encoding="utf-8")
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"#define (DUOFORGE_DATA_KIND_\w+)\s+(\d+)u", text)}


def of_data_kind(kind, constants=None):
    """The format of a data kind (its DUOFORGE_DATA_KIND_* value); constants: the kinds by name, the public header's
    (data_kinds) unless given."""
    constants = data_kinds() if constants is None else constants
    names = [n for n, v in constants.items() if n.startswith("DUOFORGE_DATA_KIND_") and v == kind]
    if len(names) != 1:
        raise FormatError(f"data kind {kind!r} is no DUOFORGE_DATA_KIND_* constant")
    if names[0] in NO_FORMAT:
        raise FormatError(f"{names[0]} plays no format ({NO_FORMAT[names[0]]})")
    if names[0] not in DATA_KIND_FORMATS:
        raise FormatError(f"{names[0]} has no format in duoforge.formats.DATA_KIND_FORMATS")
    return record(DATA_KIND_FORMATS[names[0]])
