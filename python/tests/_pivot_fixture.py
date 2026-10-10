"""A PIVOT that stays public after the view audit of 2026-10-10: a PIVOT record exists only once the moves of the turn have
publicly started (a Protect is up) and no move is left to run (a silent flinch could be outstanding on one), and random play
almost never reaches that (0 of 87 PIVOTs in 512 steps of the reference batch). Scripted on reference setup 1: Grimmsnarl
and Politoed lead against Raichu and Gholdengo; on turn 1 both Politoed and Gholdengo Protect (+4), Raichu's Fake Out (+3)
hits Politoed's Protect, and Grimmsnarl's Parting Shot (status, +1 with Prankster) at Raichu runs last and switches it out:
the PIVOT's request comes with every move run and a Protect up."""
import numpy as np

from duoforge import _layout

C = _layout.CONSTANTS
SETUP = 1
LEADS = ((5, 0, 1, 2), (4, 5, 1, 3))  # side 0: Grimmsnarl, Politoed; side 1: Raichu, Gholdengo
PARTING_SHOT, PROTECT, FAKE_OUT = 3, 3, 2  # move slots
RAICHU, POLITOED = 2, 1  # target positions (side * 2 + slot)


def _option(domain, slot, move_slot, target=None):
    for i in range(int(domain["slot_count"][slot])):
        cmd = domain["slots"][slot, i]
        if int(cmd["kind"]) == C["DUOFORGE_SLOT_MOVE"] and int(cmd["move_slot"]) == move_slot and \
                (target is None or int(cmd["target"]) == target):
            return i
    raise AssertionError(f"the fixture's move (slot {move_slot}, target {target}) is not offered")


def play_to_pivot(batch, env=0, before_step=None):
    """Steps environment env of batch (on reference setup 1, freshly reset) from team preview to the public PIVOT;
    before_step(batch) runs after each query, before each scripted step. Asserts the PIVOT is reached."""
    batch.query_factored()
    if before_step is not None:
        before_step(batch)
    choice = np.zeros((batch.envs, 2), dtype=_layout.FACTORED_CHOICE)
    for side in (0, 1):
        choice["picks"][env, side, :4] = LEADS[side]
    batch.step_factored(choice)
    batch.query_factored()
    if before_step is not None:
        before_step(batch)
    d0, d1 = batch.domains[env, 0], batch.domains[env, 1]
    choice = np.zeros((batch.envs, 2), dtype=_layout.FACTORED_CHOICE)
    choice["slot"][env, 0] = (_option(d0, 0, PARTING_SHOT, RAICHU), _option(d0, 1, PROTECT))
    choice["slot"][env, 1] = (_option(d1, 0, FAKE_OUT, POLITOED), _option(d1, 1, PROTECT))
    batch.step_factored(choice)
    batch.query_factored()
    assert int(batch.requests["boundary_kind"][env, 0]) == C["DUOFORGE_BOUNDARY_PIVOT"]
    assert int(batch.requests["requested"][env, 0]) == 1
