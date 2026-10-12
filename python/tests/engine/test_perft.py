"""duoforge.python.perft: the perft/divide regression guard (tools/perft/perft.py, tests/perft/pins.json).

The pinned counts of legal joint action sequences, and the hash of the visited node records, of fixed reference
positions must not change unnoticed: a mechanic that adds or removes a legal option (a target, a switch, a Mega, a
pass, a revive) fails this test, and the change is either a bug or gets its pin rewritten with --write and a reason
in the commit message. The other tests hold the tool to the engine's own domains and to its own definition.
"""
import copy
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "perft"))
sys.dont_write_bytecode = True

import perft  # noqa: E402

PINS = perft.load_pins()


def spec(name):
    return copy.deepcopy(perft._position(PINS, name))


class DefinitionTest(unittest.TestCase):
    def test_depth_one_is_the_engines_candidate_list(self):
        # The joint actions of a node are the engine's own: the product of the full candidate lists
        # (duoforge_battle_candidates through batch.query) of the players asked, 250 x 218 at A-B's first turn.
        for name, asked in (("closure_ab_turn1", (0, 1)), ("closure_ab_pivot", (1,)),
                            ("closure_ab_replacement", (0, 1)), ("closure_ab_team_selection", (0, 1))):
            with self.subTest(name), perft.Tree(spec(name)) as tree:
                batch, env, record = tree.node
                batch.query()
                requested = [p for p in (0, 1) if batch.requests[env, p]["requested"]]
                self.assertEqual(tuple(requested), asked)
                expected = int(np.prod([int(batch.counts[env, p]) for p in requested]))
                self.assertEqual(tree.perft(1)[0], expected)
        with perft.Tree(spec("closure_ab_turn1")) as tree:
            self.assertEqual(tree.perft(1)[0], 250 * 218)

    def test_divide_is_perft_of_each_child(self):
        # divide[k] = perft(child k, d - 1), and the child reached through the prefix is the same node.
        base = spec("closure_ab_replacement")
        with perft.Tree(base) as tree:
            count, _, per = tree.perft(2)
            self.assertEqual(count, int(per.sum()))
            self.assertEqual(per.size, tree.perft(1)[0])
            record = tree.node[2]
        for k in range(per.size):
            child = dict(base, prefix=base["prefix"] + [perft.ranks_of(record, k)])
            with self.subTest(k), perft.Tree(child) as tree:
                self.assertEqual(tree.perft(1)[0], int(per[k]))

    def test_deterministic_for_any_worker_count(self):
        results = []
        for workers in (1, perft.WORKERS, perft.WORKERS):
            with perft.Tree(spec("closure_ab_pivot"), workers=workers) as tree:
                results.append(tree.perft(2)[:2])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])


class PinTest(unittest.TestCase):
    def test_pins_are_complete(self):
        names = [s["name"] for s in PINS["positions"]]
        self.assertEqual(len(names), len(set(names)))
        kinds, boundaries = set(), set()
        for s in PINS["positions"]:
            kinds.add(s["data_kind"])
            boundaries.add(s["boundary"])
            for key in ("seed", "prefix", "teams", "setup_sha256", "context_fingerprint", "library_version"):
                self.assertIn(key, s, s["name"])
            self.assertTrue({"1", "2"} <= set(s["depths"]), s["name"])
            for d, pin in s["depths"].items():
                self.assertIsInstance(pin["count"], int, (s["name"], d))
                self.assertEqual(len(pin["sequence_sha256"]), 64, (s["name"], d))
        self.assertEqual(kinds, {"CLOSURE", "POOL"})
        self.assertTrue({"TEAM_SELECTION", "TURN", "PIVOT", "REPLACEMENT"} <= boundaries)

    def test_the_file_is_in_the_writers_form(self):
        self.assertEqual(perft.dumps(PINS), perft.PINS.read_text(encoding="utf-8").replace("\r\n", "\n"))

    def test_every_pin_matches(self):
        lines = perft.check(PINS)
        self.assertEqual(lines, [], "\n" + "\n".join(lines))

    def test_a_changed_count_is_reported_readably(self):
        pinned = spec("closure_ab_pivot")
        now = perft.measure(pinned, depths=[1, 2, 3])
        pinned["depths"]["2"]["count"] += 1
        lines = perft.diff(pinned, now)
        self.assertIn(f"closure_ab_pivot depth 2: count pinned {now['depths']['2']['count'] + 1}, now "
                      f"{now['depths']['2']['count']} (-1)", lines)
        self.assertTrue(any("--position closure_ab_pivot --depth 3 --divide" in line for line in lines), lines)
        pinned = spec("closure_ab_pivot")
        pinned["depths"]["3"]["sequence_sha256"] = "0" * 64
        self.assertTrue(any("depth 3: sequence sha256 pinned 0000000000000000" in line
                            for line in perft.diff(pinned, now)))


class RefusalTest(unittest.TestCase):
    def assertRefused(self, s, text):
        with self.assertRaises(perft.PerftError) as ctx:
            with perft.Tree(s):
                pass
        self.assertIn(text, str(ctx.exception))

    def test_refusals_are_explicit(self):
        base = spec("closure_ab_turn1")
        self.assertRefused(dict(base, data_kind="TEAM_C_DEV"), "data kind 'TEAM_C_DEV'")
        self.assertRefused(dict(base, pairing=4), "pairing 4")
        # Team C's members are not in the closure tables: the registry loader says so, nothing is skipped.
        closure_c = {k: v for k, v in base.items() if k != "pairing"}
        self.assertRefused(dict(closure_c, registry=["C", "A"]), "not in the tables of this context's data kind")
        self.assertRefused(dict(closure_c, registry=["NO_SUCH_TEAM", "A"]), "NO_SUCH_TEAM")
        self.assertRefused(dict(base, prefix=[[0, 0], [0, None]]), "asks players [0, 1]")
        self.assertRefused(dict(base, prefix=[[0, 0], [250, 0]]), "outside the domains of sizes [250, 218]")
        with perft.Tree(base) as tree:
            with self.assertRaises(perft.PerftError):
                tree.perft(0)

    def test_an_engine_refusal_names_the_status(self):
        # A step the engine refuses (here: a forged domain that offers a pair the engine never allowed) is raised
        # with the engine's status, never counted.
        with perft.Tree(spec("closure_ab_pivot")) as tree:
            batch, env, record = tree.node
            choices = tree._choices(batch, env, record, [0])
            choices[0, 1]["slot"][0] = 31  # past the slot list
            with self.assertRaises(perft.PerftError) as ctx:
                tree._expand(batch, env, tree._level(1), choices, "the forged node")
            self.assertIn("DUOFORGE_E_INVALID_ARGUMENT", str(ctx.exception))
            self.assertIn("the forged node", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
