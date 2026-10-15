"""The options of an own decision point, from the engine (M11 spec section 8; #512 D7).

A replay has no request, so superset.domain() asks the engine for the one the
player received: the point's public record as the player held it
(duoforge_live.record.build over the spectator's folds; the own values the
log does not show come from hindsight and the prior, SpectatorTracker.own_values)
is built into a world (duoforge_battle_from_view) with a hypothesis that
draws nothing in particular: the foe's leads, then its members seen, then the
others in roster order as its picks, every word zero (where no HP of a seen
foe member shows its display under zero stat points, the HP stat points 1 to
32 are tried in turn, the engine deciding which fits). The world's factored
domain of the own side is the point's domain, pair mask included, and its slot
lists are those commands in the engine's order. Python decides no option: PP,
Encore, Disable, Struggle, Mega Evolution, a lock, a recharge, the reserves
and a Revival Blessing choice are the engine's rules over the record.

What the hypothesis draws (the foe's stat points, HP and counters) is hidden
from the player and decides none of the own options. The test
duoforge.python.replay compares the domain with DuoForge's own at every own
point of the committed battles.

A point whose record the lines do not determine (record.Refusal), whose
hypothesis this module does not draw (a foe move still queued at a PIVOT), or
whose world the engine refuses (a public cause, a display no hypothesis fits)
raises Refused with the reason: the point has no row and game._fold counts it.
There is no fallback.
"""
import numpy as np

import duoforge
from duoforge import _layout, view
from duoforge._lib import status_name
from duoforge_live import options, record

from .points import TEAM_SELECTION
from .spectator import Refused

__all__ = ["Refused", "domain"]

C = _layout.CONSTANTS
PIVOT = C["DUOFORGE_BOUNDARY_PIVOT"]
_WORLDS = {}  # id(context) -> (context, a one-world Batch of it)
MAX_STAT_POINTS = 32  # the stat points of one stat (duoforge_battle_from_view refuses a spread past 32)


def _batch(context):
    kept = _WORLDS.get(id(context))
    if kept is None or kept[0] is not context:
        kept = _WORLDS[id(context)] = (context, duoforge.Batch(context, duoforge.reference_setups([0]), 1, 0))
    return kept[1]


def _hypothesis(tracker, rec, brought_count):
    """The hypothesis that draws nothing in particular: the foe's picks are its leads, its members seen, then the others in
    roster order (none at team selection); a PIVOT's queue keeps its canonical order; every word is zero."""
    h = view.hypotheses(1)
    if int(rec["boundary"]) != TEAM_SELECTION:
        foe = tracker._member(1 - tracker.side)
        leads = [int(m) for m in rec["foe_leads"]]
        seen = [m for m in range(len(foe)) if int(rec["foe_seen_mask"]) >> m & 1 and m not in leads]
        rest = [m for m in range(len(foe)) if m not in leads and m not in seen]
        h[0]["pick_order"][:brought_count] = (leads + seen + rest)[:brought_count]
    if int(rec["boundary"]) == PIVOT:
        h[0]["queue_order"][:int(rec["queue_count"])] = np.arange(int(rec["queue_count"]), dtype=np.uint8)
    return h


def _causes(context, observation, rec):
    """The names of the public causes the observation shows (duoforge_observation_causes) and a live Speed Swap, which
    only the record carries (its presence bit, record.CAUSE_SPEED_SWAP), for a refusal's reason."""
    causes = view.observation_causes(context, observation)
    if record._record_speed_swap_bit(rec):
        causes |= record.CAUSE_SPEED_SWAP
    return ",".join(name for bit, name in record.CAUSE_NAMES if causes & bit)


def domain(tracker):
    """(FACTORED_DOMAIN record, slot lists) at the tracker's point, the engine's; at team selection (team domain, None).
    Refused when the point's record is not determined or the engine refuses its world."""
    context = tracker.data.context_of(tracker.record_kind)
    observation = tracker.observation()
    try:
        with tracker.own_values():
            rec = record.build(tracker, observation)
    except record.Refusal as refusal:
        raise Refused(f"record:{refusal.reason}") from None
    if int(rec["foe_pending_mask"]):
        # a PIVOT with a foe move still queued: its command is a draw from the foe's turn-start domain (the honest
        # search's queue mask), which this hypothesis does not make
        raise Refused("hypothesis:foe-command-pending")
    worlds = _batch(context)
    h = _hypothesis(tracker, rec, context.config["brought_count"])
    status = int(worlds.from_view(rec.reshape(1), h)[0])
    for points in range(1, MAX_STAT_POINTS + 1):
        if status != C["DUOFORGE_E_INVALID_ARGUMENT"]:
            break
        # no HP of a seen foe member shows its display under these stat points (an exact half needs an even maximum):
        # the engine decides which HP stat points fit, tried in turn for every foe member
        h[0]["stat_points"][:, 0] = points
        status = int(worlds.from_view(rec.reshape(1), h)[0])
    if status:
        causes = _causes(context, observation, rec) if status == C["DUOFORGE_E_UNSUPPORTED"] else ""
        raise Refused(f"world:{status_name(status)}" + (f":{causes}" if causes else ""))
    worlds.query_factored()
    out = worlds.domains[0, tracker.side].copy()
    if int(out["kind"]) == C["DUOFORGE_CHOICE_TEAM_SELECTION"]:
        return out, None
    lists = [[options.Option(int(c["kind"]), int(c["move_slot"]), int(c["target"]), int(c["mega"]), int(c["reserve"]), "")
              for c in out["slots"][s][:int(out["slot_count"][s])]] for s in (0, 1)]
    return out, lists
