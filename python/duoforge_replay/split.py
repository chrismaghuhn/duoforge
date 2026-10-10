"""The player split of the Bo1 belief source (M11 Bo1 spec section 6).

A game is a test game when either player's hash (game._hash8 of the name's to_id, as games.npz stores it) falls into
bucket 0 of BUCKETS, otherwise a training game: no player is in both. Only hashes are used, never names.
"""
from .game import _hash8, _to_id

BUCKETS = 20


def is_test_player(h):
    return int(h) % BUCKETS == 0


def of_game(players):
    """"test" when either of the two player hashes is a test player, else "train"."""
    return "test" if any(is_test_player(h) for h in players) else "train"


def players_of(lines):
    """The hashes of the players of p1 and p2 from the log's first |player| line of each; ValueError without both."""
    names = {}
    for line in lines:
        parts = line.split("|")
        if len(parts) > 3 and parts[1] == "player" and parts[2] in ("p1", "p2") and parts[3]:
            names.setdefault(parts[2], parts[3])
    if sorted(names) != ["p1", "p2"]:
        raise ValueError("a log without both |player| lines has no split")
    return tuple(_hash8(_to_id(names[p])) for p in ("p1", "p2"))
