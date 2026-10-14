"""Visible-information lookahead (D0023). Only C builds and checks worlds.

The actual root supplies the deciding player's public record and row. Foe
rows are evaluated exclusively in reconstructed worlds. No privileged call
or true-root encoding is used, even for error reproduction.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time
import weakref

import numpy as np

import duoforge
from duoforge import _layout, data, features, state_layout, teams, view
from duoforge_learn.pairing import splitmix64
from duoforge_learn.selfplay import TEAM_TABLE

from . import belief, infokey, lookahead, matrix, seeds, tree
from . import evaluator as evaluators
from .errors import SearchError

C = _layout.CONSTANTS
RULES = lookahead.RULES
# The turn decisions' solver (D1 of the depth search, #481; spec section 8): "lp" the exact Bayes LP (the default, as
# before), "rm" CFR+ on the same candidates (matrix.solve_bayes_rm). The team preview stays on the LP.
ROOT_SOLVERS = ("lp", "rm")
# The search's depth (D2 of the depth search; spec section 8, plan docs/superpowers/plans/2026-10-14-depth-search-d2.md):
# 1 the one-turn search (the default, as before), 2 the two-turn tree (tree.solve_tree) below the turn decisions' root.
DEPTHS = (1, 2)
# A decision's steps_left without the arena's step limit (live play): the plan's decision 2 asks for it explicitly at
# depth 2, never as a default.
NO_STEP_LIMIT = -1
# The node keys' tag (spec section 4.3): node n's depth-2 leaves are seeded with splitmix64(splitmix64(decision key +
# DEPTH_TAG) + n), n its index in the node batch (its root cell (i, j, w) in the leaf plan's order), sample 0.
DEPTH_TAG = 0x4445505448000002
# A depth-2 decision's own seconds, beside its parts: the depth-1 policy call(s), the depth-2 leaves' evaluation and the
# tree solve.
TREE_PHASES = ("tree_policy", "tree_evaluate", "tree_solve")
_MASK = (1 << 64) - 1
MAX_RESPREADS = 256
# The byte of each position's trap_turns in a public record's state (state_layout field names, tail rev 5 position blocks)
_TRAP_TURNS = [dict((name, start) for name, start, _ in state_layout.fields(pool=True))
               [f"tail.side{flat // 2}.position{flat % 2}.trap_turns"] for flat in range(4)]
# The stated-spread teams of the belief (decision 0023): A/B/C and the PP_ teams of the D0023 pool, pinned on
# 2026-10-09 (79 sources, 444 sets, table sha256 1795524c...). New registry teams never widen it silently;
# a wider belief is an owner decision with a new list.
SPREAD_SOURCES = ("A", "B", "C", "PP_0071E895C381DD1C", "PP_097433EFCC505367", "PP_0A93AE91073CC690",
                  "PP_102E046831526921", "PP_1B067B3C97217EAF", "PP_1E6A03DC1764214E", "PP_1F4DA9800A6AD851",
                  "PP_202C514602D9ABE9", "PP_246AECB752FACC29", "PP_24B7E1E280B1088F", "PP_25161F401C0A2005",
                  "PP_297320B831FB73B8", "PP_2C4D3FBB866C4D2C", "PP_2D234B4EC11A9ACA", "PP_2F25D07C9B26E73C",
                  "PP_369E75B64155B6A1", "PP_37083BBE99A1BF42", "PP_3C4611CCBA18D35A", "PP_3E44CC0D5FBA21F8",
                  "PP_470A6EC2468AF8A4", "PP_4BFCE88CE42A966A", "PP_4C6EB1D0D2CBB3F3", "PP_4FCE711199944AE0",
                  "PP_56F0A0120CD736E5", "PP_56F517BBD665899F", "PP_58C15A8BD78B30AB", "PP_5B9FAE64B204F805",
                  "PP_5CEDF6DD944DB220", "PP_5D8E24080B6D3200", "PP_62AA4EF34EE42F01", "PP_674AC2A18201012A",
                  "PP_6853674468737B2E", "PP_6F1B0E8DF51CC57D", "PP_6F1D5B2B15285F2B", "PP_7C9C0663EF60180E",
                  "PP_7F7E07BF0F953B0A", "PP_8025F0AEF5F2D1B6", "PP_81D3F0FFE6EF750C", "PP_8536A2B4F89D3E72",
                  "PP_8606ABBA447D2E2E", "PP_89FAA497014B5641", "PP_8E37C3B00CBBA6B6", "PP_8F4C2600A4A63A90",
                  "PP_90F7CCC7AB5B3D0B", "PP_9F21D2E809A9F09D", "PP_9FED7BFC061AD8BB", "PP_A0582A49F5490809",
                  "PP_A5DFCE8794A63B55", "PP_A702BF47F522438B", "PP_A8154C05ECFA0E20", "PP_A982BEAEE27D32EC",
                  "PP_B80C5F3E363597C2", "PP_BB66FF17A1C4A911", "PP_BED443F8A0ACBE11", "PP_BFE773D9CDA8999C",
                  "PP_C8F60C5168BD6A83", "PP_D3277B02C40781F3", "PP_D3A1849223A946F8", "PP_D668DD98C6C7177B",
                  "PP_D6B2F01DDF4FEE52", "PP_D7C70DFF2BD9F5CF", "PP_D828BB9033A964A0", "PP_D943321333ED8846",
                  "PP_DBC606408D738253", "PP_DDCF443E371A3A19", "PP_DEB9DAC3FF5777D5", "PP_E01AD4BAD0DA9CCC",
                  "PP_E2B7674A54DEBEE7", "PP_E4AA1030C5E684B4", "PP_ECDECC58B9116D68", "PP_EE7A2C6A9F775208",
                  "PP_EEDF279FBC3AD845", "PP_F85133BAC58B317F", "PP_F853DAF986849F1D", "PP_FC5A33ABDD155CA3",
                  "PP_FD6FE5BB94A024FB")


@dataclass(frozen=True)
class LeafRequest:
    """A prepared decision (Honest._prepare): its seat, key, own candidates,
    cut-off flag, world weights, foe pairs and probabilities, the leaves'
    choices and (i, j, w) plan, their copied rows (L, width) float32, step/
    encode/result statuses and tiebreaks, and which leaves the table reads a
    value of (open)."""
    p: int
    key: int
    own: np.ndarray
    last_step: bool
    weights: np.ndarray
    foe_pairs: np.ndarray
    qs: np.ndarray
    choices: np.ndarray
    plan: tuple
    rows: np.ndarray
    step: np.ndarray
    encode: np.ndarray
    results: np.ndarray
    tiebreaks: np.ndarray
    open: np.ndarray


class Unreconstructible(Exception):
    """An explicitly counted absence of a supported public reconstruction, or of a solve: the rm root solver's
    solver_unconverged (D1, #481)."""


# How a refused leaf (its engine step is E_UNSUPPORTED) enters a decision's table (#436): "score" counts it as the
# agent's loss, as the arena does (expert.py keeps it, pinned by its manifest); "drop" removes its own candidate.
REFUSED = ("score", "drop")


def _check_refused(refused):
    if refused not in REFUSED:
        raise ValueError(f"refused must be one of {REFUSED} (got {refused!r})")


def spread_table(ctx, root=None, sources=SPREAD_SOURCES):
    """Read the pinned A/B/C and PP_ stated spreads, never LL_ importer guesses
    (sources=None: every A/B/C and PP_ team of an explicitly chosen root).

    Sets absent from the context's tables cannot occur there; count those
    exclusions. Source ids, counts and hashes are saved beside the table hash.
    """
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2] / "data/teams"
    registry = {r["id"]: r for r in json.loads((root / "index.json").read_text(encoding="utf-8"))["teams"]}
    if sources is None:  # an explicitly chosen registry: all of its stated A/B/C and PP_ teams
        sources = [x for x in registry if x in ("A", "B", "C") or x.startswith("PP_")]
    missing = [x for x in sources if x not in registry]
    if missing:
        raise SearchError(f"pinned spread sources missing from the registry: {missing}")
    sources = [registry[x] for x in sorted(sources)]
    cols = ([], [], [], [], [])
    counts = {"sets": 0, "unstated": 0, "outside_context": 0}
    for t, source in enumerate(sources):
        raw = (root / (source["id"] + ".txt")).read_bytes()
        if teams.text_sha256(raw) != source["sha256"]:
            raise SearchError(f"spread source {source['id']} differs from the registry hash")
        for member in teams.parse(raw.decode("utf-8"), source["id"]):
            sp = member["stat_points"]
            if not any(sp):
                counts["unstated"] += 1
                continue
            try:
                species = data.find(ctx, data.TABLE_SPECIES, data.to_id(member["species"]))
                nature = data.find(ctx, data.TABLE_NATURE, data.to_id(member["nature"]))
                item = 0 if member["item"] is None else 1 + data.find(ctx, data.TABLE_ITEM, data.to_id(member["item"]))
            except duoforge.DuoforgeError as err:
                if err.status_name != "DUOFORGE_E_INVALID_ARGUMENT":
                    raise
                counts["outside_context"] += 1
                continue
            for col, value in zip(cols, (t, species, nature, item, sp)):
                col.append(value)
            counts["sets"] += 1
    table = belief.SpreadTable(*cols)
    return table, {s["id"]: i for i, s in enumerate(sources)}, {**counts, "sources": sources, "sha256": table.sha256()}


# Live play's spread table (owner 2026-10-12): the spreads derived from Smogon's usage stats of Reg M-C (smogon_spreads,
# the committed data/belief table) for every species they name, and the registry's stated A/B/C and PP_ spreads only for
# a species Smogon lacks. Before, the registry alone (8904 sets of 156 species) left a foe species such as Toxapex
# without a prior, and the live search played every decision of such a game raw. A table change fails until re-pinned;
# P1 and the evaluation keep SPREAD_SOURCES.
LIVE_SPREAD_SHA256 = "5f0790722da3c81124f2868ff25ad3a888c70549c0179cc9733fc70577ccf507"


def live_spread_table(ctx, root=None):
    """(table, registry source ids, info) of live play: the Smogon rows first (team -1, no team to leave out), then the
    registry's rows of the species Smogon lacks (team = registry index, left out for its own team)."""
    from . import smogon_spreads
    with open(smogon_spreads.TABLE_PATH, "rb") as f:
        raw = f.read()
    if hashlib.sha256(raw).hexdigest() != smogon_spreads.TABLE_SHA256:
        raise SearchError(f"{smogon_spreads.TABLE_PATH.name} differs from its pinned {smogon_spreads.TABLE_SHA256}")
    smogon = json.loads(raw)
    cols, counts = smogon_spreads.rows(ctx, smogon["species"])
    registry, ids, info = spread_table(ctx, root, sources=None)
    fill = ~np.isin(registry.species, np.asarray(sorted(set(cols[1])), dtype=np.int64))
    table = belief.SpreadTable(
        np.concatenate([np.asarray(cols[0], np.int64), registry.team[fill]]),
        np.concatenate([np.asarray(cols[1], np.int64), registry.species[fill]]),
        np.concatenate([np.asarray(cols[2], np.int64), registry.nature[fill]]),
        np.concatenate([np.asarray(cols[3], np.int64), registry.item[fill]]),
        np.concatenate([np.asarray(cols[4], np.uint8).reshape(-1, belief.STAT_POINTS), registry.spreads[fill]]))
    info = {**info, "sha256": table.sha256(), "registry_rows": int(fill.sum()),
            "registry_species": int(len(set(registry.species[fill].tolist()))),
            "smogon": {**counts, "rows": len(cols[1]), "table": smogon_spreads.TABLE_PATH.name,
                       "table_sha256": smogon_spreads.TABLE_SHA256, "source": smogon["source"]["url"],
                       "derivation": smogon["derivation"]}}
    if info["sha256"] != LIVE_SPREAD_SHA256:
        raise SearchError(f"live spread table {info['sha256']} differs from the pinned {LIVE_SPREAD_SHA256}")
    return table, ids, info


_CAUSES = ((C["DUOFORGE_PUBLIC_CAUSE_VISIBLE_SLEEP"], "visible_sleep"),
           (C["DUOFORGE_PUBLIC_CAUSE_VISIBLE_CONFUSION"], "visible_confusion"),
           (C["DUOFORGE_PUBLIC_CAUSE_ILLUSION_POSSIBLE"], "illusion_possible"),
           (C["DUOFORGE_PUBLIC_CAUSE_SUBSTITUTE"], "substitute"),  # decision 0032 (step G60)
           (C["DUOFORGE_PUBLIC_CAUSE_TEMP_FORME"], "temp_forme"),  # decision 0040 (step G66): Aegislash-Blade
           (C["DUOFORGE_PUBLIC_CAUSE_RAISED_THIS_TURN"], "raised_this_turn"),  # step G72: Alluring Voice at a PIVOT
           (C["DUOFORGE_PUBLIC_CAUSE_TURN_HISTORY"], "turn_history"))  # step G88: Lash Out, Assurance at a PIVOT


def visible_causes(roots, env, player):
    """The causes (names) of environment env's public refusal for player, from the library's own predicate
    (duoforge_batch_public_causes, decision 0026 section 4): a visible sleep or confusion, a possible Illusion, a
    Substitute on either side (decision 0032: its HP is no public fact), a temporary forme the view does not show
    (decision 0040: Aegislash-Blade), a move whose effect reads this turn's history at a PIVOT (Alluring Voice, step
    G72; Lash Out and Assurance, decision 0046). The library decides them from the player's view, so no rule is
    restated here; an empty list is another refusal."""
    players = np.zeros(roots.envs, dtype=np.uint32)
    players[env] = player
    masks, statuses = roots.public_causes(players)
    if statuses[env] != 0:
        raise SearchError(f"public causes refused: {duoforge.status_name(int(statuses[env]))}")
    return cause_names(masks[env])


def cause_names(mask):
    """The names of a DUOFORGE_PUBLIC_CAUSE_* mask's bits, in _CAUSES order."""
    mask = int(mask)
    return [name for bit, name in _CAUSES if mask & bit]


def trapped_positions(record):
    """[bool] * 4, by flat position (side * 2 + position): the positions whose public record shows a hidden partial trap,
    the tail's trap_turns being DUOFORGE_VIEW_HIDDEN (src/state/view.c masks the drawn turns for both viewers). A record
    of a kind without the tail shows none. Only a field of the record is read; what a trap means stays in C."""
    size = int(record["state_size"])
    if size <= state_layout.V3_SIZE:
        return [False] * 4
    state = record["state"]
    return [int(state[_TRAP_TURNS[flat]]) == C["DUOFORGE_VIEW_HIDDEN"] for flat in range(4)]


def trap_picks(words, record):
    """trap_pick of the hypotheses of the worlds (hypothesis revision 3): (n, 4) uint8. A trapped position of the record takes
    the top byte of its world's trap word (belief.WORDS["trap"]); every other position takes zero, as the engine refuses a
    nonzero word where the record shows no hidden trap (E_INVALID_ARGUMENT). The engine maps the byte to the duration.
    record is one record for every world, or one per world (n,)."""
    words = np.asarray(words, dtype=np.uint64)
    picks = (words >> np.uint64(56)).astype(np.uint8)
    if np.ndim(record) == 0:
        picks[:, [not trapped for trapped in trapped_positions(record)]] = 0
        return picks
    for w, r in enumerate(record):  # a record per world (closed team sheets): each world takes its own record's traps
        picks[w, [not trapped for trapped in trapped_positions(r)]] = 0
    return picks


def _record_groups(records):
    """For each world, the first world with the same record (bytes)."""
    first = {}
    return np.array([first.setdefault(r.tobytes(), w) for w, r in enumerate(np.asarray(records))], np.int64)


def _world_history(histories, turn):
    """The team-preview and turn-start records of a record per world from each world's own (record, status) history,
    taken as Honest._observe keeps them: the last unrefused team-selection record, and the last unrefused turn record
    of the current turn with both requests open. A key is set only when every world has its record."""
    previews, starts = [], []
    for past in histories:
        preview = start = None
        for record, status in past:
            if status != 0:
                continue
            boundary = int(record["boundary"])
            if boundary == C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
                preview = record
            elif boundary == C["DUOFORGE_BOUNDARY_TURN"] and int(record["request_mask"]) == 3 \
                    and int(record["turn"]) == turn:
                start = record
        previews.append(preview)
        starts.append(start)
    history = {}
    for key, found in (("preview", previews), ("turn_start", starts)):
        if all(r is not None for r in found):
            out = np.zeros(len(found), dtype=view.PUBLIC_STATE)
            for w, r in enumerate(found):
                out[w] = r
            history[key] = out
    return history


def _world_causes(worlds):
    """The cause names of the worlds whose record is refused (E_UNSUPPORTED), over all of them."""
    refused = np.asarray(worlds["statuses"]) == C["DUOFORGE_E_UNSUPPORTED"]
    mask = 0
    for m in np.asarray(worlds["causes"])[refused]:
        mask |= int(m)
    return cause_names(mask)


def _hex(record):
    """A record's bytes as hex, or a list of the worlds' (a record per world)."""
    return record.tobytes().hex() if np.ndim(record) == 0 else [r.tobytes().hex() for r in record]


def draw_word(probabilities, word):
    """Network categorical draw, in index order, by its separate world word."""
    try:
        return belief.draw_index(probabilities, word)
    except ValueError as err:
        raise SearchError("no probability remains after public-fact filtering") from err


def reduce(tables, weights, qs, prior_rank, uniform, lam, oracle=False, budget=None, solver="lp", prior=None,
           rm_iterations=None, rm_epsilon=None):
    """One strategy for all worlds, with every N/E/X outcome recorded.
    budget: an optional matrix.WorkLedger for the solve (P1 teacher).
    solver (ROOT_SOLVERS; D1 of the depth search, #481): "lp" the exact Bayes LP, "rm" CFR+ (matrix.solve_bayes_rm)
    on the same tables, started from prior (our candidates' probabilities) and the foe probabilities qs; it records its
    gap and iterations and raises matrix.RMUnconverged at rm_iterations (default matrix.RM_MAX_ITERATIONS; rm_epsilon
    default matrix.RM_EPSILON). The ev row, mix and draw are the same. The rm arguments under "lp" are refused."""
    if solver not in ROOT_SOLVERS:
        raise ValueError(f"solver must be one of {ROOT_SOLVERS} (got {solver!r})")
    if solver == "lp" and (prior, rm_iterations, rm_epsilon) != (None, None, None):
        raise ValueError("prior, rm_iterations and rm_epsilon belong to the rm solver (solver is lp)")
    if solver == "rm":
        if oracle or budget is not None:  # the oracle's matrix game and the P1 teacher's ledger stay on the LP
            raise ValueError("the rm solver takes no oracle and no work budget (the P1 teacher stays on the LP)")
        if prior is None:
            raise ValueError("the rm solver needs the own candidates' prior")
        rm = matrix.solve_bayes_rm(tables, weights, prior, qs,
                                   iterations=matrix.RM_MAX_ITERATIONS if rm_iterations is None else rm_iterations,
                                   epsilon=matrix.RM_EPSILON if rm_epsilon is None else rm_epsilon)
        return _outcomes(tables, weights, qs, prior_rank, uniform, lam, rm.solution,
                         {"solver": "rm", "gap": rm.gap, "iterations": rm.iterations})
    # Without a budget the solvers are called exactly as before the teacher existed.
    extra = {} if budget is None else {"budget": budget}
    if oracle:
        single = matrix.solve(tables[0], **extra)
        sol = matrix.BayesSolution(single.x, [single.y], single.value, single.exact)
    else:
        sol = matrix.solve_bayes(tables, weights, **extra)
    # A float basis can leave roundoff at a pure vertex (e.g. 1e-16 on
    # another row). Canonicalize only within four float64 ulps of a vertex,
    # and only if the candidate still satisfies the unchanged certificate.
    def vertex(strategy):
        best = int(np.argmax(strategy))
        if 1.0 - float(strategy[best]) > 4 * np.finfo(np.float64).eps:
            return strategy
        candidate = np.zeros_like(strategy)
        candidate[best] = 1.0
        return candidate

    x, ys = vertex(sol.x), [vertex(y) for y in sol.ys]
    try:
        matrix.bayes_certify(tables, weights, x, ys)
    except SearchError:
        pass  # retain the original certified solution; do not approximate it
    else:
        sol = matrix.BayesSolution(x, ys, sol.value, sol.exact)
    return _outcomes(tables, weights, qs, prior_rank, uniform, lam, sol, {})


def _outcomes(tables, weights, qs, prior_rank, uniform, lam, sol, extra):
    """reduce's N/E/X outcomes and record from a solution sol; extra: the solver's own fields (none for the LP)."""
    expected = matrix.bayes_expected_values(tables, weights, qs)
    best = np.flatnonzero(expected == expected.max())
    ev = int(best[np.argmin(np.asarray(prior_rank)[best])])
    mixed = matrix.mix(sol.x, ev, lam)
    return {"nash": matrix.draw(sol.x, prior_rank, uniform), "ev": ev,
            "mix": matrix.draw(mixed, prior_rank, uniform)}, {
                "x": sol.x.tolist(), "ys": [y.tolist() for y in sol.ys], "value": sol.value,
                "exact": sol.exact, "expected": expected.tolist(), "pi_X": mixed.tolist(),
                "u": uniform, "lam": lam,
                "support": [int((sol.x >= matrix.PROBABILITY_FLOOR).sum()),
                            int(sum((y >= matrix.PROBABILITY_FLOOR).sum() for y in sol.ys))], **extra}


class Honest(lookahead.Lookahead):
    def __init__(self, context, model, params, encoder, ext_supported, k=8, m=8, s=16, rule="mix",
                 seed=lookahead.SEARCH_SEED, capacity=lookahead.CAPACITY, workers=8, lam=0.5,
                 table=None, exclude_teams=None, preview_mode="raw", preview_only=False, preview_steps=16,
                 species_prior=False, foe_net=None, preview_rule=None, preview_width="top", root_solver="lp",
                 rm_iterations=None, rm_epsilon=None, depth=1, k2=None, m2=None, chance=None, info_key=None,
                 evaluator=None, foe_below=None, tree_iterations=None):
        # species_prior (live play, owner 2026-10-10): True refuses a decision whose foe species has no stated spread in
        # the table instead of drawing from the belief's nature-only or table-wide levels (4 and 5); "count" (owner
        # 2026-10-12, live play) draws from those general levels and names the species in the record: spread_fallback
        # for one without any spread of its own, spread_redrawn for one whose spreads a redraw exhausted (as True
        # names the two refusals apart); False draws from them unnamed (P1, the evaluation).
        if not (type(species_prior) is bool or species_prior == "count" and type(species_prior) is str):
            raise ValueError(f"species_prior must be False, True or 'count' (got {species_prior!r})")
        self.species_prior = species_prior
        self._spread_fallback, self._spread_redrawn = [], []
        # foe_net (M7, owner 2026-10-11): (model, params, encoder, ext_supported) of a second network that models the
        # foe. Every policy call on the worlds (the foe's team draw, its queued pair and its menu) goes to it, encoded
        # with its own encoder; the own candidates (the root's policy) and the leaf values stay with the main network.
        # None: the main network models the foe, as before. A value preview (step 1 of the ladder, #440) takes its foe
        # candidates from it the same way. A turn1 preview's rollout plays the foe seat with it too (step 1b, #440, the
        # rollout takes the foe seat's rows from the foe encoding and its policy from the foe network), so every preview
        # form takes the foe seat from the foe network; the player's seat and the leaf values stay with the main one.
        self.foe_net = None
        if foe_net is not None:
            if len(foe_net) != 4:
                raise ValueError("a foe network is (model, params, encoder, ext_supported)")
            foe_model, foe_params, foe_encoder, foe_ext = foe_net
            width = features.obs_size(foe_encoder)
            if width != len(foe_model.feature_names):
                raise ValueError(f"the foe network reads {len(foe_model.feature_names)} values, its encoder "
                                 f"{foe_encoder} gives rows of {width}")
            if int(foe_ext) & ~features.version_features(foe_encoder):
                raise ValueError(f"the foe network's extension mask {int(foe_ext):#x} names features encoder "
                                 f"{foe_encoder} does not have")
            self.foe_net = (foe_model, foe_params, int(foe_encoder), int(foe_ext))
        if rule not in RULES or not 0 <= lam <= 1:
            raise ValueError("honest search needs nash/ev/mix and 0 <= lam <= 1")
        # root_solver (D1 of the depth search, #481): the turn decisions' solver (ROOT_SOLVERS). "rm" has no tableau,
        # so the LP size limit applies to it no longer; its own bound is rm_iterations (default
        # matrix.RM_MAX_ITERATIONS), its gap target rm_epsilon (matrix.RM_EPSILON), its named fallback
        # solver_unconverged. The team preview stays on the LP and keeps the limit. Under "lp" the rm settings are
        # refused, not ignored.
        if root_solver not in ROOT_SOLVERS:
            raise ValueError(f"root_solver must be one of {ROOT_SOLVERS} (got {root_solver!r})")
        if root_solver == "lp" and (rm_iterations is not None or rm_epsilon is not None):
            raise ValueError("rm_iterations and rm_epsilon require root_solver 'rm'")
        if root_solver == "rm":
            rm_iterations = matrix.RM_MAX_ITERATIONS if rm_iterations is None else rm_iterations
            rm_epsilon = matrix.RM_EPSILON if rm_epsilon is None else rm_epsilon
            if type(rm_iterations) is not int or rm_iterations < 1 or not 0 < float(rm_epsilon) < 1:
                raise ValueError(f"the rm solver needs rm_iterations >= 1 and 0 < rm_epsilon < 1 "
                                 f"(got {rm_iterations!r}, {rm_epsilon!r})")
            rm_epsilon = float(rm_epsilon)
        self.root_solver, self.rm_iterations, self.rm_epsilon = root_solver, rm_iterations, rm_epsilon
        # depth (D2 of the depth search, plan step 4): 2 solves a two-turn tree below the turn decisions' root with
        # CFR+ (so it needs root_solver "rm"), k2 / m2 candidates per depth-1 information set / foe node, chance
        # samples per edge (1; more is a later step), the observation key of our depth-1 nodes (infokey: "digest", or
        # "record" for tests), the leaf evaluator (evaluator: "jax", or #485's "engine"), the foe below the root
        # (foe_below, Q4) and the tree solver's iteration bound (tree_iterations, gap target rm_epsilon). Under depth
        # 1 the tree settings are refused, not ignored. A depth-2 decide needs steps_left (decide).
        settings = {"k2": k2, "m2": m2, "chance": chance, "info_key": info_key, "evaluator": evaluator,
                    "foe_below": foe_below, "tree_iterations": tree_iterations}
        if depth not in DEPTHS or type(depth) is not int:
            raise ValueError(f"depth must be one of {DEPTHS} (got {depth!r})")
        if depth == 1 and any(v is not None for v in settings.values()):
            raise ValueError(f"{[n for n, v in settings.items() if v is not None]} require depth 2")
        self.depth, self._keys, self.nodes, self._node_batch, self.evaluator = depth, None, None, None, None
        self.k2 = self.m2 = self.chance = self.info_key = self.foe_below = self.tree_iterations = None
        if depth == 2:
            if root_solver != "rm":
                raise ValueError("depth 2 needs root_solver 'rm' (the tree is solved by CFR+; the LP has no tree)")
            k2, m2 = 2 if k2 is None else k2, 2 if m2 is None else m2
            chance, foe_below = 1 if chance is None else chance, "nash" if foe_below is None else foe_below
            tree_iterations = tree.TREE_MAX_ITERATIONS if tree_iterations is None else tree_iterations
            for name, value in (("k2", k2), ("m2", m2), ("tree_iterations", tree_iterations)):
                if type(value) is not int or value < 1:
                    raise ValueError(f"{name} must be a positive int (got {value!r})")
            if chance != 1:
                raise ValueError(f"chance must be 1 (got {chance!r}): more samples per edge are a later step")
            if foe_below not in tree.FOE_BELOW:
                raise ValueError(f"foe_below must be one of {tree.FOE_BELOW} (got {foe_below!r})")
            info_key = "digest" if info_key is None else info_key
            self._keys = infokey.make(info_key)  # "digest": refused by name in a library without the call
            evaluator = "jax" if evaluator is None else evaluator
            if evaluator not in evaluators.EVALUATORS:
                raise ValueError(f"evaluator must be one of {evaluators.EVALUATORS} (got {evaluator!r})")
            if evaluator != "jax":
                evaluators.make(evaluator)  # "engine" is refused by name until #485's call exists
            self.k2, self.m2, self.chance, self.info_key = k2, m2, chance, info_key
            self.foe_below, self.tree_iterations = foe_below, tree_iterations
        if k != 1 and (root_solver == "lp" or preview_mode != "raw"):
            # one candidate plays raw and solves nothing; the turns' and the top preview's LPs are k x m x s
            matrix.check_bayes_size(k, m, s, "the honest search" if root_solver == "lp" else "the team preview's LP")
        if preview_mode not in ("raw", "value", "turn1") or type(preview_steps) is not int or preview_steps < 1:
            raise ValueError("preview requires raw/value/turn1 and a positive rollout bound")
        if preview_only and preview_mode == "raw":
            raise ValueError("preview_only requires preview search")
        # preview_rule (step 1 of the ladder, #440): the rule that plays the team preview's table, None for the search's
        # own rule. A raw search has no preview to play, so naming one there is refused, not ignored.
        if preview_rule is not None and preview_rule not in RULES:
            raise ValueError(f"preview_rule must be None or one of {RULES} (got {preview_rule!r})")
        if preview_rule is not None and preview_mode == "raw":
            raise ValueError("preview_rule requires a preview search (preview_mode value or turn1)")
        self.preview_mode, self.preview_only, self.preview_steps = preview_mode, preview_only, preview_steps
        self.preview_rule = preview_rule
        # preview_width (#440, owner 2026-10-13): the preview's candidates, "top" tuples of the team heads or one
        # "distinct" tuple per bring-and-lead combination with every own member covered (preview.distinct); "seats"
        # the same with the lead seats kept, only the bench order merged (the correction of #462's review).
        from . import preview
        if preview_width not in preview.WIDTHS:
            raise ValueError(f"preview_width must be one of {preview.WIDTHS} (got {preview_width!r})")
        if preview_width != "top" and preview_mode == "raw":
            raise ValueError("preview_width requires a preview search (preview_mode value or turn1)")
        if preview_width != "top" and k == 1:  # one candidate plays raw: no preview table to widen
            raise ValueError("preview_width requires k > 1 (with k = 1 the preview plays raw)")
        if preview_width != "top":  # the cover adds up to preview.COVER_MAX own rows to the preview's table
            matrix.check_bayes_size(k + preview.COVER_MAX, m, s, f"the {preview_width} preview")
        self.preview_width = preview_width
        if table is None:
            table, _, self.table_info = spread_table(context)
        else:
            self.table_info = {"sha256": table.sha256(), "sets": len(table.team)}
        self.belief = belief.Belief(table)
        self.lam = float(lam)
        self.exclude_teams = exclude_teams
        self.history = weakref.WeakKeyDictionary()
        self.worlds = None
        self._searched = False  # the worlds are a searched turn decision's root worlds (world_policies reads them)
        super().__init__(context, model, params, encoder, ext_supported, k, m, s, "nash", seed, capacity, workers, lam=lam)
        self.rule = rule
        try:
            self.worlds = duoforge.Batch(context, np.resize(duoforge.reference_setups([0]), self.s), workers, seed)
            if self.depth == 2:  # the depth-1 nodes: one environment per root edge (spec section 7.3)
                self._node_batch = duoforge.Batch(context, np.resize(duoforge.reference_setups([0]),
                                                                     self.s * self.k * self.m * self.chance),
                                                  workers, seed)
                # the key's view of it: the batch itself (record), or the digest call's adapter with its sidecar
                self.nodes = self._keys.nodes(self._node_batch)
                self.evaluator = evaluators.make(evaluator, leaves=self.leaves, model=self.model, params=self.params,
                                                 encoder=self.encoder, ext_supported=self.ext_supported,
                                                 rows=self._rows)
        except BaseException:
            for batch in (self.worlds, self._node_batch):
                if batch is not None:
                    batch.close()
            super().close()
            raise

    def close(self):
        if self.worlds is not None:
            self.worlds.close()
        if self._node_batch is not None:
            self._node_batch.close()
        super().close()

    def clear(self):
        self.history.clear()

    def _policy(self, obs, slots, pairs, net=None):
        """The pair and team log-probabilities of the main network, or of net (a foe_net)."""
        model, params = (self.model, self.params) if net is None else net[:2]
        inputs = (np.ascontiguousarray(obs), np.ascontiguousarray(slots), np.ascontiguousarray(pairs))
        model.check(inputs[0])
        shape = tuple(x.shape for x in inputs)
        compiled = shape if net is None else ("foe",) + shape
        if compiled not in self._compiled:
            np.asarray(model.apply(params, *inputs)[0])
            self._compiled.add(compiled)
        t = time.perf_counter()
        pair, team, _ = model.apply(params, *inputs)
        return np.asarray(pair), np.asarray(team), time.perf_counter() - t

    def _per_world(self, record):
        """(s,) records: one record for every world (open sheets), or the worlds' own records (closed team sheets,
        decision 0081: world w is built from particle w's record), whose public header fields must agree."""
        record = np.asarray(record)
        if record.shape == ():
            return np.repeat(record.reshape(1), self.s)
        if record.shape != (self.s,):
            raise SearchError(f"{record.size} world records for {self.s} worlds")
        for name in record.dtype.names:
            if name not in ("state", "pad") and (record[name] != record[name][0]).any():
                raise SearchError(f"the worlds' records disagree on the public field {name}")
        return record

    def _build(self, record, hypotheses):
        self._searched = False  # rebuilt: no searched decision's worlds until _prepare runs on them
        statuses = self.worlds.from_view(self._per_world(record), hypotheses).copy()
        if (statuses == C["DUOFORGE_E_UNSUPPORTED"]).any():
            raise Unreconstructible("DUOFORGE_E_UNSUPPORTED: world build")
        bad = np.flatnonzero((statuses != 0) & (statuses != C["DUOFORGE_E_INVALID_ARGUMENT"]))
        if bad.size:
            raise SearchError(f"world {bad[0]} refused: {duoforge.status_name(int(statuses[bad[0]]))}")
        return statuses

    def _world_policy(self):
        """The worlds' policy, the foe's model: the foe network's (its encoder's rows) when one is given."""
        encoder, ext = (self.encoder, self.ext_supported) if self.foe_net is None else self.foe_net[2:]
        start = time.perf_counter()
        obs, slots, pairs = self.worlds.query_encoded(encoder, ext)
        query_seconds = time.perf_counter() - start
        pp, pt, seconds = self._policy(obs.reshape(2 * self.s, -1), slots.reshape((2 * self.s,) + slots.shape[2:]),
                                       pairs.reshape((2 * self.s,) + pairs.shape[2:]), self.foe_net)
        return (pp.reshape(self.s, 2, -1), pt.reshape(self.s, 2, -1), seconds,
                pairs.copy(), obs.copy(), slots.copy(), query_seconds)

    def world_policies(self, seat):
        """The foe model's view of the turn decision just searched, read only (#440: the KO check's probes, the live
        evaluation's foe-model metric): (logp, masks), seat's pair log-probabilities under the worlds' policy (the foe
        network's when one is given, as _world_policy) and its pair masks, one row of lookahead.OPTIONS ** 2 per world,
        as the policy gives them and as bool, both copies.

        It decides nothing and changes no state a decision reads: it queries the worlds' encoding as they stand and
        runs the network on them, as the search's own query does. The worlds are the root worlds of the last root of the
        last decide() call whose turn decision was searched (reached _prepare; roots in decide()'s order), as _prepare
        read them; a deeper search keeps them as its root (the depth-2 tree's nodes live apart). SearchError when that
        call searched no turn decision (a preview, a forced or raw choice, a refusal before the search) or the worlds
        were rebuilt since (any _build: a later root's hypotheses, a preview), and before any decision."""
        if isinstance(seat, (bool, np.bool_)) or not isinstance(seat, (int, np.integer)) or seat not in (0, 1):
            raise ValueError(f"seat must be 0 or 1 (got {seat!r})")
        if self.worlds is None or not self._searched:
            raise SearchError("world_policies: no searched turn decision's worlds (none in the last decide() call, or rebuilt since)")
        pp, _, _, masks, _, _, _ = self._world_policy()
        return (np.array(pp[:, seat], copy=True),
                np.asarray(masks[:, seat], dtype=bool).reshape(self.s, -1).copy())

    def _hypotheses(self, record, observation, history, key, excluded, costs):
        """The worlds' hypotheses of a record and the player's observation: one of each for every world, or one per
        world (closed team sheets: world w draws the spreads of particle w's members, its record and observation)."""
        if "preview" not in history:
            raise Unreconstructible("missing team-preview record")
        # One record for every world (open sheets) is built and checked as it is; a record per world as the worlds'
        # records, whose public header fields agree (_per_world), so the first one's stand for all.
        per_world = np.ndim(record) != 0
        built = self._per_world(record) if per_world else record
        if per_world:
            record = built[0]
        observations = observation if per_world else [observation]
        foe = 1 - int(record["player"])
        rosters = []
        for o in observations:
            side = o["sides"][foe]
            rosters.append([(int(m["species_id"]), int(m["nature"]), int(m["item"]))
                            for m in side["members"][:int(side["member_count"])]])
        if len(rosters) != (self.s if per_world else 1):
            raise SearchError(f"{len(rosters)} observations for {self.s} world records")
        if any([m[0] for m in r] != [m[0] for m in rosters[0]] for r in rosters):
            raise SearchError("the worlds' observations disagree on the foe's species")
        members = rosters[0]  # the species, which every world shares (the team preview shows them)
        attempts = np.zeros((self.s, 6), np.int64)
        dropped = respreads = 0
        queue_mask = None
        pivot = int(record["boundary"]) == C["DUOFORGE_BOUNDARY_PIVOT"]
        # A public PIVOT record carries no pending foe command since the view audit of 2026-10-10 (a silent flinch may be
        # outstanding on a position still to move, so such a PIVOT is refused): the queue mask and its turn-start world
        # are needed only for a record that still has one.
        if pivot and int(record["foe_pending_mask"]) != 0:
            start = history.get("turn_start")
            first = None if start is None else np.asarray(start).reshape(-1)[0]
            if first is None or int(first["turn"]) != int(record["turn"]) or int(first["player"]) != int(record["player"]):
                raise Unreconstructible("missing or stale turn-start record")
            t = time.perf_counter()
            try:
                if per_world:
                    queue_mask = self._queue_masks(history["turn_start"], built)
                else:
                    mask = duoforge.queue_mask(self.worlds.context, history["turn_start"], record)
                    queue_mask = [mask] * self.s
            except duoforge.DuoforgeError as err:
                if err.status_name == "DUOFORGE_E_UNSUPPORTED":
                    raise Unreconstructible("DUOFORGE_E_UNSUPPORTED: queue mask") from err
                raise
            finally:
                costs["public_records"] += time.perf_counter() - t
        initial = None
        if self.species_prior is not False:  # from the first draw's level: a redraw raises it (SpreadTable.draw)
            initial = np.array([[self.belief.table.candidates(sp, nature, item, excluded)[0]
                                 for sp, nature, item in roster] for roster in rosters], np.int64).reshape(len(rosters), -1)
            missing = [members[m][0] for m in range(len(members)) if (initial[:, m] >= 4).any()]
            if missing and self.species_prior is True:
                raise Unreconstructible(f"no spread prior for foe species {missing}")
        for _ in range(MAX_RESPREADS):
            t = time.perf_counter()
            if per_world:  # world w draws for particle w's members (natures and items)
                sampled = self.belief.sample_worlds(rosters, self.seed, key, excluded, attempts)
            else:
                sampled = self.belief.sample(members, self.s, self.seed, key, excluded, attempts)
            if self.species_prior is True:
                past = np.flatnonzero((sampled["levels"][:, :len(members)] >= 4).any(axis=0))
                if past.size:  # every stated spread of the species contradicted the public view
                    raise Unreconstructible(f"redraw past the species prior for foe species "
                                            f"{[members[m][0] for m in past]} after {respreads} respreads")
            weights = sampled["weights"]
            h = view.hypotheses(self.s)
            for name in ("stat_points", "hp", "sleep", "confusion", "charge_target"):
                h[name] = sampled[name]
            # trap_pick (G90, hypothesis revision 3): a word only at the positions the built record shows trapped, so each
            # build below takes the words of its own record; the preview record has no trap
            h["trap_pick"] = trap_picks(sampled["trap"], history["preview"])
            if self._build(history["preview"], h).any():
                raise SearchError("a sampled spread is invalid at team preview")
            self._check_worlds(history["preview"], costs)  # the preview record is assembled like the root
            costs["world_builds"] += time.perf_counter() - t
            _, team, elapsed, _, _, _, query_seconds = self._world_policy()
            costs["world_builds"] += query_seconds
            costs["team_head"] += elapsed
            keep = np.all(TEAM_TABLE[:, :2] == record["foe_leads"], axis=1)
            for m in range(6):
                if int(record["foe_seen_mask"]) & (1 << m):
                    keep &= (TEAM_TABLE == m).any(axis=1)
            dropped = int((~keep).sum()) * self.s
            for w in range(self.s):
                probs = np.exp(team[w, foe].astype(np.float64)) * keep
                h[w]["pick_order"][:TEAM_TABLE.shape[1]] = TEAM_TABLE[draw_word(probs, sampled["bench"][w])]
            queue_pairs = []
            if queue_mask is not None:
                t = time.perf_counter()
                h["trap_pick"] = trap_picks(sampled["trap"], history["turn_start"])
                st = self._build(history["turn_start"], h)
                costs["world_builds"] += time.perf_counter() - t
                if st.any():
                    attempts[st != 0] += 1
                    respreads += int((st != 0).sum())
                    continue
                self._check_worlds(history["turn_start"], costs)
                pp, _, elapsed, legal, _, _, query_seconds = self._world_policy()
                costs["world_builds"] += query_seconds
                costs["network"] += elapsed
                for w in range(self.s):
                    probs = np.exp(pp[w, foe].astype(np.float64)) * queue_mask[w].reshape(-1) * legal[w, foe].reshape(-1)
                    pair = draw_word(probs, sampled["queue"][w])
                    queue_pairs.append(pair)
                    indices = divmod(pair, lookahead.OPTIONS)
                    for p in range(2):
                        if int(record["foe_pending_mask"]) & (1 << p):
                            h[w]["queued"][p] = self.worlds.domains[w, foe]["slots"][p, indices[p]]
            if pivot:
                for w in range(self.s):
                    h[w]["queue_order"][:int(record["queue_count"])] = np.arange(int(record["queue_count"]), dtype=np.uint8)
            t = time.perf_counter()
            h["trap_pick"] = trap_picks(sampled["trap"], built)
            statuses = self._build(built, h)
            costs["world_builds"] += time.perf_counter() - t
            if not statuses.any():
                self._check_worlds(built, costs)
                if initial is not None:  # the species drawn from the general levels (species_prior "count")
                    general = (sampled["levels"][:, :len(members)] >= 4) & (initial < 4)
                    self._spread_fallback = sorted({members[m][0] for m in range(len(members))
                                                    if (initial[:, m] >= 4).any()})
                    self._spread_redrawn = sorted({members[m][0] for m in np.flatnonzero(general.any(axis=0))}
                                                  - set(self._spread_fallback))
                return h, weights, dropped, respreads, queue_pairs
            # The current C API reports a failed world, not the member. Redraw
            # all its spreads; keep its HP/counter/bench/queue words unchanged.
            attempts[statuses != 0] += 1
            respreads += int((statuses != 0).sum())
        raise SearchError(f"a world still contradicts the public view after {MAX_RESPREADS} spread draws")

    def _queue_masks(self, turn_start, records):
        """(s, OPTIONS, OPTIONS): each world's queue mask (duoforge.queue_mask) of its turn-start record and its record,
        computed once per distinct pair (one call when every world shares one record)."""
        starts = self._per_world(turn_start)
        out, seen = [], {}
        for start, record in zip(starts, records):
            k = (start.tobytes(), record.tobytes())
            if k not in seen:
                seen[k] = np.asarray(duoforge.queue_mask(self.worlds.context, start, record))
            out.append(seen[k])
        return np.stack(out)

    def _engine_pairs(self, p):
        """(OPTIONS, OPTIONS) bool: the pairs the engine's domain allows seat p in the built worlds, which agree on
        it (the seat's own side is exact in every world); SearchError if they do not."""
        self.worlds.query_factored()
        masks = np.zeros((self.s, lookahead.OPTIONS, lookahead.OPTIONS), bool)
        for w in range(self.s):
            d = self.worlds.domains[w, p]
            bits = np.asarray(d["allowed"], np.uint64)[:int(d["slot_count"][0])]
            for i, row in enumerate(bits):
                masks[w, i, :int(d["slot_count"][1])] = (int(row) >> np.arange(int(d["slot_count"][1]))) & 1
        if (masks != masks[0]).any():
            raise SearchError("the worlds disagree on the searcher's own pairs")
        return masks[0]

    def _check_worlds(self, record, costs):
        """Every world built from a record (the root, the team preview's, the turn start's) gives it back (from_view, then public, byte for byte). A
        record assembled outside the engine (the live tracker's) that fills a field the engine masks, or contradicts
        itself, stops here with the differing fields named, instead of being searched. Engine records always pass
        (duoforge.view); the check costs one public() call per decision. With a record per world, each world gives its own
        back."""
        records = self._per_world(record)
        t = time.perf_counter()
        again, statuses = self.worlds.public(np.full(self.worlds.envs, int(records[0]["player"]), np.uint32))
        costs["public_records"] += time.perf_counter() - t
        for w in range(self.s):
            record = records[w]
            if int(statuses[w]) == 0 and again[w].tobytes() == record.tobytes():
                continue
            if int(statuses[w]) != 0:
                raise SearchError(f"world {w} built from the record refuses its public record "
                                  f"({duoforge.status_name(int(statuses[w]))})")
            header = [name for name in record.dtype.names if name not in ("state", "pad")
                      and not np.array_equal(np.asarray(record[name]), np.asarray(again[w][name]))]
            size = int(record["state_size"])
            fields = state_layout.diff(np.asarray(record["state"])[:size].tobytes(),
                                       np.asarray(again[w]["state"])[:size].tobytes(), pool=size > state_layout.V3_SIZE)
            raise SearchError(f"world {w} does not give its record back: header {header}, state fields {fields}")

    def decide(self, roots, envs, seats, keys, last_step, steps_left=None):
        """steps_left (D2, the plan's decision 2): each decision's steps left in the arena with this one (1 at its last
        step, so exactly where last_step), or NO_STEP_LIMIT (live play). A depth-2 search needs it to know where its
        depth-2 leaves are cut off (2 steps left), and refuses None; depth 1 checks it and decides without it."""
        self._searched = False  # world_policies reads a turn decision of this call only
        envs, seats = np.asarray(envs, np.int64), np.asarray(seats, np.int64)
        keys, last_step = np.asarray(keys, np.uint64), np.asarray(last_step, bool)
        n = envs.size
        if any(x.shape != (n,) for x in (envs, seats, keys, last_step)) or len(set(envs.tolist())) != n or \
                (envs < 0).any() or (envs >= roots.envs).any() or not np.isin(seats, [0, 1]).all():
            raise ValueError("decisions need unique valid environments and one seat/key/last-step flag each")
        if steps_left is None:
            if self.depth == 2:
                raise ValueError("a depth-2 search needs steps_left (NO_STEP_LIMIT without the arena's step limit); "
                                 "None is never a default")
        else:
            steps_left = np.asarray(steps_left)
            if steps_left.shape != (n,) or not np.issubdtype(steps_left.dtype, np.integer) or \
                    ((steps_left < 1) & (steps_left != NO_STEP_LIMIT)).any() or (last_step != (steps_left == 1)).any():
                raise ValueError("steps_left needs one count >= 1 or NO_STEP_LIMIT per decision, 1 exactly where "
                                 "last_step")
        if not n:
            return np.zeros(0, np.int64), []
        t = time.perf_counter()
        obs, slots, pairs = roots.query_encoded(self.encoder, self.ext_supported)
        players = np.zeros(roots.envs, np.uint32)
        players[envs] = seats
        records, statuses = roots.public(players)
        public_time = (time.perf_counter() - t) / n
        # The network sees only the viewer's rows of the real root.
        pp, pt, network_time = self._policy(obs[envs, seats], slots[envs, seats], pairs[envs, seats])
        actions, output = np.zeros(n, np.int64), []
        self.last = []
        for d, (e, p) in enumerate(zip(envs, seats)):
            e, p = int(e), int(p)
            costs = {k: 0.0 for k in ("public_records", "world_builds", "team_head", "leaves", "network", "solve")}
            if self.depth == 2:  # the tree's phases, each also counted in the parts above (D2's offline pass reads them)
                costs.update(dict.fromkeys(TREE_PHASES, 0.0))
            costs["public_records"], costs["network"] = public_time, network_time / n
            worlds = self._worlds_of(roots, e, p)
            if worlds is None:  # one record for every world
                record, status, observation = records[e:e + 1].reshape(()).copy(), int(statuses[e]), \
                    roots.observations[e, p]
                own_logp, team_logp, groups = pp[d], pt[d], None
            else:  # closed team sheets (decision 0081): world w is built from the worlds' record w
                record, observation = worlds["records"], worlds["observations"]
                status = self._world_status(worlds["statuses"])
                own_logp, team_logp, seconds = self._mean_policy(worlds, obs[e, p], slots[e, p], pairs[e, p], pp[d],
                                                                 pt[d])
                costs["network"] += seconds
                groups = _record_groups(record)
            # a record per world: each world's own history, never the search's memory of an earlier particle there
            history = self._observe(roots, e, p, record, status) if worlds is None else \
                _world_history(worlds["histories"], int(roots.observations[e, p]["turn"]))
            boundary = int(roots.requests[e, p]["boundary_kind"])
            base = {"env": e, "seat": p, "key": int(keys[d]), "epoch": int(roots.requests[e, p]["epoch"]),
                    "boundary": lookahead._BOUNDARIES[boundary], "last_step": bool(last_step[d]),
                    "search": "honest", "w": self.s, "table_sha256": self.table_info["sha256"], "lam": self.lam}
            if self.root_solver != "lp":  # the default's record stays as it was
                base["root_solver"] = {"solver": self.root_solver, "max_iterations": self.rm_iterations,
                                       "epsilon": self.rm_epsilon}
            if self.foe_net is not None:  # which encoding modelled the foe (a reproduction needs it)
                base["foe_net"] = {"encoder": self.foe_net[2], "ext_supported": self.foe_net[3]}
            if self.depth != 1:  # the default's record stays as it was
                base["depth"] = {"depth": self.depth, "k2": self.k2, "m2": self.m2, "chance": self.chance,
                                 "info_key": self.info_key, "evaluator": self.evaluator.name,
                                 "foe_below": self.foe_below, "max_iterations": self.tree_iterations,
                                 "epsilon": self.rm_epsilon}
            if boundary == C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
                actions[d] = int(np.argmax(team_logp))
                result = {"kind": "team", "choice": int(actions[d])}
                if self.preview_mode != "raw" and self.k != 1:
                    excluded = None if self.exclude_teams is None else self.exclude_teams[e]
                    try:
                        if status == C["DUOFORGE_E_UNSUPPORTED"]:
                            raise Unreconstructible("preview_public_record_unsupported")
                        if status != 0:
                            raise SearchError(f"preview public record refused: {duoforge.status_name(status)}")
                        from . import preview
                        result = preview.decide(self, record, observation, p, int(keys[d]),
                                                team_logp, excluded, bool(last_step[d]), costs)
                        actions[d] = result["choice"]
                    except Unreconstructible as error:
                        result.update(kind="unreconstructible", reason=str(error), causes=[str(error)])
                    except (SearchError, duoforge.DuoforgeError, ValueError) as error:
                        stop = SearchError(str(error))
                        stop.reproduction = {**base, "public_view": _hex(record) if status == 0 else None}
                        raise stop from error
            else:
                own, own_p = lookahead.select(own_logp, pairs[e, p], self.k)
                actions[d] = int(own[0])
                result = {"kind": "forced" if pairs[e, p].sum() == 1 else "raw", "choice": int(actions[d])}
                excluded = None if self.exclude_teams is None else self.exclude_teams[e]
                if result["kind"] != "forced" and self.k != 1 and not self.preview_only:
                    try:
                        if status == C["DUOFORGE_E_UNSUPPORTED"]:
                            names = visible_causes(roots, e, p) if worlds is None else _world_causes(worlds)
                            result["causes"] = names or ["public_record_unsupported"]
                            raise Unreconstructible("DUOFORGE_E_UNSUPPORTED: public record")
                        if status != 0:
                            raise SearchError(f"public record refused: {duoforge.status_name(status)}")
                        hypotheses, weights, dropped, respreads, queue_pairs = self._hypotheses(record, observation, history,
                                                                         int(keys[d]), excluded, costs)
                        # A root's pair mask may be provisional (the live tracker's: Showdown judges a pair); the own
                        # candidates are the engine's own pairs of the worlds (the searcher's side is exact in each).
                        root_mask = np.asarray(pairs[e, p], bool).reshape(lookahead.OPTIONS, lookahead.OPTIONS)
                        legal = root_mask & self._engine_pairs(p)
                        if not legal.any():
                            raise SearchError("no pair of the root's mask is in the engine's domain")
                        if (legal != root_mask).any():
                            own, own_p = lookahead.select(own_logp, legal, self.k)
                        result = self._decision(p, int(keys[d]), own, own_p, weights, bool(last_step[d]), costs,
                                                refused="drop", groups=groups,
                                                steps_left=None if steps_left is None else int(steps_left[d]))
                        result["cut_pairs"] = int((root_mask & ~legal).sum())  # the root's pairs the engine refuses
                        self.last[-1]["hypotheses"] = hypotheses.copy()
                        result.update({"bench_dropped": dropped, "respreads": respreads, "exclude_team": excluded,
                                       "queue_pairs": queue_pairs})
                        if self.species_prior == "count":  # the foe species drawn from the general levels, named
                            result["spread_fallback"] = list(self._spread_fallback)
                            result["spread_redrawn"] = list(self._spread_redrawn)
                        actions[d] = result["choice"]
                    except Unreconstructible as err:
                        result.update({"kind": "unreconstructible", "reason": str(err)})
                        result.setdefault("causes", [str(err)])
                        if isinstance(err.__cause__, matrix.RMUnconverged):  # its gap, recorded with the fallback
                            result["gap"], result["iterations"] = err.__cause__.gap, err.__cause__.iterations
                    except (SearchError, duoforge.DuoforgeError, ValueError) as err:
                        stop = SearchError(str(err))
                        stop.reproduction = {**getattr(err, "reproduction", {}), **base,
                                             "public_view": _hex(record) if status == 0 else None,
                                             "search_seed": self.seed, "exclude_team": excluded,
                                             "preview": _hex(history["preview"]) if "preview" in history else None,
                                             "turn_start": _hex(history["turn_start"]) if "turn_start" in history else None}
                        raise stop from err
            output.append({**base, **result, "cost": costs,
                           "time": {"network": costs["network"] + costs["team_head"],
                                    "engine": costs["public_records"] + costs["world_builds"] + costs["leaves"],
                                    "reduction": costs["solve"], "split": 0.0}})
        return actions, output

    def _observe(self, roots, e, p, record, status):
        """The public history of seat p in environment e (team preview,
        turn start), updated from its current request; returns it."""
        if roots.requests[e, p]["requested"] == 0:
            raise ValueError(f"seat {p} of environment {e} has no request")
        histories = self.history.setdefault(roots, {})
        episode = roots.episode(e)
        history = histories.setdefault((e, p), {})
        if history.get("episode") != episode:
            history.clear()
            history["episode"] = episode
        boundary = int(roots.requests[e, p]["boundary_kind"])
        current_turn = int(roots.observations[e, p]["turn"])
        start = history.get("turn_start")
        if start is not None and int(np.asarray(start).reshape(-1)[0]["turn"]) != current_turn:
            history.pop("turn_start")
        if boundary == C["DUOFORGE_BOUNDARY_TURN"] and roots.requests[e, 0]["requested"] and roots.requests[e, 1]["requested"]:
            history.pop("turn_start", None)
        if status == 0:  # a record per world (closed team sheets) is kept as the worlds' records
            if boundary == C["DUOFORGE_BOUNDARY_TEAM_SELECTION"]:
                history["preview"] = record.copy()
            if boundary == C["DUOFORGE_BOUNDARY_TURN"] and int(np.asarray(record).reshape(-1)[0]["request_mask"]) == 3:
                history["turn_start"] = record.copy()
        return history

    def _worlds_of(self, roots, e, p):
        """The worlds' own parts of seat p in environment e (RecordRoots.set_worlds), or None. ValueError when their
        count is not the search's or a preview search would read them (it builds its worlds from one record)."""
        worlds = roots.worlds(e, p) if callable(getattr(roots, "worlds", None)) else None
        if worlds is None:
            return None
        if len(worlds["records"]) != self.s:
            raise ValueError(f"{len(worlds['records'])} world records for {self.s} worlds")
        if self.preview_mode != "raw":
            raise ValueError("a preview search builds its worlds from one record: not with a record per world")
        return worlds

    @staticmethod
    def _world_status(statuses):
        """The decision's status of the worlds' records: E_UNSUPPORTED when any world's record is refused for a public
        cause, else the first other refusal, else 0."""
        statuses = np.asarray(statuses).reshape(-1)
        if (statuses == C["DUOFORGE_E_UNSUPPORTED"]).any():
            return int(C["DUOFORGE_E_UNSUPPORTED"])
        bad = np.flatnonzero(statuses)
        return int(statuses[bad[0]]) if bad.size else 0

    def _mean_policy(self, worlds, obs, slots, pairs, pair_logp, team_logp):
        """(pair, team log-probabilities, seconds) of the root under a record per world: the mean of the policy's
        probabilities over the worlds' rows, each world weighing 1/W as in the belief (decision 0081: the root's own
        candidates and team). Worlds whose rows are all the root's own give the root's (pair_logp, team_logp)."""
        rows, slot_rows = np.asarray(worlds["obs"]), np.asarray(worlds["slots"])
        if all(np.array_equal(r, obs) for r in rows) and all(np.array_equal(r, slots) for r in slot_rows):
            return pair_logp, team_logp, 0.0
        masks = np.repeat(np.asarray(pairs)[None], rows.shape[0], axis=0)
        pair, team, seconds = self._policy(rows, slot_rows, masks)
        with np.errstate(divide="ignore"):  # a pair outside the mask has probability 0 in every world
            return (np.log(np.exp(pair.astype(np.float64)).mean(axis=0)),
                    np.log(np.exp(team.astype(np.float64)).mean(axis=0)), seconds)

    def _decision(self, p, key, own, own_p, weights, last_step, costs, budget=None, *, refused="score", groups=None,
                  steps_left=None):
        _check_refused(refused)
        if self.depth == 2:
            return self._tree_decision(p, key, own, own_p, weights, last_step, steps_left, costs, refused, groups)
        request = self._prepare(p, key, own, weights, last_step, costs, groups)
        return self._finish(request, self._values(request, costs), own_p, costs, budget, refused=refused)

    def _prepare(self, p, key, own, weights, last_step, costs, groups=None, into=None):
        """Phase one of a decision on the current worlds: the worlds' policy,
        the foe's pairs and every expand chunk with its tiebreaks. The rows
        and statuses are copied out, so later roots may reuse the worlds and
        the leaf batch before this request is finished (stage 3 P2).
        groups (a record per world): each world's first world of the same
        record; the viewer's rows must agree within a group, its pairs in all.
        into (D2): a batch that keeps every leaf (one expand call into its
        environments 0 .. leaves - 1, the depth-1 nodes) instead of the leaf
        batch's chunks."""
        pp, _, elapsed, masks, obs, slots, query_seconds = self._world_policy()
        if self.foe_net is not None:  # the viewer's check below reads the main encoder's rows, as without a foe network
            t = time.perf_counter()
            obs, slots, own_masks = (x.copy() for x in self.worlds.query_encoded(self.encoder, self.ext_supported))
            query_seconds += time.perf_counter() - t
            if not np.array_equal(own_masks, masks):
                raise SearchError("the foe network's encoder gives the worlds another pair mask")
        costs["world_builds"] += query_seconds
        costs["network"] += elapsed
        for w in range(1, self.s):
            g = 0 if groups is None else int(groups[w])
            if not np.array_equal(masks[w, p], masks[0, p]) or g != w and (
                    not np.array_equal(obs[w, p], obs[g, p]) or not np.array_equal(slots[w, p], slots[g, p])):
                raise SearchError("the viewer's encoded row differs across worlds")
        foe = 1 - p
        if self.worlds.requests[0, foe]["requested"]:
            probabilities = np.exp(pp[:, foe].astype(np.float64))
            mean = np.sum(weights[:, None] * probabilities, axis=0)
            order = np.lexsort((np.arange(mean.size), -mean))
            # Switch options can name different hidden bench members in each
            # world. Filter the common probability ranking through C's mask
            # per world; each column is that world's legal best response.
            ranked = [order[masks[w, foe].reshape(-1)[order] != 0][:self.m] for w in range(self.s)]
            m = min(len(x) for x in ranked)
            if not m:
                raise SearchError("a requested foe has no legal pair")
            foe_pairs = np.array([x[:m] for x in ranked])
            qs = np.take_along_axis(probabilities, foe_pairs, axis=1)
        else:
            foe_pairs, qs = np.full((self.s, 1), lookahead.NO_FOE, np.int64), np.ones((self.s, 1))
        i, j, w = np.indices((own.size, foe_pairs.shape[1], self.s)).reshape(3, -1)
        total = w.size
        choices = np.zeros((total, 2), _layout.FACTORED_CHOICE)
        choices["slot"][:, p, 0], choices["slot"][:, p, 1] = np.divmod(own[i], lookahead.OPTIONS)
        other = foe_pairs[w, j]
        asked = other != lookahead.NO_FOE
        choices["slot"][asked, foe, 0], choices["slot"][asked, foe, 1] = np.divmod(other[asked], lookahead.OPTIONS)
        rows = np.zeros((total, self._rows.shape[1]), np.float32)
        step, encode, results, tiebreaks = (np.zeros(total, np.uint32) for _ in range(4))
        root_keys, viewers = np.full(self.s, key, np.uint64), np.full(self.s, p, np.uint8)
        target, chunk = (self.leaves, self.capacity) if into is None else (into, max(total, 1))
        for start in range(0, total, chunk):
            end = min(total, start + chunk)
            t = time.perf_counter()
            row, st, enc, _, res = target.expand(self.worlds, self.encoder, self.ext_supported, self.seed,
                                                 root_keys, viewers, w[start:end].astype(np.uint32),
                                                 w[start:end].astype(np.uint32), choices[start:end])
            step[start:end], encode[start:end], results[start:end] = st, enc, res
            rows[start:end] = row
            if last_step:
                for x in np.flatnonzero((st == 0) & (res == 0)):
                    try:
                        tiebreaks[start + x] = target.tiebreak(int(x))
                    except duoforge.DuoforgeError as err:
                        if err.status_name != "DUOFORGE_E_UNSUPPORTED":
                            raise
                        tiebreaks[start + x] = np.uint32(0xFFFFFFFF)
            costs["leaves"] += time.perf_counter() - t
        # The table reads a value only where the step ran, the leaf is not terminal and not cut off.
        open_ = (step == 0) & (results == 0) & (not last_step)
        self._searched = True  # the worlds are this decision's (world_policies; every depth calls _prepare)
        return LeafRequest(p, key, own.copy(), bool(last_step), np.array(weights, copy=True), foe_pairs, qs, choices,
                           (i, j, w), rows, step, encode, results, tiebreaks, open_)

    def _values(self, request, costs):
        """Today's per-root value calls: the request's rows in capacity
        chunks through the preallocated row buffer, padded with zeros."""
        total = request.rows.shape[0]
        values = np.zeros(total, np.float32)
        for start in range(0, total, self.capacity):
            end = min(total, start + self.capacity)
            self._rows.fill(0)
            self._rows[:end - start] = request.rows[start:end]
            t = time.perf_counter()
            values[start:end] = np.asarray(self.model.value(self.params, self._rows))[:end - start]
            costs["network"] += time.perf_counter() - t
        return values

    def _finish(self, request, values, own_p, costs, budget=None, *, refused="score"):
        """Phase two: the table from the request's leaves and their values
        (float32; non-open leaves are never read: a SearchError reproduction
        records them as given), the reduction and the decision record.
        refused="drop" (#436): an own candidate with a refused leaf is left
        out of the solve and named in refused_pairs; when none remains the
        decision is Unreconstructible."""
        _check_refused(refused)
        values = np.asarray(values)
        if values.shape != request.step.shape or values.dtype != np.float32:
            raise ValueError("a request needs one float32 value per leaf")
        p, key, own, weights, qs = request.p, request.key, request.own, request.weights, request.qs
        i, j, w = request.plan
        t = time.perf_counter()
        breaks = request.tiebreaks.astype(np.int64)
        breaks[breaks == 0xFFFFFFFF] = lookahead.UNRESOLVED
        try:
            tab = lookahead.table(values, request.step, request.encode, request.results, breaks, (i, j, w), p,
                                  request.last_step)
        except SearchError as err:
            err.reproduction = {"values": values.tolist(), "step_statuses": request.step.tolist(),
                                "encode_statuses": request.encode.tolist(), "samples": w.tolist(),
                                "choices": request.choices.tobytes().hex()}
            raise
        tables = tab.values.transpose(2, 0, 1)
        raw, refused_pairs = int(own[0]), []
        if refused == "drop":
            # The own candidates with a refused leaf are no outcome of the engine: they leave the solve (#436).
            refused_rows = np.unique(i[request.step == lookahead._UNSUPPORTED])
            if refused_rows.size:
                keep = np.setdiff1d(np.arange(own.size), refused_rows)
                if not keep.size:
                    raise Unreconstructible("engine_refused_leaves")
                refused_pairs = [int(own[r]) for r in refused_rows]
                own, own_p = own[keep], np.asarray(own_p)[keep]
                tab = lookahead.Table(tab.a[keep], tab.stderr[keep], tab.counts, tab.values[keep])
                tables = tab.values.transpose(2, 0, 1)
        return self._play(request, tab, tables, own, own_p, raw, refused_pairs, costs, budget, t, refused)

    def _play(self, request, tab, tables, own, own_p, raw, refused_pairs, costs, budget, t, refused):
        """The root rule (spec section 5) on the decision's tables and its record: _finish's tables, or the tree's
        root tables under the solved continuation (D2). t: the start of the decision's solve time."""
        key, weights, qs, w = request.key, request.weights, request.qs, request.plan[2]
        rank = np.arange(own.size)
        solver = {} if self.root_solver == "lp" else {
            "solver": self.root_solver, "prior": own_p, "rm_iterations": self.rm_iterations,
            "rm_epsilon": self.rm_epsilon}
        try:
            outcomes, reduced = reduce(tables, weights, qs, rank,
                                       float(seeds.play_uniforms(self.seed, np.array([key], np.uint64))[0]), self.lam,
                                       budget=budget, **solver)
        except matrix.RMUnconverged as err:  # the named fallback solver_unconverged (Q1), counted, never silent
            costs["solve"] += time.perf_counter() - t  # its time is the decision's, counted like a solve
            raise Unreconstructible("solver_unconverged") from err
        except SearchError as err:
            err.reproduction = {"tables": tables.tolist(), "weights": weights.tolist(), "foe_probs": qs.tolist()}
            raise
        costs["solve"] += time.perf_counter() - t
        self.last.append({"tables": tables.copy(), "choices": request.choices.copy(),
                          "samples": w.copy(), "values": tab.values.copy()})
        foe_pairs = request.foe_pairs
        action = int(own[outcomes[self.rule]])
        dropped = {} if refused == "score" else {"refused_pairs": refused_pairs}
        return {"kind": "searched", "rule": self.rule, "k": own.size, "m": foe_pairs.shape[1], "s": self.s,
                "own_pairs": own.tolist(), "own_probs": own_p.tolist(), "foe_pairs": foe_pairs.tolist(),
                "foe_probs": qs.tolist(), "weights": weights.tolist(), "coverage": float(np.sum(weights * qs.sum(axis=1))),
                "table": tab.a.tolist(), "tables": tables.tolist(), "stderr": tab.stderr.tolist(),
                "choice": action, "raw": raw, "changed": action != raw, "outcomes": outcomes,
                "leaves": tab.counts, "near_duplicates": lookahead.near_duplicates(tab.a), "split": None, **dropped,
                **reduced}

    def _tree_decision(self, p, key, own, own_p, weights, last_step, steps_left, costs, refused, groups):
        """A turn decision on the two-turn tree (D2; spec sections 4 and 8 "D2 in detail", plan step 4): the root edges
        expanded into the node batch; the depth-1 candidates (ours per information set, the foe's per node) from one
        policy call per network; the depth-2 leaves through the evaluator; one CFR+ solve (tree.solve_tree); the root
        rule of spec section 5 on the root tables under the solved continuation (_play). A refused leaf (#436) drops
        its own candidate at its information set; a set left without one, or a refused leaf of a node where only the
        foe is asked, drops its root row; no row left is engine_refused_leaves, as at depth 1."""
        if refused != "drop":
            raise ValueError("the depth-2 tree drops refused candidates (#436): refused must be 'drop'")
        request = self._prepare(p, key, own, weights, last_step, costs, groups, into=self.nodes)
        i, j, w = request.plan
        breaks = request.tiebreaks.astype(np.int64)
        breaks[breaks == 0xFFFFFFFF] = lookahead.UNRESOLVED
        try:  # the root edges: exact where refused, TERMINAL or cut off; the decision nodes' values come from the tree
            root = lookahead.table(np.zeros(i.size, np.float32), request.step, request.encode, request.results, breaks,
                                   (i, j, w), p, request.last_step)
        except SearchError as err:
            err.reproduction = {"step_statuses": request.step.tolist(), "encode_statuses": request.encode.tolist(),
                                "samples": w.tolist(), "choices": request.choices.tobytes().hex()}
            raise
        dropped_rows = set(np.unique(i[request.step == lookahead._UNSUPPORTED]).tolist())
        envs = np.flatnonzero(request.open)  # the decision nodes; a node's index in the node batch is its leaf's
        phase = self._depth_one(p, key, envs, i, j, w, request, steps_left, costs, groups, dropped_rows) \
            if envs.size else None
        keep = np.array(sorted(set(range(own.size)) - dropped_rows), np.int64)
        if not keep.size:
            raise Unreconstructible("engine_refused_leaves")
        t = time.perf_counter()
        row_of = {int(r): n for n, r in enumerate(keep)}
        leaf = root.values[keep].transpose(2, 0, 1)
        node = np.full(leaf.shape, -1, np.int64)
        kept = [] if phase is None else [x for x in range(envs.size) if int(i[envs[x]]) in row_of]
        for n, x in enumerate(kept):
            e = envs[x]
            node[w[e], row_of[int(i[e])], j[e]] = n
        sets = [] if phase is None else sorted({int(phase["set"][x]) for x in kept if phase["set"][x] >= 0})
        set_of = {s: n for n, s in enumerate(sets)}
        info = np.array([set_of.get(int(phase["set"][x]), -1) for x in kept], np.int64)
        z = np.zeros((len(kept), self.k2, self.m2))
        own_valid, own_prior = np.zeros((len(sets), self.k2), bool), np.zeros((len(sets), self.k2))
        foe_valid, foe_prior = np.zeros((len(kept), self.m2), bool), np.zeros((len(kept), self.m2))
        for s, n in set_of.items():
            valid = phase["valid"][s]
            own_valid[n, :valid.size] = valid
            own_prior[n, :valid.size] = np.where(valid, phase["own_probs"][s], 0.0)
        for n, x in enumerate(kept):
            probs = phase["foe"][x][1]
            foe_valid[n, :probs.size] = True
            foe_prior[n, :probs.size] = probs
        if phase is not None:
            position = {x: n for n, x in enumerate(kept)}
            for y, (x, a, b) in enumerate(zip(phase["node"], phase["a"], phase["b"])):
                if x in position:
                    z[position[x], a, b] = phase["z"][y]
        own_k, own_pk = own[keep], np.asarray(own_p)[keep]
        shape = tree.Tree(weights=request.weights, leaf=leaf, node=node, info=info, z=z, own_valid=own_valid,
                          foe_valid=foe_valid, own_prior=own_prior, foe_prior=foe_prior)
        started = time.perf_counter()
        try:
            solved = tree.solve_tree(shape, own_pk, request.qs, iterations=self.tree_iterations,
                                     epsilon=self.rm_epsilon, foe_below=self.foe_below)
        except matrix.RMUnconverged as err:  # the named fallback solver_unconverged (Q1), counted, never silent
            costs["tree_solve"] += time.perf_counter() - started
            costs["solve"] += time.perf_counter() - t
            raise Unreconstructible("solver_unconverged") from err
        except SearchError as err:
            err.reproduction = {"tree": {name: np.asarray(value).tolist() for name, value in shape._asdict().items()},
                                "prior": own_pk.tolist(), "foe_probs": request.qs.tolist()}
            raise
        costs["tree_solve"] += time.perf_counter() - started
        tables = solved.tables
        cube = tables.transpose(1, 2, 0)
        tab = lookahead.Table(*lookahead.cell_stats(cube), root.counts, cube)
        result = self._play(request, tab, tables, own_k, own_pk, int(own[0]),
                            [int(own[r]) for r in sorted(dropped_rows)], costs, None, t, refused)
        ours = info >= 0
        merged = sum(int((info == s).sum()) for s in range(len(sets)) if int((info == s).sum()) > 1)
        result["tree"] = {"nodes": len(kept), "information_sets": len(sets),
                          "merge_share": merged / int(ours.sum()) if ours.any() else 0.0,
                          "iterations": solved.root.iterations, "gap": solved.root.gap,
                          "leaves": dict(phase["leaves"]) if phase is not None else
                          {"refused": 0, "terminal": 0, "cut_off": 0, "unresolved": 0, "open": 0},
                          "dropped_candidates": 0 if phase is None else phase["dropped"]}
        self.last[-1]["tree"] = {"cells": [(int(w[envs[x]]), row_of[int(i[envs[x]])], int(j[envs[x]])) for x in kept],
                                 "sets": info.tolist(), "own": solved.own, "foe": solved.foe, "solution": solved}
        return result

    def _depth_one(self, p, key, envs, i, j, w, request, steps_left, costs, groups, dropped_rows):
        """The depth-1 phase of a tree decision on the node batch's decision nodes envs: their candidates, their
        depth-2 leaves through the evaluator and those leaves' values. Adds to dropped_rows the root rows a refused
        leaf drops. Returns, per node x (envs order): set[x] our information set (-1 where we are not asked); per set
        s: own_probs[s] its candidates' prior, valid[s] the candidates no refused leaf dropped; foe[x] (pairs, prior);
        per depth-2 leaf: node, a, b and its value z; the leaf counts by kind and the dropped candidates."""
        foe = 1 - p
        t = time.perf_counter()
        obs, slots, pairs = (x.copy() for x in self.nodes.query_encoded(self.encoder, self.ext_supported))
        asked = self.nodes.requests["requested"] != 0
        costs["leaves"] += time.perf_counter() - t
        n = self.nodes.envs
        if self.foe_net is None:  # one call, both seats, the whole node batch's fixed shape (spec section 7.2)
            pp, _, seconds = self._policy(obs.reshape(2 * n, -1), slots.reshape((2 * n,) + slots.shape[2:]),
                                          pairs.reshape((2 * n,) + pairs.shape[2:]))
            pp = pp.reshape(n, 2, -1)
            own_logp, foe_logp = pp[:, p], pp[:, foe]
            costs["tree_policy"] += seconds
        else:  # our seat with the main network, the foe's with the foe network on its own encoding
            own_logp, _, seconds = self._policy(obs[:, p], slots[:, p], pairs[:, p])
            t = time.perf_counter()
            fobs, fslots, fpairs = self.nodes.query_encoded(self.foe_net[2], self.foe_net[3])
            costs["leaves"] += time.perf_counter() - t
            if not np.array_equal(fpairs, pairs):
                raise SearchError("the foe network's encoder gives the depth-1 nodes another pair mask")
            foe_logp, _, more = self._policy(fobs[:, foe], fslots[:, foe], fpairs[:, foe], self.foe_net)
            seconds += more
            costs["tree_policy"] += seconds
        costs["network"] += seconds
        ours, theirs = asked[envs, p], asked[envs, foe]
        if not (ours | theirs).all():
            raise SearchError("a depth-1 node that is neither TERMINAL nor asks for a choice")
        t = time.perf_counter()
        keys, refused_keys = self._keys.keys(self.nodes, envs[ours], p, groups is not None)
        costs["leaves"] += time.perf_counter() - t
        if refused_keys.any():
            raise Unreconstructible("observation_key_refused")
        node_set, first = np.full(envs.size, -1, np.int64), {}
        for x, k in zip(np.flatnonzero(ours), keys):
            node_set[x] = first.setdefault((int(i[envs[x]]), k.tobytes()), len(first))
        members = [[] for _ in first]
        for x in np.flatnonzero(ours):
            members[node_set[x]].append(int(x))
        cands, own_probs, set_rows = [], [], []
        for s, xs in enumerate(members):
            mask = pairs[envs[xs[0]], p]
            if any(not np.array_equal(pairs[envs[x], p], mask) for x in xs[1:]):
                raise SearchError(f"information set {s}: its nodes' own pairs differ (the observation key merged "
                                  f"states the searcher tells apart)")
            # the plan's decision 3: node (w, i, j) weighs p_w x the foe model's prior of j x its chance weight (1)
            weight = [float(request.weights[w[envs[x]]]) * float(request.qs[w[envs[x]], j[envs[x]]]) for x in xs]
            total = math.fsum(weight)
            if not total > 0.0:
                raise SearchError(f"information set {s} has no weight")
            # the weighted mean of the nodes' probabilities, in logs (a set of one node keeps its row's logs exactly)
            logs = np.stack([own_logp[envs[x]].astype(np.float64) for x in xs])
            top = logs.max(axis=0)
            mean = np.zeros(lookahead.PAIRS)
            with np.errstate(invalid="ignore"):  # -inf - -inf outside the mask: never selected
                for x, row in enumerate(logs):
                    mean += (weight[x] / total) * np.exp(row - top)
            with np.errstate(divide="ignore", invalid="ignore"):
                pair, probs = lookahead.select(top + np.log(mean), mask, self.k2)
            cands.append(pair)
            own_probs.append(probs)
            set_rows.append(int(i[envs[xs[0]]]))
        foes = [lookahead.select(foe_logp[e], pairs[e, foe], self.m2) if theirs[x] else
                (np.array([lookahead.NO_FOE], np.int64), np.ones(1)) for x, e in enumerate(envs)]
        plan = [(x, a, b) for x in range(envs.size) for a in range(cands[node_set[x]].size if ours[x] else 1)
                for b in range(foes[x][0].size)]
        node_of, a_of, b_of = (np.array(c, np.int64) for c in zip(*plan))
        total = node_of.size
        choices = np.zeros((total, 2), _layout.FACTORED_CHOICE)
        mine = ours[node_of]
        own_pair = np.array([cands[node_set[x]][a] if ours[x] else 0 for x, a in zip(node_of, a_of)], np.int64)
        choices["slot"][mine, p, 0], choices["slot"][mine, p, 1] = np.divmod(own_pair[mine], lookahead.OPTIONS)
        foe_pair = np.array([foes[x][0][b] for x, b in zip(node_of, b_of)], np.int64)
        other = foe_pair != lookahead.NO_FOE
        choices["slot"][other, foe, 0], choices["slot"][other, foe, 1] = np.divmod(foe_pair[other], lookahead.OPTIONS)
        head = splitmix64(np.array([(int(key) + DEPTH_TAG) & _MASK], np.uint64))
        node_keys = splitmix64(head + np.arange(n, dtype=np.uint64))
        cut = steps_left == 2  # the depth-2 leaves are the arena's cut-off
        t = time.perf_counter()
        leaves = self.evaluator.leaves(self._node_batch, self.seed, node_keys, np.full(n, p, np.uint8),
                                       envs[node_of].astype(np.uint32), np.zeros(total, np.uint32), choices,
                                       np.full(total, cut), costs)
        costs["tree_evaluate"] += time.perf_counter() - t
        breaks = leaves.tiebreaks.astype(np.int64)
        breaks[breaks == 0xFFFFFFFF] = lookahead.UNRESOLVED
        index, zero = np.arange(total), np.zeros(total, np.int64)
        try:
            scored = lookahead.table(leaves.values, leaves.step, leaves.encode, leaves.results, breaks,
                                     (index, zero, zero), p, cut)
        except SearchError as err:
            if hasattr(err, "leaf"):
                y = err.leaf
                e = int(envs[node_of[y]])
                err.reproduction = {"node": e, "world": int(w[e]), "root_cell": [int(i[e]), int(j[e])],
                                    "own_pair": int(own_pair[y]), "foe_pair": int(foe_pair[y]),
                                    "node_key": int(node_keys[e]), "sample": 0, "search_seed": self.seed,
                                    "step_status": duoforge.status_name(int(leaves.step[y])),
                                    "encode_status": duoforge.status_name(int(leaves.encode[y]))}
            raise
        counts = dict(scored.counts)
        counts["open"] = total - counts["refused"] - counts["terminal"] - counts["cut_off"]
        valid = [np.ones(c.size, bool) for c in cands]
        for y in np.flatnonzero(leaves.step == lookahead._UNSUPPORTED):
            x = int(node_of[y])
            if ours[x]:
                valid[node_set[x]][a_of[y]] = False
            else:  # only the foe is asked: our empty response is the candidate the refusal drops
                dropped_rows.add(int(i[envs[x]]))
        for s, v in enumerate(valid):
            if not v.any():
                dropped_rows.add(set_rows[s])
        return {"set": node_set, "own_probs": own_probs, "valid": valid, "foe": foes, "node": node_of.tolist(),
                "a": a_of.tolist(), "b": b_of.tolist(), "z": scored.values[:, 0, 0], "leaves": counts,
                "dropped": int(sum(int((~v).sum()) for v in valid))}
