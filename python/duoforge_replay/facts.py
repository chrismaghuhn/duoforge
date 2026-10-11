"""What a log without open team sheets reveals of each member of a side (M11 Bo1 spec section 3).

The facts are fixed, never resampled: the preview species and gender, every move the member used, the item it held
before anything could change it, and the ability it had before anything could change it. A rule that cannot tell
says nothing: from the first line that can move an item (Trick, Switcheroo, Thief, Covet, Bestow, Pickup, Magician,
Pickpocket, Symbiosis) no further item is taken for the members it names, and from the first line that can change
an ability (Skill Swap, Entrainment, Worry Seed, Simple Beam, Doodle, Role Play, Mummy, Lingering Aroma, Wandering
Spirit, Power of Alchemy, Receiver, a forme change) no further ability. A game the facts cannot describe is a Skip
with its own reason.
"""
from dataclasses import dataclass

from duoforge_live.data import trace_to_c

from .points import Skip

ROSTER = 6
MOVES = 4
_ITEM_KEEPERS = ("[from] ability: Frisk", "[from] ability: Harvest", "[from] move: Recycle")
_ITEM_MOVERS = ("move: Trick", "move: Switcheroo")
_ABILITY_MOVES = ("Skill Swap", "Entrainment", "Worry Seed", "Simple Beam", "Doodle", "Role Play")
_ABILITY_TAKERS = ("Mummy", "Lingering Aroma", "Wandering Spirit", "Power of Alchemy", "Receiver")


@dataclass(frozen=True)
class MemberFacts:
    species: str  # as the preview (or, for a wildcard, the switch) names it
    gender: str  # "M", "F" or "" (none)
    moves: frozenset  # the own moves it used, as the log spells them
    item: object  # str or None
    ability: object  # str or None


def _details(text):
    fields = [f.strip() for f in text.split(",")]
    gender = next((f for f in fields[1:] if f in ("M", "F")), "")
    return fields[0], gender


def _froms(attrs):
    return [a for a in attrs if a.startswith("[from]")]


def _own_move(attrs):
    froms = [f.replace(" ", "") for f in _froms(attrs)]
    return all(f == "[from]lockedmove" or f == "[from]move:Instruct" for f in froms)


def side_facts(lines, side, data):
    """The MemberFacts of side's six members in |poke| preview order (module docstring)."""
    p = f"p{side + 1}"
    if any(line.startswith("|-transform|") for line in lines):
        raise Skip("skip:belief-transform")
    preview = [line.split("|")[3] for line in lines if line.startswith(f"|poke|{p}|") and len(line.split("|")) > 3]
    if len(preview) != ROSTER:
        raise Skip("skip:belief-preview")
    switched = [line.split("|")[3].split(",")[0].strip() for line in lines
                if line.split("|")[1:2] in (["switch"], ["drag"], ["replace"]) and line.split("|")[2].startswith(p)
                and len(line.split("|")) > 3]
    names, genders = [], []
    for text in preview:
        name, gender = _details(text)
        if name.endswith("-*"):
            found = sorted({s for s in switched if s == name[:-2] or s.startswith(name[:-1])})
            if len(found) != 1:
                raise Skip("skip:belief-preview")
            name = found[0]
        if trace_to_c.key(name).startswith("ZOROARK"):
            raise Skip("skip:illusion")
        names.append(name)
        genders.append(gender)

    def base(name):
        try:
            return data.base_forme(data.forme(name))
        except ValueError:
            raise Skip(f"name:FORME {name}") from None

    bases = [base(n) for n in names]

    def member_of(species):
        b = base(species)
        if bases.count(b) != 1:
            raise Skip("skip:belief-preview")
        return bases.index(b)

    occupant, by_name = {}, {}
    moves = [set() for _ in range(ROSTER)]
    item, ability = [None] * ROSTER, [None] * ROSTER
    moves_done, item_done, ability_done = set(), set(), set()

    def who(ident):
        """The member an identifier of this side names ("p1a: Nick" by position, "p1: Nick" by name), or None."""
        ident = ident.strip()
        if not ident.startswith(p):
            return None
        if len(ident) > 2 and ident[2] in "ab":
            return occupant.get(ident[:3])
        return by_name.get(ident.split(": ", 1)[1] if ": " in ident else None)

    def note_item(m, value):
        if m is not None and m not in item_done:
            item[m] = value
            item_done.add(m)  # the first evidence is the original item

    def note_ability(m, value):
        if m is not None and m not in ability_done:
            ability[m] = value
            ability_done.add(m)

    for line in lines:
        parts = line.split("|")
        if len(parts) < 3:
            continue
        kind, subject = parts[1], parts[2]
        attrs = parts[3:]
        of = next((who(a[len("[of] "):]) for a in attrs if a.startswith("[of] ")), None)
        if kind in ("switch", "drag", "replace") and len(parts) > 3:
            if subject.startswith(p):
                m = member_of(parts[3].split(",")[0].strip())
                occupant[subject[:3]] = m
                by_name[subject.split(": ", 1)[1]] = m
            continue
        if kind == "swap" and len(parts) > 3 and subject.startswith(p) and parts[3] in ("0", "1"):
            here, there = subject[:3], p + "ab"[int(parts[3])]  # Ally Switch: the two positions trade occupants
            occupant[here], occupant[there] = occupant.get(there), occupant.get(here)
            continue
        m = who(subject)
        if kind in ("detailschange", "-formechange"):
            ability_done.add(m)
            continue
        if kind == "-mega" and len(parts) > 4:
            note_item(m, parts[4])
            continue
        if kind == "move" and len(parts) > 3:
            if m is not None and parts[3] != "Struggle" and m not in moves_done and _own_move(parts[4:]):
                moves[m].add(parts[3])
            continue
        if kind == "-start" and len(parts) > 3 and parts[3] in ("Mimic", "move: Mimic"):
            moves_done.add(m)
            continue
        if any(text in line for text in _ABILITY_MOVES):
            ability_done.update({m, of})
        if kind == "-activate" and len(parts) > 3 and parts[3] in _ITEM_MOVERS:
            item_done.update({m, of})
            continue
        if kind == "-item" and len(parts) > 3:
            froms = _froms(attrs)
            if not froms:
                note_item(m, parts[3])
            elif froms[0] == "[from] ability: Frisk":
                note_item(m, parts[3])
                note_ability(of, "Frisk")
            elif froms[0] in _ITEM_KEEPERS:
                note_item(m, parts[3])
            else:
                item_done.update({m, of})
            continue
        if kind == "-enditem" and len(parts) > 3:
            note_item(m, parts[3])
            if "[from] stealeat" in attrs:
                item_done.add(of)  # Bug Bite, Pluck: the biter's heal names the eaten berry, not its own item
            continue
        if kind == "-ability" and len(parts) > 3:
            froms = _froms(attrs)
            if not froms:
                note_ability(m, parts[3])
            elif froms[0] == "[from] ability: Trace":
                note_ability(m, "Trace")
                note_ability(of, parts[3])
            else:
                ability_done.update({m, of})
            continue
        if kind == "-activate" and len(parts) > 3 and parts[3].startswith("ability: "):
            name = parts[3][len("ability: "):]
            note_ability(m, name)
            if name in _ABILITY_TAKERS:
                ability_done.add(of)
            continue
        has_of = any(a.startswith("[of] ") for a in attrs)
        holder = of if has_of else m  # the effect's holder: [of] when it is named
        for a in attrs:
            if a.startswith("[from] item: "):
                note_item(holder, a[len("[from] item: "):])
            elif a.startswith("[from] ability: ") and not (kind == "-heal" and has_of):
                # a heal by an ability names the attacker as [of] (Volt Absorb) or the holder (Hospitality): unsaid
                note_ability(holder, a[len("[from] ability: "):])
    ability_done.discard(None)
    for m in range(ROSTER):
        if len(moves[m]) > MOVES:
            raise Skip("skip:belief-moves")
    return tuple(MemberFacts(names[m], genders[m], frozenset(moves[m]), item[m], ability[m]) for m in range(ROSTER))
