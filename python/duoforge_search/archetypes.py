"""Archetype tags of a team sheet (issue #458): the data table data/book/archetype-tags.json read against the engine.

    python -m duoforge_search.archetypes --check
    python -m duoforge_search.archetypes --team FILE [--team FILE ...]

A tag (weather, speed control, setup, support) is a feature of a team-preview prior, not a battle rule: nothing here
decides a battle. The table names the abilities, moves and items of each tag by the engine's ids. A weather tag's
"setter" names a weather, and its abilities are the engine's own weather setters of that weather (ability family
WEATHER_SETTER); a Mega Stone gives the tags of its Mega forme's ability (the engine's item and forme data), besides
the tags of the member's own ability. So no mechanic is restated here. An id the engine does not know or does not
support stops the check by name; a team member's name the engine does not know is refused by name, never skipped.
"""
import argparse
import json
import sys
from pathlib import Path

TABLE_PATH = Path(__file__).resolve().parents[2] / "data/book/archetype-tags.json"
FORMAT = 1
KINDS = ("abilities", "moves", "items")
SETTERS = ("rain", "sun", "sand", "snow")
FAMILIES = ("weather", "speed", "setup", "support")


class TagError(ValueError):
    """A table or a team the tags cannot be read for, with the offending name."""


def load(path=TABLE_PATH):
    """The table as a dict, its shape checked: format 1, tags named FAMILY or FAMILY:NAME of a known family, each with
    sorted, distinct id lists of the known kinds (at least one entry or a setter), and a setter only on a weather tag."""
    with open(path, encoding="utf-8") as f:
        table = json.load(f)
    if table.get("format") != FORMAT:
        raise TagError(f"{Path(path).name}: format {table.get('format')!r}, expected {FORMAT}")
    if not table.get("credits"):
        raise TagError(f"{Path(path).name}: no credits")
    tags = table.get("tags")
    if not isinstance(tags, dict) or not tags:
        raise TagError(f"{Path(path).name}: no tags")
    if list(tags) != sorted(tags):
        raise TagError(f"{Path(path).name}: the tags are not sorted")
    for tag, entry in tags.items():
        family = tag.split(":", 1)[0]
        if family not in FAMILIES:
            raise TagError(f"tag {tag!r}: unknown family {family!r} (one of {FAMILIES})")
        unknown = set(entry) - set(KINDS) - {"setter"}
        if unknown:
            raise TagError(f"tag {tag!r}: unknown fields {sorted(unknown)}")
        if "setter" in entry and (family != "weather" or entry["setter"] not in SETTERS):
            raise TagError(f"tag {tag!r}: a setter is one of {SETTERS} on a weather tag (got {entry['setter']!r})")
        for kind in KINDS:
            ids = entry.get(kind, [])
            if not isinstance(ids, list) or ids != sorted(set(ids)) or kind in entry and not ids:
                raise TagError(f"tag {tag!r}: its {kind} must be a sorted list of distinct ids")
        if "setter" not in entry and not any(entry.get(kind) for kind in KINDS):
            raise TagError(f"tag {tag!r} names nothing")
    return table


def resolve(ctx, table):
    """{kind: {engine id: [tags]}} for abilities, moves and items, the setters' abilities included. TagError naming
    every listed id the engine does not know or does not support under this context."""
    import duoforge
    from duoforge import _layout, data
    C = _layout.CONSTANTS
    tables = {"abilities": data.TABLE_ABILITY, "moves": data.TABLE_MOVE, "items": data.TABLE_ITEM}
    out = {kind: {} for kind in KINDS}
    bad = []
    for tag, entry in table["tags"].items():
        for kind in KINDS:
            for name in entry.get(kind, []):
                try:
                    ident = data.find(ctx, tables[kind], name)
                except duoforge.DuoforgeError as err:
                    if err.status_name != "DUOFORGE_E_INVALID_ARGUMENT":
                        raise
                    bad.append(f"{tag}: {kind[:-1] if kind != 'abilities' else 'ability'} {name!r} is unknown")
                    continue
                if not data.supported(ctx, tables[kind], ident):
                    bad.append(f"{tag}: {name!r} is not supported by the engine")
                    continue
                out[kind].setdefault(ident, []).append(tag)
        if "setter" in entry:
            weather = C[f"DUOFORGE_WEATHER_{entry['setter'].upper()}"]
            setters = [a for a in range(data.count(ctx, data.TABLE_ABILITY))
                       if data.supported(ctx, data.TABLE_ABILITY, a)
                       and data.ability_static(ctx, a)["family"] == C["DUOFORGE_ABILITY_FAMILY_WEATHER_SETTER"]
                       and data.ability_static(ctx, a)["family_param"] == weather]
            if not setters:
                bad.append(f"{tag}: the engine has no supported setter of {entry['setter']}")
            for a in setters:
                out["abilities"].setdefault(a, []).append(tag)
    if bad:
        raise TagError("the tag table names ids the engine refuses: " + "; ".join(bad))
    return {kind: {k: sorted(set(v)) for k, v in table_.items()} for kind, table_ in out.items()}


def member_tags(ctx, resolved, member):
    """The sorted tags of one member (teams.parse's shape: ability, item, moves): its ability's, its moves', its item's
    and, for a Mega Stone, its Mega forme's ability's. TagError naming a name the engine does not know."""
    import duoforge
    from duoforge import data

    def find(table, name, what):
        try:
            return data.find(ctx, table, data.to_id(name))
        except duoforge.DuoforgeError as err:
            if err.status_name != "DUOFORGE_E_INVALID_ARGUMENT":
                raise
            raise TagError(f"{member.get('species')}: the engine has no {what} {name!r}") from None

    tags = set()
    tags.update(resolved["abilities"].get(find(data.TABLE_ABILITY, member["ability"], "ability"), []))
    for move in member["moves"]:
        tags.update(resolved["moves"].get(find(data.TABLE_MOVE, move, "move"), []))
    if member.get("item"):
        item = find(data.TABLE_ITEM, member["item"], "item")
        tags.update(resolved["items"].get(item, []))
        info = data.item_static(ctx, item)
        if info["is_mega_stone"]:
            mega_ability = data.forme_static(ctx, info["mega_species"])["default_ability"]
            tags.update(resolved["abilities"].get(mega_ability, []))
    return sorted(tags)


def team_tags(ctx, resolved, members):
    """{"members": [tags of each member], "team": the sorted union}. A team without any tag has an empty union: the
    caller reports it as untagged by name, nothing is guessed."""
    per = [member_tags(ctx, resolved, m) for m in members]
    return {"members": per, "team": sorted(set().union(*per))}


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.archetypes", description=__doc__.split("\n")[0])
    p.add_argument("--check", action="store_true", help="check the table against the engine")
    p.add_argument("--team", action="append", default=[], help="a team file (a registry paste or a packed team)")
    p.add_argument("--table", default=str(TABLE_PATH))
    args = p.parse_args(sys.argv[1:] if argv is None else list(argv))
    if not args.check and not args.team:
        raise SystemExit("give --check or --team FILE")
    import duoforge
    from duoforge import _layout
    from . import ladder
    try:
        table = load(args.table)
    except TagError as err:
        raise SystemExit(str(err)) from None
    with duoforge.Context(_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx:
        try:
            resolved = resolve(ctx, table)
            if args.check:
                print(json.dumps({"tags": len(table["tags"]), **{k: len(v) for k, v in resolved.items()}}))
            for path in args.team:
                members, _, _ = ladder.read_team(path)
                out = team_tags(ctx, resolved, members)
                print(json.dumps({"team": Path(path).name, "tags": out["team"],
                                  "members": {m["species"]: t for m, t in zip(members, out["members"])}}, indent=1))
        except TagError as err:
            raise SystemExit(str(err)) from None
    return 0


if __name__ == "__main__":
    sys.exit(main())
