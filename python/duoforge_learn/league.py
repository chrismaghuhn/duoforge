"""The league of Learner v2 (decision 0017, spec section 11).

The first round(share * E) environments play self-play: the learner on both
seats. The others are league environments: the learner sits on seat
e mod 2 and a frozen snapshot of itself plays the other seat. K slots hold
one snapshot each; a league environment takes a slot when its episode
starts (a draw over the open slots), so an opponent changes only at an
episode boundary. Every `refresh` updates the next slot in round robin
starts draining: it takes no new episodes and, once its last episode has
ended, loads a snapshot drawn from the pool (Refill: uniformly by default,
or mixed with prioritized fictitious self-play and anchors). One slot
drains at a time.

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


WEIGHTINGS = ("hard", "linear", "variance")
SOURCES = ("uniform", "pfsp", "anchor")


class Refill:
    """Which snapshot a drained slot loads: prioritized fictitious self-play
    (PFSP, AlphaStar) mixed with uniform and anchor refills.

    A refill at update u first draws its source over the shares (uniform
    1 - pfsp_share - anchor_share, pfsp_share, anchor_share) with
    pairing.draw(seed, LEAGUE_SOURCE, u, 0), then the snapshot within the
    source with pairing.draw(seed, LEAGUE_SNAPSHOT, u, 0), the draw the
    uniform scheme always used; so the refills are a pure function of the
    seed, the update, the pool and the league's stats (persisted in the run
    state). With both shares 0 (the default) a refill is exactly the
    uniform draw of the code before PFSP and the source draw is not made.

    - uniform: every snapshot of the pool alike.
    - pfsp: snapshot s weighted max(f(p_s), min_weight), p_s the learner's
      win rate against s from LeagueState.stats [games, wins, draws], a draw
      counting half: p_s = (wins + draws / 2 + prior * prior_games) /
      (games + prior_games), so an unseen snapshot has p = prior. f is
      "hard" (1 - p)^2 (AlphaStar), "linear" 1 - p or "variance" p (1 - p).
      The stats count every game since the snapshot first played, not a
      recent window.
    - anchor: the `anchors` earliest snapshots alike (1: params-0, the
      initial or --init network), so old weaknesses stay in the games.
    """

    def __init__(self, pfsp_share=0.0, anchor_share=0.0, anchors=1, weighting="hard", min_weight=0.05, prior=0.5,
                 prior_games=4.0):
        pfsp_share, anchor_share = float(pfsp_share), float(anchor_share)
        if not (0.0 <= pfsp_share <= 1.0 and 0.0 <= anchor_share <= 1.0 and pfsp_share + anchor_share <= 1.0):
            raise ValueError(f"the league's pfsp share {pfsp_share} and anchor share {anchor_share} must lie in "
                             f"[0, 1] with a sum of at most 1 (the rest refills uniformly)")
        if weighting not in WEIGHTINGS:
            raise ValueError(f"pfsp weighting {weighting!r} is not one of {WEIGHTINGS}")
        if not 0.0 < float(min_weight) <= 1.0:
            raise ValueError(f"pfsp min_weight {min_weight} is not in (0, 1]")
        if not 0.0 <= float(prior) <= 1.0:
            raise ValueError(f"pfsp prior {prior} is not in [0, 1]")
        if not float(prior_games) > 0.0:
            raise ValueError(f"pfsp prior_games {prior_games} must be positive (an unseen snapshot needs a win rate)")
        if int(anchors) < 1:
            raise ValueError(f"league anchors {anchors} must be at least 1")
        self.pfsp_share, self.anchor_share, self.anchors = pfsp_share, anchor_share, int(anchors)
        self.weighting, self.min_weight = weighting, float(min_weight)
        self.prior, self.prior_games = float(prior), float(prior_games)

    @property
    def enabled(self):
        return self.pfsp_share > 0.0 or self.anchor_share > 0.0

    def win_rates(self, updates, stats):
        """The learner's smoothed win rate against each snapshot of updates."""
        record = np.array([stats.get(str(u), (0, 0, 0)) for u in updates], dtype=np.float64).reshape(-1, 3)
        games, wins, draws = record.T
        return (wins + 0.5 * draws + self.prior * self.prior_games) / (games + self.prior_games)

    def weights_of(self, p):
        p = np.asarray(p, dtype=np.float64)
        f = {"hard": (1.0 - p) ** 2, "linear": 1.0 - p, "variance": p * (1.0 - p)}[self.weighting]
        return np.maximum(f, self.min_weight)

    def draw(self, seed, update, updates, stats):
        """(chosen update, source) of the refill at update from the pool's
        updates (in the pool's order)."""
        if not updates:
            raise ValueError("the snapshot pool is empty")
        u = pairing.draw(seed, pairing.LEAGUE_SNAPSHOT, np.array([update]), np.array([0]))
        source = "uniform"
        if self.enabled:
            s = pairing.draw(seed, pairing.LEAGUE_SOURCE, np.array([update]), np.array([0]))
            shares = [1.0 - self.pfsp_share - self.anchor_share, self.pfsp_share, self.anchor_share]
            source = SOURCES[int(pairing.pick(s, shares)[0])]
        if source == "uniform":
            candidates, weights = list(updates), np.ones(len(updates))
        elif source == "pfsp":
            candidates = list(updates)
            weights = self.weights_of(self.win_rates(candidates, stats))
        else:
            candidates = sorted(updates)[:self.anchors]
            weights = np.ones(len(candidates))
        return candidates[int(pairing.pick(u, weights)[0])], source


def learner_results(state, envs, rewards):
    """+1, -1 or 0 of the learner in ended episodes (rewards (K, 2) of envs)."""
    seat = np.maximum(state.learner_seat[np.asarray(envs, dtype=np.int64)], 0)
    return np.asarray(rewards)[np.arange(len(seat)), seat]


PRECISIONS = ("float32", "bfloat16")


class Opponents:
    """The slots' snapshots as players: one jitted call evaluates the K
    stacked parameter sets on all given rows (vmap over the slots) and keeps
    each row's slot. precision "bfloat16" runs the matrix products of their
    forward pass in bfloat16 (jax.default_matmul_precision); ids, masks,
    sampling and every elementwise step stay float32, and the learner, whose
    log-probabilities enter the PPO ratio, is never affected."""

    def __init__(self, model, slots, precision="float32"):
        import jax
        import jax.numpy as jnp

        from .policy import _act
        if precision not in PRECISIONS:
            raise ValueError(f"opponent precision {precision!r} is not one of {PRECISIONS}")
        self.model = model
        self.precision = precision
        self._params = [None] * slots
        self._stacked = None

        def act(stacked, key, obs, slot_part, mask, is_team, slot_idx):
            with jax.default_matmul_precision(precision):
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
