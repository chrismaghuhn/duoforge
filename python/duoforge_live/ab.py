"""The live A/B test of the search's root rule (owner, 2026-10-14; #385, docs/benchmarks/2026-10-14-ab-root-rule).

Each battle the bot plays with its team plays one arm: ladder step 0 (the root's mixed rule, lambda 0.5, the settings of
bot commit 1ffa6a03) or step 2e (the best answer, the live search since a7dd956b). The arms differ in the root rule only
(check_arms): the preview, the networks, the foe model, the worlds and the budget are the same.

The battles are numbered in the order the bot opens them, and the arms are randomized in blocks of two: block b (battles
2b and 2b + 1) plays one battle of each arm, in an order drawn from the run's seed and b alone. The draw reads nothing of
the opponent, the format or the battle: only the seed and the battle's number. The seed is in the run log's head, the arm
and its settings in each battle log's first record.
"""
import hashlib
import secrets

ARMS = ("0", "2e")  # ladder steps (duoforge_search.ladder.STEPS)
BLOCK = 2


def new_seed():
    """A run's seed: 63 random bits (the run log names it)."""
    return secrets.randbits(63)


def arm(seed, index):
    """The arm of battle `index` (0, 1, 2, ... in the order opened) under `seed`: a pure function of the two."""
    if isinstance(seed, bool) or not isinstance(seed, int) or isinstance(index, bool) or not isinstance(index, int) \
            or index < 0:
        raise ValueError(f"an A/B draw needs an int seed and a battle number >= 0 (got {seed!r}, {index!r})")
    block, position = divmod(index, BLOCK)
    digest = hashlib.blake2b(f"duoforge-ab-root-rule|{seed}|{block}".encode("utf-8"), digest_size=8).digest()
    swap = digest[0] & 1
    return ARMS[position ^ swap]


def settings():
    """{arm: the search settings of its ladder step}."""
    from duoforge_search import ladder
    return {a: ladder.step_settings(a) for a in ARMS}


def check_arms(live_settings):
    """ValueError unless the arms differ in the root rule alone and the live search's settings (search.load's) are one
    arm's but for the rule: the bot switches only the rule, battle by battle, on one search."""
    arms = settings()
    keys = set().union(*arms.values())
    differ = sorted(k for k in keys if len({repr(s.get(k)) for s in arms.values()}) > 1)
    if differ != ["rule"]:
        raise ValueError(f"the A/B arms differ in {differ}, not in the root rule alone")
    base = {k: v for k, v in arms[ARMS[0]].items() if k != "rule"}
    live = {k: v for k, v in dict(live_settings).items() if k != "rule"}
    if live != base:
        raise ValueError(f"the live search's settings {live} are not the arms' {base} (but the rule)")


def rule(arm_name):
    """The root rule of an arm."""
    return settings()[arm_name]["rule"]
