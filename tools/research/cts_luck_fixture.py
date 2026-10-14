"""A committed pool battle (tests/reference/traces) as player 1's closed-sheet battle log in the arena bot's format 2,
for the luck meter's tests (python/tests/support/data/cts_luck_<id>.jsonl, #494): every line received ({"in"}), the
batches fed ({"feed"}, without |showteam|), a decision record and the accepted choice at each asked point (the trace's
inputs), and the last batch received but not fed, with pending_at_end and the end, as pkmn_arena writes a battle that
ended on its last choice. The streams come from the pinned Showdown: node tools/reference/ps_client.js <checkout>
<repo root> --every > STREAMS.jsonl.

    python tools/research/cts_luck_fixture.py STREAMS.jsonl OUT.jsonl BATTLE [PLAYER]

PLAYER is p1 (the default) or p2: whose stream, decisions and log.
"""
import json
import sys

streams, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, "python")
from duoforge_live.data import ROOT, trace_to_c  # noqa: E402

NAME = sys.argv[3]
PLAYER = sys.argv[4] if len(sys.argv) > 4 else "p1"
if PLAYER not in ("p1", "p2"):
    raise SystemExit(f"PLAYER is p1 or p2, not {PLAYER!r}")
_, trace = trace_to_c.load_battle(str(ROOT), NAME)
messages = [json.loads(l)["lines"] for l in open(streams, encoding="utf-8")
            if json.loads(l)["battle"] == NAME and json.loads(l)["to"] == PLAYER]
records = [{"log_format": 2}]
k, seen, pending = -1, set(), None
for i, m in enumerate(messages):
    closed = [line for line in m if not line.startswith("|showteam|")]
    last = i == len(messages) - 1
    if not closed:  # a message of |showteam| lines only: under closed sheets nothing comes
        continue
    for line in closed:
        records.append({"in": line})
    if last:  # the battle ended in this batch: the bot ends it before feeding it
        records.append({"pending_at_end": pending})
        records.append({"end": next(line for line in closed if line.startswith("|win|"))})
        break
    if pending is not None and any(not line.startswith("|request|") for line in closed):
        records.append({"accepted": pending})
        pending = None
    records.append({"feed": closed})
    for line in closed:
        if line.startswith("|request|"):
            request = json.loads(line[len("|request|"):])
            if request["rqid"] in seen:
                continue
            seen.add(request["rqid"])
            k += 1
            text = trace["steps"][k]["input"].get(PLAYER)
            if text is not None and not request.get("wait"):
                records.append({"decision": request["rqid"], "sent": text,
                                "search": {"action": None, "cause": "fixture", "fallback": None, "reason": None,
                                           "seconds": 0.0, "spread_fallback": None, "spread_redrawn": None}})
                pending = text
with open(out, "w", encoding="utf-8", newline="\n") as f:
    for r in records:
        f.write(json.dumps(r) + "\n")
print(len(records), "records")
