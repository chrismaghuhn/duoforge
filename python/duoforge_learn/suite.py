"""The evaluation suite (decision 0017, spec section 13): a fixed list of
games, each a pairing (side-0 and side-1 team), the learner's seat and a
game number.

Up to 8 teams the suite is complete: every ordered pairing, both seats,
`games` games each. With more teams it holds `budget` games stratified by
team: the learner's team is each team budget // N or budget // N + 1
times, and its opponents cycle through a permutation of the pool drawn
for that team (pairing.SUITE), so they are spread evenly; the seat
alternates. The suite is a pure function of the pool size and the seed.
"""
import numpy as np

from . import pairing

SUITE = np.dtype([("side0", np.uint32), ("side1", np.uint32), ("learner_seat", np.uint32), ("game", np.uint32)])
_COMPLETE_UP_TO = 8


def _row(mine, other, seat, game):
    return (mine, other, seat, game) if seat == 0 else (other, mine, seat, game)


def make_suite(n_teams, seed, games=2, budget=512):
    if n_teams < 1 or games < 1 or budget < 1:
        raise ValueError(f"a suite needs teams, games and a budget (got {n_teams}, {games}, {budget})")
    rows = []
    if n_teams <= _COMPLETE_UP_TO:
        for mine in range(n_teams):
            for other in range(n_teams):
                for seat in (0, 1):
                    for g in range(games):
                        rows.append(_row(mine, other, seat, g))
        return np.array(rows, dtype=SUITE)
    base, extra = divmod(budget, n_teams)
    first = np.argsort(pairing.draw(seed, pairing.SUITE, np.array([n_teams]), np.arange(n_teams)))
    more = set(first[:extra].tolist())  # which teams get the extra game
    for mine in range(n_teams):
        order = np.argsort(pairing.draw(seed, pairing.SUITE, np.full(n_teams, mine), np.arange(n_teams)))
        for k in range(base + (mine in more)):
            rows.append(_row(mine, int(order[k % n_teams]), (mine + k) % 2, k))
    return np.array(rows, dtype=SUITE)
