"""The protocol of one battle room folded into DuoForge's observation.

A Tracker follows what one player receives (spec section 6) and builds, at
each decision point, the OBSERVATION record DuoForge would show that player
(decision 0007). It implements no battle rule: every battle line goes through
the converter's own parser (trace_to_c.step_events, which raises on a line it
does not know), and the events are folded into the fields the observation
reads. The test duoforge.python.live proves the result equal to DuoForge's
observation, byte for byte, at every request of every committed closure
battle; the field sources are in the plan's Task 5 table.

Decision points: at the pin a step's update comes before its requests
(Battle.sendUpdates), so a |request| with a new rqid is a decision point over
the battle lines received since the previous one. At team preview it waits
for the |showteam| lines of both sides. An updated request (update: true)
comes after Showdown refused a choice the request did not rule out (a switch
of a hidden-trapped last active: Side.emitChoiceError, sim/side.ts:527-534):
the current move request again, under a new rqid, with what the refusal
revealed. No battle line comes between, so it is a new request epoch of the
same decision point: the state stays, the options follow the update.

The public record (public_parts, record.py; M12 option A): the tracker also
folds the public facts the canonical public record holds and its views do not
(entry activation ids, move actions since entry, the opponent's knowledge of
each own member, revealed facts, a freeze's turns, the foe's leads), and
record.assemble serialises them. duoforge.python.live proves the record equal
to the engine's at every decision point of every committed closure battle, or
refused with the engine's status and cause mask.

The package (restructure step 7) splits the former tracker.py by fold family: constants (the constants and
tables), state (_Position, _Member), core (Tracker: input and the battle line), conditions, sheets, requests,
events, fold_event (_fold_event), actions and views (the output), each family a mixin of Tracker. This module
re-exports every name the former module had, so `from duoforge_live.tracker import X` and `tracker.X` keep
working. Each submodule binds the constants it reads: to patch one in a test, patch it where it is read
(or mutate the object); rebinding `tracker.X` reaches no submodule.
"""

import collections
import json

import numpy as np

from duoforge import _layout
from duoforge._state_layout import VALUES as _ENC

from .. import lines, options, teams
from ..data import trace_to_c
from .constants import (ACTIVE, ALLY_SWITCH_LEVEL_MAX, ALLY_SWITCH_TURNS, _ATTRACT_SOURCE_BITS, _ATTRACT_SOURCE_SHIFT,
                        BENCH, C, CHARGE_TURNS, DIRECT_COST_MOVES, DISABLE_TURNS, ENCORE_TURNS, EV, EXT2_TRAP_ELAPSED,
                        EXT_CURSE, EXT_FIELDS, EXT_REVISION, EXT_THROAT_CHOP, FIELD_TURNS, FIELD_TURNS_EXTENDED, FLAG,
                        FLAG_FOLLOW_ME, FLAG_HELPING_HAND, FLAG_UNBURDEN, FREEZE_TURNS, _HAZARD, HEAL_BLOCK_TURNS,
                        _HIT_PIVOTS, HITS_TAKEN_MAX, HP_EXACT, HP_PERCENT, HP_UNKNOWN, ITEM_NOW_NONE, _kind,
                        _LOCKED_MOVE, _MOVE_PIVOTS, MOVE_SLOT_NONE, _MUST_PRESSURE, NOPOS, NOT_BROUGHT, _PASSED, PIVOT,
                        PP_DERIVED, PP_EXACT, _PRESENCE_BITS, REPLACEMENT, REVEALED_ITEM_CONSUMED, REVEALED_MEGA,
                        ROOM_LINES, ROSTER_NONE, SCREEN_EXTENDER, SCREEN_TURNS, SCREEN_TURNS_CLAY, SESSION_LINES,
                        _SIDE_CONDITION, SPECTATOR, STAGE_NEUTRAL, STALL_DURATION, STALL_LEVEL_MAX, STATUS,
                        SWITCH_EMERGENCY_EXIT, SWITCH_FAINTED, SWITCH_MOVE, TAILWIND_TURNS, TARGET_NONE, TAUNT_TURNS,
                        TEAM_SELECTION, _TERRAIN, TERRAIN_EXTENDER, THROAT_CHOP_TURNS, TOXIC_STAGE_MAX,
                        TRAP_ELAPSED_MAX, TURN, UNDETERMINED, _WEATHER_ROCK, YAWN_TURNS)
from .core import Tracker
from .state import _condition, _Member, _Position, SheetContradiction, _SWAP_MOVES, _SWAP_SLOT
from .views import restrict_ext
