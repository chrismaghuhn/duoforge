"""duoforge.python.random_pool: random teams in the training pool (lever 17, infrastructure only, no training run).

A random-team corpus (tools/reference/random_teams.py: RT_<sha16>.txt, index.json, manifest.json, outside the
repository) loads whole with teams.load_root, every team checked by the library as the registry's are; a refused
team stops explicitly. teams.combine joins it to a registry pool so that each side's team is drawn from the corpus
with probability `share` (uniform within it), the registry keeping its own weights among the rest. The corpus's
provenance (pin, seed, count, the sha256 of index.json and manifest.json, its own teams digest checked against the
index) is what a run records.
"""
import hashlib
import json
import os
import shutil
import tempfile
import unittest

import numpy as np

import duoforge
from duoforge import _layout, teams

REGISTRY = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "teams")


def _registry_ids(count):
    with open(os.path.join(REGISTRY, "index.json"), encoding="utf-8") as f:
        return [t["id"] for t in json.load(f)["teams"] if t["id"].startswith("PP_")][:count]


def make_corpus(folder, count=3, seed="0x2026101100000017", pin="b2cb775", skip=0):
    """A corpus in random_teams.py's form from registry pastes (POOL teams the library accepts, the PP_ ones after the
    first skip), renamed RT_<sha16>."""
    os.makedirs(folder)
    entries = []
    for tid in _registry_ids(skip + count)[skip:]:
        with open(os.path.join(REGISTRY, f"{tid}.txt"), "rb") as f:
            raw = f.read()
        rid = "RT_" + hashlib.sha256(raw).hexdigest()[:16]
        with open(os.path.join(folder, rid + ".txt"), "wb") as f:
            f.write(raw)
        entries.append({"id": rid, "sha256": teams.text_sha256(raw)})
    with open(os.path.join(folder, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"teams": entries}, f, indent=1)
    manifest = {"generator": "gen9championsrandomdoublesbattle", "pin": pin, "seed": seed, "kept": len(entries),
                "teams_sha256": hashlib.sha256("".join(e["sha256"] for e in entries).encode()).hexdigest()}
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    return [e["id"] for e in entries]


class RandomPoolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"])

    @classmethod
    def tearDownClass(cls):
        cls.ctx.close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "rt")
        self.ids = make_corpus(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_root_loads_every_team_of_the_index(self):
        pool = teams.load_root(self.ctx, self.root)
        self.assertEqual(list(pool.ids), self.ids)
        self.assertEqual(pool.sides.shape, (3,))
        self.assertTrue(all(len(s) == 64 for s in pool.sha256))

    def test_a_refused_or_altered_team_stops(self):
        path = os.path.join(self.root, self.ids[1] + ".txt")
        with open(path, "rb") as f:
            raw = f.read()
        with open(path, "wb") as f:
            f.write(raw.replace(b"Ability:", b"Ability: Not An Ability\nOld:", 1))
        with self.assertRaisesRegex(teams.TeamError, self.ids[1]):  # the index hash no longer matches
            teams.load_root(self.ctx, self.root)
        # Matching hash, but a name the tables do not have: refused, never skipped.
        self._reindex()
        with self.assertRaisesRegex(teams.TeamError, self.ids[1]):
            teams.load_root(self.ctx, self.root)

    def _reindex(self):
        with open(os.path.join(self.root, "index.json"), encoding="utf-8") as f:
            index = json.load(f)
        for t in index["teams"]:
            with open(os.path.join(self.root, t["id"] + ".txt"), "rb") as f:
                t["sha256"] = teams.text_sha256(f.read())
        with open(os.path.join(self.root, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f)

    def test_combine_draws_each_side_from_the_corpus_with_the_share(self):
        registry = teams.load(self.ctx, _registry_ids(5)[3:5], root=REGISTRY, weights=[3.0, 1.0])
        corpus = teams.load_root(self.ctx, self.root)
        pool = teams.combine(registry, corpus, 0.25)
        self.assertEqual(list(pool.ids), list(registry.ids) + list(corpus.ids))
        p = pool.weights / pool.weights.sum()
        self.assertAlmostEqual(p[2:].sum(), 0.25)
        np.testing.assert_allclose(p[2:], [0.25 / 3] * 3)
        np.testing.assert_allclose(p[:2], [0.75 * 0.75, 0.75 * 0.25])  # the registry's own weights, scaled
        everything = teams.combine(registry, corpus, 1.0)  # only the corpus
        self.assertAlmostEqual(float((everything.weights / everything.weights.sum())[2:].sum()), 1.0)
        for bad in (0.0, -0.1, 1.5, float("nan")):
            with self.assertRaises(ValueError):
                teams.combine(registry, corpus, bad)
        with self.assertRaisesRegex(ValueError, "unique"):  # the same team in both
            teams.combine(corpus, corpus, 0.5)

    def test_load_corpus_reads_the_pool_and_its_provenance_from_one_index(self):
        pool, provenance = teams.load_corpus(self.ctx, self.root)
        self.assertEqual(list(pool.ids), self.ids)
        self.assertEqual(list(pool.sha256), list(teams.load_root(self.ctx, self.root).sha256))
        self.assertEqual(provenance, teams.corpus_provenance(self.root))
        # An index that is not the manifest's stops before a team is loaded.
        with open(os.path.join(self.root, "index.json"), encoding="utf-8") as f:
            index = json.load(f)
        index["teams"] = index["teams"][:2]
        with open(os.path.join(self.root, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f)
        with self.assertRaisesRegex(teams.TeamError, "manifest"):
            teams.load_corpus(self.ctx, self.root)

    def test_check_disjoint_refuses_a_team_in_two_corpora(self):
        held = os.path.join(self.tmp.name, "held")
        make_corpus(held, count=2, seed="0x2026101100000018", skip=3)
        teams.check_disjoint(self.root, held)  # a training corpus and a held-out one share no id
        teams.check_disjoint(self.root, held, REGISTRY)
        again = os.path.join(self.tmp.name, "again")
        same = make_corpus(again, count=1, seed="0x2026101100000019")  # ids are content addressed: the same team
        with self.assertRaisesRegex(teams.TeamError, same[0]):
            teams.check_disjoint(self.root, held, again)
        with self.assertRaises(teams.TeamError):
            teams.check_disjoint(self.root, os.path.join(self.tmp.name, "missing"))

    def test_provenance(self):
        got = teams.corpus_provenance(self.root)
        with open(os.path.join(self.root, "index.json"), "rb") as f:
            index_sha = hashlib.sha256(f.read()).hexdigest()
        with open(os.path.join(self.root, "manifest.json"), "rb") as f:
            manifest_sha = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(got, {"pin": "b2cb775", "seed": "0x2026101100000017", "count": 3,
                               "index_sha256": index_sha, "manifest_sha256": manifest_sha})
        # The manifest's teams digest must be the index's: a corpus whose index was changed after its run is refused.
        with open(os.path.join(self.root, "index.json"), encoding="utf-8") as f:
            index = json.load(f)
        index["teams"] = index["teams"][:2]
        with open(os.path.join(self.root, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f)
        with self.assertRaisesRegex(teams.TeamError, "manifest"):
            teams.corpus_provenance(self.root)
        shutil.rmtree(self.root)
        with self.assertRaises(teams.TeamError):
            teams.corpus_provenance(self.root)


if __name__ == "__main__":
    unittest.main()
