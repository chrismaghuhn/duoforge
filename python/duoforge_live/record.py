"""The public record of a live decision point (M12 option A, plan 2026-10-10-live-honest-search; decision 0023).

assemble(tracker) writes what a Tracker has folded from the protocol lines into the canonical public record layout
(PUBLIC_STATE: its header and the canonical state encoding, field names and byte ranges from duoforge.state_layout). It
serialises facts; it decides no rule and no mask:

- it fills only fields the tracker folds as public, plus the player's own exact values from its requests (HP, stats, PP,
  stat points, the pick order). Everything the engine masks in a public record (the RNG, the foe's HP, stats, stat
  points, PP, brought set and bench order) the tracker never knows, so it stays zero;
- the context's constants (the envelope and the fingerprint) and the encoding's size come from the engine's own record of
  the same kind (Data.record_head);
- the values an encoded byte holds (volatile bits, switch reasons, revealed facts) come from the generated layout
  (duoforge._state_layout.VALUES); the opponent's HP display of an own member from the library (duoforge.view.hp_display).

The engine checks every assembled record (check below; RecordRoots does the same in the search): a world built from it
must give it back byte for byte (duoforge_battle_from_view, then duoforge_battle_public), so a filled field that the engine
masks, or one that contradicts the others, is refused there (E_MALFORMED) instead of being searched.

Refusals: where the engine refuses a player's record (duoforge_battle_public's E_UNSUPPORTED) the tracker refuses with the
same status, derived from public facts only (refusal below): the cause mask of duoforge_battle_public_causes, computed from
the observation as the C predicate reads it, the Revival Blessing proxy, a possible lockedmove, and a PIVOT before moves
or with a move still queued. A decision point the assembler cannot reproduce exactly is refused too, with its own named
reason, never approximated: unburden-without-item-line, last-move-not-on-sheet, and move-result-not-determined (the
library cannot tell an action's result from its events). The POOL tail's move_result is the library's classification of
each move action's events (duoforge_move_result, the engine's rule; the tracker only collects the events); its other
fields are the tracker's folds (party order, Aurora Veil, the position counters, item_now, the toxic stage, the raised
flag). The features the tracker does not fold stop it at their lines (lines.check) before a record could need them.
"""
import numpy as np

from duoforge import _layout, state_layout
from duoforge._state_layout import VALUES

from . import tracker as _tracker

C = _layout.CONSTANTS
E_UNSUPPORTED = C["DUOFORGE_E_UNSUPPORTED"]
TEAM_SELECTION, TURN, REPLACEMENT, PIVOT = (C[f"DUOFORGE_BOUNDARY_{n}"] for n in
                                            ("TEAM_SELECTION", "TURN", "REPLACEMENT", "PIVOT"))
CAUSE_SLEEP, CAUSE_CONFUSION = C["DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP"], C["DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION"]
CAUSE_ILLUSION = C["DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE"]
CAUSE_RAISED = C["DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN"]
MAX_ROSTER = 6
Q_RESIDUAL = VALUES["DFI_Q_RESIDUAL"]
AILMENT_SLEEP = C["DUOFORGE_AILMENT_SLEEP"]
PICK_NONE = C["DUOFORGE_VIEW_PICK_NONE"]
OCCUPANT_NONE = VALUES["DFI_OCCUPANT_NONE"]
STAGE_NEUTRAL = VALUES["DFI_STAGE_NEUTRAL"]
REVEALED_ITEM_CONSUMED, REVEALED_MEGA = VALUES["DFI_REVEALED_ITEM_CONSUMED"], VALUES["DFI_REVEALED_MEGA"]
VOL_PROTECT, VOL_FLASH_FIRE = VALUES["DFI_VOL_PROTECT"], VALUES["DFI_VOL_FLASH_FIRE"]
VOL_FOLLOW_ME, VOL_HELPING_HAND, VOL_UNBURDEN = (VALUES[f"DFI_VOL_{n}"] for n in ("FOLLOW_ME", "HELPING_HAND", "UNBURDEN"))
VOL_CHOICE_LOCK, VOL_NEWLY_SWITCHED = VALUES["DFI_VOL_CHOICE_LOCK"], VALUES["DFI_VOL_NEWLY_SWITCHED"]
PARTY_HIDDEN = 7  # DFI_PARTY_HIDDEN
POSFLAG_STATS_RAISED = 2  # DFI_POSFLAG_STATS_RAISED
MR_UNCLASSIFIED_NOW, MR_UNCLASSIFIED_LAST = VALUES["DFI_MOVE_RESULT_UNCLASSIFIED_NOW"], VALUES["DFI_MOVE_RESULT_UNCLASSIFIED_LAST"]
_FIELDS = {name: (start, size) for name, start, size in state_layout.fields(pool=True)}


class Refusal(Exception):
    """A decision point whose record the tracker refuses: status E_UNSUPPORTED, the cause mask, a named reason."""

    def __init__(self, reason, causes=0):
        super().__init__(reason)
        self.reason, self.causes = reason, int(causes)


class _State:
    """The canonical encoding being written, by state_layout field name."""

    def __init__(self, size):
        self.bytes = bytearray(size)

    def put(self, name, value):
        """An integer, little-endian over the field's bytes."""
        start, size = _FIELDS[name]
        self.bytes[start:start + size] = int(value).to_bytes(size, "little")

    def put_list(self, name, values, width=1):
        """A list of integers of `width` bytes each, filling the field exactly."""
        start, size = _FIELDS[name]
        data = b"".join(int(v).to_bytes(width, "little") for v in values)
        if len(data) != size:
            raise ValueError(f"{name}: {len(data)} bytes for a field of {size}")
        self.bytes[start:start + size] = data


def visible_causes(observation, tables):
    """The DUOFORGE_PUBLIC_CAUSE_* mask that the player's observation decides, read as src/state/view.c
    dfi_view_visible_causes reads it: a member of either side shown asleep; a position of either side shown confused; a
    foe member with Illusion on its open sheet that the player has neither seen fainted nor sees on the field under its
    own name; at a PIVOT, an active Pokemon of either side with Alluring Voice among its moves (the view does not carry
    statsRaisedThisTurn mid-turn). tables: the tracker's (the POOL rows; a closure table without them has no such
    member). The Substitute and temporary forme bits need lines the tracker stops at (lines.check: SUBSTITUTE,
    FORME_CHANGE), and the foe's disguise state is zero while no Illusion line came (ILLUSION stops too)."""
    mask = 0
    for side in (0, 1):
        s = observation["sides"][side]
        if (s["members"]["status"] == AILMENT_SLEEP).any():
            mask |= CAUSE_SLEEP
        if (s["positions"]["confused"] != 0).any():
            mask |= CAUSE_CONFUSION
    illusion = tables["ABILITY"].get("ILLUSION")
    foe = observation["sides"][1 - int(observation["player"])]
    for m in range(int(foe["member_count"])):
        v = foe["members"][m]
        if illusion is None or int(v["ability"]) != illusion + 1:
            continue
        fainted_seen = int(v["hp_kind"]) == C["DUOFORGE_HP_PERCENT"] and int(v["hp"]) == 0
        if not fainted_seen and m not in (int(foe["occupant"][0]), int(foe["occupant"][1])):
            mask |= CAUSE_ILLUSION
    alluring = tables["MOVE"].get("ALLURINGVOICE")
    if int(observation["boundary_kind"]) == PIVOT and alluring is not None:
        for side in (0, 1):
            s = observation["sides"][side]
            for occupant in s["occupant"]:
                if int(occupant) < MAX_ROSTER:
                    v = s["members"][int(occupant)]
                    if alluring in [int(x) for x in v["move_ids"][:int(v["move_count"])]]:
                        mask |= CAUSE_RAISED
    return mask


def revive_proxy(observation, tables):
    """decision 0023's Revival Blessing proxy (src/state/view.c dfi_view_foe_revive_proxy): a foe member whose Revival
    Blessing slot shows derived PP 0 may have revived, which the record keeps no history of; refused without a cause bit."""
    blessing = tables["MOVE"].get("REVIVALBLESSING")
    foe = observation["sides"][1 - int(observation["player"])]
    for v in foe["members"]:
        for k in range(int(v["move_count"])):
            if blessing is not None and int(v["move_ids"][k]) == blessing and int(v["pp"][k]) == 0:
                return True
    return False


def refusal(tracker, observation):
    """None, or the Refusal of the engine's public record at this decision point, from public facts alone, in the
    order of src/state/view.c dfi_view_encode."""
    causes = visible_causes(observation, tracker.data.tables)
    if causes:
        names = [n for bit, n in ((CAUSE_SLEEP, "visible-sleep"), (CAUSE_CONFUSION, "visible-confusion"),
                                  (CAUSE_ILLUSION, "illusion-possible"), (CAUSE_RAISED, "raised-this-turn")) if causes & bit]
        raise Refusal(",".join(names), causes)
    if revive_proxy(observation, tracker.data.tables):
        raise Refusal("revive-proxy")
    for side in tracker._positions:
        for p in side:
            # a lockedmove may run while the occupant's last used move is one (src/state/knowledge.h dfi_maybe_lockedmove):
            # its drawn length can end silently, so the engine refuses the record
            if p.occupant != OCCUPANT_NONE and p.last_move is not None and \
                    tracker.data.move_flags(p.last_move) & _tracker._LOCKED_MOVE:
                raise Refusal("lockedmove-possible")
    if tracker.boundary() == PIVOT:
        flags = [p.protecting or p.flags & (_tracker.FLAG_FOLLOW_ME | _tracker.FLAG_HELPING_HAND)
                 for side in tracker._positions for p in side]
        if not any(flags):
            raise Refusal("pivot-before-moves")
        if any(p.move_queued for side in tracker._positions for p in side):
            # a silent flinch may be outstanding on a position still to move (src/state/view.c): the engine refuses
            raise Refusal("pivot-move-queued")
    # the tracker's own refusals, where the engine has a record that the lines do not determine
    if any(p.unburden_unseen for side in tracker._positions for p in side):
        raise Refusal("unburden-without-item-line")  # the volatile may be up with no line (tracker, Knock Off)
    return None


def move_result_of(data, user, events):
    """The result of one move action (the POOL tail's move_result of this turn: DFI_MOVE_RESULT_* with
    DFI_MOVE_RESULT_UNCLASSIFIED_NOW), classified by the library from the action's events (duoforge.view.move_result,
    the engine's rule); None where the events do not determine it."""
    from duoforge import view
    return view.move_result(data.context(), user, events)


def move_result_byte(now, last):
    """The tail's move_result byte of this turn's and last turn's results (each a value with its unclassified bit, in this
    turn's form: DFI_MOVE_RESULT_UNCLASSIFIED_NOW): this turn in bits 0-1 and 4, last turn in bits 2-3 and 5."""
    return (now & 3) | (now & MR_UNCLASSIFIED_NOW) | ((last & 3) << 2) | (MR_UNCLASSIFIED_LAST if last & MR_UNCLASSIFIED_NOW else 0)


def assemble(tracker, observation):
    """(record, status, causes, reason) at the tracker's current decision point: the PUBLIC_STATE record and status 0,
    or a zero record with E_UNSUPPORTED, the cause mask and the named reason of the refusal."""
    try:
        refusal(tracker, observation)
        record = _record(tracker, observation)  # a field it cannot reproduce exactly refuses (Refusal) too
        return record, 0, 0, None
    except Refusal as r:
        return np.zeros((), dtype=_layout.PUBLIC_STATE), E_UNSUPPORTED, r.causes, r.reason


def _record(t, observation):
    head, size = t.data.record_head(t.record_kind)
    s = _State(size)
    s.bytes[:len(head)] = head
    player, foe = t.side, 1 - t.side
    boundary = int(observation["boundary_kind"])
    request_mask = sum(1 << side for side in (0, 1) if t._requested(side, boundary)[0])
    s.put("next_activation_id", t._next_activation)
    s.put("boundary", boundary)
    s.put("request_mask", request_mask)
    s.put("request_epoch", t.epoch)
    s.put("turn", t._turn)
    s.put("weather", t._weather)
    s.put("weather_turns", t._weather_turns)
    s.put("terrain", t._terrain)
    s.put("terrain_turns", t._terrain_turns)
    s.put("trick_room_turns", t._trick_room)
    leads = [PICK_NONE, PICK_NONE]
    for side in (0, 1):
        _side(t, s, side, side == player, boundary)
    if boundary != TEAM_SELECTION:
        leads = list(t._foe_leads)
    queue = 0
    if boundary == PIVOT:
        # a PIVOT the record supports has no MOVE left (refusal): the turn's residual is all its queue holds
        s.put("queue_len", 1)
        s.put("queue0.kind", Q_RESIDUAL)
        queue = 1
    if size > state_layout.V3_SIZE:
        _tail(t, s, boundary)
    rec = np.zeros((), dtype=_layout.PUBLIC_STATE)
    rec["revision"] = C["DUOFORGE_VIEW_REVISION"]
    rec["player"] = player
    rec["state_size"] = size
    rec["boundary"] = boundary
    rec["turn"] = t._turn
    rec["request_mask"] = request_mask
    rec["epoch"] = t.epoch
    rec["foe_seen_mask"] = _seen_mask(t, foe)
    rec["foe_leads"] = leads
    rec["queue_count"] = queue
    rec["state"][:size] = np.frombuffer(bytes(s.bytes), np.uint8)
    return rec


def _seen_mask(t, side):
    """The members of `side` its opponent has seen in battle."""
    return sum(1 << m for m, member in enumerate(t._member(side)) if member.seen)


def _side(t, s, side, own, boundary):
    pre = f"side{side}."
    members = t._member(side)
    s.put(pre + "member_count", len(members))
    order = [PICK_NONE] * 6
    if own:
        if t._picks is not None and boundary != TEAM_SELECTION:
            order[:len(t._picks)] = t._picks
            s.put(pre + "brought_mask", sum(1 << m for m in t._picks))
    elif boundary != TEAM_SELECTION:
        order[:2] = t._foe_leads
    s.put_list(pre + "brought_order", order)
    s.put(pre + "requested_slots", t._requested(side, boundary)[1])
    s.put(pre + "mega_used", t._mega_used[side])
    s.put(pre + "seen_mask", _seen_mask(t, 1 - side))
    reflect, light_screen, tailwind = t._conditions[side][:3]
    s.put(pre + "reflect_turns", reflect)
    s.put(pre + "light_screen_turns", light_screen)
    s.put(pre + "tailwind_turns", tailwind)
    for k, p in enumerate(t._positions[side]):
        _position(t, s, f"{pre}position{k}.", p, side, k, own)
    # side s's knowledge of the opposing members
    for m, member in enumerate(t._member(1 - side)):
        kpre = f"{pre}knowledge{m}."
        if member.seen:
            s.put(kpre + "hp_percent", member.hp_percent)
            s.put(kpre + "hp_flag", member.hp_flag)
        s.put(kpre + "revealed", member.revealed)
        s.put_list(kpre + "moves_used", (min(u, 255) for u in member.uses + [0] * (4 - len(member.uses))))
    for m, member in enumerate(members):
        _member(t, s, f"{pre}member{m}.", member, own)


def _position(t, s, pre, p, side, k, own):
    s.put(pre + "occupant", p.occupant)
    if p.occupant == OCCUPANT_NONE:
        s.put_list(pre + "stages", [STAGE_NEUTRAL] * 7)
        return
    s.put(pre + "activation", p.activation)
    s.put_list(pre + "stages", p.stages)
    flags = 0
    if p.protecting:
        flags |= VOL_PROTECT
    if p.flash_fire:
        flags |= VOL_FLASH_FIRE
    if p.flags & _tracker.FLAG_FOLLOW_ME:
        flags |= VOL_FOLLOW_ME
    if p.flags & _tracker.FLAG_HELPING_HAND:
        flags |= VOL_HELPING_HAND
    if p.flags & _tracker.FLAG_UNBURDEN:
        flags |= VOL_UNBURDEN
    if p.choice_slot != _tracker.MOVE_SLOT_NONE:
        flags |= VOL_CHOICE_LOCK
    if p.newly_switched and t.data.kind == "pool":
        flags |= VOL_NEWLY_SWITCHED
    s.put(pre + "flags", flags)
    s.put(pre + "stall_level", p.chain)
    s.put(pre + "stall_turns", p.stall)
    s.put(pre + "charge_turns", p.charge)
    if p.charge:
        s.put(pre + "locked_move", p.locked_slot + 1)
        s.put(pre + "locked_target", p.locked_target if own else C["DUOFORGE_VIEW_HIDDEN_TARGET"])
    elif p.choice_slot != _tracker.MOVE_SLOT_NONE:
        s.put(pre + "locked_move", p.choice_slot + 1)
    s.put(pre + "move_actions", min(p.move_actions, 255))
    # switch_flag: a PIVOT shows why a position must switch; a REPLACEMENT carries no flags (its request names the
    # positions, src/combat/turn.c dfi_finish_turn), a pass keeps a flag only while its side can still answer, which asks
    # it again (dfi_pivot_pending: a PIVOT), and a TURN follows only when no flag is left
    if t.boundary() == PIVOT and not p.fainted:
        s.put(pre + "switch_flag", p.flag)  # a fainted position's flag goes at the PIVOT (dfi_pivot)


def _member(t, s, pre, member, own):
    sheet = member.sheet
    count = len(sheet["moves"])
    s.put(pre + "species", sheet["species"])
    if own:
        s.put(pre + "hp", member.hp)
        s.put(pre + "hp_max", member.hp_max)
        s.put_list(pre + "stats", member.stats, width=2)
        s.put_list(pre + "stat_points", sheet["sp"])
    s.put(pre + "move_count", count)
    s.put(pre + "mega_capable", 1 if member.mega_capable else 0)
    s.put(pre + "is_mega", member.is_mega)
    s.put(pre + "gender", sheet["gender"])
    s.put(pre + "nature", sheet["nature"])
    s.put(pre + "status", member.status)
    s.put(pre + "status_counter", member.freeze_turns)
    s.put(pre + "item", sheet["item"])
    s.put(pre + "item_consumed", member.item_consumed)
    s.put(pre + "ability", member.ability)
    for k in range(count):
        mpre = f"{pre}move{k}."
        s.put(mpre + "move_id", sheet["moves"][k])
        if own:
            s.put(mpre + "pp", member.pp_max[k] - member.uses[k])
        s.put(mpre + "pp_max", member.pp_max[k])


def neutral_hypotheses(record, brought):
    """Hypotheses for a world of `record` that draw nothing in particular, for check(): the middle word of every uniform,
    the foe's pick order of `brought` members (the leads, then the members seen, then the others in roster order; none at
    team preview), and zero stat points but for the HP points of each foe member whose shown HP carries a colour flag
    (an exact share of its maximum HP, which only some maxima have): each of 0 to 4 in turn. The round trip holds for
    every hypothesis the record allows; the engine refuses one that contradicts the record (E_INVALID_ARGUMENT)."""
    import itertools
    from duoforge import view
    size = int(record["state_size"])
    state = bytes(record["state"][:size])
    player, foe = int(record["player"]), 1 - int(record["player"])
    members = state[_FIELDS[f"side{foe}.member_count"][0]]
    base = view.hypotheses(1)
    for name in ("hp", "sleep", "confusion", "charge_target"):
        base[name] = 1 << 63
    flagged = []
    if int(record["boundary"]) != TEAM_SELECTION:
        order = [int(m) for m in record["foe_leads"] if int(m) != PICK_NONE]
        order += [m for m in range(members) if int(record["foe_seen_mask"]) >> m & 1 and m not in order]
        order += [m for m in range(members) if m not in order]
        base["pick_order"][0, :brought] = order[:brought]
        flagged = [m for m in range(members) if int(record["foe_seen_mask"]) >> m & 1
                   and state[_FIELDS[f"side{player}.knowledge{m}.hp_flag"][0]]]
    for points in itertools.product(range(5), repeat=len(flagged)):
        h = base.copy()
        for m, v in zip(flagged, points):
            h["stat_points"][0, m, 0] = v
        yield h


def check(worlds, record, brought):
    """The engine's check of an assembled record: a world built from it and a neutral hypothesis
    (duoforge_battle_from_view; the first of neutral_hypotheses the engine accepts) gives it back byte for byte
    (duoforge_battle_public). worlds: a duoforge.Batch of the record's context whose environment 0 is overwritten.
    Returns (status, fields): the from_view or public status (0 when both succeed) and the differing header and state
    fields (state_layout names; [] when byte-identical, None when a call refused)."""
    invalid = C["DUOFORGE_E_INVALID_ARGUMENT"]
    status = invalid
    for h in neutral_hypotheses(record, brought):
        status = int(worlds.from_view(np.asarray(record).reshape(1), h, 1)[0])
        if status != invalid:
            break
    if status:
        return status, None
    players = np.zeros(worlds.envs, np.uint32)
    players[0] = int(record["player"])
    again, statuses = worlds.public(players)
    if int(statuses[0]):
        return int(statuses[0]), None
    again = again[0]
    header = [n for n in record.dtype.names if n not in ("state", "pad") and not np.array_equal(record[n], again[n])]
    size = int(record["state_size"])
    return 0, header + state_layout.diff(bytes(record["state"][:size]), bytes(again["state"][:size]),
                                         pool=size > state_layout.V3_SIZE)


def _party_bytes(entries):
    """party_order's 3 bytes of one side: entry k (roster index + 1, or DFI_PARTY_HIDDEN) at bits 3k..3k+2."""
    value = 0
    for k, entry in enumerate(entries):
        value |= entry << (3 * k)
    return list(value.to_bytes(3, "little"))


def _tail(t, s, boundary):
    """The POOL kinds' tail (src/codec/state_codec.c dfi_encode_tail) of what the tracker folds."""
    party = []
    for side in (0, 1):
        entries = [0] * 6
        if side == t.side:
            if t._party is not None and boundary != TEAM_SELECTION:
                entries[:len(t._party)] = [m + 1 for m in t._party]
        else:
            entries[:2] = [p.occupant + 1 if p.occupant != OCCUPANT_NONE else 0 for p in t._positions[side]]
            entries[2:] = [PARTY_HIDDEN] * 4
        party += _party_bytes(entries)
    s.put_list("tail.field.party_order", party)
    for side in (0, 1):
        pre = f"tail.side{side}."
        s.put(pre + "aurora_veil_turns", t._conditions[side][3])
        members = t._member(side)
        for k, p in enumerate(t._positions[side]):
            if p.occupant == OCCUPANT_NONE:
                continue
            ppre = f"{pre}position{k}."
            if p.result_now is None or p.result_last is None:
                raise Refusal("move-result-not-determined")  # the library could not tell an action's result from its events
            s.put(ppre + "move_result", move_result_byte(p.result_now, p.result_last))
            if p.last_slot is None:
                raise Refusal("last-move-not-on-sheet")  # the move of its last line is on no slot of its sheet
            s.put(ppre + "last_move", p.last_slot)
            s.put(ppre + "encore_slot", p.encore_slot)
            s.put(ppre + "encore_turns", p.encore_turns)
            s.put(ppre + "throat_chop_turns", p.throat_chop)
            s.put(ppre + "perish", p.perish)
            s.put(ppre + "hits_taken", p.hits_taken)
            s.put(f"tail5.position{side * 2 + k}.position_flags", POSFLAG_STATS_RAISED if p.raised else 0)
            if p.ability_now:
                s.put(f"{pre}member{p.occupant}.ability_now", p.ability_now)
        for m, member in enumerate(members):
            s.put(f"{pre}member{m}.item_now", member.item_now)
            s.put(f"{pre}member{m}.toxic_stage", member.toxic_stage)
