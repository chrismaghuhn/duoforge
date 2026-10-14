"""The campaign.conf of an AWS preview-oracle campaign (#458): one predeclared series of the preview oracle on one box,
its networks and its foe team named by sha256 only.

    python3 oracle_conf.py check CONF                     validate (exit 2 and the reason on a bad conf)
    python3 oracle_conf.py shas CONF                      the networks' sha256, one per line (the box fetches
                                                          nets/<sha>.npz)
    python3 oracle_conf.py team CONF                      the foe team's sha256 (the box fetches teams/<sha>.txt)
    python3 oracle_conf.py ours CONF                      our team's registry id (data/teams/<id>.txt at the commit)
    python3 oracle_conf.py workers CONF                   the engine workers of each process
    python3 oracle_conf.py argv CONF NETS TEAMS OUT       the series' arguments, one per line (NETS, TEAMS: where the box
                                                          put the networks and the foe team)

The launcher reads the conf at the commit it launches and checks it here; the box reads the same file at the same
commit and builds the command line here, so the two cannot differ. Keys (key=value lines, # comments):

    kind=oracle                     required: a preview-oracle campaign, not a ladder or fuzz one
    plan=NAME                       required: the predeclared series the box runs, one of PLANS (its seeds, pairs,
                                    rounds, stop rule and final measurement are the plan's README, not the conf's)
    checkpoint=SHA256               required: the main network (both seats search with it)
    foe_net=SHA256                  required: the foe model of the searched worlds
    ours=ID                         required: our team, a registry id of data/teams/index.json (its file
                                    data/teams/<ID>.txt at the commit must have the index's sha256)
    foe_team=SHA256                 required: the foe team's sheet, a private file of the bucket's teams/ (read-only
                                    for the box, checked against this sha256)
    workers=N                       optional (default 8): engine workers per process, fixed for the series
    max_steps=N                     optional (default 1000)

No path, no URL, no seed, no pair count and no flag of the oracle reaches the box from the conf: the plan fixes them.
"""
import re
import sys

PLANS = ("preview-mixed-2026-10-14",)  # docs/benchmarks/2026-10-14-preview-mixed/README.md (f6b924a4)
REQUIRED = ("kind", "plan", "checkpoint", "foe_net", "ours", "foe_team")
OPTIONAL = {"workers": "8", "max_steps": "1000"}
SHA = re.compile(r"^[0-9a-f]{64}$")
TEAM_ID = re.compile(r"^[A-Za-z0-9_]{1,40}$")


class ConfError(ValueError):
    """A campaign.conf that is not a valid preview-oracle campaign, named."""


def _int(text, key, low, high):
    try:
        value = int(text, 0)
    except ValueError:
        raise ConfError(f"{key}={text!r} is not a number") from None
    if not low <= value <= high:
        raise ConfError(f"{key}={value} is not between {low} and {high}")
    return value


def parse(text):
    """The validated conf as a dict."""
    raw = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ConfError(f"line {number} is not key=value")
        key, value = key.strip(), value.strip()
        if key not in REQUIRED and key not in OPTIONAL:
            raise ConfError(f"unknown key {key!r} (line {number})")
        if key in raw:
            raise ConfError(f"key {key!r} twice")
        raw[key] = value
    missing = [k for k in REQUIRED if not raw.get(k)]
    if missing:
        raise ConfError(f"missing key(s): {', '.join(missing)}")
    if raw["kind"] != "oracle":
        raise ConfError(f"kind={raw['kind']!r}: not a preview-oracle campaign")
    if raw["plan"] not in PLANS:
        raise ConfError(f"plan={raw['plan']!r} is not a predeclared plan ({', '.join(PLANS)})")
    conf = {"kind": "oracle", "plan": raw["plan"]}
    for key in ("checkpoint", "foe_net", "foe_team"):
        if not SHA.match(raw[key]):
            raise ConfError(f"{key} must be a 64-digit lowercase sha256 (got {raw[key]!r})")
        conf[key] = raw[key]
    if not TEAM_ID.match(raw["ours"]):
        raise ConfError(f"ours={raw['ours']!r} is not a registry id (letters, digits and underscores)")
    conf["ours"] = raw["ours"]
    conf["workers"] = _int(raw.get("workers", OPTIONAL["workers"]), "workers", 1, 16)
    conf["max_steps"] = _int(raw.get("max_steps", OPTIONAL["max_steps"]), "max_steps", 1, 100000)
    return conf


def shas(conf):
    """Every network's sha256 the series needs, sorted, each once (the foe team is apart: team)."""
    return sorted({conf["checkpoint"], conf["foe_net"]})


def argv(conf, nets, teams, out):
    """The arguments of `python -m duoforge_search.preview_series`: the networks as NETS/<sha256>.npz, our team as its
    registry file, the foe team as TEAMS/<sha256>.txt."""
    net = lambda sha: f"{nets}/{sha}.npz"  # noqa: E731
    return ["--plan", conf["plan"], "--checkpoint", net(conf["checkpoint"]), "--foe-net", net(conf["foe_net"]),
            "--ours", f"data/teams/{conf['ours']}.txt", "--foe", f"{teams}/{conf['foe_team']}.txt",
            "--workers", str(conf["workers"]), "--max-steps", str(conf["max_steps"]), "--out", out]


def main(argv_=None):
    args = sys.argv[1:] if argv_ is None else argv_
    counts = {"check": 2, "shas": 2, "team": 2, "ours": 2, "workers": 2, "argv": 5}
    if not args or args[0] not in counts or len(args) != counts[args[0]]:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    try:
        with open(args[1], encoding="utf-8") as f:
            conf = parse(f.read())
        if args[0] == "shas":
            print("\n".join(shas(conf)))
        elif args[0] == "team":
            print(conf["foe_team"])
        elif args[0] == "ours":
            print(conf["ours"])
        elif args[0] == "workers":
            print(conf["workers"])
        elif args[0] == "argv":
            print("\n".join(argv(conf, args[2], args[3], args[4])))
    except (OSError, ConfError) as err:
        print(f"oracle_conf: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
