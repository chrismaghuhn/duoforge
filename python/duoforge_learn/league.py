"""The league of Learner v2 (decision 0017, spec section 11).

The first round(share * E) environments play self-play: the learner on both
seats. The others are league environments: the learner sits on seat
e mod 2 and a frozen snapshot of itself plays the other seat. K slots hold
one snapshot each; a league environment takes a slot when its episode
starts (a draw over the open slots), so an opponent changes only at an
episode boundary. Every `refresh` updates the next slot in round robin
starts draining: it takes no new episodes and, once its last episode has
ended, loads a snapshot drawn from the pool. One slot drains at a time.

LeagueState is NumPy only; Opponents (JAX) plays the slots' snapshots.
"""
import numpy as np

from . import pairing


class LeagueState:
    def __init__(self, envs, self_play_share, slots, refresh, seed):
        if not 0.0 <= self_play_share <= 1.0:
            raise ValueError(f"self_play_share {self_play_share} is not in [0, 1]")
        n_self = int(round(self_play_share * envs))
        self.self_play = np.arange(envs) < n_self
        if n_self < envs and slots < 2:
            raise ValueError(f"league environments need at least 2 slots (one may drain), not {slots}")
        if refresh < 1:
            raise ValueError(f"refresh {refresh} must be at least 1")
        self.learner_seat = np.where(self.self_play, -1, np.arange(envs) % 2).astype(np.int8)
        self.slot_of = np.full(envs, -1, dtype=np.int64)
        self.slots, self.refresh, self.seed = int(slots), int(refresh), int(seed)
        self.snapshots = ["init"] * self.slots
        self.draining = -1
        self.next_drain = 0
        self.active = np.zeros(self.slots, dtype=np.int64)
        self.stats = {}

    @property
    def has_league(self):
        return not self.self_play.all()

    def learner_rows(self):
        """(E, 2) bool: the rows the learner plays, its training rows."""
        seats = np.arange(2)[None, :]
        return self.self_play[:, None] | (self.learner_seat[:, None] == seats)

    def start(self, envs, episodes):
        """Gives every league environment among envs a slot for its episode."""
        envs, episodes = np.asarray(envs, dtype=np.int64), np.asarray(episodes, dtype=np.int64)
        league = ~self.self_play[envs]
        if not league.any():
            return
        open_slots = np.array([k for k in range(self.slots) if k != self.draining])
        u = pairing.draw(self.seed, pairing.LEAGUE_SLOT, envs[league], episodes[league])
        chosen = open_slots[pairing.pick(u, np.ones(len(open_slots)))]
        self.slot_of[envs[league]] = chosen
        np.add.at(self.active, chosen, 1)

    def end(self, envs, learner_results):
        """Ends the episodes of envs: +1, -1 or 0 from the learner's view (a
        cut-off episode as the tiebreak scored it) goes to the stats of its
        snapshot."""
        for e, r in zip(np.asarray(envs, dtype=np.int64).tolist(), np.asarray(learner_results).tolist()):
            slot = int(self.slot_of[e])
            if slot < 0:
                continue
            record = self.stats.setdefault(self.snapshots[slot], [0, 0, 0])
            record[0] += 1
            record[1] += int(r > 0)
            record[2] += int(r == 0)
            self.active[slot] -= 1
            self.slot_of[e] = -1

    def tick(self, update):
        """Every `refresh` updates the next slot starts draining, unless one drains."""
        if self.has_league and update % self.refresh == 0 and self.draining < 0:
            self.draining = self.next_drain
            self.next_drain = (self.next_drain + 1) % self.slots

    def ready(self):
        """The drained slot that may load a new snapshot, or -1."""
        return self.draining if self.draining >= 0 and self.active[self.draining] == 0 else -1

    def load(self, slot, snapshot):
        self.snapshots[slot] = snapshot
        if slot == self.draining:
            self.draining = -1

    def to_dict(self):
        return {"self_play": self.self_play.tolist(), "learner_seat": self.learner_seat.tolist(),
                "slot_of": self.slot_of.tolist(), "slots": self.slots, "refresh": self.refresh, "seed": self.seed,
                "snapshots": list(self.snapshots), "draining": self.draining, "next_drain": self.next_drain,
                "active": self.active.tolist(), "stats": {k: list(v) for k, v in self.stats.items()}}

    @staticmethod
    def from_dict(d):
        st = LeagueState.__new__(LeagueState)
        st.self_play = np.array(d["self_play"], dtype=bool)
        st.learner_seat = np.array(d["learner_seat"], dtype=np.int8)
        st.slot_of = np.array(d["slot_of"], dtype=np.int64)
        st.slots, st.refresh, st.seed = int(d["slots"]), int(d["refresh"]), int(d["seed"])
        st.snapshots = list(d["snapshots"])
        st.draining, st.next_drain = int(d["draining"]), int(d["next_drain"])
        st.active = np.array(d["active"], dtype=np.int64)
        st.stats = {k: list(v) for k, v in d["stats"].items()}
        return st


def learner_results(state, envs, rewards):
    """+1, -1 or 0 of the learner in ended episodes (rewards (K, 2) of envs)."""
    seat = np.maximum(state.learner_seat[np.asarray(envs, dtype=np.int64)], 0)
    return np.asarray(rewards)[np.arange(len(seat)), seat]


class Opponents:
    """The slots' snapshots as players: one jitted call evaluates the K
    stacked parameter sets on all given rows (vmap over the slots) and keeps
    each row's slot."""

    def __init__(self, model, slots):
        import jax
        import jax.numpy as jnp

        from .policy import _act
        self.model = model
        self._params = [None] * slots
        self._stacked = None

        def act(stacked, key, obs, slot_part, mask, is_team, slot_idx):
            every = jax.vmap(lambda p: _act(model.apply, p, key, obs, slot_part, mask, is_team)[0])(stacked)
            return every[slot_idx, jnp.arange(obs.shape[0])]

        self._act = jax.jit(act)

    def set(self, slot, params):
        import jax
        import jax.numpy as jnp
        self._params[slot] = params
        if all(p is not None for p in self._params):
            self._stacked = jax.tree_util.tree_map(lambda *xs: jnp.stack(xs), *self._params)

    def act(self, key, obs, slot_part, mask, is_team, slot_idx):
        """Sampled actions of rows whose slots are slot_idx (int, (B,))."""
        if self._stacked is None:
            raise ValueError("every league slot needs parameters before the league plays")
        self.model.check(np.asarray(obs))
        return np.asarray(self._act(self._stacked, key, obs, slot_part, mask, is_team, np.asarray(slot_idx)))
