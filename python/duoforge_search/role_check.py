"""The role check (#440, owner and HauptSession 2026-10-15): after one of our Pokemon falls, have we still an answer to
every foe Pokemon left? A measurement on the bot's own worlds, nothing live.

The pair probe (probe_pair, setup_choices): one of our living members B (on the field or on the bench) against one living
foe member X, in a world of the decision. Turn 1 brings them in: a side whose member is not active plays the likeliest
legal pair of its policy that switches the member in (the policy picks the slot), the other side its likeliest pair;
turn 1 is left out when both are already active. Where turn 1 ends at a replacement (or a pivot) boundary, each
requested side plays its policy's likeliest legal pair there, through the engine, up to REPLACE_ROUNDS times, until a
turn (settle_choice); who fell in these steps and how is kept apart (fell_in). Turn 2 is the probe: B tries each of its
commands, its partner and the foe side playing their likeliest pairs, and X does the same against B. Every number comes
from the engine's events of the step (privileged.step_events on the world, an offline measurement like the oracle's,
never a player's), nothing from a type or damage rule here:
- the damage of B's command to X: the HP X loses to hits that B's [move] makes (DAMAGE with no cause after B's
  [move]), read from X's side's events (its exact HP); the same for X against B;
- best: each side's command with the most damage (the worst case for us on X's side);
- order: which of the two moves first when both play their best command;
- the HP of both at the start of turn 2.
From them the KO race: turns to KO for each side = HP / best damage per turn, rounded up (the damage per turn assumed to
stay what turn 2 measured), the side that needs fewer turns wins, at a tie the one that moves first. All commands of a
world are stepped with one seed (common random numbers), so they differ only by the command.

The partners' and the foe's likeliest pairs come from a policy: policy(batch, envs, side) -> (len(envs), PAIRS) log
probabilities over the pair index i * OPTIONS + k of the batch's current domains (role_policy: BC6 for our side and the
foe model for the foe, as the search encodes them)."""
import argparse
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from duoforge import _layout, data, privileged

from . import lookahead

C = _layout.CONSTANTS
_SLOTS = C["DUOFORGE_CHOICE_SLOTS"]
_MOVE, _SWITCH = C["DUOFORGE_SLOT_MOVE"], C["DUOFORGE_SLOT_SWITCH"]
_EV_MOVE, _EV_DAMAGE, _EV_HEAL = C["DUOFORGE_EVENT_MOVE"], C["DUOFORGE_EVENT_DAMAGE"], C["DUOFORGE_EVENT_HEAL"]
_EV_SWITCH, _EV_DRAG, _EV_UPKEEP = C["DUOFORGE_EVENT_SWITCH"], C["DUOFORGE_EVENT_DRAG"], C["DUOFORGE_EVENT_UPKEEP"]
_CAUSE_NONE, _CAUSE_MOVE = C["DUOFORGE_CAUSE_NONE"], C["DUOFORGE_CAUSE_MOVE"]
_EV_FAINT = C["DUOFORGE_EVENT_FAINT"]
_TURN, _TERMINAL = C["DUOFORGE_BOUNDARY_TURN"], C["DUOFORGE_BOUNDARY_TERMINAL"]
_SETTLE = (C["DUOFORGE_BOUNDARY_REPLACEMENT"], C["DUOFORGE_BOUNDARY_PIVOT"])
PROBE_SAMPLE = 0x7000  # the probe's seeds: search_seeds(seed, key, PROBE_SAMPLE + world), one per world
REPLACE_SAMPLE = 0x7400  # a replacement step's seed: search_seeds(seed, key, REPLACE_SAMPLE + 0x100 * round + world)
REPLACE_ROUNDS = 3  # replacement or pivot steps after turn 1 at most; a world short of a turn then: "replacement_chain"
HAZARDS = ("stealthrock", "spikes")  # the entry hazards that deal damage, by the engine's move names


class Unprobed(ValueError):
    """A pair the probe cannot measure in a world, named (its args[0]): the reason is reported, never read as a
    result."""


def legal_pairs(batch, env, side):
    """[(i, k)] of the side's current domain (a turn: DUOFORGE_CHOICE_SLOTS), in index order."""
    d = batch.domains[env, side]
    if int(d["kind"]) != _SLOTS:
        raise Unprobed("not_a_turn")
    return [(i, k) for i in range(int(d["slot_count"][0])) for k in range(int(d["slot_count"][1]))
            if (int(d["allowed"][i]) >> k) & 1]


def command(batch, env, side, slot, index):
    return batch.domains[env, side]["slots"][slot, index]


def likeliest(logp, pairs, keep=None):
    """The pair of `pairs` (and keep(pair), when given) with the highest log probability; ties to the lower index."""
    best, best_v = None, -math.inf
    for i, k in pairs:
        if keep is not None and not keep((i, k)):
            continue
        v = float(logp[i * lookahead.OPTIONS + k])
        if best is None or v > best_v:
            best, best_v = (i, k), v
    return best


def occupants(batch, env, side):
    """(slot 0's, slot 1's) roster index on the side (as the side itself sees it), None where empty."""
    own = batch.observations[env, side]["sides"][side]
    count = int(own["member_count"])
    return tuple(int(own["occupant"][s]) if int(own["occupant"][s]) < count else None for s in (0, 1))


def hp_of(batch, env, side, member):
    return int(batch.observations[env, side]["sides"][side]["members"][member]["hp"])


def switch_keep(batch, env, side, member):
    """keep(pair): the pair switches `member` in, in either slot."""
    def keep(pair):
        for slot, index in enumerate(pair):
            cmd = command(batch, env, side, slot, index)
            if int(cmd["kind"]) == _SWITCH and int(cmd["reserve"]) == member:
                return True
        return False
    return keep


def setup_choices(batch, envs, p, wants, policy):
    """Turn 1's FACTORED_CHOICE (len(envs), 2) and a need flag per env. wants[n] = (b, x): our member b and the foe's x
    for env envs[n]. A side whose member is not active plays its likeliest pair that switches it in; the other side its
    likeliest pair. need[n] is False where both are active (turn 1 is left out). Unprobed for a member that cannot come
    in (no such switch in the domain)."""
    foe = 1 - p
    envs = np.asarray(envs, np.int64)
    choices = np.zeros((envs.size, 2), _layout.FACTORED_CHOICE)
    need = np.zeros(envs.size, bool)
    logps = {side: policy(batch, envs, side) for side in (p, foe)}
    for n, (env, (b, x)) in enumerate(zip(envs.tolist(), wants)):
        for side, member in ((p, b), (foe, x)):
            pairs = legal_pairs(batch, env, side)
            active = member in occupants(batch, env, side)
            pair = likeliest(logps[side][n], pairs, None if active else switch_keep(batch, env, side, member))
            if pair is None:
                raise Unprobed("cannot_switch_in")
            choices["slot"][n, side] = pair
            need[n] |= not active
    return choices, need


def boundary(batch, env):
    """The environment's boundary kind (DUOFORGE_BOUNDARY_*) in its last query's requests."""
    return max(int(batch.requests[env, side]["boundary_kind"]) for side in (0, 1))


def settle_choice(batch, env, policy):
    """FACTORED_CHOICE (2,) at a replacement or pivot boundary: each requested side its policy's likeliest legal
    pair (our side by the main network, the foe's by the foe model); Unprobed where a requested side has none."""
    choice = np.zeros(2, _layout.FACTORED_CHOICE)
    for side in (0, 1):
        if int(batch.requests[env, side]["requested"]):
            pair = likeliest(policy(batch, np.array([env]), side)[0], legal_pairs(batch, env, side))
            if pair is None:
                raise Unprobed("replacement_refused")
            choice["slot"][side] = pair
    return choice


def fell_in(events, occupant, hazards, p, b, x):
    """[[who, how]] for each FAINT in one player's events of a step: who is "b", "x", "own_other" or "foe_other"
    (occupant(position): the roster index standing there after the step, None where none), how the cause of the last
    damage at that position before the faint: "hit" (a move's own hit, no cause), "hazard" (a move cause whose move is
    in hazards, the engine's ids of HAZARDS), "other" (any other cause: recoil, weather, an item, ...) or "unseen" (no
    damage before it)."""
    out, last = [], {}
    for e in events:
        kind, pos = int(e["kind"]), int(e["position"])
        if kind == _EV_DAMAGE:
            cause = int(e["cause"])
            last[pos] = ("hit" if cause == _CAUSE_NONE else
                         "hazard" if cause == _CAUSE_MOVE and int(e["id2"]) in hazards else "other")
        elif kind == _EV_FAINT:
            side, member = pos // 2, occupant(pos)
            who = ("b" if side == p and member == b else "x" if side != p and member == x else
                   "own_other" if side == p else "foe_other")
            out.append([who, last.pop(pos, "unseen")])
    return out


def _damage(events, user, target, hp):
    """(damage the user's moves did to the target position, whether the user moved) in one player's events, the
    target's HP before the step being hp. A switch at the target's position ends the count (another Pokemon stands
    there)."""
    mover, done, moved = None, 0, False
    for e in events:
        kind, pos = int(e["kind"]), int(e["position"])
        if kind == _EV_MOVE:
            mover = pos
            moved |= pos == user
        elif kind == _EV_UPKEEP:
            mover = None
        elif kind in (_EV_SWITCH, _EV_DRAG) and pos == target:
            break
        elif kind == _EV_DAMAGE and pos == target:
            if int(e["cause"]) == _CAUSE_NONE and mover == user:
                done += hp - int(e["hp"])
            hp = int(e["hp"])
        elif kind == _EV_HEAL and pos == target:
            hp = int(e["hp"])
    return done, moved


def _first(events, a, b):
    """Which of positions a and b makes the first [move] of the step: a, b or None (neither moved)."""
    for e in events:
        if int(e["kind"]) == _EV_MOVE and int(e["position"]) in (a, b):
            return int(e["position"])
    return None


def probe_pair(batch, env, p, b, x, policy, rng):
    """The probe of our member b against the foe's x in batch environment env (queried: requests, domains,
    observations), both active. rng: the probe's seed pair. Returns a dict: hp_b, hp_x (at the start of the step),
    best_b and best_x (the most damage per turn, None where no command of that side got to move), first ("b", "x" or
    None) and the race: turns_b, turns_x (None for no damage) and winner ("b", "x" or None when neither can KO)."""
    foe = 1 - p
    ours, theirs = occupants(batch, env, p), occupants(batch, env, foe)
    if b not in ours or x not in theirs:
        raise Unprobed("not_active")
    slot_b, slot_x = ours.index(b), theirs.index(x)
    pos_b, pos_x = 2 * p + slot_b, 2 * foe + slot_x
    hp_b, hp_x = hp_of(batch, env, p, b), hp_of(batch, env, foe, x)
    if hp_b == 0 or hp_x == 0:
        raise Unprobed("fainted")
    pairs = {side: legal_pairs(batch, env, side) for side in (p, foe)}
    logp = {side: policy(batch, np.array([env]), side)[0] for side in (p, foe)}
    base = {side: likeliest(logp[side], pairs[side]) for side in (p, foe)}

    def step(ours_pair, theirs_pair):
        choice = np.zeros(2, _layout.FACTORED_CHOICE)
        choice["slot"][p], choice["slot"][foe] = ours_pair, theirs_pair
        got = privileged.step_events(batch, env, choice, rng=rng)
        if got["status"] != 0:
            raise Unprobed("step_refused")
        return got["events"]

    def sweep(side, slot, user, target, target_side, hp):
        """{command index: damage} for each move command of the side's slot (None: it did not get to move)."""
        out = {}
        other = foe if side == p else p
        for index in sorted({pair[slot] for pair in pairs[side]}):
            if int(command(batch, env, side, slot, index)["kind"]) != _MOVE:
                continue
            pair = likeliest(logp[side], pairs[side], lambda ik, s=slot, i=index: ik[s] == i)
            events = step(pair, base[other]) if side == p else step(base[other], pair)
            done, moved = _damage(events[target_side], user, target, hp)
            out[index] = done if moved else None
        return out

    dmg_b = sweep(p, slot_b, pos_b, pos_x, foe, hp_x)
    dmg_x = sweep(foe, slot_x, pos_x, pos_b, p, hp_b)

    def best(dmg):
        moved = {i: d for i, d in dmg.items() if d is not None}
        return (None, None) if not moved else max(moved.items(), key=lambda kv: (kv[1], -kv[0]))[::-1]

    best_b, cmd_b = best(dmg_b)
    best_x, cmd_x = best(dmg_x)
    first = None
    if cmd_b is not None and cmd_x is not None:
        ours_pair = likeliest(logp[p], pairs[p], lambda ik: ik[slot_b] == cmd_b)
        theirs_pair = likeliest(logp[foe], pairs[foe], lambda ik: ik[slot_x] == cmd_x)
        events = step(ours_pair, theirs_pair)
        mover = _first(events[p], pos_b, pos_x)
        first = None if mover is None else "b" if mover == pos_b else "x"
    turns_b = None if not best_b else math.ceil(hp_x / best_b)
    turns_x = None if not best_x else math.ceil(hp_b / best_x)
    return {"hp_b": hp_b, "hp_x": hp_x, "best_b": best_b, "best_x": best_x, "first": first,
            "turns_b": turns_b, "turns_x": turns_x, "winner": race(turns_b, turns_x, first)}


def race(turns_b, turns_x, first):
    """The KO race's winner: the side needing fewer turns, at a tie the one moving first; None when neither can KO."""
    if turns_b is None and turns_x is None:
        return None
    if turns_x is None or (turns_b is not None and turns_b < turns_x):
        return "b"
    if turns_b is None or turns_x < turns_b:
        return "x"
    return first


# --- one decision: the role table over every living pair and every world -------------------------------------------

ANSWER = 0.5  # a foe Pokemon is answered when we win its KO race in at least this share of the worlds (fixed before the run)


class RolePolicy:
    """The policy of the probe: our side by the search's network, the foe's by its foe model (the search's own
    encodings), each batch state encoded once for all its environments (refresh after a step of the batch)."""

    def __init__(self, search):
        self.search, self.cache = search, {}

    def refresh(self, batch, n):
        s = self.search
        obs, slots, pairs = (x.copy() for x in batch.query_encoded(s.encoder, s.ext_supported))
        out = {}
        for side in (0, 1):
            out[(side, "main")] = s._policy(obs[:n, side], slots[:n, side], pairs[:n, side])[0]
        if s.foe_net is not None:
            fobs, fslots, fpairs = (x.copy() for x in batch.query_encoded(s.foe_net[2], s.foe_net[3]))
            for side in (0, 1):
                out[(side, "foe")] = s._policy(fobs[:n, side], fslots[:n, side], fpairs[:n, side], s.foe_net)[0]
        batch.query()
        batch.query_factored()
        self.cache[id(batch)] = out

    def for_side(self, p):
        """The callable policy(batch, envs, side): side p by the main network, the other side by the foe model."""
        def policy(batch, envs, side):
            got = self.cache[id(batch)]
            key = (side, "main") if side == p or (side, "foe") not in got else (side, "foe")
            return got[key][np.asarray(envs, np.int64)]
        return policy


def living(batch, env, side):
    """The roster indices of the side's brought members (its brought_order, as the side itself sees it) with HP
    left; a member not brought to the battle is no answer and no foe."""
    own = batch.observations[env, side]["sides"][side]
    count = int(own["member_count"])
    brought = [int(m) for m in own["brought_order"] if int(m) < count]
    return [m for m in brought if int(own["members"][m]["hp"]) > 0]


def role_table(search, p, key):
    """({(b, x): [probe dict, or the Unprobed reason as a str, per world]}, {(b, x): [None, or fell_in's [[who, how]]
    of the setup's steps, per world]}) for every living member b of ours and x of the foe's (in world 0's rosters; a
    pair dead in a world is "fainted" there). A world whose setup felled b or x is "fell_in_setup"; one whose battle
    ended in it "setup_ended"."""
    worlds, leaves, s = search.worlds, search.leaves, search.s
    if s > 0x100:
        raise ValueError(f"the replacement steps' seeds hold 256 worlds, the search has {s}")
    foe = 1 - p
    worlds.query()
    worlds.query_factored()
    policy = RolePolicy(search)
    policy.refresh(worlds, s)
    pol = policy.for_side(p)
    pairs = [(b, x) for b in living(worlds, 0, p) for x in living(worlds, 0, foe)]
    out = {pair: [None] * s for pair in pairs}
    fell = {pair: [None] * s for pair in pairs}
    wants, roots = [], []
    for w in range(s):
        for b, x in pairs:
            if b not in living(worlds, w, p) or x not in living(worlds, w, foe):
                out[(b, x)][w] = "fainted"
                continue
            wants.append((b, x))
            roots.append(w)
    rng = {w: _seeds(search.seed, key, PROBE_SAMPLE + w) for w in range(s)}
    if roots:
        choices = np.zeros((len(roots), 2), _layout.FACTORED_CHOICE)
        need = np.zeros(len(roots), bool)
        ok = []
        for n, (w, bx) in enumerate(zip(roots, wants)):  # each pair in each world on its own: a refusal is that one's
            try:
                one, flag = setup_choices(worlds, [w], p, [bx], pol)
            except Unprobed as err:
                out[bx][w] = err.args[0]
                continue
            choices[n], need[n] = one[0], flag[0]
            ok.append(n)
        direct = [n for n in ok if not need[n]]
        for n in direct:
            out[wants[n]][roots[n]] = _probe(worlds, roots[n], p, wants[n], pol, rng[roots[n]])
        moved = [n for n in ok if need[n]]
        if moved:
            hazards = {data.find(_raw(worlds).context, data.TABLE_MOVE, name) for name in HAZARDS}
            import duoforge
            with duoforge.Batch(_raw(leaves).context, np.resize(duoforge.reference_setups([0]), leaves.envs), 1,
                                search.seed) as scratch:
                for start in range(0, len(moved), leaves.envs):
                    part = moved[start:start + leaves.envs]
                    _settle(search, p, key, [(roots[n], wants[n], choices[n]) for n in part], (leaves, scratch),
                            policy, pol, rng, hazards, out, fell)
    return out, fell


def _raw(batch):
    """The batch itself under a DigestNodes sidecar (which forwards only reads)."""
    return getattr(batch, "batch", batch)


def _settle(search, p, key, entries, batches, policy, pol, rng, hazards, out, fell):
    """Turn 1 of each entry (world, (b, x), its FACTORED_CHOICE) through the engine, then each replacement or pivot
    boundary by the policy (settle_choice), up to REPLACE_ROUNDS steps, alternating between the two batches; the probe
    at the first turn. Each step's events come from privileged.step_events on the step's source with the expansion's
    seed and choice, and its digest must equal the expanded environment's (else RuntimeError: the events would not be
    the step's)."""
    src = search.worlds
    live = [(w, bx, choice, w, PROBE_SAMPLE + w) for w, bx, choice in entries]  # (world, pair, choice, env, sample)
    for rnd in range(REPLACE_ROUNDS + 1):
        dst = batches[rnd % 2]
        source = _raw(src)
        _, step, _, _, _ = dst.expand(source, search.encoder, search.ext_supported, search.seed,
                                      np.full(source.envs, key, np.uint64), np.full(source.envs, p, np.uint8),
                                      np.array([e[3] for e in live], np.uint32),
                                      np.array([e[4] for e in live], np.uint32),
                                      np.array([e[2] for e in live], _layout.FACTORED_CHOICE))
        step = np.array(step, copy=True)
        target = _raw(dst)
        policy.refresh(target, len(live))
        nxt = []
        for j, (w, bx, choice, env, sample) in enumerate(live):
            if step[j] != 0:
                out[bx][w] = "setup_refused"
                continue
            got = privileged.step_events(source, env, choice, rng=_seeds(search.seed, key, sample))
            if got["status"] != 0 or bytes(got["digest"]) != target.digest(j):
                raise RuntimeError(f"replay_mismatch: the events of world {w}'s step {rnd} are not its expansion's")

            def occupant(pos, j=j):
                return occupants(target, j, pos // 2)[pos % 2]
            fell[bx][w] = (fell[bx][w] or []) + fell_in(got["events"][p], occupant, hazards, p, *bx)
            kind = boundary(target, j)
            if any(who in ("b", "x") for who, _ in fell[bx][w]):
                out[bx][w] = "fell_in_setup"
            elif kind == _TURN:
                out[bx][w] = _probe(target, j, p, bx, pol, rng[w])
            elif kind == _TERMINAL:
                out[bx][w] = "setup_ended"
            elif kind in _SETTLE and rnd < REPLACE_ROUNDS:
                try:
                    nxt.append((w, bx, settle_choice(target, j, pol), j, REPLACE_SAMPLE + 0x100 * rnd + w))
                except Unprobed as err:
                    out[bx][w] = err.args[0]
            else:
                out[bx][w] = "replacement_chain" if kind in _SETTLE else "not_a_turn"
        if not nxt:
            return
        src, live = dst, nxt


def _seeds(seed, key, sample):
    import duoforge
    return duoforge.search_seeds(seed, key, sample)


def _probe(batch, env, p, bx, policy, rng):
    try:
        return probe_pair(batch, env, p, bx[0], bx[1], policy, rng)
    except Unprobed as err:
        return err.args[0]


def answers(table, foes=None):
    """{x: the share, among the worlds in which some pair (b, x) was probed, of those in which some b of ours wins x's
    KO race; None where no pair of x was probed in any world}. A world without a probe of x (x not brought in it under
    closed sheets, a turn 1 that ended in a replacement, any named refusal) is left out of x's share, never read as
    no answer; the report counts those cells apart."""
    won, probed = {}, {}
    for (b, x), worlds in table.items():
        if foes is not None and x not in foes:
            continue
        w_won = won.setdefault(x, [False] * len(worlds))
        w_probed = probed.setdefault(x, [False] * len(worlds))
        for w, got in enumerate(worlds):
            if isinstance(got, dict):
                w_probed[w] = True
                w_won[w] |= got["winner"] == "b"
    return {x: (sum(a and q for a, q in zip(won[x], probed[x])) / sum(probed[x]) if any(probed[x]) else None)
            for x in won}


def _answered(share):
    return share is not None and share >= ANSWER


# --- the logs: every own faint, the role table before and after it --------------------------------------------------

def phase(turn):
    """The game phase of a turn, fixed before the run (as the KO check's report): early 1-3, middle 4-6, endgame 7+."""
    return "early" if turn <= 3 else "middle" if turn <= 6 else "endgame"


def has_switch(candidate_texts):
    return any("switch" in t for t in candidate_texts)


def battle(path, tables, net, live, team_text, bot, prior, counts, pairs_out=None, setup=None):
    """The rows of one closed-sheet log: one per own faint (the first searched decision after our faint count rose),
    with the answers before (the decision before it) and after, the turn, whether the search had a switch among its
    candidates at the turn of the faint, and the battle's result. pairs_out: a file for the private pair table; setup:
    a Counter of who fell how in the probes' setup steps ("who:how", over every pair and world of every decision)."""
    from duoforge_live import cts, cts_luck
    from . import ko_check
    search = live.searcher.searcher
    with open(path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    result = cts_luck.result_of(records, bot)
    rows, before = [], None
    for game, record, searched in cts.replay_closed(path, tables, net, live, team_text, bot, prior, counts):
        p = int(searched["seat"])
        seen = (C["DUOFORGE_HP_EXACT"], C["DUOFORGE_HP_PERCENT"])
        search.worlds.query()
        ours = int(ko_check.fainted(search.worlds.observations[:1, p]["sides"], seen)[0, p])
        table, fell = role_table(search, p, int(searched["key"]))
        turn = int(cts.root_view(game)[0]["turn"])
        texts = {v: t for t, v in cts.pair_texts(game, net).items()}
        candidates = [texts.get(int(c), "") for c in searched["own_pairs"]]
        now = {"turn": turn, "fainted": ours, "answers": answers(table), "switch": has_switch(candidates)}
        if pairs_out is not None:
            for (b, x), worlds in table.items():
                pairs_out.write(json.dumps({"turn": turn, "b": b, "x": x, "worlds": worlds,
                                            "fell": fell[(b, x)]}) + "\n")
        if setup is not None:
            for worlds in fell.values():
                for got in worlds:
                    setup.update(f"{who}:{how}" for who, how in got or ())
        if before is not None and ours > before["fainted"]:
            alive = set(now["answers"])
            known = [x for x in alive if now["answers"][x] is not None and before["answers"].get(x) is not None]
            lost = [x for x in known if _answered(before["answers"][x]) and not _answered(now["answers"][x])]
            rows.append({"turn": turn, "phase": phase(turn), "foes_left": len(alive),
                         "foes_unknown": len(alive) - len(known),
                         "answered_before": sum(_answered(before["answers"].get(x)) for x in alive),
                         "answered_after": sum(_answered(now["answers"][x]) for x in alive),
                         "lost_last_answer": len(lost), "switch_candidate": before["switch"], "result": result})
        before = now
    return rows


def aggregate(rows):
    """The report's sums: per phase and over all, the own faints, those that lost the last answer to some foe
    Pokemon, the games lost among them, and the share that had a switch among the search's candidates."""
    out = {}
    for name in ("all", "early", "middle", "endgame"):
        part = [r for r in rows if name == "all" or r["phase"] == name]
        lost = [r for r in part if r["lost_last_answer"] > 0]
        out[name] = {"own_faints": len(part), "lost_last_answer": len(lost),
                     "lost_last_answer_game_lost": sum(r["result"] == -1.0 for r in lost),
                     "lost_last_answer_switch_candidate": sum(r["switch_candidate"] for r in lost),
                     "foes_left": sum(r["foes_left"] for r in part),
                     "foes_unknown": sum(r.get("foes_unknown", 0) for r in part),
                     "answered_after": sum(r["answered_after"] for r in part),
                     "games_lost": sum(r["result"] == -1.0 for r in part)}
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.role_check", description=__doc__.split("\n\n")[0])
    p.add_argument("--logs", required=True, help="a directory of the arena's closed-sheet battle logs (private)")
    p.add_argument("--team", required=True, help="our team's paste, the one the logged games played")
    p.add_argument("--checkpoint", required=True, help="the live network (BC6)")
    p.add_argument("--foe-net", default=None, help="the foe model (default: the checkpoint itself)")
    p.add_argument("--step", default="0", help="the ladder step whose search is replayed (ladder.STEPS)")
    p.add_argument("--bot", required=True, help="the bot's name, as in its log files' names")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", required=True, help="the report directory, outside the repository")
    args = p.parse_args(argv)
    from duoforge_replay.dataset import refuse_repository
    try:
        refuse_repository(args.out)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    from . import ladder
    try:
        settings = ladder.step_settings(args.step)
    except ValueError as err:
        raise SystemExit(str(err)) from None
    from duoforge_live import cts, data, pkmn_arena, policy, search as live_search
    team_text = Path(args.team).read_text(encoding="utf-8")
    files = sorted(Path(args.logs).glob("battle-*.jsonl"))[:args.limit]
    if not files:
        raise SystemExit(f"no battle logs in {args.logs}")
    foe_path = args.foe_net or args.checkpoint
    net, tables = policy.load(args.checkpoint), data.for_checkpoint(args.checkpoint)
    live = live_search.load(args.checkpoint, settings=settings, foe_net=foe_path,
                            foe_net_sha256=pkmn_arena.sha256_of(foe_path))
    live.searcher = cts.Capture(live.searcher)
    if live.searcher.s != cts.PARTICLES:
        live.close()
        raise SystemExit(f"the step's search has {live.searcher.s} worlds, the tracker {cts.PARTICLES} particles")
    prior = cts.SetPrior.from_table(tables)
    os.makedirs(args.out, exist_ok=True)
    rows, games, refused, counts, setup = [], Counter(), Counter(), Counter(), Counter()
    try:
        with open(os.path.join(args.out, "faints.jsonl"), "w", encoding="utf-8") as f, \
                open(os.path.join(args.out, "pairs.jsonl"), "w", encoding="utf-8") as pairs_out:
            for n, path in enumerate(files):
                try:
                    got = battle(path, tables, net, live, team_text, args.bot, prior, counts, pairs_out, setup)
                except cts.Refused as err:
                    refused[str(err)] += 1
                    continue
                games["followed"] += 1
                rows.extend(got)
                for r in got:
                    f.write(json.dumps(r) + "\n")
                print(f"{n + 1}/{len(files)} games, {len(rows)} own faints", file=sys.stderr, flush=True)
    finally:
        live.close()
    report = {"step": args.step, "answer_share": ANSWER, "phases": {"early": "turns 1-3", "middle": "turns 4-6",
                                                                     "endgame": "turns 7+"},
              "games": {"files": len(files), **games, "refused": dict(refused)}, "decision_points": dict(counts),
              "setup_fell": dict(sorted(setup.items())),
              **aggregate(rows)}
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
