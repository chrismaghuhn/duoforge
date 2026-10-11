"""Test positions: curated decision points with a known right answer (M12 bundle 7; docs/ROADMAP.md "A test-position
suite"). Diagnostic only: per the chess-programming rule, nothing is tuned on them.

A position (data/positions/*.json) is reached from registry teams, a battle seed and a choice prefix, and names the
seat to move, the acceptable answers and why. Its claim is proven against the engine by verify(): the property it
names holds in every one of N reseeded copies of the step (privileged.step_events), so damage rolls, critical hits and
speed ties are sampled, not enumerated (the engine has no chance enumeration). The claim holds with a critical hit too,
and the sample must contain critical hits for that to mean anything.

    python -m duoforge_search.positions --checkpoint P --out DIR

plays every position with the checkpoint's raw policy and its honest search (and, for the positions an oracle
answers, the true-state lookahead) and writes the hits to DIR, which must lie outside the repository: results per
checkpoint stay private.

Choice labels (one per active slot): {"move": <move id name>, "target": <flat position side * 2 + slot>} (target left
out for a move without one), {"switch": <species id name>}, {"pass": true}; {"any": true} in an expected answer
accepts every option of that slot.
"""
import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import duoforge
from duoforge import _layout, data, privileged, teams

C = _layout.CONSTANTS
ROOT = Path(__file__).resolve().parents[2] / "data" / "positions"
KINDS = ("fake_out_partner", "protect_vs_ko", "set_trick_room", "undo_trick_room", "endgame", "fake_out_fails")
SAMPLES = 256
RNG_BASE = (0x2026101100000A00, 0x2026101100000B00)


class PositionError(AssertionError):
    """A position that is not what it claims."""


@dataclass(frozen=True)
class Position:
    name: str
    kind: str
    teams: tuple
    seed: int
    picks: tuple
    prefix: tuple
    seat: int
    expected: tuple
    reason: str
    claim: dict

    @staticmethod
    def load(path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        p = Position(raw["name"], raw["kind"], tuple(raw["teams"]), int(raw["seed"]),
                     tuple(tuple(x) for x in raw["picks"]), tuple(tuple(tuple(s) for s in step) for step in raw["prefix"]),
                     int(raw["seat"]), tuple(tuple(e) for e in raw["expected"]), raw["reason"], raw.get("claim", {}))
        if p.kind not in KINDS or p.seat not in (0, 1) or not p.expected or not p.reason.strip():
            raise PositionError(f"{path}: a position needs a known kind, a seat, expected answers and a reason")
        return p


def load_all(root=ROOT):
    return [Position.load(f) for f in sorted(Path(root).glob("*.json"))]


# ---------------------------------------------------------------- labels

def _name(ctx, table, ident):
    return data.name(ctx, table, int(ident))


def slot_label(batch, env, side, slot, cmd):
    """The label of one slot command of `side` in environment env (the viewer is the side itself)."""
    ctx = batch.context
    kind = int(cmd["kind"])
    own = batch.observations[env, side]["sides"][side]
    if kind == C["DUOFORGE_SLOT_MOVE"]:
        member = own["members"][int(own["occupant"][slot])]
        move = int(member["move_ids"][int(cmd["move_slot"])]) if int(cmd["move_slot"]) < 4 else None
        label = {"move": _name(ctx, data.TABLE_MOVE, move) if move is not None else "struggle_or_recharge"}
        if int(cmd["target"]) < 4:
            label["target"] = int(cmd["target"])
        if int(cmd["mega"]):
            label["mega"] = True
        return label
    if kind == C["DUOFORGE_SLOT_SWITCH"]:
        return {"switch": _name(ctx, data.TABLE_SPECIES, own["members"][int(cmd["reserve"])]["species_id"])}
    if kind == C["DUOFORGE_SLOT_PASS"]:
        return {"pass": True}
    if kind == C["DUOFORGE_SLOT_NONE"]:
        return {"none": True}
    raise PositionError(f"a slot command of kind {kind} has no label")


def pairs(batch, env, side):
    """[((i, k), (label0, label1))] of every allowed pair of `side`'s current domain."""
    d = batch.domains[env, side]
    if int(d["kind"]) != C["DUOFORGE_CHOICE_SLOTS"]:
        raise PositionError("the position is no slot decision")
    labels = [[slot_label(batch, env, side, s, d["slots"][s, i]) for i in range(int(d["slot_count"][s]))]
              for s in (0, 1)]
    return [((i, k), (labels[0][i], labels[1][k])) for i in range(int(d["slot_count"][0]))
            for k in range(int(d["slot_count"][1])) if (int(d["allowed"][i]) >> k) & 1]


def _matches(want, have):
    if "not" in want:
        return not _matches(want["not"], have)
    return bool(want.get("any")) or all(have.get(k) == v for k, v in want.items())


def accepted(expected, labels):
    """Whether a pair's labels are one of the expected answers."""
    return any(_matches(e[0], labels[0]) and _matches(e[1], labels[1]) for e in expected)


def _exact(want, have):
    return bool(want.get("any")) or want == have


def resolve(batch, env, side, labels):
    """The (i, k) pair of `side` whose labels are `labels` exactly (one pair, or PositionError)."""
    hits = [ik for ik, lab in pairs(batch, env, side) if _exact(labels[0], lab[0]) and _exact(labels[1], lab[1])]
    if len(hits) != 1:
        raise PositionError(f"the labels {labels} name {len(hits)} pairs of side {side}")
    return hits[0]


# ---------------------------------------------------------------- reaching a position

def reach(ctx, position, root=None, on_preview=None):
    """A one-environment batch at the position's decision point (the caller closes it); on_preview(batch) is
    called at the team preview (a search records its history there)."""
    ids = list(dict.fromkeys(position.teams))  # a pool's ids are unique: A against A is one team twice
    pool = teams.load(ctx, ids, root=root or ROOT.parent / "teams")
    batch = duoforge.Batch(ctx, pool.setups(np.array([ids.index(position.teams[0])]),
                                            np.array([ids.index(position.teams[1])])), 1, position.seed)
    try:
        batch.query_factored()
        if on_preview is not None:
            on_preview(batch)
        choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
        for side in (0, 1):
            choices["picks"][0, side, :4] = position.picks[side]
        batch.step_factored(choices)
        for step in position.prefix:
            batch.query_factored()
            choices = np.zeros((1, 2), _layout.FACTORED_CHOICE)
            for side in (0, 1):
                if batch.requests["requested"][0, side]:
                    choices["slot"][0, side] = resolve(batch, 0, side, step[side])
            batch.step_factored(choices)
            if batch.result(0) != 0:
                raise PositionError(f"{position.name}: the prefix ends the battle")
        batch.query_factored()
        if not batch.requests["requested"][0, position.seat] or \
                int(batch.requests["boundary_kind"][0, position.seat]) == C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
            raise PositionError(f"{position.name}: the prefix does not reach a decision of seat {position.seat}")
        return batch
    except BaseException:
        batch.close()
        raise


# ---------------------------------------------------------------- sampled outcomes

@dataclass(frozen=True)
class Outcome:
    fainted: frozenset   # flat positions whose Pokemon fainted this step
    moved: frozenset     # flat positions whose Pokemon used a move
    crits: int
    result: int          # DUOFORGE_RESULT_* after the step, 0 before TERMINAL
    trick_room: int      # +1: Trick Room started this step, -1: it ended, 0: neither


def sample(batch, env, seat, own, foe, n=SAMPLES, base=RNG_BASE):
    """The outcomes of n reseeded copies of the step: seat plays pair `own`, the other side `foe` ((i, k) each)."""
    choice = np.zeros(2, _layout.FACTORED_CHOICE)
    choice["slot"][seat], choice["slot"][1 - seat] = own, foe
    out = []
    for r in range(n):
        step = privileged.step_events(batch, env, choice, rng=(base[0] + r, base[1] + r))
        if step["status"] != 0:
            raise PositionError(f"a sampled step was refused: {duoforge.status_name(step['status'])}")
        events = step["events"][seat]
        kinds = events["kind"].astype(int)
        room = events["detail"].astype(int) == C["DUOFORGE_FIELD_TRICK_ROOM"]
        trick_room = 1 if (room & (kinds == C["DUOFORGE_EVENT_FIELD_START"])).any() else             -1 if (room & (kinds == C["DUOFORGE_EVENT_FIELD_END"])).any() else 0
        out.append(Outcome(frozenset(int(e["position"]) for e in events[kinds == C["DUOFORGE_EVENT_FAINT"]]),
                           frozenset(int(e["position"]) for e in events[kinds == C["DUOFORGE_EVENT_MOVE"]]),
                           int((kinds == C["DUOFORGE_EVENT_CRIT"]).sum()), step["battle_result"], trick_room))
    return out


# ---------------------------------------------------------------- verification

def _safe(batch, seat, own, foe, flat, n, base):
    """Whether the Pokemon at flat survives every (own, foe) pair in all n samples; the critical hits seen."""
    crits = 0
    for o in own:
        for f in foe:
            for out in sample(batch, 0, seat, o, f, n, base):
                if flat in out.fainted:
                    return False, crits
                crits += out.crits
    return True, crits


def _killer(batch, seat, o, foe, flat, n, base):
    """A foe pair that knocks out the Pokemon at flat in all n samples against own pair o, and the crits seen."""
    for f in foe:
        outs = sample(batch, 0, seat, o, f, n, base)
        if all(flat in out.fainted for out in outs):
            return f, sum(out.crits for out in outs)
    return None, 0


def _no_escape(own_pairs, slot, allow_protect=False):
    return all("switch" not in lab[slot] and (allow_protect or lab[slot].get("move") != "protect")
               for _, lab in own_pairs)


def _speeds(b, seat):
    """(our actives' Speed, the foe actives' Speed, our living bench's Speed), each read from its own player's view
    (privileged: the foe's stats are hidden from us)."""
    def side(s, active):
        v = b.observations[0, s]["sides"][s]
        if active:
            return [int(v["members"][int(v["occupant"][k])]["stats"][4]) for k in (0, 1) if int(v["occupant"][k]) < 6]
        return [int(m["stats"][4]) for m in v["members"][:int(v["member_count"])]
                if int(m["location"]) == C["DUOFORGE_LOCATION_BENCH"] and int(m["hp"]) > 0]
    return side(seat, True), side(1 - seat, True), side(seat, False)


def _endgame(b, seat, own, foe, expected, n, base, name):
    """Every pair ends the battle this step with one result in all samples. The game is a sure win: its value (the
    exact matrix game over win 1, tie 1/2, loss 0) is 1, and the expected answers are exactly the pure pairs that win
    against every foe pair."""
    from . import matrix
    win = C["DUOFORGE_RESULT_SIDE_0"] if seat == 0 else C["DUOFORGE_RESULT_SIDE_1"]
    payoff, crits = [], 0
    for o, _ in own:
        row = []
        for f, _ in foe:
            outs = sample(b, 0, seat, o, f, n, base)
            results = {out.result for out in outs}
            if len(results) != 1 or 0 in results:
                raise PositionError(f"{name}: a pair does not end the battle with one result in all samples")
            crits += sum(out.crits for out in outs)
            r = results.pop()
            row.append(1.0 if r == win else 0.5 if r == C["DUOFORGE_RESULT_TIE"] else 0.0)
        payoff.append(row)
    if crits == 0:
        raise PositionError(f"{name}: no critical hit in the samples: the proof is too small")
    value = matrix.solve(np.array(payoff, dtype=np.float64)).value
    secure = sorted(o for (o, _), row in zip(own, payoff) if min(row) == 1.0)
    if not secure or abs(value - 1.0) > 1e-12 or len(secure) == len(own):
        raise PositionError(f"{name}: not a sure win with a wrong answer (value {value}, {len(secure)} winning pairs)")
    if secure != sorted(expected):
        raise PositionError(f"{name}: the exact answers {secure} are not the expected {sorted(expected)}")
    return {"value": value, "crits": crits, "winning_pairs": len(secure)}


def verify(ctx, position, n=SAMPLES, base=RNG_BASE):
    """Proves the position's claim against the engine (PositionError otherwise); returns a summary of the proof."""
    with reach(ctx, position) as b:
        seat, claim = position.seat, position.claim
        own, foe = pairs(b, 0, seat), pairs(b, 0, 1 - seat)
        expected = [ik for ik, lab in own if accepted(position.expected, lab)]
        if not expected:
            raise PositionError(f"{position.name}: no legal pair is an expected answer")
        all_foe = [ik for ik, _ in foe]
        rest = [ik for ik, _ in own if ik not in expected]
        labels = dict(own)
        report = {"name": position.name, "kind": position.kind, "expected": len(expected), "pairs": len(own)}
        if position.kind in ("fake_out_partner", "protect_vs_ko"):
            slot = claim["partner"] if position.kind == "fake_out_partner" else claim["protector"]
            flat = 2 * seat + slot
            if not _no_escape(own, slot, allow_protect=position.kind == "protect_vs_ko"):
                raise PositionError(f"{position.name}: the threatened Pokemon could switch out (or Protect)")
            safe, crits = _safe(b, seat, expected, all_foe, flat, n, base)
            if not safe:
                raise PositionError(f"{position.name}: an expected answer leaves the Pokemon at {flat} knocked out")
            for o in rest:
                f, c = _killer(b, seat, o, all_foe, flat, n, base)
                if f is None:
                    raise PositionError(f"{position.name}: {labels[o]} keeps the Pokemon at {flat} standing too")
                crits += c
            if crits == 0:
                raise PositionError(f"{position.name}: no critical hit in the samples: the proof is too small")
            report["crits"] = crits
        elif position.kind in ("set_trick_room", "undo_trick_room"):
            want = 1 if position.kind == "set_trick_room" else -1
            room = int(b.observations[0, seat]["trick_room_turns"])
            if (want == 1 and room != 0) or (want == -1 and room < 2):
                raise PositionError(f"{position.name}: Trick Room has {room} turns left")
            ours, theirs, bench = _speeds(b, seat)
            if want == 1 and not max(ours) < min(theirs):
                raise PositionError(f"{position.name}: our actives are not both slower than the foe's")
            if want == -1 and not min(ours + bench) > max(theirs):
                raise PositionError(f"{position.name}: our actives and bench are not all faster than the foe's actives")
            for o in expected:
                for f in all_foe:
                    if not all(out.trick_room == want for out in sample(b, 0, seat, o, f, n, base)):
                        raise PositionError(f"{position.name}: an expected answer does not "
                                            f"{'set' if want == 1 else 'end'} Trick Room against {dict(foe)[f]}")
            report["speeds"] = {"ours": ours, "foe": theirs, "our_bench": bench}
        elif position.kind == "endgame":
            report.update(_endgame(b, seat, own, foe, expected, n, base, position.name))
        elif position.kind == "fake_out_fails":
            u, target = claim["u"], claim["fake_out_target"]
            fo = [ik for ik, lab in own if lab[u].get("move") == "fakeout" and lab[u].get("target") == target]
            movers = [ik for ik, lab in foe if "move" in lab[target % 2] and lab[target % 2]["move"] != "protect"
                      and int(data.move_static(ctx, data.find(ctx, data.TABLE_MOVE, lab[target % 2]["move"]))
                              ["priority"]) == 0]
            if not fo or not movers:
                raise PositionError(f"{position.name}: no Fake Out of slot {u} at {target}, or no slower foe move")
            for f in movers:
                if not all(target in out.moved for out in sample(b, 0, seat, fo[0], f, n, base)):
                    raise PositionError(f"{position.name}: Fake Out stops the foe: it is not this Pokemon's first turn")
            if any(ik in expected for ik in fo):
                raise PositionError(f"{position.name}: a failing Fake Out is an expected answer")
        return report


# ---------------------------------------------------------------- the tool

ORACLE_KINDS = ("fake_out_partner", "protect_vs_ko", "endgame")
KEY = 0x2026101100000C00


def _labels_of(batch, seat, action):
    i, k = divmod(int(action), 32)
    return dict(pairs(batch, 0, seat))[(i, k)]


def play(ctx, position, model, params, encoder, ext, searcher=None, oracle=None):
    """{"raw", "honest", "oracle"}: each player's labels at the position and whether they are an expected answer."""
    out = {}
    with reach(ctx, position, on_preview=None if searcher is None else
               lambda b: searcher.decide(b, [0], [position.seat], [KEY], [False])) as b:
        obs, slots, mask = b.query_encoded(encoder, ext)
        s = position.seat
        logp = np.asarray(model.apply(params, obs[0, s][None], slots[0, s][None], mask[0, s][None])[0])[0]
        logp = np.where(np.asarray(mask[0, s], bool).reshape(-1), logp, -np.inf)
        players = {"raw": int(np.argmax(logp))}
        if searcher is not None:
            players["honest"] = int(searcher.decide(b, [0], [s], [KEY + 1], [False])[0][0])
        if oracle is not None and position.kind in ORACLE_KINDS:
            players["oracle"] = int(oracle.decide(b, [0], [s], [KEY + 1], [False])[0][0])
        for name, action in players.items():
            labels = _labels_of(b, s, action)
            out[name] = {"labels": labels, "hit": accepted(position.expected, labels)}
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m duoforge_search.positions", description=__doc__.split("\n")[0])
    p.add_argument("--checkpoint", required=True, help="a format-2 checkpoint in its trained layout")
    p.add_argument("--out", required=True, help="the private output directory (outside the repository)")
    p.add_argument("--positions", default=str(ROOT))
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--m", type=int, default=8)
    p.add_argument("--worlds", type=int, default=16)
    args = p.parse_args(argv)
    from duoforge_replay.dataset import refuse_repository
    refuse_repository(args.out)
    from duoforge_learn import checkpoint
    from . import honest, lookahead
    params, config = checkpoint.load_trained(args.checkpoint)
    model = checkpoint.trained_model(config, params)
    encoder, ext = checkpoint.encoder_of(config), checkpoint.ext_supported_of(config)
    rows = []
    with duoforge.Context(C["DUOFORGE_DATA_KIND_POOL"]) as ctx:
        table, _, _ = honest.live_spread_table(ctx)
        with honest.Honest(ctx, model, params, encoder, ext, k=args.k, m=args.m, s=args.worlds, rule="mix",
                           table=table) as searcher, \
                lookahead.Lookahead(ctx, model, params, encoder, ext, k=args.k, m=args.m, s=args.worlds) as oracle:
            for position in load_all(args.positions):
                searcher.clear()
                rows.append({"name": position.name, "kind": position.kind,
                             **play(ctx, position, model, params, encoder, ext, searcher, oracle)})
    rates = {name: sum(r[name]["hit"] for r in rows if name in r) / max(1, sum(name in r for r in rows))
             for name in ("raw", "honest", "oracle")}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {"checkpoint": str(args.checkpoint), "positions": rows, "hit_rates": rates}
    (out / "positions.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
