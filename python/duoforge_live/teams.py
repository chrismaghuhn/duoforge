"""Team A and B for the live adapter: Showdown's packed format and the match
of a revealed sheet.

pack(text) is the pinned Showdown's Teams.pack(Teams.import(text)) for the
pastes of tests/reference/teams (checked through tools/reference/ps_client.js
--pack); unpack reads a packed team, such as the payload of |showteam|.
match(sets, text) accepts the same six sets in any order, each with the same
species, item, ability, moves (in any order), nature, gender and level: what
open team sheets show.
"""
import re

from . import data

FILES = {"A": "team_a.txt", "B": "team_b.txt"}
STATS = ("HP", "Atk", "Def", "SpA", "SpD", "Spe")


def text(name):
    """The paste of Team A or B."""
    if name not in FILES:
        raise ValueError(f"no team {name!r}: A or B")
    return (data.ROOT / "tests" / "reference" / "teams" / FILES[name]).read_text(encoding="utf-8")


def _pack_name(name):
    return re.sub(r"[^A-Za-z0-9]+", "", name or "")


def _paste(paste):
    """The sets of a paste in the converter's dialect (trace_to_c.parse_team)."""
    sets = []
    for block in paste.strip().split("\n\n"):
        lines = [line.strip() for line in block.strip().split("\n")]
        head, item = lines[0], ""
        if " @ " in head:
            head, item = head.split(" @ ")
        m = re.match(r"^(.+?)(?: \(([MF])\))?$", head)
        if "(" in m.group(1):
            raise ValueError(f"a nickname or forme in parentheses is not supported: {head!r}")
        s = {"name": m.group(1), "species": m.group(1), "item": item, "ability": "", "moves": [], "nature": "",
             "evs": [0] * 6, "gender": m.group(2) or "", "level": 100}
        for line in lines[1:]:
            if line.startswith("Ability: "):
                s["ability"] = line[len("Ability: "):]
            elif line.startswith("Level: "):
                s["level"] = int(line[len("Level: "):])
            elif line.startswith("EVs: "):
                for part in line[len("EVs: "):].split(" / "):
                    value, stat = part.split(" ")
                    s["evs"][STATS.index(stat)] = int(value)
            elif line.endswith(" Nature"):
                s["nature"] = line[:-len(" Nature")]
            elif line.startswith("- "):
                s["moves"].append(line[2:])
            else:
                raise ValueError(f"unknown paste line {line!r}")
        sets.append(s)
    return sets


def pack(paste):
    """Showdown's packed team (sim/teams.ts Teams.pack) of a paste."""
    out = []
    for s in _paste(paste):
        evs = ",".join(str(v) if v else "" for v in s["evs"])
        out.append("|".join([
            s["name"], "" if _pack_name(s["species"]) == _pack_name(s["name"]) else _pack_name(s["species"]),
            _pack_name(s["item"]), _pack_name(s["ability"]), ",".join(_pack_name(m) for m in s["moves"]),
            s["nature"], "" if evs == ",,,,," else evs, s["gender"], "", "",
            "" if s["level"] == 100 else str(s["level"]), ""]))
    return "]".join(out)


def unpack(packed):
    """The sets of a packed team: name, species, item, ability, moves, nature, evs (6), gender, level."""
    sets = []
    for chunk in packed.split("]"):
        f = chunk.split("|")
        if len(f) != 12:
            raise ValueError(f"not a packed set: {chunk!r}")
        evs = [int(v) if v else 0 for v in f[6].split(",")] if f[6] else [0] * 6
        if len(evs) != 6:
            raise ValueError(f"not six EVs: {chunk!r}")
        sets.append({"name": f[0], "species": f[1] or f[0], "item": f[2], "ability": f[3],
                     "moves": f[4].split(",") if f[4] else [], "nature": f[5], "evs": evs, "gender": f[7],
                     "level": int(f[10]) if f[10] else 100})
    return sets


def to_text(sets):
    """A paste of sets that trace_to_c.parse_team reads (ids normalise through its key())."""
    blocks = []
    for s in sets:
        head = s["species"] + (f" ({s['gender']})" if s["gender"] else "") + (f" @ {s['item']}" if s["item"] else "")
        ability = "No Ability" if _pack_name(s["ability"]).lower() == "noability" else s["ability"]  # parse_team's spelling
        lines = [head, f"Ability: {ability}", f"Level: {s['level']}"]
        if any(s["evs"]):
            lines.append("EVs: " + " / ".join(f"{v} {STATS[i]}" for i, v in enumerate(s["evs"]) if v))
        lines.append(f"{s['nature']} Nature")
        lines += [f"- {m}" for m in s["moves"]]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _sheet(s):
    """What an open team sheet shows of a set, comparable across spellings."""
    k = _pack_name
    return (k(s["species"]).lower(), k(s["item"]).lower(), k(s["ability"]).lower(),
            tuple(sorted(k(m).lower() for m in s["moves"])), k(s["nature"]).lower(), s["gender"], s["level"])


def match(sets, paste):
    """Whether `sets` are the team of `paste`: the same six sheets, in any order."""
    return sorted(_sheet(s) for s in sets) == sorted(_sheet(s) for s in _paste(paste))
