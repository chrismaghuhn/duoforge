"""Whole sets for the members of a game without sheets (M11 Bo1 spec section 3): the set belief.

A member's set is drawn from the corpus sets of its species, frequency-weighted by a word:
  L0  a set that agrees with every fact (the used moves are among its moves, the revealed item and ability equal);
  L1  none does: the base set is drawn from the sets that agree on the item and ability; its moves are the used
      moves plus slots drawn, without replacement and weighted by their frequency among those sets, from theirs.
Fewer than min_sets sets of the species, or none that agrees on the item and ability, is
Skip("skip:belief-unsupported <species>"): no set is guessed from another species.

A word is the first 8 bytes of SHA-256 of "seed|replay|side|member|attempt|draw": the same tuple gives the same
draw in any worker and any order. Stat points are not drawn here (the prior does it, as for sheet games).
"""
import collections
import hashlib

from duoforge_live.data import trace_to_c

from .points import Skip

MIN_SETS = 5
MOVES = 4
LEVEL = 50


def word(seed, replay_id, side, member, attempt, draw):
    text = f"{int(seed)}|{replay_id}|{int(side)}|{int(member)}|{int(attempt)}|{int(draw)}"
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little")


def _sub(w, i):
    return int.from_bytes(hashlib.sha256(f"{int(w)}|{i}".encode("utf-8")).digest()[:8], "little")


def _pick(w, weights):
    """The index floor(w * total / 2^64) points at in the cumulative weights."""
    x = (int(w) * sum(weights)) >> 64
    for i, n in enumerate(weights):
        if x < n:
            return i
        x -= n
    raise ValueError("no weight to pick from")


class SetBelief:
    def __init__(self, corpus, data, min_sets=MIN_SETS):
        self.corpus, self.data, self.min_sets = corpus, data, int(min_sets)

    def draw(self, member, w):
        """(set, level) of a facts.MemberFacts under word w: a teams.unpack-shaped set (Level 50, no EVs)."""
        key = trace_to_c.key
        try:
            sets = self.corpus.sets(key(self.data.canonical(member.species)))
        except ValueError:
            raise Skip(f"skip:belief-unsupported {member.species}") from None
        if sum(s[4] for s in sets) < self.min_sets:
            raise Skip(f"skip:belief-unsupported {member.species}")
        used = {key(m) for m in member.moves}

        def agrees(s):
            return ((member.item is None or key(s[0]) == key(member.item))
                    and (member.ability is None or key(s[1]) == key(member.ability)))
        fitting = [s for s in sets if agrees(s)]
        whole = [s for s in fitting if used <= {key(m) for m in s[3]}]
        if whole:
            base, level = whole[_pick(w, [s[4] for s in whole])], 0
            moves = list(base[3])
        elif fitting:
            base, level = fitting[_pick(w, [s[4] for s in fitting])], 1
            moves = sorted(member.moves)
            freq, spelling = collections.Counter(), {}
            for s in fitting:
                for m in s[3]:
                    if key(m) not in used:
                        freq[key(m)] += s[4]  # one move under every spelling (sheets "FakeOut", pastes "Fake Out")
                        spelling[key(m)] = min(spelling.get(key(m), m), m)
            pool = sorted((spelling[k], n) for k, n in freq.items())
            i = 0
            while len(moves) < MOVES and pool:
                k = _pick(_sub(w, i), [n for _, n in pool])
                moves.append(pool.pop(k)[0])
                i += 1
        else:
            raise Skip(f"skip:belief-unsupported {member.species}")
        return ({"name": member.species, "species": member.species,
                 "item": member.item if member.item is not None else base[0],
                 "ability": member.ability if member.ability is not None else base[1],
                 "moves": moves, "nature": base[2], "evs": [0] * 6, "gender": member.gender, "level": LEVEL}, level)
