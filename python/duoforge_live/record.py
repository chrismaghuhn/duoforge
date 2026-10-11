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

The engine decides every refusal of its own, and checks every record: the causes that the player's observation decides
come from duoforge_observation_causes (the one predicate of src/state/view.c, the part the observation carries), and an
assembled record goes through duoforge_public_record_check (a world built from it must give it back byte for byte:
duoforge_battle_from_view, then duoforge_battle_public). A PIVOT's record carries its queue (the MOVE actions still to run,
the foe's command hidden, and the residual), so the engine refuses a PIVOT before the moves or with a move left, a
possible lockedmove and the Revival Blessing proxy itself (E_UNSUPPORTED, reason engine-refuses-record); a filled masked
field or a contradiction (E_MALFORMED) is an assembler error and raises. Python holds no copy of the predicate.

The tracker refuses, with a named reason, only a record that the engine has and the lines do not determine:
unburden-without-item-line, last-move-not-on-sheet, own-command-unknown, and move-result-not-determined (the library
cannot tell an action's result from its events). The POOL tail's move_result is the library's classification of each move
action's events (duoforge_move_result, the engine's rule; the tracker only collects the events); its other fields are the
tracker's folds (party order, Aurora Veil, the position counters, item_now, the toxic stage, the raised flag, and the
view-extension folds of #342: the entry hazards and their creation order, Wide Guard, Taunt, Heal Block, Yawn and Disable
with their counts, Imprison, the recharge, Glaive Rush, Rage Powder's Follow Me flag, the type Soak or Double Shock set, and
Attract's source of each infatuated position (the tail5 reserve bytes, step G71)).
The features the tracker does not fold stop it at their lines (lines.check) before a record could need them.
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
Q_RESIDUAL, Q_MOVE = VALUES["DFI_Q_RESIDUAL"], VALUES["DFI_Q_MOVE"]
PICK_NONE = C["DUOFORGE_VIEW_PICK_NONE"]
OCCUPANT_NONE = VALUES["DFI_OCCUPANT_NONE"]
STAGE_NEUTRAL = VALUES["DFI_STAGE_NEUTRAL"]
VOL_PROTECT, VOL_FLASH_FIRE = VALUES["DFI_VOL_PROTECT"], VALUES["DFI_VOL_FLASH_FIRE"]
VOL_FOLLOW_ME, VOL_HELPING_HAND, VOL_UNBURDEN = (VALUES[f"DFI_VOL_{n}"] for n in ("FOLLOW_ME", "HELPING_HAND", "UNBURDEN"))
VOL_CHOICE_LOCK, VOL_NEWLY_SWITCHED = VALUES["DFI_VOL_CHOICE_LOCK"], VALUES["DFI_VOL_NEWLY_SWITCHED"]
PARTY_HIDDEN = VALUES["DFI_PARTY_HIDDEN"]
POSFLAG_STATS_RAISED = VALUES["DFI_POSFLAG_STATS_RAISED"]
POSFLAG_HEALING_WISH = VALUES["DFI_POSFLAG_HEALING_WISH"]  # G82: the slot's pending Healing Wish (decision 0045)
POSFLAG_LOWERED, POSFLAG_HURT = VALUES["DFI_POSFLAG_LOWERED"], VALUES["DFI_POSFLAG_HURT"]  # step G88 (decision 0046)
POSFLAG_CURSED = VALUES["DFI_POSFLAG_CURSED"]  # step G84b (decision 0063): the Ghost Curse's volatile, bit 7
# the position flags the states of a kind may carry (dfi_kind_limits_of: the POOL kinds add theirs), by table kind
VOL_FLAGS_MASK = {"closure": VALUES["VOL_FLAGS_MASK_CLOSURE"], "pool": VALUES["VOL_FLAGS_MASK_POOL"]}
MR_UNCLASSIFIED_NOW, MR_UNCLASSIFIED_LAST = VALUES["DFI_MOVE_RESULT_UNCLASSIFIED_NOW"], VALUES["DFI_MOVE_RESULT_UNCLASSIFIED_LAST"]
MR_VALUE_MASK, MR_LAST_SHIFT = VALUES["DFI_MOVE_RESULT_VALUE_MASK"], VALUES["DFI_MOVE_RESULT_LAST_SHIFT"]
TAIL_FLAG, WIDE_GUARD = VALUES["DFI_TAIL_FLAG_MAX"], VALUES["DFI_TAIL_WIDE_GUARD_MAX"]  # the 0/1 tail bytes when set
TYPE_TYPELESS = VALUES["DFI_TAIL_TYPE2_TYPELESS"]  # soak_type of Double Shock's ??? slot
# the tail's hazard kind of each hazard field (DFI_HAZARD_*, 2 bits per slot of hazard_order)
_HAZARD_KIND = {field: VALUES[f"DFI_HAZARD_{field.upper()}"] for field in
                ("stealth_rock", "spikes", "toxic_spikes", "sticky_web")}
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


CAUSE_NAMES = ((CAUSE_SLEEP, "visible-sleep"), (CAUSE_CONFUSION, "visible-confusion"),
               (CAUSE_ILLUSION, "illusion-possible"), (CAUSE_RAISED, "raised-this-turn"))


def tracker_refusal(tracker):
    """The tracker's own refusal of a decision point whose record the engine has but the lines do not determine, or None."""
    if any(p.unburden_unseen for side in tracker._positions for p in side):
        return "unburden-without-item-line"  # the volatile may be up with no line (tracker, Knock Off)
    return None


def move_result_of(data, user, events):
    """The result of one move action (the POOL tail's move_result of this turn: DFI_MOVE_RESULT_* with
    DFI_MOVE_RESULT_UNCLASSIFIED_NOW), classified by the library from the action's events (duoforge.view.move_result,
    the engine's rule); None where the events do not determine it. An event whose position the log does not name (an
    [of] without its slot: Shell Bell after a hit that made its target faint) leaves the result undetermined too: the
    library takes no unknown position."""
    from duoforge import view
    if any(field is None for e in events for field in e):
        return None
    return view.move_result(data.context(), user, events)


def move_result_byte(now, last):
    """The tail's move_result byte of this turn's and last turn's results (each a value with its unclassified bit, in this
    turn's form: DFI_MOVE_RESULT_UNCLASSIFIED_NOW): this turn in the low bits and UNCLASSIFIED_NOW, last turn shifted by
    DFI_MOVE_RESULT_LAST_SHIFT and UNCLASSIFIED_LAST."""
    return ((now & MR_VALUE_MASK) | (now & MR_UNCLASSIFIED_NOW) | ((last & MR_VALUE_MASK) << MR_LAST_SHIFT)
            | (MR_UNCLASSIFIED_LAST if last & MR_UNCLASSIFIED_NOW else 0))


def assemble(tracker, observation):
    """(record, status, causes, reason) at the tracker's current decision point: the PUBLIC_STATE record and status 0,
    or a zero record with E_UNSUPPORTED, the cause mask and the named reason of the refusal. The engine decides every
    refusal of its own: the causes from the observation (duoforge_observation_causes, the one predicate's part that the
    observation decides), then the assembled record's verdict (duoforge_public_record_check: from_view, then public); the
    tracker adds only the refusals of a record the lines do not determine. A record the engine does not take back for
    another reason (a filled masked field, a contradiction) is an assembler error: ValueError."""
    from duoforge import _lib, view
    zero = np.zeros((), dtype=_layout.PUBLIC_STATE)
    ctx = tracker.data.context_of(tracker.record_kind)
    causes = view.observation_causes(ctx, observation)
    if causes:
        return zero, E_UNSUPPORTED, causes, ",".join(name for bit, name in CAUSE_NAMES if causes & bit)
    try:
        record = _record(tracker, observation)  # a field it cannot reproduce exactly refuses (Refusal) too
    except Refusal as r:
        return zero, E_UNSUPPORTED, r.causes, r.reason
    status = view.public_record_check(ctx, record)
    if status == E_UNSUPPORTED:
        return zero, E_UNSUPPORTED, 0, "engine-refuses-record"
    if status != 0:
        raise ValueError(f"the engine does not take the assembled record back: {_lib.status_name(status)}")
    reason = tracker_refusal(tracker)
    if reason is not None:
        return zero, E_UNSUPPORTED, 0, reason
    return record, 0, 0, None


def _record(t, observation):
    head, size = t.data.record_head(t.record_kind)
    s = _State(size)
    s.bytes[:len(head)] = head
    player, foe = t.side, 1 - t.side
    boundary = int(observation["boundary_kind"])
    request_mask = sum(1 << side for side in (0, 1) if t._requested(side, boundary)[0])
    if boundary == PIVOT and request_mask == 0:
        raise Refusal("pivot-switch-reason-unknown")  # a PIVOT asks someone: the lines did not show the tracker whom
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
    queue, pending = 0, 0
    if boundary == PIVOT:
        # the turn's queue at a PIVOT, in its canonical order (kind, side, slot): the MOVE actions still to run (the own
        # command the player accepted; the foe's hidden), then the residual. The engine refuses a PIVOT with a move left.
        for side in (0, 1):
            for k, p in enumerate(t._positions[side]):
                if not p.move_queued:
                    continue
                qpre = f"queue{queue}."
                s.put(qpre + "kind", Q_MOVE)
                s.put(qpre + "side", side)
                s.put(qpre + "slot", k)
                s.put(qpre + "activation_id", p.activation)
                if side == player:
                    command = (t._accepted_commands or [None, None])[k]
                    if command is None:
                        raise Refusal("own-command-unknown")  # the accepted choice names no option of the request
                    s.put(qpre + "move_slot", command.move_slot)
                    s.put(qpre + "target", command.target)
                else:
                    s.put(qpre + "move_slot", C["DUOFORGE_VIEW_HIDDEN"])
                    s.put(qpre + "target", C["DUOFORGE_VIEW_HIDDEN_TARGET"])
                    pending |= 1 << k
                queue += 1
        s.put(f"queue{queue}.kind", Q_RESIDUAL)
        queue += 1
        s.put("queue_len", queue)
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
    rec["foe_pending_mask"] = pending
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
    if p.flags & _tracker.FLAG_FOLLOW_ME or p.rage_powder:
        flags |= VOL_FOLLOW_ME  # Rage Powder sets the same flag (dfi_run_follow_me); the observation tells them apart
    if p.flags & _tracker.FLAG_HELPING_HAND:
        flags |= VOL_HELPING_HAND
    if p.flags & _tracker.FLAG_UNBURDEN:
        flags |= VOL_UNBURDEN
    if p.choice_slot != _tracker.MOVE_SLOT_NONE:
        flags |= VOL_CHOICE_LOCK
    carried = VOL_FLAGS_MASK[t.data.kind]
    if p.newly_switched and carried & VOL_NEWLY_SWITCHED:
        flags |= VOL_NEWLY_SWITCHED  # the closure kind's states carry no newlySwitched flag (dfi_kind_limits_of)
    if flags & ~carried:
        raise ValueError(f"{pre}flags {flags:#x}: bits the {t.data.kind} kind's states do not carry ({carried:#x})")
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
    if t.boundary() == PIVOT and t._requested(side, PIVOT)[1] >> k & 1:
        if not p.flag:
            raise Refusal("pivot-switch-reason-unknown")  # asked to switch for a reason no line showed the tracker
        s.put(pre + "switch_flag", p.flag)  # the PIVOT asks exactly the flagged positions (dfi_pivot)


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


def check(context, record):
    """The engine's verdict on an assembled record (duoforge_public_record_check): 0 when a world of it gives it back byte
    for byte, E_UNSUPPORTED when the engine refuses it, E_MALFORMED for a filled masked field or a contradiction."""
    from duoforge import view
    return view.public_record_check(context, record)



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
    # Attract's source of each infatuated position (step G71, decision 0034): the rev 5 reserve bytes 0..3, by flat position
    # (side * 2 + slot), 1 + side * DUOFORGE_MAX_ROSTER + roster index of the holder; 0 where no infatuation stands
    attract = [0] * 4
    for side in (0, 1):
        for k, p in enumerate(t._positions[side]):
            attract[side * 2 + k] = p.attract
    s.put_list("tail5.attract_source", attract)
    # tail rev 5 (step G80): Ally Switch's counter per flat position, (level << 2) | turns, 0 = none
    s.put_list("tail5.ally_switch", [(p.ally_level << 2) | p.ally_turns if p.ally_level else 0
                                      for side in (0, 1) for p in t._positions[side]])
    for side in (0, 1):
        pre = f"tail.side{side}."
        s.put(pre + "aurora_veil_turns", t._conditions[side][3])
        s.put(pre + "wide_guard", WIDE_GUARD if ("WIDE_GUARD", side) in t._guards else 0)
        order = 0
        for n, (field, layers) in enumerate(t._hazards[side].items()):  # the kinds that are up, in creation order
            s.put(pre + field, layers)
            order |= _HAZARD_KIND[field] << (2 * n)
        s.put(pre + "hazard_order", order)
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
            s.put(ppre + "taunt_turns", p.taunt)
            s.put(ppre + "heal_block_turns", p.heal_block)
            s.put(ppre + "yawn_turns", p.yawn)
            s.put(ppre + "leech_seed_source", p.leech_source)
            s.put(ppre + "disable_slot", p.disable_slot)
            s.put(ppre + "disable_turns", p.disable_turns)
            for field in ("imprison", "must_recharge", "glaive_rush"):
                s.put(ppre + field, TAIL_FLAG if getattr(p, field) else 0)
            mpre = f"{pre}member{p.occupant}."
            if p.type_now != (0, 0):
                s.put(mpre + "soak_type", p.type_now[0] or TYPE_TYPELESS)  # Soak's type + 1, or Double Shock's ???
            s.put(mpre + "type2", p.type2)
            if p.trap:
                # the partial trap (step G90, decision 0060): the drawn turns are hidden for both viewers (src/state/view.c); the
                # source (0 once it left), the move, the band and the elapsed count are public
                s.put(ppre + "trap_turns", C["DUOFORGE_VIEW_HIDDEN"])
                s.put(ppre + "trap_source", p.trap_source)
                s.put(ppre + "trap_move", p.trap_move)
                s.put(ppre + "trap_band", p.trap_band)
                s.put(ppre + "trap_elapsed", p.trap_elapsed)
            s.put(f"tail5.position{side * 2 + k}.position_flags", (POSFLAG_STATS_RAISED if p.raised else 0) |
                  (POSFLAG_LOWERED if p.lowered else 0) | (POSFLAG_HURT if p.hurt else 0) |
                  (POSFLAG_HEALING_WISH if p.wish else 0) | (POSFLAG_CURSED if p.cursed else 0))
            if p.ability_now:
                s.put(f"{pre}member{p.occupant}.ability_now", p.ability_now)
        for m, member in enumerate(members):
            s.put(f"{pre}member{m}.item_now", member.item_now)
            s.put(f"{pre}member{m}.toxic_stage", member.toxic_stage)
