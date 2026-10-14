"""The campaign.conf of an AWS ladder campaign (#484): one ladder arm, its networks named by sha256 only.

    python3 ladder_conf.py check CONF             validate (exit 2 and the reason on a bad conf)
    python3 ladder_conf.py shas CONF              the networks' sha256, one per line (the box fetches nets/<sha>.npz)
    python3 ladder_conf.py argv CONF NETS OUT     the ladder's arguments, one per line (NETS: where the box put them)

launch_ladder.sh reads the conf at the commit it launches and checks it here; the box reads the same file at the same
commit and builds the ladder's command line here, so the two cannot differ. Keys (key=value lines, # comments):

    kind=ladder                     required: a ladder campaign, not a fuzz one
    step=NAME                       required: the step measured (duoforge_search.ladder.STEPS; the ladder refuses an
                                    unknown one)
    previous=NAME                   optional: the previous step (the paired comparison)
    h2h=0|1                         optional (default 0): the head-to-head against previous (needs previous)
    pairs=N                         required: 1 to 4096 team pairs
    seed=N                          required: the ladder's seed, decimal or 0x hex
    workers=N                       required: 1 to 64 engine workers, fixed for the run (the equality proof compares
                                    runs of the same worker count)
    max_steps=N                     optional (default 1000)
    checkpoint=SHA256               required: the main network
    foe_net=SHA256                  required: the foe model
    teams_from=SHA256               required: the pool network whose config's teams are the suite's pool
    opponents=NAME=SHA256 ...       required: 1 to 6 opponents, names of lowercase letters and digits

No path, no URL and no flag of the ladder's beyond these reaches the box from the conf.
"""
import re
import sys

REQUIRED = ("kind", "step", "pairs", "seed", "workers", "checkpoint", "foe_net", "teams_from", "opponents")
OPTIONAL = {"previous": None, "h2h": "0", "max_steps": "1000"}
SHA = re.compile(r"^[0-9a-f]{64}$")
STEP = re.compile(r"^[0-9a-z][0-9a-z-]{0,31}$")
NAME = re.compile(r"^[a-z0-9]{1,16}$")


class ConfError(ValueError):
    """A campaign.conf that is not a valid ladder campaign, named."""


def _int(text, key, low, high):
    try:
        value = int(text, 0)
    except ValueError:
        raise ConfError(f"{key}={text!r} is not a number") from None
    if not low <= value <= high:
        raise ConfError(f"{key}={value} is not between {low} and {high}")
    return value


def parse(text):
    """The validated conf as a dict (opponents: a list of (name, sha256))."""
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
    if raw["kind"] != "ladder":
        raise ConfError(f"kind={raw['kind']!r}: not a ladder campaign")
    conf = {"kind": "ladder"}
    for key in ("step", "previous"):
        value = raw.get(key)
        if value is not None and not STEP.match(value):
            raise ConfError(f"{key}={value!r} is not a step name")
        conf[key] = value
    conf["h2h"] = raw.get("h2h", OPTIONAL["h2h"])
    if conf["h2h"] not in ("0", "1"):
        raise ConfError(f"h2h={conf['h2h']!r}: 0 or 1")
    if conf["h2h"] == "1" and not conf["previous"]:
        raise ConfError("h2h=1 needs previous")
    conf["pairs"] = _int(raw["pairs"], "pairs", 1, 4096)
    conf["seed"] = _int(raw["seed"], "seed", 0, 2**64 - 1)
    conf["workers"] = _int(raw["workers"], "workers", 1, 64)
    conf["max_steps"] = _int(raw.get("max_steps", OPTIONAL["max_steps"]), "max_steps", 1, 100000)
    for key in ("checkpoint", "foe_net", "teams_from"):
        if not SHA.match(raw[key]):
            raise ConfError(f"{key} must be a 64-digit lowercase sha256 (got {raw[key]!r})")
        conf[key] = raw[key]
    opponents = []
    for item in raw["opponents"].split():
        name, sep, sha = item.partition("=")
        if not sep or not NAME.match(name) or not SHA.match(sha):
            raise ConfError(f"opponent {item!r} is not NAME=SHA256")
        if name in {n for n, _ in opponents}:
            raise ConfError(f"opponent {name!r} twice")
        opponents.append((name, sha))
    if not 1 <= len(opponents) <= 6:
        raise ConfError(f"{len(opponents)} opponents: 1 to 6")
    conf["opponents"] = opponents
    return conf


def shas(conf):
    """Every network's sha256 the run needs, sorted, each once."""
    return sorted({conf["checkpoint"], conf["foe_net"], conf["teams_from"], *(s for _, s in conf["opponents"])})


def argv(conf, nets, out):
    """The arguments of `python -m duoforge_search.ladder`: every network as nets/<sha256>.npz."""
    net = lambda sha: f"{nets}/{sha}.npz"  # noqa: E731
    args = ["--checkpoint", net(conf["checkpoint"]), "--foe-net", net(conf["foe_net"]),
            "--teams-from", net(conf["teams_from"]), "--step", conf["step"]]
    if conf["previous"]:
        args += ["--previous", conf["previous"]]
    if conf["h2h"] == "1":
        args.append("--h2h")
    for name, sha in conf["opponents"]:
        args += ["--opponent", f"{name}={net(sha)}"]
    args += ["--pairs", str(conf["pairs"]), "--seed", hex(conf["seed"]), "--workers", str(conf["workers"]),
             "--max-steps", str(conf["max_steps"]), "--out", out]
    return args


def main(argv_=None):
    args = sys.argv[1:] if argv_ is None else argv_
    if len(args) < 2 or args[0] not in ("check", "shas", "argv") or (args[0] == "argv") != (len(args) == 4):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    try:
        with open(args[1], encoding="utf-8") as f:
            conf = parse(f.read())
    except (OSError, ConfError) as err:
        print(f"ladder_conf: {err}", file=sys.stderr)
        return 2
    if args[0] == "shas":
        print("\n".join(shas(conf)))
    elif args[0] == "argv":
        print("\n".join(argv(conf, args[2], args[3])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
