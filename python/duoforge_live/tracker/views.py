"""The output at a decision point: observation, its extension, the domain and the public parts.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

import numpy as np

from duoforge import _layout
from duoforge._state_layout import VALUES as _ENC

from .. import lines, options
from .constants import (ACTIVE, _ATTRACT_SOURCE_SHIFT, BENCH, C, EXT2_TRAP_ELAPSED, EXT_FIELDS, EXT_REVISION,
                        FLAG_UNBURDEN, _HAZARD, HP_EXACT, HP_PERCENT, HP_UNKNOWN, ITEM_NOW_NONE, _LOCKED_MOVE,
                        MOVE_SLOT_NONE, NOT_BROUGHT, PIVOT, PP_DERIVED, PP_EXACT, _PRESENCE_BITS, REPLACEMENT,
                        ROSTER_NONE, STAGE_NEUTRAL, TARGET_NONE, TEAM_SELECTION, TURN, UNDETERMINED)


class _Views:
    # ------------------------------------------------------------------ output
    def boundary(self):
        r = self.request
        if r.get("teamPreview"):
            return TEAM_SELECTION
        if "active" in r:
            return TURN
        return REPLACEMENT if "|upkeep" in self._step_lines else PIVOT

    def _requested(self, side, boundary):
        """(requested, requested slots) of a side at the decision point."""
        r = self.request
        if side == self.side:
            if r.get("wait"):
                return 0, 0
            if boundary == TEAM_SELECTION:
                return 1, 0
            if boundary == TURN:
                return 1, self._occupied(side)
            return 1, sum(1 << k for k, flag in enumerate(r["forceSwitch"]) if flag)
        if boundary == TEAM_SELECTION:
            return 1, 0
        if boundary == TURN:
            return 1, self._occupied(side)
        slots = self._foe_switch_slots(side, boundary)
        return (1, slots) if slots else (0, 0)

    def _occupied(self, side):
        return sum(1 << k for k, p in enumerate(self._positions[side]) if p.occupant != ROSTER_NONE)

    def _foe_switch_slots(self, side, boundary):
        """The foe positions asked to switch (src/combat/turn.c dfi_finish_turn, dfi_pivot): the flagged ones
        (a faint at the end of the turn, Emergency Exit, Parting Shot); a fainted one and any at a PIVOT only
        while the foe has a reserve (brought, unseen or on the bench, standing)."""
        members = self._member(side)
        gone = sum(1 for m in members if m.seen and m.hp_percent == 0)
        standing = sum(1 for p in self._positions[side] if p.occupant != ROSTER_NONE and not p.fainted)
        brought = self._teamsize[side]
        if brought is None:
            raise ValueError("no |teamsize| line for the foe")
        reserve = brought - gone - standing > 0
        out = 0
        for k, p in enumerate(self._positions[side]):
            if p.occupant == ROSTER_NONE or not p.flag:
                continue
            # Revival Blessing's request is made with no check of a living reserve (src/combat/turn.c: the revive answers it)
            if reserve or (boundary == REPLACEMENT and not p.fainted) or p.flag == _ENC["DFI_SWITCH_REVIVE_BLESSING"]:
                out |= 1 << k
        return out

    def observation(self):
        """The OBSERVATION record DuoForge shows this player at the current decision point."""
        if not self.ready:
            raise ValueError("no decision point")
        o = np.zeros((), dtype=_layout.OBSERVATION)
        boundary = self.boundary()
        o["epoch"], o["boundary_kind"], o["player"] = self.epoch, boundary, self.side
        requested, slots = self._requested(self.side, boundary)
        o["requested"], o["slot_mask"] = requested, slots
        o["turn"] = self._turn
        o["weather"], o["weather_turns"] = self._weather, self._weather_turns
        o["terrain"], o["terrain_turns"] = self._terrain, self._terrain_turns
        o["trick_room_turns"] = self._trick_room
        for side in (0, 1):
            self._view_side(o["sides"][side], side, boundary)
        return o

    def _shown_locked_slot(self, p, own):
        """The locked slot the view shows: a running two-turn move's or a Choice lock's, but none for a foe whose last
        move is a lockedmove, whose drawn length may end silently (src/state/observation.c, dfi_maybe_lockedmove), unless
        a Choice item locks the same move (decision 0083: the Choice lock still names its slot)."""
        if not own and p.choice_slot == MOVE_SLOT_NONE and p.last_move is not None and \
                self.data.move_flags(p.last_move) & _LOCKED_MOVE:
            return MOVE_SLOT_NONE
        return p.locked_slot if p.locked_slot != MOVE_SLOT_NONE else p.choice_slot

    def _view_side(self, v, side, boundary):
        own = side == self.side
        members = self._member(side)
        v["member_count"] = len(members)
        for m, member in enumerate(members):
            self._view_member(v["members"][m], member, m, side, own, boundary)
        for k, p in enumerate(self._positions[side]):
            pv = v["positions"][k]
            pv["locked_slot"], pv["locked_target"] = MOVE_SLOT_NONE, TARGET_NONE
            if p.occupant == ROSTER_NONE:
                pv["stages"] = [STAGE_NEUTRAL] * 7
                continue
            pv["stages"] = p.stages
            pv["confused"], pv["charging"] = p.confused, 1 if p.charge else 0
            pv["locked_slot"] = self._shown_locked_slot(p, own)
            holder = members[p.occupant]
            gone = holder.item_used or holder.item_now == ITEM_NOW_NONE
            # Unburden doubles the Speed only while the item is gone: an item a move gave hides the flag
            pv["reserved"] = p.flags if gone else p.flags & ~FLAG_UNBURDEN
            if own and p.charge:
                pv["locked_target"] = p.locked_target
            pv["acted"], pv["protect_chain"] = p.acted, p.chain
            pv["flash_fire"], pv["protecting"] = p.flash_fire, p.protecting
        v["occupant"] = [p.occupant for p in self._positions[side]]
        v["mega_used"] = self._mega_used[side]
        order = [ROSTER_NONE] * 6
        if own and self._picks is not None:
            order[:len(self._picks)] = self._picks
        v["brought_order"] = order
        requested, slots = self._requested(side, boundary)
        v["requested"], v["requested_slots"] = requested, slots
        v["reflect_turns"], v["light_screen_turns"], v["tailwind_turns"] = self._conditions[side][:3]

    def _view_member(self, v, member, m, side, own, boundary):
        sheet = member.sheet
        count = len(sheet["moves"])
        v["species_id"] = sheet["species"]  # the set's species; a Mega Evolution shows as is_mega
        v["move_count"] = count
        v["mega_capable"] = 1 if member.mega_capable else 0
        v["gender"], v["nature"] = sheet["gender"], sheet["nature"]
        v["ability"], v["item"] = member.ability, sheet["item"]
        v["move_ids"][:count] = sheet["moves"]
        v["pp_max"][:count] = member.pp_max
        # item_used: the sheet's item is gone (a member without one has none to lose, whatever it got and used since)
        v["is_mega"], v["item_used"] = member.is_mega, member.item_used if sheet["item"] else 0
        active = any(p.occupant == m for p in self._positions[side])
        if own:
            v["hp"], v["hp_max"], v["hp_kind"], v["pp_kind"] = member.hp, member.hp_max, HP_EXACT, PP_EXACT
            v["pp"][:count] = [mx - u for mx, u in zip(member.pp_max, member.uses)]
            v["stats"] = member.stats
            v["stat_points"] = sheet["sp"]
            v["status"] = member.status if member.hp != 0 else 0
            if boundary == TEAM_SELECTION:
                v["location"] = UNDETERMINED
            elif active:
                v["location"] = ACTIVE
            elif self._picks is not None and m in self._picks:
                v["location"] = BENCH
            else:
                v["location"] = NOT_BROUGHT
            return
        v["pp_kind"] = PP_DERIVED
        v["pp"][:count] = [max(mx - u, 0) for mx, u in zip(member.pp_max, member.uses)]
        if member.seen:
            v["hp"], v["hp_flag"], v["hp_max"], v["hp_kind"] = member.hp_percent, member.hp_flag, 100, HP_PERCENT
            v["location"] = ACTIVE if active else BENCH
            v["status"] = member.status if member.hp_percent != 0 else 0
        else:
            v["hp_kind"], v["location"] = HP_UNKNOWN, UNDETERMINED

    def request_record(self):
        """The REQUEST record of the decision point as the engine sets it (duoforge_battle_request): the epoch, the
        boundary, the player, whether it is requested and the positions that need a command. candidate_count stays 0: the
        engine's joint domain excludes pairs by rules the tracker does not hold (its domain() pair mask is provisional), and
        the honest search does not read it."""
        if not self.ready:
            raise ValueError("no decision point")
        r = np.zeros((), dtype=_layout.REQUEST)
        boundary = self.boundary()
        requested, slots = self._requested(self.side, boundary)
        r["epoch"], r["boundary_kind"], r["player"] = self.epoch, boundary, self.side
        r["requested"], r["slot_mask"] = requested, slots
        return r

    def public_parts(self):
        """The player's parts of the decision point for the honest search (duoforge_search.record_roots.RecordRoots):
        dict(request, observation, record, status, causes, reason). record is the public record assembled from what the
        tracker folded (record.assemble) with status 0, or a zero record with status E_UNSUPPORTED, the cause mask that
        duoforge_battle_public_causes gives (0 for a refusal without a cause bit) and the named reason. An expected refusal
        never raises; the engine checks an assembled record (record.check, and the search's own round trip)."""
        from .. import record
        observation = self.observation()
        rec, status, causes, reason = record.assemble(self, observation)
        return {"request": self.request_record(), "observation": observation, "record": rec, "status": status,
                "causes": causes, "reason": reason}

    def observation_ext(self):
        """The OBSERVATION_EXT record (decision 0018) DuoForge shows this player at the current decision point: the
        fields of the features this tracker folds (EXT_FIELDS), from the public lines; all zero under a kind without
        the extension (not POOL), as duoforge_battle_observe_ext gives it."""
        if not self.ready:
            raise ValueError("no decision point")
        o = np.zeros((), dtype=_layout.OBSERVATION_EXT)
        if self.data.kind != "pool":
            return o
        o["revision"], o["player"], o["epoch"] = EXT_REVISION, self.side, self.epoch
        o["supported"] = lines.LIBRARY_SUPPORTED
        for side in (0, 1):
            v = o["sides"][side]
            v["aurora_veil_turns"] = self._conditions[side][3]
            v["guard_flags"] = C["DUOFORGE_SIDE_GUARD_WIDE_GUARD"] if ("WIDE_GUARD", side) in self._guards else 0
            for field, _ in _HAZARD.values():
                v[field] = self._hazards[side][field]
            for m, member in enumerate(self._member(side)):
                v["members"][m]["item_now"] = member.item_now
            for k, p in enumerate(self._positions[side]):
                if p.occupant == ROSTER_NONE:
                    continue  # an empty position: all zero
                pv = v["positions"][k]
                pv["volatiles"] = sum(bit for name, bit in _PRESENCE_BITS if getattr(p, name))
                if p.type_now != (0, 0):
                    pv["volatiles"] |= C["DUOFORGE_POSITION_EXT_TYPE_CHANGED"]
                    pv["type_now"] = p.type_now
                pv["perish"], pv["encore_slot"], pv["disable_slot"] = p.perish, p.encore_slot, p.disable_slot
                if p.trap:  # POSITION_EXT2 bits 4 to 6: the elapsed count (zero without the trap)
                    o["volatiles2"][side][k] = sum(bit for n, bit in enumerate(EXT2_TRAP_ELAPSED) if p.trap_elapsed >> n & 1)
                own = self._member(side)[p.occupant].ability
                pv["ability_now"] = p.ability_now if p.ability_now != own else 0  # shown when it differs
                if p.attract:
                    o["volatiles2"][side][k] |= p.attract_from << _ATTRACT_SOURCE_SHIFT
        return o

    def domain(self):
        """The FACTORED_DOMAIN of the decision point (the provisional pair mask), and the slot lists."""
        r = self.request
        if r.get("wait"):
            return options.none_domain(self.epoch), None
        if r.get("teamPreview"):
            return options.team_domain(self.epoch, len(self.own_sheets), r["maxChosenTeamSize"]), None
        locked = {k: p.locked_target for k, p in enumerate(self._positions[self.side]) if p.charge}
        roster_of = {mon["ident"]: self._names[self.side][mon["ident"].split(": ", 1)[1]]
                     for mon in r["side"]["pokemon"]}
        lists = options.slot_options(r, self.side, roster_of, locked)
        return options.domain(lists, self.epoch), lists


def restrict_ext(ext, folds):
    """DuoForge's OBSERVATION_EXT record `ext` as a tracker that folds the features of the mask `folds` shows it: the
    header (revision, player, epoch, supported) and the EXT_FIELDS of those features, everything else zero. KeyError
    for a feature of the mask without an EXT_FIELDS entry."""
    out = np.zeros((), dtype=_layout.OBSERVATION_EXT)
    for name in ("revision", "player", "epoch", "supported"):
        out[name] = ext[name]
    for name, bit in lines.FEATURES.items():
        if not folds >> bit & 1:
            continue
        for where, field in EXT_FIELDS[name]:
            for s in (0, 1):
                src, dst = ext["sides"][s], out["sides"][s]
                if where == "bit":
                    dst["positions"]["volatiles"] = dst["positions"]["volatiles"] | (src["positions"]["volatiles"] & field)
                elif where == "v2bits":
                    out["volatiles2"][s] = out["volatiles2"][s] | (ext["volatiles2"][s] & field)
                elif where == "side_bit":
                    name, bit = field
                    dst[name] = dst[name] | (src[name] & bit)
                elif where == "side":
                    dst[field] = src[field]
                elif where == "global":
                    out["field"][field] = ext["field"][field]
                else:
                    group = "positions" if where == "position" else "members"
                    dst[group][field] = src[group][field]
    return out
