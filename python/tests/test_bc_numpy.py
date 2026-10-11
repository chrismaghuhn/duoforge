"""duoforge.python.bc_numpy: the BC data path without JAX (M11 BC spec sections 5 and 6).

The fixture dataset is built with the replay pipeline from our own reference
battle's spectator log (python/tests/data/replay/c12_real_cb_4.log), into a
temporary directory outside the repository.
"""
import itertools
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

import duoforge
from duoforge import _layout, features
from duoforge_live import lines

FIXTURE = Path(__file__).resolve().parent / "data" / "replay" / "c12_real_cb_4.log"


class _Stats:
    """A stand-in for the Showdown stat source (no Node): fixed stats per forme."""

    def stats(self, species, nature, stat_points):
        return [100 + len(species), 90, 80, 70, 60, 50]


def stats_factory():
    return _Stats()


NATURES = ("Adamant", "Jolly", "Brave", "Lonely", "Naughty", "Hardy", "Docile", "Serious", "Bashful", "Quirky",
           "Bold", "Relaxed", "Impish", "Lax", "Timid", "Hasty", "Naive", "Modest", "Mild", "Quiet", "Rash", "Calm",
           "Gentle", "Sassy", "Careful")


def variant(log, n1, n2):
    """The fixture log with Kingambit's nature n1 (p1) and Politoed's n2 (p2): another sheet pair, the same game."""
    out = []
    for line in log.split(chr(10)):
        if line.startswith("|showteam|p1|"):
            line = line.replace("KowtowCleave,SuckerPunch,IronHead,Protect|Adamant|", f"KowtowCleave,SuckerPunch,IronHead,Protect|{n1}|")
        elif line.startswith("|showteam|p2|"):
            line = line.replace("WeatherBall,MuddyWater,IceBeam,Protect|Modest|", f"WeatherBall,MuddyWater,IceBeam,Protect|{n2}|")
        out.append(line)
    return chr(10).join(out)


def split_variants(train, val):
    """(n1, n2) nature pairs whose sheet pairs give `train` games outside and `val` games inside the validation
    bucket (bc_data.split_key)."""
    from duoforge_learn import bc_data
    from duoforge_replay import game
    log = FIXTURE.read_text(encoding="utf-8")
    picked = {False: [], True: []}
    for n1, n2 in itertools.product(NATURES, NATURES):
        packed = [line.split("|", 3)[3] for line in variant(log, n1, n2).split(chr(10)) if line.startswith("|showteam|")]
        is_val = bc_data.split_key(np.array([game._hash8(p) for p in packed], dtype=np.uint64))
        if len(picked[is_val]) < (val if is_val else train):
            picked[is_val].append((n1, n2))
        if len(picked[False]) == train and len(picked[True]) == val:
            return picked[False] + picked[True]
    raise AssertionError("no nature pairs for the split")


def short_log(log):
    """The fixture log cut before p1's Salamence enters: three of p1's four brought members are seen."""
    lines = log.split(chr(10))
    cut = next(i for i, line in enumerate(lines) if line.startswith("|switch|p1a: Salamence|"))
    return chr(10).join(lines[:cut] + ["|win|p2"])


def build_fixture(tmp, copies=2, format_id="gen9championsvgc2026regmc", natures=None, name="dataset",
                  pick_hypotheses=False):
    """A dataset of games of the fixture log (ids fixture-0..): `copies` plain copies, or one game per nature pair
    of `natures` (split_variants); built into tmp/name. pick_hypotheses: the copies are the short log (short_log),
    built with the pick hypotheses."""
    from duoforge_replay import build
    log = FIXTURE.read_text(encoding="utf-8")
    if pick_hypotheses:
        log = short_log(log)
    prior_path = tmp / "prior.json"
    prior_path.write_text(json.dumps({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]}),
                          encoding="utf-8")
    logs = [variant(log, n1, n2) for n1, n2 in natures] if natures else [log] * copies
    source = tmp / f"{name}.jsonl"
    with open(source, "w", encoding="utf-8", newline=chr(10)) as f:
        for i, text in enumerate(logs):
            f.write(json.dumps({"id": f"fixture-{i}", "formatid": format_id, "log": text}) + chr(10))
    out = tmp / name
    build.build([source], prior_path, out, stats_factory=stats_factory, log=lambda _: None,
                format_prefix=format_id[:len("gen9championsvgc2026regmc")], pick_hypotheses=pick_hypotheses)
    return out


class BcDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from duoforge_learn import bc_data
        cls.bc_data = bc_data
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_bc_"))
        cls.out = build_fixture(cls.tmp)
        cls.context = duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"])
        cls.mask = bc_data.bc_mask(cls.context)
        cls.rows = bc_data.load([cls.out], cls.context, cls.mask)

    @classmethod
    def tearDownClass(cls):
        cls.context.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_rating_weight(self):
        w = self.bc_data.rating_weight
        self.assertEqual((w(1300), w(1000), w(1150), w(-1), w(1600), w(900)), (1.0, 0.25, 0.625, 0.25, 1.0, 0.25))

    def test_split_by_team_pair(self):
        rng = np.random.default_rng(7)
        pairs = rng.integers(0, 2 ** 63, size=(10000, 2), dtype=np.uint64)
        val = np.array([self.bc_data.split_key(p) for p in pairs])
        self.assertTrue(0.03 < val.mean() < 0.07, val.mean())
        self.assertTrue(all(self.bc_data.split_key(p) == self.bc_data.split_key(p[::-1]) for p in pairs[:200]))
        self.assertTrue(all(self.bc_data.split_key(p) == v for p, v in zip(pairs[:200], val[:200])))

    def test_rows_and_labels(self):
        from duoforge_replay import dataset
        r = self.rows
        n = sum(len(s["game"]) for s in dataset.read(self.out))
        self.assertEqual(len(r.weight), n)
        self.assertEqual(r.obs.shape, (n, features.OBS_SIZE))
        shards = list(dataset.read(self.out))
        label_slots = np.concatenate([s["label_slots"] for s in shards])
        for i in range(n):
            if r.is_team[i]:
                self.assertTrue(r.label_team[i].any(), i)
                continue
            a = [(int(label_slots[i, 0]) >> k) & 1 == 1 for k in range(32)]
            b = [(int(label_slots[i, 1]) >> k) & 1 == 1 for k in range(32)]
            expected = np.outer(a, b) & r.mask[i]
            self.assertTrue(np.array_equal(r.label_pairs[i], expected), i)
            self.assertTrue(r.label_pairs[i].any(), i)  # the logged choice is inside the set

    def test_rows_are_packed(self):
        # 1.1 million M-C and M-B rows must fit: the three bool masks are kept bit-packed, unpacked on access
        r = self.rows
        n = len(r)
        self.assertEqual((r.mask_bits.dtype, r.mask_bits.shape), (np.uint8, (n, 128)))
        self.assertEqual((r.pair_bits.shape, r.team_bits.shape), ((n, 128), (n, 45)))
        self.assertEqual((r.mask.shape, r.label_pairs.shape, r.label_team.shape), ((n, 32, 32), (n, 32, 32), (n, 360)))
        part = r.take(np.array([2, 0]))
        self.assertTrue(np.array_equal(part.label_pairs, r.label_pairs[[2, 0]]))
        self.assertTrue(np.array_equal(part.mask, r.mask[[2, 0]]))

    def test_value_targets(self):
        from duoforge_replay import dataset
        r = self.rows
        games = dataset.read_games(dataset.parts(self.out)[0])
        winner = int(games["winner"][0])
        self.assertIn(winner, (0, 1))
        self.assertTrue(r.has_z.all())
        self.assertTrue(np.array_equal(r.z, np.where(r.side == winner, 1.0, -1.0).astype(np.float32)))

    def test_mask_holds_only_folded_bits(self):
        # review #2: a base-value bit the library supports but the tracker does not fold (Electric/Misty after #163)
        # never reaches a row, so its input rows would keep their random init: it must not be in the BC mask
        from unittest import mock
        snow = 1 << lines.FEATURES["WEATHER_SNOW"]
        with mock.patch.object(lines, "TRACKER_FOLDS", lines.TRACKER_FOLDS & ~snow):
            self.assertFalse(self.bc_data.bc_mask(self.context) & snow)
        self.assertTrue(self.bc_data.bc_mask(self.context) & snow)

    def test_mask_mismatch_raises(self):
        from unittest import mock
        with mock.patch.object(lines, "LIBRARY_SUPPORTED", lines.LIBRARY_SUPPORTED ^ 1):
            with self.assertRaises(ValueError) as caught:
                self.bc_data.bc_mask(self.context)
        message = str(caught.exception)
        self.assertIn(f"{lines.LIBRARY_SUPPORTED ^ 1:#x}", message)
        self.assertIn(f"{lines.LIBRARY_SUPPORTED:#x}", message)

    def with_manifest(self, name, change):
        """A copy of the fixture dataset whose output manifest.json is changed by `change`."""
        copy = self.tmp / name
        if copy.exists():
            shutil.rmtree(copy)
        shutil.copytree(self.out, copy)
        path = copy / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        change(manifest)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return copy

    def test_a_new_dataset_names_its_source(self):
        self.assertEqual(self.bc_data.dataset_source(self.out), "sheet")

    def test_a_belief_dataset_without_its_weight_is_refused(self):
        belief = self.with_manifest("belief", lambda m: m.update(source="bo1_belief"))
        with self.assertRaisesRegex(ValueError, "--source-weight bo1_belief"):
            self.bc_data.load([belief], self.context, self.mask)
        half = self.bc_data.load([belief], self.context, self.mask, source_weights={"bo1_belief": 0.5})
        np.testing.assert_allclose(half.weight, self.rows.weight * 0.5)

    def test_a_drop_sheets_dataset_never_trains(self):
        # review minor: drop_sheets holds the test split's games; no weight lets it into training
        drop = self.with_manifest("drop", lambda m: m.update(source="drop_sheets"))
        with self.assertRaisesRegex(ValueError, "validation"):
            self.bc_data.load([drop], self.context, self.mask, source_weights={"drop_sheets": 1.0})

    def test_belief_rows_split_by_player(self):
        # review I4: a belief game's drawn sheets change with each draw; its split follows its players
        from duoforge_replay import dataset, split
        belief = self.with_manifest("belief-split", lambda m: m.update(source="bo1_belief"))
        part = next(iter(dataset.parts(belief)))
        games = dataset.read_games(part)
        want = split.of_game(tuple(int(h) for h in games["players"][0])) == "test"
        # sheet hashes whose sheet-pair split is the other one: a split by sheets would fail this test
        other = next(np.array([a, a + 1], dtype=np.uint64) for a in range(1, 10 ** 6)
                     if bool(self.bc_data.split_key(np.array([a, a + 1], dtype=np.uint64))) != want)
        games["sheets"] = np.tile(other, (len(games["sheets"]), 1))
        dataset.write_npz(Path(part) / "games.npz", games)
        rows = self.bc_data.load([belief], self.context, self.mask, source_weights={"bo1_belief": 1.0})
        self.assertTrue((rows.val == want).all())

    def test_the_source_weight_of_sheets_is_one_unless_named(self):
        named = self.bc_data.load([self.out], self.context, self.mask, source_weights={"sheet": 2.0})
        np.testing.assert_allclose(named.weight, self.rows.weight * 2.0)

    def test_an_old_dataset_is_a_sheet_dataset_but_never_loads(self):
        # format version 1 (before the source existed) was always a sheet build; versions 1 and 2 carry no extension
        # record, and since #334 their rows can hold fold states the encoder cannot see: rebuild them
        old = self.with_manifest("old", lambda m: (m.pop("source"), m.pop("tracker_folds"), m.pop("ext_revision"),
                                                   m.update(format_version=1)))
        self.assertEqual(self.bc_data.dataset_source(old), "sheet")
        for version in (1, 2):
            legacy = self.with_manifest(f"legacy{version}", lambda m: (m.pop("tracker_folds"), m.pop("ext_revision"),
                                                                      m.update(format_version=version)))
            with self.subTest(version), self.assertRaisesRegex(ValueError, "extension record"):
                self.bc_data.load([legacy], self.context, self.mask)

    def test_hypothesis_rows_load_only_with_their_weight(self):
        # M11 pick hypotheses spec, section 5: left out by default; --pick-hypotheses-weight W gives W/H per row
        from duoforge_replay import dataset
        hyp = build_fixture(self.tmp, name="hyp", pick_hypotheses=True)
        shards = list(dataset.read(hyp))
        h = np.concatenate([s["picks_hypotheses"] for s in shards])
        self.assertEqual(set(h.tolist()), {1, 3})
        plain = self.bc_data.load([hyp], self.context, self.mask)
        self.assertEqual(len(plain), int((h == 1).sum()))
        taken = self.bc_data.load([hyp], self.context, self.mask, pick_hypotheses_weight=0.6)
        self.assertEqual(len(taken), len(h))
        rating = np.concatenate([[self.bc_data.rating_weight(int(r)) for r in dataset.read_games(Path(hyp) / s["part"])[
            "ratings"][s["game"].astype(np.int64), s["side"].astype(np.int64)]] for s in shards])
        np.testing.assert_allclose(taken.weight, rating * np.where(h > 1, 0.6 / h, 1.0), rtol=1e-6)
        np.testing.assert_allclose(taken.weight[h == 1], plain.weight, rtol=1e-6)
        for bad in (0.0, -1.0):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "pick_hypotheses_weight"):
                self.bc_data.load([hyp], self.context, self.mask, pick_hypotheses_weight=bad)

    def test_a_version_3_dataset_has_no_hypothesis_rows(self):
        v3 = self.with_manifest("v3", lambda m: m.update(format_version=3))
        self.assertEqual(len(self.bc_data.load([v3], self.context, self.mask)), len(self.rows))

    def assert_rows_equal(self, a, b):
        from dataclasses import fields
        self.assertEqual(len(a), len(b))
        for f in fields(a):
            self.assertTrue(np.array_equal(np.asarray(getattr(a, f.name)), np.asarray(getattr(b, f.name))), f.name)

    def test_rows_can_be_written_to_and_read_from_a_memmap_directory(self):
        # the BC run of 2026-10-11: 6.6 million rows (about 51 GB) do not fit in memory; the encoded rows go into one
        # .npy memmap per field on disk, and training reads them batch by batch
        out = self.tmp / "memmap"
        written = self.bc_data.load([self.out], self.context, self.mask, memmap=out)
        self.assertIsInstance(written.obs, np.memmap)
        self.assert_rows_equal(written, self.rows)
        del written
        again = self.bc_data.load_memmap(out)
        self.assertIsInstance(again.slots, np.memmap)
        self.assert_rows_equal(again, self.rows)
        part = again.take(np.array([3, 1]))
        self.assertTrue(np.array_equal(part.label_pairs, self.rows.label_pairs[[3, 1]]))
        del again, part
        with self.assertRaisesRegex(ValueError, "not empty"):
            self.bc_data.load([self.out], self.context, self.mask, memmap=out)
        (out / "rows.json").unlink()  # a directory a crash left half written
        with self.assertRaisesRegex(ValueError, "not a complete"):
            self.bc_data.load_memmap(out)

    def test_a_memmap_directory_inside_the_repository_is_refused(self):
        root = Path(__file__).resolve().parents[2]
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            self.bc_data.load([self.out], self.context, self.mask, memmap=root / "build" / "bc-rows")

    def test_the_players_split_holds_out_every_row_of_a_test_players_game(self):
        # the BC run of 2026-10-11 (owner via HS): held out by player for every source, so that a model of human play
        # is never validated on players it trained on; the default stays the sheet-pair split of the BC spec
        from duoforge_replay import dataset, split
        copy = self.with_manifest("players-split", lambda m: None)
        part = next(iter(dataset.parts(copy)))
        games = dataset.read_games(part)
        test_pair = next((a, a + 1) for a in range(1, 10 ** 6) if split.of_game((a, a + 1)) == "test")
        train_pair = next((a, a + 1) for a in range(1, 10 ** 6) if split.of_game((a, a + 1)) == "train")
        games["players"] = np.array([test_pair if g == 0 else train_pair for g in range(len(games["players"]))],
                                    dtype=np.uint64)
        dataset.write_npz(Path(part) / "games.npz", games)
        rows = self.bc_data.load([copy], self.context, self.mask, split="players")
        game = np.concatenate([s["game"] for s in dataset.read(copy)])
        self.assertTrue(np.array_equal(rows.val, game == 0))
        self.assertTrue(rows.val.any() and not rows.val.all())
        default = self.bc_data.load([copy], self.context, self.mask)  # unchanged: the sheet pair decides
        self.assertTrue(np.array_equal(default.val, self.rows.val))
        with self.assertRaisesRegex(ValueError, "split"):
            self.bc_data.load([self.out], self.context, self.mask, split="nonsense")

    def test_rows_folded_under_other_folds_are_refused(self):
        other = self.with_manifest("folds", lambda m: m.update(tracker_folds=lines.TRACKER_FOLDS ^ 1))
        with self.assertRaisesRegex(ValueError, "other folds"):
            self.bc_data.load([other], self.context, self.mask)

    def test_the_mask_takes_the_extension_features_the_tracker_folds(self):
        library = self.bc_data.library_mask(self.context)
        self.assertEqual(self.bc_data.bc_mask(self.context), library & lines.TRACKER_FOLDS)

    def test_a_new_manifest_without_its_source_is_refused(self):
        # a version 2 build always writes its source: one without it is no sheet dataset by default
        bare = self.with_manifest("bare", lambda m: m.pop("source"))
        with self.assertRaisesRegex(ValueError, "names no source"):
            self.bc_data.load([bare], self.context, self.mask)

    def test_dataset_of_another_library_is_refused(self):
        other = self.tmp / "other"
        shutil.copytree(self.out, other)
        marker = other / "replay-dataset.json"
        inputs = json.loads(marker.read_text(encoding="utf-8"))
        inputs["fingerprint"] = "00" * 32
        marker.write_text(json.dumps(inputs), encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            self.bc_data.load([other], self.context, self.mask)
        self.assertIn("00" * 32, str(caught.exception))
        self.assertIn(self.context.fingerprint().hex(), str(caught.exception))

    def test_team_table_order(self):
        from duoforge_learn import selfplay
        from duoforge_live import game
        self.assertEqual(game.TEAM_TABLE, [tuple(int(x) for x in row) for row in selfplay.TEAM_TABLE])
        self.assertEqual(game.TEAM_TABLE, list(itertools.permutations(range(6), 4)))
        self.assertEqual(self.rows.label_team.shape[1], 360)


class RegMBTest(unittest.TestCase):
    """Reg M-B as a second source (BC spec section 11)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_bc_mb_"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_build_two_prefixes(self):
        from duoforge_replay import build, dataset
        log = FIXTURE.read_text(encoding="utf-8")
        prior = self.tmp / "prior.json"
        prior.write_text(json.dumps({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]}),
                         encoding="utf-8")
        source = self.tmp / "both.jsonl"
        with open(source, "w", encoding="utf-8", newline=chr(10)) as f:
            for i, fmt in enumerate(("gen9championsvgc2026regmcbo3", "gen9championsvgc2026regmbbo3",
                                     "gen9championsvgc2026regmabo3")):
                f.write(json.dumps({"id": f"g{i}", "formatid": fmt, "log": log}) + chr(10))
        out = self.tmp / "both"
        c = build.build([source], prior, out, stats_factory=stats_factory, log=lambda _: None,
                        format_prefix=("gen9championsvgc2026regmc", "gen9championsvgc2026regmb"))
        self.assertEqual(c["games.processed"], 2)
        games = dataset.read_games(dataset.parts(out)[0])
        self.assertEqual(sorted(games["format_id"].tolist()),
                         ["gen9championsvgc2026regmbbo3", "gen9championsvgc2026regmcbo3"])
        marker = json.loads((out / dataset.MARKER).read_text(encoding="utf-8"))
        self.assertEqual(marker["filters"]["format_prefix"], ["gen9championsvgc2026regmc", "gen9championsvgc2026regmb"])
        again = build.build([source], prior, out, stats_factory=stats_factory, log=lambda _: None,
                            format_prefix=("gen9championsvgc2026regmc", "gen9championsvgc2026regmb"))
        self.assertEqual(again["parts.written"], 0)  # a resume with the same prefixes is the same dataset

    def test_format_weight(self):
        from duoforge_learn import bc_data
        out = build_fixture(self.tmp, copies=1, format_id="gen9championsvgc2026regmbbo3", name="mb")
        with duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as context:
            mask = bc_data.bc_mask(context)
            plain = bc_data.load([out], context, mask)
            half = bc_data.load([out], context, mask, format_weights={"gen9championsvgc2026regmb": 0.5})
        self.assertTrue(np.allclose(half.weight, plain.weight * 0.5))


if __name__ == "__main__":
    unittest.main()
