"""Opt-in evaluation-only preview evidence. Legality stays in the C domain.

No completion of missing backs or conversion of marginal weights to games.
Unordered observed lead/back pairs map to every engine-listed ordering; prior
mass is split equally across those orderings. Override takes the lowest rank
of the highest-win-rate supported observed choice (fixed key breaks ties).
"""
import collections
import hashlib
import json

import numpy as np

import duoforge
from duoforge import data
from duoforge_replay import book

from . import evaluate
from .selfplay import Observation, TEAM


def add_arguments(parser):
    parser.add_argument("--book", help="private schema-2 opening book; omitted = original evaluation")
    parser.add_argument("--book-min-count", type=int, default=20)
    parser.add_argument("--book-mode", choices=("override", "prior"), default="override")
    parser.add_argument("--book-weight", type=float, default=0.5, help="prior mixture weight in [0,1]")


def load_options(args):
    if args.book_min_count < 1 or not np.isfinite(args.book_weight) or not 0 <= args.book_weight <= 1:
        raise ValueError("book-min-count must be positive and book-weight finite in [0,1]")
    return None if args.book is None else book.load(args.book)


def info(args, evidence=None):
    if evidence is not None:
        return {"sha256": evidence.source_sha256, "mode": args.book_mode,
                "min_count": args.book_min_count, "weight": args.book_weight}
    digest = hashlib.sha256()
    with open(args.book, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "mode": args.book_mode,
            "min_count": args.book_min_count, "weight": args.book_weight}


def sheets(context, pool):
    """Decode only open-sheet species/items from authoritative data names."""
    species, items = {}, {}
    output = []
    for side in pool.sides:
        team = []
        for member in side["members"][:int(side["member_count"])]:
            ident, item = int(member["species_id"]), int(member["item"])
            if ident not in species:
                species[ident] = data.name(context, data.TABLE_SPECIES, ident)
            if item and item not in items:
                items[item] = data.name(context, data.TABLE_ITEM, item - 1)
            team.append({"species": species[ident], "item": items[item] if item else ""})
        output.append(team)
    return output


def mapped_distribution(answer, own, domain, min_count, mode):
    """(probabilities over legal joint ranks, override rank, refusal causes).
    Counts gate each full observed choice, not a book level's total sample.
    Mapping uses the existing public domain helpers, never a guessed tuple.
    """
    causes = collections.Counter()
    if answer["level"] == "unavailable":
        return None, None, {"below_level_min_count": 1}
    names = [data.to_id(m["species"]) for m in own]
    if len(names) != 6 or len(set(names)) != 6:
        return None, None, {"unsupported_or_ambiguous_roster": 1}
    if int(domain["kind"]) != TEAM or int(domain["member_count"]) != 6 or int(domain["pick_count"]) != 4:
        return None, None, {"unsupported_preview_domain": 1}
    n = int(duoforge.joint_counts(np.asarray(domain).reshape(1))[0])
    domains = np.repeat(np.asarray(domain).reshape(1), n)
    legal = duoforge.factored_choices(domains, np.arange(n))
    # Round-trip the existing public encoding against the actual domain.
    ranks = duoforge.joint_indices(domains, legal)
    by_pairs = collections.defaultdict(list)
    for rank, choice in zip(ranks, legal):
        pair = (frozenset(names[int(i)] for i in choice["picks"][:2]),
                frozenset(names[int(i)] for i in choice["picks"][2:4]))
        by_pairs[pair].append(int(rank))
    mass = np.zeros(n, dtype=np.float64)
    candidates = []
    for suggestion in answer["suggestions"]:
        if suggestion["count"] < min_count:
            causes["below_choice_min_count"] += 1
            continue
        if suggestion["backs"] is None:
            causes["missing_backs"] += 1
            continue
        leads, backs = set(suggestion["leads"]), set(suggestion["backs"])
        if len(leads) != 2 or len(backs) != 2 or leads & backs:
            causes["invalid_book_choice"] += 1
            continue
        if not (leads | backs) <= set(names):
            causes["species_not_in_roster"] += 1
            continue
        allowed = by_pairs.get((frozenset(leads), frozenset(backs)), [])
        if not allowed:
            causes["no_legal_mapping"] += 1
            continue
        if mode == "override" and suggestion["win_rate"] is None:
            causes["no_decisive_games"] += 1
            continue
        weight = float(suggestion["probability"])
        if not np.isfinite(weight) or weight <= 0:
            causes["invalid_book_probability"] += 1
            continue
        mass[allowed] += weight / len(allowed)
        key = json.dumps((sorted(leads), sorted(backs)), separators=(",", ":"))
        candidates.append((-(suggestion["win_rate"] or 0), key, min(allowed)))
    if not candidates:
        return None, None, dict(causes or {"no_supported_choice": 1})
    mass /= mass.sum()
    return mass, min(candidates)[2], dict(causes)


class BookPlayer(evaluate.Player):
    """Wrap one evaluation player; call its original indices before applying
    preview evidence. An unsupported/no-answer query keeps those bytes intact.
    Book never sees a battle state, HP, stats or either player's hidden state.
    """

    def __init__(self, base, evidence, team_sheets, rows, min_count=20, mode="override", weight=0.5, network=None):
        if type(min_count) is not int or min_count < 1 or mode not in ("override", "prior"):
            raise ValueError("invalid book minimum/mode")
        if not np.isfinite(weight) or not 0 <= weight <= 1:
            raise ValueError("book weight must be finite in [0,1]")
        self.base, self.evidence, self.team_sheets, self.rows = base, evidence, team_sheets, rows
        self.min_count, self.mode, self.weight = min_count, mode, weight
        self.network = base if network is None else network
        self.name = base.name
        self.events = []
        self._answers = {}  # Preview-only cache per sheet matchup; never consulted during battle decisions.

    def indices(self, batch, choices, step=None, seats=None, last_step=None):
        out = self.base.indices(batch, choices, step=step, seats=seats, last_step=last_step)
        if seats is None:
            raise ValueError("book preview needs the evaluation player's seats")
        preview = (batch.requests["requested"] != 0) & (batch.domains["kind"] == TEAM)
        asked = [(e, int(p)) for e, p in enumerate(seats) if p >= 0 and preview[e, int(p)]]
        distributions = None
        for e, p in asked:
            own_index, foe_index = int(self.rows[f"side{p}"][e]), int(self.rows[f"side{1-p}"][e])
            own, foe = self.team_sheets[own_index], self.team_sheets[foe_index]
            event = {"env": e, "seat": p, "answered": False, "applied": False, "level": "unavailable",
                     "fallback": {}, "rejected_choices": {}}
            if self.mode == "prior" and self.weight == 0:
                event["fallback"] = {"zero_prior_weight": 1}
                self.events.append(event)
                continue
            try:
                key = own_index, foe_index
                if key not in self._answers:
                    self._answers[key] = self.evidence.leads(own, foe, min_count=self.min_count)
                answer = self._answers[key]
            except ValueError as error:
                event["fallback"] = {"query_refused": 1}
                event["reason"] = str(error)
                self.events.append(event)
                continue
            event["level"] = answer["level"]
            event["answered"] = answer["level"] != "unavailable"
            try:
                prior, override, rejected = mapped_distribution(answer, own, batch.domains[e, p], self.min_count, self.mode)
            except ValueError as error:
                event["fallback"] = {"mapping_refused": 1}
                event["reason"] = str(error)
                self.events.append(event)
                continue
            event["rejected_choices"] = rejected
            if prior is None:
                event["fallback"] = {cause: 1 for cause in rejected}
            else:
                rank = override
                if self.mode == "prior":
                    if distributions is None:
                        obs = Observation(batch, self.network.encoder, self.network.ext_supported)
                        envs = batch.envs
                        self.network.model.check(obs.obs.reshape(2 * envs, -1))
                        _, logp, _ = self.network.model.apply(
                            self.network.params, obs.obs.reshape(2 * envs, -1),
                            obs.slots.reshape((2 * envs,) + obs.slots.shape[2:]),
                            obs.mask.reshape((2 * envs,) + obs.mask.shape[2:]))
                        distributions = np.asarray(logp, dtype=np.float64).reshape(envs, 2, -1)
                    net = np.exp(distributions[e, p] - np.max(distributions[e, p]))
                    if net.shape != prior.shape or not np.isfinite(net).all() or net.sum() <= 0:
                        raise ValueError("network preview distribution does not match the native domain")
                    rank = int(np.argmax((1 - self.weight) * net / net.sum() + self.weight * prior))
                # Return a native index, and keep the passed factored choices consistent.
                out[e, p] = rank
                choices[e, p] = duoforge.factored_choices(np.asarray(batch.domains[e, p]).reshape(1), [rank])[0]
                event["applied"] = True
                event["choice"] = rank
                # Search diagnostics must describe the action actually played.
                if hasattr(self.base, "records"):
                    for record in reversed(self.base.records.get(e, [])):
                        if record.get("kind") == "team" and record.get("seat") == p and record.get("step") == step:
                            record["network_choice"] = record["choice"]
                            record["choice"] = rank
                            record["book"] = {"level": answer["level"], "mode": self.mode}
                            break
            self.events.append(event)
        return out

    def summary(self, envs=None, games=None):
        events = self.events if envs is None else [event for event in self.events if event["env"] in envs]
        levels = collections.Counter(event["level"] for event in events if event["answered"])
        fallbacks, rejected = collections.Counter(), collections.Counter()
        for event in events:
            fallbacks.update(event["fallback"])
            rejected.update(event["rejected_choices"])
        n = len(events)
        denominator = n if games is None else games
        if denominator < n:
            raise ValueError("more preview observations than games in this report")
        if denominator > n:
            fallbacks["preview_not_requested"] = denominator - n
        return {"games": denominator, "preview_games": n, "answered": sum(event["answered"] for event in events),
                "answered_share": sum(event["answered"] for event in events) / denominator if denominator else 0,
                "applied": sum(event["applied"] for event in events),
                "applied_share": sum(event["applied"] for event in events) / denominator if denominator else 0,
                "levels": dict(sorted(levels.items())),
                "level_shares": {level: count / denominator for level, count in sorted(levels.items())},
                "fallbacks": dict(sorted(fallbacks.items())),
                "rejected_choices": dict(sorted(rejected.items()))}


def wrap(player, evidence, team_sheets, rows, args, network=None):
    """The default-off path returns exactly the original object."""
    if evidence is None:
        return player
    return BookPlayer(player, evidence, team_sheets, rows, args.book_min_count, args.book_mode,
                      args.book_weight, network)
