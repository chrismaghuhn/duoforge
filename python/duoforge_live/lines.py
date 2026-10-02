"""The class of every protocol line before the fold (M11 spec section 5).

The converter (trace_to_c.step_events) parses the lines of the mechanics
DuoForge implements, and raises on a line kind it does not know. Some lines
of a known kind still mean something the fold does not apply, and would be
folded wrongly in silence: an ability changed by Trace comes as an -ability
line, an item knocked off as an -enditem line. check() sorts every line
first:

- room: a line of the room, not of the battle (None);
- fold: a line the tracker folds ("fold");
- feature: an effect of decision 0018 section 6.1. It is folded only when the
  library supports its DUOFORGE_VIEWEXT_FEATURE_* bit; otherwise Stop
  ("feature:<NAME>"). The single-turn features of a PIVOT boundary (Rage
  Powder, Wide Guard, Quick Guard) return "turn:<NAME>": they change no
  TURN or REPLACEMENT observation, and the caller decides;
- unknown: everything else, Stop("line:<kind> <effect>").

The live adapter forfeits on a Stop (a ValueError) as on any line it cannot
follow; the replay pipeline ends the perspective there and counts the
reason. Names follow the pinned Showdown's protocol (sim/ at the pin).
"""
import re

from .data import ROOT, trace_to_c


def line_kind(line):
    """The kind of a protocol line ("move" for "|move|..."), or None for a text line of the room."""
    if not line.startswith("|") or line.startswith("||"):
        return None
    return line.split("|")[1]


def flat_position(ident):
    """The flat position (side * 2 + slot) of "p1a: Name", or None for a side ident or anything else."""
    if len(ident) < 4 or ident[0] != "p" or not ident[1].isdigit() or ident[2] not in "ab":
        return None
    return (int(ident[1]) - 1) * 2 + "ab".index(ident[2])


class Stop(ValueError):
    """A line the view cannot represent: the perspective ends here (reason: the counter's name)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


# Lines of the room, not of the battle: nobody folds them. "-message" is text too: a forfeit or a timer loss
# ("<name> forfeited.", server/room-battle.ts) and the sim's own notes come that way before |win|.
ROOM_LINES = {"c", "c:", "chat", "j", "J", "l", "L", "n", "N", "raw", "html", "uhtml", "uhtmlchange", "inactive",
              "inactiveoff", "tempnotify", "tempnotifyoff", "controlshtml", "fieldhtml", "cantleave", "allowleave",
              "title", "badge", "rated", "message", "-message", "notify", "error", "timer", "seed", "debug", "",
              "join", "leave", "name", "b", "B", "battle", "unlink", "hidelines", "-hint", "-center", "-nothing",
              "-notarget", "-hitcount", "-waiting", "-combine"}

# Battle lines whose whole effect on the view is in the line (HP, stages, status, a move, a switch, a turn) or that
# change no field; the converter parses them and refuses what it does not know.
GENERIC = {"move", "switch", "-damage", "-heal", "faint", "cant", "-miss", "-crit", "-supereffective", "-resisted",
           "-immune", "-fail", "-boost", "-unboost", "-status", "-curestatus", "-prepare", "-anim", "-mega", "turn",
           "upkeep", "win", "tie"} | trace_to_c.NOT_EVENTS

# Moves whose effect on the view no line shows: Baton Pass hands stages and volatiles to the incoming Pokemon,
# Revival Blessing revives a member through a request of its own.
SILENT_MOVES = {"Baton Pass", "Revival Blessing", "Shed Tail"}

# Showdown's choice items at the pin (isChoice; the reference test checks the list): a holder is locked into the move
# of its |move| line until it leaves (data/items.ts onModifyMove, data/conditions.ts choicelock).
CHOICE_ITEMS = ("choiceband", "choicescarf", "choicespecs")

TURN_SCOPED = {"RAGE_POWDER", "WIDE_GUARD", "QUICK_GUARD"}


def _features():
    """DUOFORGE_VIEWEXT_FEATURE_* of include/duoforge/duoforge.h: name -> bit (decision 0018 section 7.1)."""
    header = (ROOT / "include" / "duoforge" / "duoforge.h").read_text(encoding="ascii")
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r"#define DUOFORGE_VIEWEXT_FEATURE_([A-Z_]+) +(\d+)u", header) if m.group(1) != "COUNT"}


FEATURES = _features()


def supported(root=ROOT):
    """The library's supported mask of the view extension: view_ext_features of src/data/support_manifest.c, the
    value duoforge_observation_ext.supported carries (0u, or an OR of 1ull << DUOFORGE_VIEWEXT_FEATURE_* terms)."""
    source = (root / "src" / "data" / "support_manifest.c").read_text(encoding="ascii")
    m = re.search(r"\.view_ext_features = ([^;,]+?)[,;]?\n", source)
    if m is None:
        raise ValueError("support_manifest.c: no view_ext_features")
    expression = m.group(1).strip()
    if expression == "0u":
        return 0
    mask = 0
    for term in expression.split("|"):
        bit = re.fullmatch(r"\(?\s*1u?ll?u?\s*<<\s*DUOFORGE_VIEWEXT_FEATURE_([A-Z_]+)\s*\)?", term.strip())
        if bit is None or bit.group(1) not in FEATURES:
            raise ValueError(f"support_manifest.c: view_ext_features term {term.strip()!r} is not understood")
        mask |= 1 << FEATURES[bit.group(1)]
    return mask


SUPPORTED = supported()

# Effects of decision 0018 section 6.1, by line kind: the effect (without "move: " / "ability: ") -> feature.
_START = {"move: Taunt": "TAUNT", "Taunt": "TAUNT", "Encore": "ENCORE", "Substitute": "SUBSTITUTE",
          "typechange": "TYPE_CHANGE", "Throat Chop": "THROAT_CHOP", "move: Heal Block": "HEAL_BLOCK",
          "Heal Block": "HEAL_BLOCK", "move: Imprison": "IMPRISON", "Disable": "DISABLE", "Stockpile": "STOCKPILE",
          "move: Yawn": "YAWN", "move: Leech Seed": "LEECH_SEED", "Salt Cure": "SALT_CURE", "Curse": "CURSE",
          "move: No Retreat": "NO_RETREAT", "Charge": "CHARGE", "move: Dragon Cheer": "DRAGON_CHEER",
          "move: Focus Energy": "FOCUS_ENERGY", "Infestation": "PARTIAL_TRAP", "move: Infestation": "PARTIAL_TRAP",
          "Wrap": "PARTIAL_TRAP", "Bind": "PARTIAL_TRAP", "Fire Spin": "PARTIAL_TRAP", "Whirlpool": "PARTIAL_TRAP",
          "Sand Tomb": "PARTIAL_TRAP", "Magma Storm": "PARTIAL_TRAP", "Snap Trap": "PARTIAL_TRAP",
          "Thunder Cage": "PARTIAL_TRAP"}
_WEATHER = {"Sandstorm": "WEATHER_SAND", "Snowscape": "WEATHER_SNOW", "Snow": "WEATHER_SNOW"}
_FIELD = {"move: Electric Terrain": "TERRAIN_ELECTRIC", "move: Misty Terrain": "TERRAIN_MISTY",
          "move: Gravity": "GRAVITY"}
_SIDE = {"move: Aurora Veil": "AURORA_VEIL", "Aurora Veil": "AURORA_VEIL", "move: Stealth Rock": "STEALTH_ROCK",
         "Stealth Rock": "STEALTH_ROCK", "move: Spikes": "SPIKES", "Spikes": "SPIKES",
         "move: Toxic Spikes": "TOXIC_SPIKES", "Toxic Spikes": "TOXIC_SPIKES", "move: Sticky Web": "STICKY_WEB",
         "Sticky Web": "STICKY_WEB"}
_SINGLE_TURN = {"move: Rage Powder": "RAGE_POWDER", "Rage Powder": "RAGE_POWDER", "Wide Guard": "WIDE_GUARD",
                "move: Wide Guard": "WIDE_GUARD", "Quick Guard": "QUICK_GUARD", "move: Quick Guard": "QUICK_GUARD"}
_SINGLE_MOVE = {"Glaive Rush": "GLAIVE_RUSH", "move: Glaive Rush": "GLAIVE_RUSH", "Destiny Bond": "DESTINY_BOND",
                "move: Destiny Bond": "DESTINY_BOND"}
_ITEM_CHANGE_FROM = {"move: Trick", "move: Switcheroo", "move: Thief", "move: Covet", "move: Recycle",
                     "move: Knock Off", "move: Incinerate", "move: Fling", "move: Bug Bite", "move: Pluck", "stealeat",
                     "ability: Pickpocket", "ability: Magician", "ability: Harvest", "ability: Pickup"}

# The fold's own effects, beside the generic kinds (the converter's step_events and the tracker's _event).
# The -activate effects of the committed reference battles (python/tests/test_replay.py checks that their spectator
# logs never stop): a Protect block, a Psychic Terrain block, confusion, Emergency Exit (folded), and two
# announcements that change no field: Lightning Rod drawing a move, Struggle when no move is left.
_FOLD_ACTIVATE = {"move: Protect", "move: Psychic Terrain", "confusion", "ability: Emergency Exit",
                  "ability: Lightning Rod", "ability: Storm Drain", "move: Struggle"}
# A guard blocking a move this turn: the same single-turn feature as its -singleturn line.
_GUARD_ACTIVATE = {"move: Wide Guard": "WIDE_GUARD", "move: Quick Guard": "QUICK_GUARD"}
_FOLD_SINGLE_TURN = {"Protect", "Helping Hand", "move: Follow Me"}
_FOLD_START = {"confusion", "ability: Flash Fire"}
_FOLD_END = {"confusion"}
_FOLD_WEATHER = {"RainDance", "SunnyDay", "none"}
_FOLD_FIELD = {"move: Grassy Terrain", "move: Psychic Terrain", "move: Trick Room"}
_FOLD_SIDE = {"move: Tailwind", "Reflect", "move: Reflect", "move: Light Screen"}


def _feature(name):
    """A feature line: folded when its bit is supported, else Stop."""
    if name not in FEATURES:
        raise ValueError(f"no DUOFORGE_VIEWEXT_FEATURE_{name}")
    if SUPPORTED >> FEATURES[name] & 1:
        return "fold"
    if name in TURN_SCOPED:
        return f"turn:{name}"
    raise Stop(f"feature:{name}")


def _unknown(kind, effect=None):
    raise Stop(f"line:{kind}" + (f" {effect}" if effect else ""))


def _froms(attrs):
    return [a[len("[from] "):] for a in attrs if a.startswith("[from] ") or a.startswith("[from]")]


def _toxic(parts):
    """Whether an HP or status field of the line shows Toxic (badly poisoned): Tox of 0018 section 4."""
    return any(p == "tox" or p.endswith(" tox") for p in parts[2:] if not p.startswith("["))


def check(line, view):
    """The class of a protocol line (module docstring). `view` is the tracker: view.data, view.sheet_of(ident) (the
    member's sheet: species, item, ability ids as parse_team has them) and view.ability_now(ident) (its current
    ability + 1)."""
    if not line.startswith("|") or line.startswith("||"):
        return None
    parts = line.split("|")
    kind = parts[1]
    if kind in ROOM_LINES or kind.startswith("t:"):
        return None
    attrs = [p for p in parts[2:] if p.startswith("[")]
    args = [p for p in parts[2:] if not p.startswith("[")]
    tables = view.data.tables
    if _toxic(parts) and kind in ("switch", "-damage", "-heal", "-status", "-curestatus"):
        return _feature("AILMENT_TOX")
    if kind == "replace":
        return _feature("ILLUSION")
    if kind == "switch" and len(args) > 1:
        # A member back in another forme than its own or its Mega changed on the way out, silently (Zero to Hero:
        # Palafin-Hero): decision 0018's FORME_CHANGE, its permanent forme shown by the switch line.
        try:
            forme = view.data.forme(args[1].split(",")[0])
        except ValueError:
            return _feature("FORME_CHANGE")
        sheet = view.known_sheet(args[0])
        if sheet is not None and view.data.base_forme(forme) != sheet["species"]:
            return _feature("FORME_CHANGE")
        return "fold"
    if kind == "move":
        if len(args) > 1 and args[1] in SILENT_MOVES:
            _unknown(kind, args[1])
        return "fold"
    if kind == "-fail" and len(args) > 1 and args[1] not in trace_to_c.AILMENT:
        _unknown(kind, args[1])  # a failure the converter does not parse (a stat drop Clear Body stopped: unboost)
    if kind in GENERIC:
        return "fold"
    if kind == "-clearnegativeboost" and attrs == ["[silent]"]:
        return "fold"  # White Herb (Team C): the [silent] line the converter skips; the tracker folds it
    effect = args[1] if len(args) > 1 else ""
    if kind == "-activate":
        if effect in _FOLD_ACTIVATE:
            return "fold"
        if effect in _GUARD_ACTIVATE:
            return _feature(_GUARD_ACTIVATE[effect])
        if effect in ("move: Skill Swap",):
            return _feature("ABILITY_CHANGE")
        if effect in _START:
            return _feature(_START[effect])
        _unknown(kind, effect)
    if kind == "-singleturn":
        if effect in _FOLD_SINGLE_TURN:
            return "fold"
        if effect in _SINGLE_TURN:
            return _feature(_SINGLE_TURN[effect])
        _unknown(kind, effect)
    if kind == "-singlemove":
        if effect in _SINGLE_MOVE:
            return _feature(_SINGLE_MOVE[effect])
        _unknown(kind, effect)
    if kind in ("-start", "-end"):
        if effect in (_FOLD_START if kind == "-start" else _FOLD_END):
            return "fold"
        if re.fullmatch(r"perish[0-3]", effect):
            return _feature("PERISH")
        if re.fullmatch(r"stockpile[1-3]", effect):
            return _feature("STOCKPILE")
        if effect in _START:
            return _feature(_START[effect])
        _unknown(kind, effect)
    if kind == "-mustrecharge":
        return _feature("MUST_RECHARGE")
    if kind == "-weather":
        weather = args[0] if args else ""
        if weather in _FOLD_WEATHER:
            return "fold"
        if weather in _WEATHER:
            return _feature(_WEATHER[weather])
        _unknown(kind, weather)
    if kind in ("-fieldstart", "-fieldend"):
        field = args[0] if args else ""
        if field in _FOLD_FIELD:
            return "fold"
        if field in _FIELD:
            return _feature(_FIELD[field])
        _unknown(kind, field)
    if kind in ("-sidestart", "-sideend"):
        if effect in _FOLD_SIDE:
            return "fold"
        if effect in _SIDE:
            return _feature(_SIDE[effect])
        _unknown(kind, effect)
    if kind == "-ability":
        froms = _froms(attrs)
        if froms:
            if froms[0].startswith("ability: ") or froms[0].startswith("move: "):
                return _feature("ABILITY_CHANGE")
            _unknown(kind, f"{effect} [from] {froms[0]}")
        ability = tables["ABILITY"].get(trace_to_c.key(effect))
        if ability is not None and ability + 1 == view.ability_now(args[0]):
            return "fold"  # an announcement of the holder's own ability (Intimidate, Pressure, ...)
        _unknown(kind, effect)
    if kind == "-enditem":
        froms = _froms(attrs)
        if any(f in _ITEM_CHANGE_FROM or f.startswith("move: ") for f in froms):
            return _feature("ITEM_CHANGE")
        item = tables["ITEM"].get(trace_to_c.key(effect))
        if not froms and item is not None and item + 1 == view.sheet_of(args[0])["item"]:
            return "fold"  # the holder used its own item up (a berry, Focus Sash, White Herb, a popped balloon)
        _unknown(kind, effect)
    if kind == "-item":
        froms = _froms(attrs)
        item = tables["ITEM"].get(trace_to_c.key(effect))
        own = item is not None and item + 1 == view.sheet_of(args[0])["item"]
        if own and ("[identify]" in attrs or not froms):
            return "fold"  # Frisk, or the holder's own announcement (Air Balloon): an item the open sheet shows
        if any(f in _ITEM_CHANGE_FROM for f in froms):
            return _feature("ITEM_CHANGE")
        _unknown(kind, effect)
    if kind == "detailschange":
        sheet = view.sheet_of(args[0])
        forme = tables["FORME"].get(trace_to_c.key(effect.split(",")[0]))
        if forme is not None and forme == view.data.mega_of(sheet["species"], sheet["item"]):
            return "fold"  # Mega Evolution; the -mega line follows
        return _feature("FORME_CHANGE")
    if kind == "-formechange":
        return _feature("FORME_CHANGE")
    _unknown(kind)
