"""The campaign.conf of an AWS ladder campaign (#484): up to MAX_ARMS ladder arms on one box, side by side, their
networks named by sha256 only.

    python3 ladder_conf.py check CONF                 validate (exit 2 and the reason on a bad conf)
    python3 ladder_conf.py shas CONF                  the networks' sha256, one per line (the box fetches nets/<sha>.npz)
    python3 ladder_conf.py arms CONF                  the arms' names, one per line, in the conf's order
    python3 ladder_conf.py argv CONF ARM NETS OUT     arm ARM's ladder arguments, one per line (NETS: where the box put
                                                      the networks)

launch_ladder.sh reads the conf at the commit it launches and checks it here; the box reads the same file at the same
commit and builds each arm's command line here, so the two cannot differ. Keys (key=value lines, # comments):

    kind=ladder                     required: a ladder campaign, not a fuzz one
    arm=NAME step=S [previous=P] [h2h=0|1]
                                    1 to MAX_ARMS lines: an arm's name (lowercase letters, digits, dashes; its results
                                    go under <run>/<NAME>/), the step measured (duoforge_search.ladder.STEPS; the ladder
                                    refuses an unknown one), the previous step and the head-to-head against it
    pairs=N                         required: 1 to 4096 team pairs, every arm
    seed=N                          required: the ladder's seed, decimal or 0x hex, every arm
    workers=N                       optional (default 8): engine workers per arm, fixed for the run (HauptSession: 8)
    max_steps=N                     optional (default 1000)
    checkpoint=SHA256               required: the main network
    foe_net=SHA256                  required: the foe model
    teams_from=SHA256               required: the pool network whose config's teams are the suite's pool
    opponents=NAME=SHA256 ...       required: 1 to 6 opponents, names of lowercase letters and digits

The arms share the networks, the opponents, the pairs and the seed: an arm's digests must not depend on what runs
beside it (the equality proof checks one arm alone and beside others). No path, no URL and no flag of the ladder's
beyond these reaches the box from the conf.
"""
import re
import sys

MAX_ARMS = 3  # HauptSession, 2026-10-14: three arms of 16 CPUs on a c7a.16xlarge, 16 left for the box; 4 only by its decision
REQUIRED = ("kind", "pairs", "seed", "checkpoint", "foe_net", "teams_from", "opponents")
OPTIONAL = {"workers": "8", "max_steps": "1000"}
SHA = re.compile(r"^[0-9a-f]{64}$")
STEP = re.compile(r"^[0-9a-z][0-9a-z-]{0,31}$")
NAME = re.compile(r"^[a-z0-9]{1,16}$")
ARM = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


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


def _arm(value, number):
    """One arm line's value: NAME step=S [previous=P] [h2h=0|1]."""
    name, *fields = value.split()
    if not ARM.match(name):
        raise ConfError(f"arm {name!r} (line {number}): lowercase letters, digits and dashes")
    arm = {"name": name, "step": None, "previous": None, "h2h": "0"}
    for field in fields:
        key, sep, item = field.partition("=")
        if not sep or key not in ("step", "previous", "h2h") or (key != "h2h" and arm[key] is not None):
            raise ConfError(f"arm {name}: {field!r} is not step=, previous= or h2h= (each once)")
        arm[key] = item
    for key in ("step", "previous"):
        if arm[key] is not None and not STEP.match(arm[key]):
            raise ConfError(f"arm {name}: {key}={arm[key]!r} is not a step name")
    if arm["step"] is None:
        raise ConfError(f"arm {name}: no step=")
    if arm["h2h"] not in ("0", "1"):
        raise ConfError(f"arm {name}: h2h={arm['h2h']!r}: 0 or 1")
    if arm["h2h"] == "1" and not arm["previous"]:
        raise ConfError(f"arm {name}: h2h=1 needs previous")
    return arm


def parse(text):
    """The validated conf as a dict (arms: a list of dicts; opponents: a list of (name, sha256))."""
    raw, arms = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ConfError(f"line {number} is not key=value")
        key, value = key.strip(), value.strip()
        if key == "arm":
            arms.append(_arm(value, number))
            continue
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
    if not 1 <= len(arms) <= MAX_ARMS:
        raise ConfError(f"{len(arms)} arms: 1 to {MAX_ARMS}")
    if len({a["name"] for a in arms}) != len(arms):
        raise ConfError("an arm name twice")
    conf = {"kind": "ladder", "arms": arms}
    conf["pairs"] = _int(raw["pairs"], "pairs", 1, 4096)
    conf["seed"] = _int(raw["seed"], "seed", 0, 2**64 - 1)
    conf["workers"] = _int(raw.get("workers", OPTIONAL["workers"]), "workers", 1, 16)
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


def argv(conf, arm_name, nets, out):
    """The arguments of `python -m duoforge_search.ladder` for one arm: every network as nets/<sha256>.npz."""
    arm = next((a for a in conf["arms"] if a["name"] == arm_name), None)
    if arm is None:
        raise ConfError(f"no arm {arm_name!r}")
    net = lambda sha: f"{nets}/{sha}.npz"  # noqa: E731
    args = ["--checkpoint", net(conf["checkpoint"]), "--foe-net", net(conf["foe_net"]),
            "--teams-from", net(conf["teams_from"]), "--step", arm["step"]]
    if arm["previous"]:
        args += ["--previous", arm["previous"]]
    if arm["h2h"] == "1":
        args.append("--h2h")
    for name, sha in conf["opponents"]:
        args += ["--opponent", f"{name}={net(sha)}"]
    args += ["--pairs", str(conf["pairs"]), "--seed", hex(conf["seed"]), "--workers", str(conf["workers"]),
             "--max-steps", str(conf["max_steps"]), "--out", out]
    return args


def main(argv_=None):
    args = sys.argv[1:] if argv_ is None else argv_
    counts = {"check": 2, "shas": 2, "arms": 2, "argv": 5}
    if not args or args[0] not in counts or len(args) != counts[args[0]]:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    try:
        with open(args[1], encoding="utf-8") as f:
            conf = parse(f.read())
        if args[0] == "shas":
            print("\n".join(shas(conf)))
        elif args[0] == "arms":
            print("\n".join(a["name"] for a in conf["arms"]))
        elif args[0] == "argv":
            print("\n".join(argv(conf, args[2], args[3], args[4])))
    except (OSError, ConfError) as err:
        print(f"ladder_conf: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
