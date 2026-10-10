"""Roots for Honest.decide from a player's own parts instead of a batch (the live path, plan 2026-10-10-live-honest-search
Task 2). decide() reads a root batch's requests, observations, encoded features, public records and episodes; RecordRoots
serves exactly those from what the caller sets per (environment, seat):

- request (REQUEST) and observation (OBSERVATION): the player's own, as the live tracker produces them;
- obs, slots, pairs: the encoded features of that observation and the legal pair mask (Batch.query_encoded's per-seat
  rows), computed by the caller with the checkpoint's encoder;
- record and status: the player's public record (duoforge_public_state) and 0, or a refusal status. A record assembled
  outside the engine is checked by the search itself: every world built from it must give it back (Honest._check_worlds);
- causes: for a refused record, the DUOFORGE_PUBLIC_CAUSE_* mask of what the player sees (visible sleep or confusion, a
  possible Illusion; Batch.public_causes), 0 otherwise;
- episode: the game, so the search's history (team preview record) belongs to one game.

Plays nothing and holds no rule: decide() over a RecordRoots filled from a batch gives the batch's decisions
(test_honest)."""
import numpy as np

from duoforge import _layout, view


class RecordRoots:
    def __init__(self, envs):
        if int(envs) < 1:
            raise ValueError("RecordRoots needs at least one environment")
        self.envs = int(envs)
        self.requests = np.zeros((self.envs, 2), dtype=_layout.REQUEST)
        self.observations = np.zeros((self.envs, 2), dtype=_layout.OBSERVATION)
        self._parts = {}
        self._episodes = np.zeros(self.envs, np.int64)

    def set(self, env, seat, *, request, observation, obs, slots, pairs, record, status, episode, causes=0):
        """The parts of seat `seat` in environment `env` for the next decide()."""
        if not 0 <= int(env) < self.envs or int(seat) not in (0, 1):
            raise ValueError(f"no environment {env} / seat {seat}")
        self.requests[env, seat] = request
        self.observations[env, seat] = observation
        self._parts[(int(env), int(seat))] = (np.asarray(obs), np.asarray(slots), np.asarray(pairs),
                                              np.array(record, copy=True), int(status), int(causes))
        self._episodes[env] = int(episode)

    def clear(self, env, seat):
        """Removes a seat's parts (it has no request)."""
        self._parts.pop((int(env), int(seat)), None)
        self.requests[env, seat] = np.zeros((), dtype=_layout.REQUEST)

    def _part(self, env, seat):
        try:
            return self._parts[(int(env), int(seat))]
        except KeyError:
            raise ValueError(f"environment {env} seat {seat} has no parts set") from None

    def query_encoded(self, encoder, ext_supported=0):
        """(obs, slots, pairs) as Batch.query_encoded: (E, 2, ...) with every set seat's rows, zeros elsewhere."""
        if not self._parts:
            raise ValueError("no parts set")
        o, s, p = next(iter(self._parts.values()))[:3]
        obs = np.zeros((self.envs, 2) + o.shape, o.dtype)
        slots = np.zeros((self.envs, 2) + s.shape, s.dtype)
        pairs = np.zeros((self.envs, 2) + p.shape, p.dtype)
        for (e, seat), (o, s, p, *_) in self._parts.items():
            obs[e, seat], slots[e, seat], pairs[e, seat] = o, s, p
        return obs, slots, pairs

    def public(self, players):
        """(records, statuses) as Batch.public for the given seat per environment; a seat without parts is refused."""
        players = np.asarray(players)
        records = np.zeros(self.envs, dtype=view.PUBLIC_STATE)
        statuses = np.full(self.envs, _layout.CONSTANTS["DUOFORGE_E_UNSUPPORTED"], np.uint32)
        for e in range(self.envs):
            part = self._parts.get((e, int(players[e])))
            if part is not None:
                records[e], statuses[e] = part[3], part[4]
        return records, statuses

    def public_causes(self, players):
        """(masks, statuses) as Batch.public_causes: the set cause mask of each environment's given seat."""
        players = np.asarray(players)
        masks = np.zeros(self.envs, np.uint32)
        statuses = np.zeros(self.envs, np.uint32)
        for e in range(self.envs):
            part = self._parts.get((e, int(players[e])))
            if part is not None:
                masks[e] = part[5]
        return masks, statuses

    def episode(self, env):
        return int(self._episodes[env])
