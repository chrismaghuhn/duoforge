"""duoforge.python.replay_teams: tools/reference/replay_teams.py, the private team corpus from the open sheets of the
replays (owner, 2026-10-11), in the random-team corpus format (#397) that duoforge.teams.load_corpus reads.

The sources are made-up JSON lines of the committed fixture log (python/tests/data/replay/c12_real_cb_4.log), written
to a temporary directory outside the repository. Needs the library (the POOL tables and the engine check).
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "reference"))
sys.dont_write_bytecode = True

import duoforge  # noqa: E402
from duoforge import _layout, teams  # noqa: E402

import replay_teams  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "data" / "replay" / "c12_real_cb_4.log"
FORMAT = "gen9championsvgc2026regmcbo3"


def with_sheet(log, side, change):
    """The log with side's packed sheet changed by change(list of packed sets)."""
    out = []
    for line in log.split("\n"):
        if line.startswith(f"|showteam|p{side + 1}|"):
            head, packed = "|".join(line.split("|", 3)[:3]), line.split("|", 3)[3]
            line = head + "|" + "]".join(change(packed.split("]")))
        out.append(line)
    return "\n".join(out)


def shuffled(sets):
    """The members in another order and each set's moves reversed: the same team (the canonical form sorts both)."""
    out = []
    for s in sets:
        f = s.split("|")
        f[4] = ",".join(reversed(f[4].split(",")))
        out.append("|".join(f))
    return list(reversed(out))


def unknown_item(sets):
    f = sets[0].split("|")
    f[2] = "NotAnItem"
    return ["|".join(f)] + sets[1:]


class ReplayTeamsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="duoforge_replay_teams_"))
        log = FIXTURE.read_text(encoding="utf-8")
        cls.prior = cls.tmp / "prior.json"
        cls.prior.write_text(json.dumps({"version": 1, "pastes": 0, "skipped": {}, "levels": [{}, {}, {}, {}]}),
                             encoding="utf-8")
        bo1 = "\n".join(line for line in log.split("\n") if not line.startswith("|showteam|"))
        games = [log, log, with_sheet(log, 0, shuffled), with_sheet(log, 1, unknown_item), bo1]
        cls.source = cls.tmp / "games.jsonl"
        with open(cls.source, "w", encoding="utf-8", newline="\n") as f:
            for i, text in enumerate(games):
                f.write(json.dumps({"id": f"{FORMAT}-{i}", "formatid": FORMAT, "log": text}) + "\n")
        cls.other = cls.tmp / "other.jsonl"  # another regulation: not in this corpus
        cls.other.write_text(json.dumps({"id": "x", "formatid": "gen9championsvgc2026regmbbo3", "log": log}) + "\n",
                             encoding="utf-8")
        cls.out = cls.tmp / "corpus"
        replay_teams.build([cls.source, cls.other], "gen9championsvgc2026regmc", cls.prior, cls.out, ps_dir=None)
        cls.manifest = json.loads((cls.out / "manifest.json").read_text(encoding="utf-8"))
        cls.index = json.loads((cls.out / "index.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_corpus_loads_through_the_training_loader(self):
        # teams.load_corpus (#397), as train reads a corpus: every team's hash, parse, ids and library check, and the
        # manifest's teams digest against the index
        ids = [t["id"] for t in self.index["teams"]]
        with duoforge.Context(data_kind=_layout.CONSTANTS["DUOFORGE_DATA_KIND_POOL"]) as ctx:
            pool, provenance = teams.load_corpus(ctx, str(self.out))
        self.assertEqual(pool.ids, tuple(ids))
        self.assertEqual((provenance["seed"], provenance["count"]), (None, len(ids)))
        self.assertTrue(all(t.startswith("RP_") and len(t) == 3 + 16 for t in ids))
        teams.check_disjoint(str(self.out))  # content-addressed ids: none twice

    def test_teams_are_counted_deduplicated_and_weighted_by_frequency(self):
        c = self.manifest["counts"]
        # five games of the format, four with two sheets: 8 sheets; the game of another regulation is not taken
        self.assertEqual((c["games"], c["games_without_sheets"], c["sheets"]), (5, 1, 8))
        # p1's sheet four times (three as is, once with members and moves in another order), p2's three times as is
        # and once with an unknown item: another team, which the engine check refuses
        self.assertEqual((c["distinct"], c["kept"], c["distinct_without_gender"], c["sheets_refused"]), (3, 2, 3, 0))
        self.assertEqual(sorted(self.manifest["frequency"].values()), [3, 4])
        self.assertEqual(sorted(self.manifest["frequency"]), sorted(t["id"] for t in self.index["teams"]))

    def test_a_refused_team_is_counted_with_its_reason_and_left_out(self):
        self.assertEqual(self.manifest["verdicts"], {"name": 1, "pool": 2})
        self.assertEqual(sum(self.manifest["reasons"].values()), 1)
        self.assertTrue(any("notanitem" in r.lower() for r in self.manifest["reasons"]), self.manifest["reasons"])

    def test_the_paste_is_a_function_of_the_canonical_form(self):
        # review of #408: two spellings of one team (an alias, another case) give one key, so they must give one paste
        # and one id whatever sheet comes first, or check_disjoint misses a team in two corpora
        from duoforge_live import data as live_data
        from duoforge_live import teams as live_teams
        from duoforge_replay.prior import Prior
        live, prior = live_data.load(kind="pool"), Prior.load(self.prior)
        log = FIXTURE.read_text(encoding="utf-8")
        plain = live_teams.unpack(replay_teams.sheets_of(log)[0])
        spelled = [dict(s, species=s["species"].lower(), item=s["item"].upper(), nature=s["nature"].lower(),
                        moves=[m.lower() for m in reversed(s["moves"])]) for s in reversed(plain)]
        key = replay_teams.canonical(plain, live)
        self.assertEqual(replay_teams.canonical(spelled, live), key)
        self.assertEqual(replay_teams.to_paste(replay_teams.canonical(spelled, live), live, prior)[0],
                         replay_teams.to_paste(key, live, prior)[0])

    def test_a_sheet_field_the_corpus_cannot_carry_is_refused(self):
        # review of #408: unpack drops IVs, shiny and the misc field (Tera, Hidden Power); such a sheet is refused
        log = FIXTURE.read_text(encoding="utf-8")

        def tera(sets):
            f = sets[0].split("|")
            f[11] = ",,,,,Fairy"
            return ["|".join(f)] + sets[1:]
        source = self.tmp / "tera.jsonl"
        source.write_text(json.dumps({"id": "t", "formatid": FORMAT, "log": with_sheet(log, 0, tera)}) + "\n",
                          encoding="utf-8")
        m = replay_teams.build([source], "gen9championsvgc2026regmc", self.prior, self.tmp / "tera", ps_dir=None)
        self.assertEqual((m["counts"]["sheets"], m["counts"]["sheets_refused"], m["counts"]["distinct"]), (2, 1, 1))
        self.assertTrue(any(r.startswith("sheet: ") for r in m["reasons"]), m["reasons"])

    def test_a_pending_team_counts_each_blocking_feature_once(self):
        from unittest import mock
        verdict = ("pending", ["set 2: move Infestation", "set 6: move Infestation", "set 6: ability Magma Armor"])
        with mock.patch("import_vgcpastes.engine_check", lambda ctx: lambda text: verdict):
            m = replay_teams.build([self.source], "gen9championsvgc2026regmc", self.prior, self.tmp / "pending",
                                   ps_dir=None)
        self.assertEqual(m["verdicts"], {"pending": 3})
        self.assertEqual(m["reasons"], {"pending: ability Magma Armor": 3, "pending: move Infestation": 3})

    def test_the_manifest_names_its_provenance_and_the_stat_point_source(self):
        m = self.manifest
        self.assertEqual(m["format_prefix"], "gen9championsvgc2026regmc")
        self.assertEqual([s["file"] for s in m["sources"]], ["games.jsonl", "other.jsonl"])
        self.assertTrue(all(len(s["sha256"]) == 64 for s in m["sources"]))
        self.assertEqual(m["stat_points"]["source"], "prior")
        self.assertEqual(len(m["stat_points"]["prior_sha256"]), 64)
        self.assertEqual(m["stat_points"]["members_without_prior"], 12)  # an empty prior knows no set
        self.assertIn("pin", m)
        self.assertIsNone(m["seed"])
        self.assertEqual(len(m["code"]["commit"]), 40)

    def test_ids_name_the_content_and_the_build_is_deterministic(self):
        again = self.tmp / "again"
        replay_teams.build([self.source, self.other], "gen9championsvgc2026regmc", self.prior, again, ps_dir=None)
        for name in ("index.json", "manifest.json"):
            self.assertEqual((self.out / name).read_bytes(), (again / name).read_bytes(), name)
        for t in self.index["teams"]:
            raw = (self.out / f"{t['id']}.txt").read_bytes()
            self.assertEqual(t["sha256"], teams.text_sha256(raw))
            self.assertEqual(t["id"], replay_teams.team_id(raw.decode("utf-8")))

    def test_the_output_is_refused_inside_the_repository_or_when_it_exists(self):
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            replay_teams.build([self.source], "gen9championsvgc2026regmc", self.prior, ROOT / "build" / "rp-corpus",
                               ps_dir=None)
        with self.assertRaisesRegex(ValueError, "exists"):
            replay_teams.build([self.source], "gen9championsvgc2026regmc", self.prior, self.out, ps_dir=None)

    def test_reg_ma_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Reg M-A"):
            replay_teams.build([self.source], "gen9championsvgc2026regma", self.prior, self.tmp / "ma", ps_dir=None)


if __name__ == "__main__":
    unittest.main()
