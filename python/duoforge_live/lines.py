"""The class of every protocol line before the fold (M11 spec section 5).

The converter (trace_to_c.step_events) parses the lines of the mechanics
DuoForge implements, and raises on a line kind it does not know. Some lines
of a known kind still mean something the fold does not apply, and would be
folded wrongly in silence: an ability changed by Trace comes as an -ability
line, an item knocked off as an -enditem line. check() sorts every line
first:

- room: a line of the room, not of the battle (None);
- fold: a line the tracker folds ("fold");
- keep: a line that changes no field and that the converter does not read
  ("keep"): a stat drop that the holder's own ability stopped (Intimidate
  against Inner Focus or Clear Body). The tracker keeps it with the step's
  lines and folds nothing;
- feature: an effect of decision 0018 section 6.1. It is folded only when the
  library supports its DUOFORGE_VIEWEXT_FEATURE_* bit; otherwise Stop
  ("feature:<NAME>"). The single-turn features of a PIVOT boundary (Rage
  Powder, Wide Guard, Quick Guard) return "turn:<NAME>": they change no
  TURN or REPLACEMENT observation, and the caller decides;
- unknown: a kind whose effect the view cannot hold (UNREPRESENTABLE_KINDS), or a
  known kind with an effect no entry names: Stop("line:<kind> <effect>").
  Any other kind goes to the converter, which parses the forms of the
  mechanics DuoForge implements and raises on the rest (a Stop "converter:");
  the replay test proves the fold equal to DuoForge on every committed battle.

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
              "join", "leave", "name", "player", "b", "B", "battle", "unlink", "hidelines", "-hint", "-center",
              "-nothing",
              "-notarget", "-hitcount", "-waiting", "-combine"}

# Battle lines whose whole effect on the view is in the line (HP, stages, status, a move, a switch, a turn) or that
# change no field; the converter parses them and refuses what it does not know.
GENERIC = {"move", "switch", "-damage", "-heal", "faint", "cant", "-miss", "-crit", "-supereffective", "-resisted",
           "-immune", "-fail", "-boost", "-unboost", "-status", "-curestatus", "-prepare", "-anim", "-mega", "turn",
           "upkeep", "win", "tie"} | trace_to_c.NOT_EVENTS

# Moves whose effect on the view no line shows: Baton Pass hands stages and volatiles to the incoming Pokemon,
# Revival Blessing revives a member through a request of its own.
SILENT_MOVES = {"Baton Pass", "Shed Tail"}  # Revival Blessing: folded since step G52 (the REVIVE event)

# Showdown's choice items at the pin (isChoice; the reference test checks the list): a holder is locked into the move
# of its |move| line until it leaves (data/items.ts onModifyMove, data/conditions.ts choicelock).
CHOICE_ITEMS = ("choiceband", "choicescarf", "choicespecs")

TURN_SCOPED = {"RAGE_POWDER", "WIDE_GUARD", "QUICK_GUARD"}

# Kinds whose effect on the view no field holds and the fold does not apply: stops with a readable reason.
UNREPRESENTABLE_KINDS = {"-sethp", "-clearboost", "-clearpositiveboost", "-copyboost", "-setboost",
                         "-swapboost", "-invertboost", "-transform", "swap", "-endability", "-swapsideconditions",
                         "-cureteam"}


def _features():
    """DUOFORGE_VIEWEXT_FEATURE_* of include/duoforge/duoforge.h: name -> bit (decision 0018 section 7.1)."""
    header = (ROOT / "include" / "duoforge" / "duoforge.h").read_text(encoding="ascii")
    return {m.group(1): int(m.group(2))
            for m in re.finditer(r"#define DUOFORGE_VIEWEXT_FEATURE_([A-Z_]+) +(\d+)u", header) if m.group(1) != "COUNT"}


FEATURES = _features()


def parse_supported(expression):
    """The mask of a view_ext_features expression: 0u, or an OR of 1 shifted by DUOFORGE_VIEWEXT_FEATURE_* bits
    ("1ull << X", "((uint64_t)1u << X)"). ValueError for anything else."""
    expression = expression.strip()
    if expression == "0u":
        return 0
    mask = 0
    for term in expression.split("|"):
        bit = re.fullmatch(r"\(*\s*(?:\(\s*uint64_t\s*\)\s*)?1(?:u|ull|ul|llu)?\s*<<\s*"
                           r"DUOFORGE_VIEWEXT_FEATURE_([A-Z_]+)\s*\)*", term.strip())
        if bit is None or bit.group(1) not in FEATURES:
            raise ValueError(f"support_manifest.c: view_ext_features term {term.strip()!r} is not understood")
        mask |= 1 << FEATURES[bit.group(1)]
    return mask


def supported(root=ROOT):
    """The library's supported mask of the view extension: view_ext_features of src/data/support_manifest.c, the
    value duoforge_observation_ext.supported carries."""
    return extract_supported((root / "src" / "data" / "support_manifest.c").read_text(encoding="ascii"))


def extract_supported(source):
    """The mask of the view_ext_features initializer in a support manifest's source, which may span lines (the
    expression ends at the comma before the next field or the closing brace)."""
    m = re.search(r"\.view_ext_features\s*=\s*(.*?)\s*,?\s*\n\s*(?:\}|\.)", source, re.S)
    if m is None:
        raise ValueError("support_manifest.c: no view_ext_features")
    return parse_supported(" ".join(m.group(1).split()))


LIBRARY_SUPPORTED = supported()
# The features this tracker folds (decision 0018 section 6.1). The base-value features: Sand, Snow and Tox show in the
# base view's own fields (weather, a member's status), which the converter's events already fill, so they need no
# extension record (M11 BC spec section 5). Electric and Misty terrain join when the library supports them (#163),
# with tests of their own. Every other feature still stops until its fold is here. The replay rows carry no extension
# record yet: a BC mask keeps only the base-value features (duoforge_learn.bc_data.bc_mask).
BASE_FOLDS = sum(1 << FEATURES[n] for n in ("WEATHER_SAND", "WEATHER_SNOW", "AILMENT_TOX"))
# The view-extension folds (tracker.EXT_FIELDS: the record fields the tracker fills; test_replay compares them with
# DuoForge's record byte for byte and requires each to be shown at compared points of both viewers, own and foe side).
EXT_FOLDS = sum(1 << FEATURES[n] for n in ("THROAT_CHOP", "AURORA_VEIL"))
TRACKER_FOLDS = BASE_FOLDS | EXT_FOLDS
SUPPORTED = LIBRARY_SUPPORTED & TRACKER_FOLDS

# Effects of decision 0018 section 6.1, by line kind: the effect (without "move: " / "ability: ") -> feature.
_START = {"move: Taunt": "TAUNT", "Taunt": "TAUNT", "Encore": "ENCORE", "Substitute": "SUBSTITUTE",
          "move: Substitute": "SUBSTITUTE",  # the absorbed hit's -activate (decision 0032, step G60)
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
                "move: Wide Guard": "WIDE_GUARD", "Quick Guard": "QUICK_GUARD", "move: Quick Guard": "QUICK_GUARD",
                "move: Roost": "ROOST", "Roost": "ROOST"}  # Roost's grounded turn (G42; its residual end is silent)
_SINGLE_MOVE = {"Glaive Rush": "GLAIVE_RUSH", "move: Glaive Rush": "GLAIVE_RUSH", "Destiny Bond": "DESTINY_BOND",
                "move: Destiny Bond": "DESTINY_BOND"}
_ITEM_CHANGE_FROM = {"move: Trick", "move: Switcheroo", "move: Thief", "move: Covet", "move: Recycle",
                     "move: Knock Off", "move: Incinerate", "move: Fling", "move: Bug Bite", "move: Pluck", "stealeat",
                     "ability: Pickpocket", "ability: Magician", "ability: Harvest", "ability: Pickup"}

# The fold's own effects, beside the generic kinds (the converter's step_events and the tracker's _event).
# The -activate effects of the committed reference battles (python/tests/test_replay.py checks that their spectator
# logs never stop): a Protect block, a Psychic Terrain block, confusion, Emergency Exit (folded), and three
# announcements that change no field: Lightning Rod drawing a move, Struggle when no move is left, and Sticky Hold
# keeping the item of a holder that a move went for (step G16; the item stays, so no ITEM_CHANGE), and Feint breaking a
# Protect or a side's guard (step G28; the tracker clears the target's protecting flag and stall chain and its side's
# guard markers in the ACTIVATE event).
_FOLD_ACTIVATE = {"move: Protect", "move: Psychic Terrain", "confusion", "ability: Emergency Exit",
                  "ability: Lightning Rod", "ability: Storm Drain", "move: Struggle", "ability: Sticky Hold",
                  "move: Feint", "move: After You", "move: Quash", "move: Phantom Force"}  # After You, Quash: the queue, no field (G62); Phantom Force: its [broken] protection (G58)
# A guard blocking a move this turn: the same single-turn feature as its -singleturn line.
_GUARD_ACTIVATE = {"move: Wide Guard": "WIDE_GUARD", "move: Quick Guard": "QUICK_GUARD"}
# `-singleturn|X|move: Protect` is the Protect volatile of Spiky Shield, Baneful Bunker and Burning Bulwark (their condition
# prints it with the `move:` prefix, data/moves.ts:17532 and :985; Protect and Detect print `Protect`). On the view the line
# only means "protected this turn", so it folds like Protect's; Baneful Bunker's poison and Burning Bulwark's burn arrive
# as their own -status lines, and Spiky Shield's damage as a -damage line with [from] Spiky Shield (trace_to_c.ev_cause
# knows that source).
_FOLD_SINGLE_TURN = {"Protect", "move: Protect", "Helping Hand", "move: Follow Me"}
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


# The stats' full names, as older servers wrote them in -fail|X|unboost lines ("Attack"; Reg M-B replays); the pin
# writes the ids of trace_to_c.EV_STATS ("atk").
_STAT_NAMES = {"Attack", "Defense", "Special Attack", "Special Defense", "Speed", "accuracy", "evasiveness"}


def _kept_drop(args, attrs, view):
    """-fail|X|unboost[|stat]|[from] ability: A|[of] X: X's own ability A stopped a drop (Intimidate against Inner
    Focus, Scrappy, Oblivious, Own Tempo or Hyper Cutter, which name the stat; any drop against Clear Body or White
    Smoke, which do not; data/abilities.ts onTryBoost). The stat stays: no field changes ("keep"). Any other form
    stops."""
    froms = _froms(attrs)
    of = [a[len("[of] "):] for a in attrs if a.startswith("[of] ")]
    stats = args[2:]
    if (len(froms) == 1 and froms[0].startswith("ability: ") and of == [args[0]] and len(stats) <= 1
            and all(s in trace_to_c.EV_STATS or s in _STAT_NAMES for s in stats)):
        ability = view.data.tables["ABILITY"].get(trace_to_c.key(froms[0][len("ability: "):]))
        if ability is not None and ability + 1 == view.ability_now(args[0]):
            return "keep"
    _unknown("-fail", "unboost")


def _not_its_own(kind, effect, ident, view):
    """A line whose item or ability is not the named member's: under a possible Illusion (an Illusion holder on that
    side's open sheet, decision 0026) the name may be the disguise's, so it is the Illusion feature; else unknown."""
    illusion = view.data.tables["ABILITY"].get("ILLUSION")
    if illusion is not None and any(s["ability"] == illusion + 1 for s in view.side_sheets(ident)):
        return _feature("ILLUSION")
    _unknown(kind, effect)


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
    if kind == "-fail" and len(args) > 1 and args[1] == "unboost":
        return _kept_drop(args, attrs, view)
    if kind in GENERIC:
        return "fold"
    if kind == "-ohko" and not args and not attrs:
        # Sheer Cold (step G64, sim/battle-actions.ts:999): shown after its target's faint, which its own lines fold;
        # no field changes ("keep": the converter drops it only in that place, so the tracker does not convert it)
        return "keep"
    if kind == "-clearnegativeboost" and attrs == ["[silent]"]:
        return "fold"  # White Herb (Team C): the [silent] line the converter skips; the tracker folds it
    effect = args[1] if len(args) > 1 else ""
    if kind == "-activate":
        if effect in _FOLD_ACTIVATE:
            return "fold"
        if effect in _GUARD_ACTIVATE:
            return _feature(_GUARD_ACTIVATE[effect])
        if effect in ("move: Electric Terrain", "move: Misty Terrain"):
            return _feature(_FIELD[effect])  # the terrain blocking Yawn or its sleep: its own feature, as -fieldstart
        if effect in ("move: Skill Swap", "Skill Swap"):  # the pin prints it without "move: " (decision 0041)
            return _feature("ABILITY_CHANGE")
        if effect == "move: Poltergeist" and len(args) == 3:
            # Poltergeist (step G64): it names the item its target holds; the open sheet's item is no news (an
            # ACTIVATE without state). Any other item stops: the view does not know it.
            item = tables["ITEM"].get(trace_to_c.key(args[2]))
            target = view.sheet_of(args[0])
            if item is not None and item + 1 == target["item"]:
                return "fold"
            _unknown(kind, effect)
        if effect == "ability: Symbiosis":
            return _feature("ITEM_CHANGE")  # the holder hands its item to its partner (step G69), as a Trick does
        if effect == "move: Trick":
            return _feature("ITEM_CHANGE")  # Trick's announcement before its -item lines (G29; Switcheroo prints none)
        if effect in _START:
            return _feature(_START[effect])
        if effect.startswith("ability: "):
            # the holder announcing its own current ability (Synchronize, Telepathy, ...): its effects come in their
            # own lines (-status, -immune, a skipped hit), so this line changes no field; another holder's ability
            # stays unknown (an ability change shows in its own -ability line)
            ability = tables["ABILITY"].get(trace_to_c.key(effect[len("ability: "):]))
            if ability is not None and ability + 1 == view.ability_now(args[0]):
                return "fold"
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
        return _not_its_own(kind, effect, args[0], view)
    if kind == "-enditem":
        froms = _froms(attrs)
        if any(f in _ITEM_CHANGE_FROM or f.startswith("move: ") for f in froms):
            return _feature("ITEM_CHANGE")
        item = tables["ITEM"].get(trace_to_c.key(effect))
        if not froms and item is not None and item + 1 == view.sheet_of(args[0])["item"]:
            return "fold"  # the holder used its own item up (a berry, Focus Sash, White Herb, a popped balloon)
        if not froms:
            return _not_its_own(kind, effect, args[0], view)
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
    if kind in UNREPRESENTABLE_KINDS:
        _unknown(kind)
    return "fold"  # the converter decides: it parses what DuoForge implements and refuses the rest
