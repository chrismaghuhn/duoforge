"""Read-only empirical opening book. No legality, damage or battle rules.

Schema 2 is required: schema 1 discarded matchup, item, back and rating data.
Probabilities describe observed leads/actions, not optimal play. Species backoff
uses products of marginal lead frequencies, including previously unseen pairs.
Counts and win rates still describe actual pair observations, never products.
"""
import argparse
import collections
import itertools
import json
import re
from pathlib import Path

from .prior import to_id

SOURCES = ("champions", "sv_vgc")
LEAD_LEVELS = ("exact_team", "team_ignoring_items", "lead_pair_vs_opposing_lead_pair", "single_species")


def _names(values, size):
    if not isinstance(values, (list, tuple)) or len(values) != size:
        raise ValueError(f"expected {size} species")
    names = tuple(to_id(value) if isinstance(value, str) else "" for value in values)
    if any(not name for name in names) or len(set(names)) != size:
        raise ValueError("species must be nonempty and distinct")
    return names


def _team(values):
    """Six species strings (items unknown) or six species/item dictionaries."""
    if not isinstance(values, (list, tuple)) or len(values) != 6:
        raise ValueError("expected six team members")
    members = [value if isinstance(value, dict) else {"species": value} for value in values]
    species = _names([member.get("species") for member in members], 6)
    items = []
    for member in members:
        item = member.get("item")
        if item is not None and not isinstance(item, str):
            raise ValueError("item must be a string or unknown (None)")
        items.append(None if item is None else to_id(item))
    return tuple(sorted(zip(species, items)))


def _validate_row(row, action=False):
    if not isinstance(row, dict) or row.get("source") not in SOURCES:
        raise ValueError("invalid opening row/source")
    if not isinstance(row.get("format"), str) or not row["format"]:
        raise ValueError("missing format")
    required = (("actor", "action", "target", "switch_context", "slot", "side") if action else
                ("team_species", "team_items", "opposing_team_species", "backs"))
    if any(field not in row for field in (*required, "leads", "opposing_leads")):
        raise ValueError("missing schema-2 fields")
    for field in ("count", "decisive_count", "wins", "rating_band", "opposing_rating_band"):
        value = row.get(field)
        if type(value) is not int or value < (-1 if "rating" in field else 0):
            raise ValueError(f"invalid {field}")
        if "rating" in field and value != -1 and value % 100:
            raise ValueError(f"{field} must be a 100-point band lower edge, or -1")
    if not 0 <= row["wins"] <= row["decisive_count"] <= row["count"] or row["count"] == 0:
        raise ValueError("inconsistent observation counts")
    own = tuple(sorted(_names(row.get("leads"), 2)))
    opposing = row.get("opposing_leads")
    opposing = None if opposing is None else tuple(sorted(_names(opposing, 2)))
    normalized = dict(row, leads=own, opposing_leads=opposing)
    if action:
        if opposing is None or row.get("action_kind") not in ("move", "switch", "mega"):
            raise ValueError("invalid action kind/leads")
        if row.get("slot") not in ("a", "b") or type(row.get("side")) is not int or row["side"] not in (0, 1):
            raise ValueError("invalid action slot/side")
        for field in ("actor", "action", "switch_context"):
            if not isinstance(row.get(field), str) or (field != "switch_context" and not row[field]):
                raise ValueError(f"invalid {field}")
        if row.get("target") is not None and not isinstance(row["target"], str):
            raise ValueError("invalid target")
        if row["action_kind"] == "switch" and row["switch_context"] not in ("choice", "pivot", "replacement", "drag"):
            raise ValueError("invalid switch_context")
        normalized["actor"] = to_id(row["actor"])
    else:
        species = _names(row.get("team_species"), 6)
        items = row.get("team_items")
        if not isinstance(items, (list, tuple)) or len(items) != 6 or any(not isinstance(i, str) for i in items):
            raise ValueError("expected six aligned team_items")
        normalized["team"] = tuple(sorted(zip(species, map(to_id, items))))
        normalized["opposing_team"] = tuple(sorted(_names(row.get("opposing_team_species"), 6)))
        backs = row.get("backs")
        backs = None if backs is None else tuple(sorted(_names(backs, 2)))
        if not set(own) <= set(species) or (backs is not None and
                (not set(backs) <= set(species) or set(backs) & set(own))):
            raise ValueError("leads/backs do not belong to the own team")
        if opposing is not None and not set(opposing) <= set(normalized["opposing_team"]):
            raise ValueError("opposing leads do not belong to opposing team")
        normalized["backs"] = backs
    return normalized


def load(path):
    """Load schema 2 outside any worktree of this repo; never write a cache."""
    from .dataset import refuse_repository

    path = Path(path)
    refuse_repository(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 2:
        raise ValueError("opening book requires schema_version 2; regenerate schema 1 with openings.py")
    tables = payload.get("tables")
    if not isinstance(tables, dict) or any(not isinstance(tables.get(name), list)
                                           for name in ("leads_per_team", "turn_1_actions")):
        raise ValueError("missing opening tables")
    return Book([_validate_row(row) for row in tables["leads_per_team"]],
                [_validate_row(row, action=True) for row in tables["turn_1_actions"]])


def _stats(rows):
    count = sum(row["count"] for row in rows)
    decisive = sum(row["decisive_count"] for row in rows)
    wins = sum(row["wins"] for row in rows)
    return {"count": count, "decisive_count": decisive, "wins": wins,
            "win_rate": wins / decisive if decisive else None}


def _distribution(groups, level, confidence, weights=None):
    entries = []
    for key, rows in groups.items():
        stats = _stats(rows)
        entries.append({"key": key, **stats, "weight": weights[key] if weights is not None else stats["count"],
                        "level": level, "confidence": confidence})
    total = sum(entry["weight"] for entry in entries)
    for entry in entries:
        entry["probability"] = entry.pop("weight") / total
    return sorted(entries, key=lambda entry: (-entry["probability"], json.dumps(entry["key"], sort_keys=True)))


class Book:
    """Query loaded observations. Not connected to training or M12 search.

    min_count applies to the total matching observations of each level (per
    actor for actions; per species for marginal leads). Rating bounds apply
    to the observing player's 100-point rating band lower edge;
    unknown (-1) ratings are excluded when a bound is requested.
    """

    def __init__(self, leads, actions):
        self._leads = leads
        self._actions = actions

    def _filter(self, rows, sources, min_count, min_rating, max_rating):
        if isinstance(sources, str) or not sources or any(source not in SOURCES for source in sources):
            raise ValueError("sources must explicitly select champions and/or sv_vgc")
        if type(min_count) is not int or min_count < 1:
            raise ValueError("min_count must be at least 1")
        for bound in (min_rating, max_rating):
            if bound is not None and (type(bound) is not int or bound < 0):
                raise ValueError("rating bounds must be nonnegative integers")
            if bound is not None and bound % 100:
                raise ValueError("rating bounds must be band lower edges (multiples of 100)")
        if min_rating is not None and max_rating is not None and min_rating > max_rating:
            raise ValueError("min_rating exceeds max_rating")
        rows = [row for row in rows if row["source"] in sources]
        if min_rating is not None or max_rating is not None:
            if rows and not any(row["rating_band"] >= 0 for row in rows):
                raise ValueError("rating filter requested but selected source has no ratings")
            rows = [row for row in rows if row["rating_band"] >= 0 and
                    (min_rating is None or row["rating_band"] >= min_rating) and
                    (max_rating is None or row["rating_band"] <= max_rating)]
        return rows

    def leads(self, own, foe, *, opposing_leads=None, sources=("champions",), min_count=20,
              min_rating=None, max_rating=None):
        """Preview prior: exact items/matchup -> species teams -> lead matchup
        -> marginal species weights. Without opposing_leads,
        lead matchups marginalize observed foe pairs contained in the foe six.
        Backs are returned only when observed and contained in the query team.
        """
        own_team, foe_team = _team(own), _team(foe)
        own_species = tuple(species for species, _item in own_team)
        foe_species = tuple(species for species, _item in foe_team)
        foe_pair = None if opposing_leads is None else tuple(sorted(_names(opposing_leads, 2)))
        if foe_pair is not None and not set(foe_pair) <= set(foe_species):
            raise ValueError("opposing_leads outside foe team")
        all_rows = self._filter(self._leads, sources, min_count, min_rating, max_rating)
        rows = [row for row in all_rows if set(row["leads"]) <= set(own_species)]
        skipped = []
        for level, confidence in zip(LEAD_LEVELS, ("high", "medium", "low", "low")):
            selected = rows
            reason = "below_min_count"
            if level in LEAD_LEVELS[:2]:
                selected = [row for row in rows if tuple(s for s, _i in row["team"]) == own_species and
                            row["opposing_team"] == foe_species and
                            (foe_pair is None or row["opposing_leads"] == foe_pair)]
                if level == "exact_team":
                    if any(item is None for _species, item in own_team):
                        selected, reason = [], "own_items_unknown"
                    else:
                        selected = [row for row in selected if row["team"] == own_team]
            elif level == "lead_pair_vs_opposing_lead_pair":
                selected = [row for row in rows if row["opposing_leads"] is not None and
                            (row["opposing_leads"] == foe_pair if foe_pair is not None else
                             set(row["opposing_leads"]) <= set(foe_species))]
            count = sum(row["count"] for row in selected)
            frequencies, weights = None, None
            support_count = count
            if level == "single_species":
                frequencies = collections.Counter()
                for row in all_rows:
                    for species in row["leads"]:
                        if species in own_species:
                            frequencies[species] += row["count"]
                eligible = sorted(s for s, n in frequencies.items() if n >= min_count)
                weights = {(pair, None): frequencies[pair[0]] * frequencies[pair[1]]
                           for pair in itertools.combinations(eligible, 2)}
                support_count = min((frequencies[s] for s in eligible), default=0) if weights else 0
            if support_count < min_count:
                skip = {"level": level, "count": count, "reason": reason}
                if level == "single_species":
                    skip["support_count"] = support_count
                skipped.append(skip)
                continue
            groups = collections.defaultdict(list)
            if weights is not None:
                groups.update({key: [] for key in weights})
            for row in selected:
                backs = row["backs"]
                if level == "single_species" or (backs is not None and not set(backs) <= set(own_species)):
                    backs = None
                key = (row["leads"], backs)
                if weights is None or key in weights:
                    groups[key].append(row)
            suggestions = _distribution(groups, level, confidence, weights)
            for suggestion in suggestions:
                suggestion["leads"], suggestion["backs"] = suggestion.pop("key")
            return {"level": level, "confidence": confidence, "count": sum(s["count"] for s in suggestions),
                    "support_count": support_count, "suggestions": suggestions,
                    "skipped": skipped, "species_counts": None if frequencies is None else dict(sorted(frequencies.items())),
                    "opposing_leads_marginalized": foe_pair is None and level == LEAD_LEVELS[2]}
        return {"level": "unavailable", "confidence": "none", "count": 0, "suggestions": [], "skipped": skipped}

    def turn_1(self, own_leads, opposing_leads, *, sources=("champions",), min_count=20,
               min_rating=None, max_rating=None):
        """Ordered query leads define slots a/b. Aggregate by actor, retaining
        observed_slots and relative protocol target; never infer legal targets.
        Mega events are supplementary, and only choice switches are included.
        """
        own = _names(own_leads, 2)
        foe = tuple(sorted(_names(opposing_leads, 2)))
        rows = self._filter(self._actions, sources, min_count, min_rating, max_rating)
        rows = [row for row in rows if row["actor"] in row["leads"] and
                (row["action_kind"] == "move" or
                 (row["action_kind"] == "switch" and row["switch_context"] == "choice"))]
        result = {}
        for slot, actor in zip(("a", "b"), own):
            actor_rows = [row for row in rows if row["actor"] == actor]
            skipped = []
            for level in ("exact_pairs", "single_species"):
                selected = actor_rows if level == "single_species" else [row for row in actor_rows
                            if row["leads"] == tuple(sorted(own)) and row["opposing_leads"] == foe]
                count = sum(row["count"] for row in selected)
                if count < min_count:
                    skipped.append({"level": level, "count": count, "reason": "below_min_count"})
                    continue
                groups = collections.defaultdict(list)
                for row in selected:
                    target = row["target"]
                    match = re.fullmatch(r"p([12])([ab])(?:: (.*))?", target or "")
                    if match:
                        relation = "own" if int(match[1]) - 1 == row["side"] else "foe"
                        target = relation + ":" + match[2] + (": " + match[3] if match[3] else "")
                    key = (row["action_kind"], row["action"], target, row["switch_context"])
                    groups[key].append(row)
                confidence = "medium" if level == "exact_pairs" else "low"
                suggestions = _distribution(groups, level, confidence)
                for suggestion in suggestions:
                    values = suggestion.pop("key")
                    suggestion.update(zip(("action_kind", "action", "target", "switch_context"), values))
                    slots = collections.Counter()
                    for row in groups[values]:
                        slots[row["slot"]] += row["count"]
                    suggestion["observed_slots"] = dict(sorted(slots.items()))
                result[slot] = {"actor": actor, "level": level, "confidence": confidence, "count": count,
                                "suggestions": suggestions, "skipped": skipped}
                break
            else:
                result[slot] = {"actor": actor, "level": "unavailable", "confidence": "none", "count": 0,
                                "suggestions": [], "skipped": skipped}
        return result


def parse_team(text):
    """Six comma-separated species or a Showdown paste (also read via @path).
    Only paste headers matter; ability/move/stat lines are not interpreted.
    """
    if text.startswith("@"):
        text = Path(text[1:]).read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n")
    if "\n" not in text and " @ " not in text:
        return [species for species, _item in _team([s.strip() for s in text.split(",")])]
    members = []
    for block in re.split(r"\n\s*\n", text.strip()):
        head = block.splitlines()[0].strip()
        head, item = (head.split(" @ ", 1) + [""])[:2]
        head = re.sub(r"\s*\([MF]\)$", "", head)
        nick = re.fullmatch(r".+\((.+)\)", head)
        members.append({"species": nick[1] if nick else head, "item": item.strip()})
    _team(members)
    return members


def main(argv=None):
    parser = argparse.ArgumentParser(description="Query a private schema-2 opening book (empirical evidence only)")
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--own", required=True, help="six comma-separated species, literal paste, or @paste-file")
    parser.add_argument("--foe", required=True, help="six comma-separated species, literal paste, or @paste-file")
    parser.add_argument("--own-leads", help="ordered comma-separated pair; requires --foe-leads")
    parser.add_argument("--foe-leads", help="ordered comma-separated pair; requires --own-leads")
    parser.add_argument("--source", choices=SOURCES, action="append", help="default: champions only")
    parser.add_argument("--min-count", type=int, default=20)
    parser.add_argument("--min-rating", type=int, help="minimum rating band lower edge (multiple of 100)")
    parser.add_argument("--max-rating", type=int, help="maximum rating band lower edge, inclusive (multiple of 100)")
    args = parser.parse_args(argv)
    try:
        book = load(args.book)
        own, foe = parse_team(args.own), parse_team(args.foe)
        options = dict(sources=args.source or ("champions",), min_count=args.min_count,
                       min_rating=args.min_rating, max_rating=args.max_rating)
        if bool(args.own_leads) != bool(args.foe_leads):
            raise ValueError("--own-leads and --foe-leads must be supplied together")
        own_pair = None if args.own_leads is None else _names(args.own_leads.split(","), 2)
        foe_pair = None if args.foe_leads is None else _names(args.foe_leads.split(","), 2)
        if own_pair is not None and not set(own_pair) <= {s for s, _i in _team(own)}:
            raise ValueError("own leads outside own team")
        lead_result = book.leads(own, foe, opposing_leads=foe_pair, **options)
        if own_pair is not None:
            scenarios = [(own_pair, foe_pair)]
        else:
            # Team preview has no observed leads yet. Explicitly label the
            # scenario as hypothetical: best own prior vs best foe prior.
            foe_result = book.leads(foe, own, **options)
            scenarios = [(lead_result["suggestions"][0]["leads"], foe_result["suggestions"][0]["leads"])] \
                if lead_result["suggestions"] and foe_result["suggestions"] else []
        output = {"leads": lead_result, "turn_1": [
            {"hypothetical": own_pair is None, "own_leads": a, "opposing_leads": b,
             "slots": book.turn_1(a, b, **options)} for a, b in scenarios]}
        print(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
