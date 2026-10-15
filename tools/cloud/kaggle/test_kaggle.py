#!/usr/bin/env python3
"""Offline tests of tools/cloud/kaggle, with a stub `kaggle` first on the PATH: nothing here reaches Kaggle (owner rule:
only the HauptSession starts anything there, with the owner). The stub logs every call and answers from STUB_*
variables. Fail closed, as the AWS tests: setUp checks that `kaggle` is the stub before anything runs; the environment
holds no KAGGLE_* variable of the caller (KAGGLE_API_TOKEN, KAGGLE_USERNAME, KAGGLE_KEY removed), its KAGGLE_CONFIG_DIR
is a directory that does not exist and HOME an empty one, so the owner's real token (~/.kaggle/access_token, in WSL
too) is out of reach (a test checks exactly that). A test that needs a token present gets a made-up one in a directory
of its own, which only the stub ever sees, and every output is searched for it."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kaggle_job  # noqa: E402
import kaggle_run  # noqa: E402

USER, TOKEN = "stubuser7", "KGAT_" + "9f" * 20  # made up here; searched for in every output
STUB = textwrap.dedent('''\
    import json, os, shutil, sys
    a = sys.argv[1:]
    with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps(a) + "\\n")
    def opt(k):
        return a[a.index(k) + 1] if k in a else None
    public = set(filter(None, os.environ.get("STUB_PUBLIC", "").split(",")))
    unknown = set(filter(None, os.environ.get("STUB_UNKNOWN", "").split(",")))
    appear = os.environ.get("STUB_APPEAR")  # a ref that appears, public, once something was created
    appeared = appear and os.path.exists(os.environ["STUB_LOG"] + ".appeared")
    if appeared:
        public.add(appear)
    token = os.path.join(os.environ.get("KAGGLE_CONFIG_DIR", "/nonexistent"), "access_token")
    if not os.path.isfile(token):  # as the real CLI: no token, no call
        print("You must authenticate before you can call the Kaggle API.", file=sys.stderr)
        sys.exit(1)
    if os.environ.get("STUB_LEAK") == "1":  # a CLI that echoes its token in an error
        print("error with token " + open(token, encoding="utf-8").read().strip(), file=sys.stderr)
        sys.exit(1)
    kind, op = a[0], a[1]
    if op == "list":
        refs = os.environ.get("STUB_" + kind.upper(), "").split(",") + ([appear] if appeared and kind == "datasets" else [])
        print("ref,title")
        for r in filter(None, refs):
            print(r + "," + r.split("/")[-1])
    elif kind == "datasets" and op == "metadata":
        ref = a[-1]
        meta = {"id": ref} if ref in unknown else {"id": ref, "isPrivate": ref not in public}
        json.dump(meta, open(os.path.join(opt("-p"), "dataset-metadata.json"), "w"))
    elif kind == "kernels" and op == "pull":
        ref = a[-1]
        meta = {"id": ref} if ref in unknown else {"id": ref, "is_private": ref not in public}
        json.dump(meta, open(os.path.join(opt("-p"), "kernel-metadata.json"), "w"))
    elif op == "create" or op == "push":
        d = opt("-p")
        if appear:
            open(os.environ["STUB_LOG"] + ".appeared", "w").close()
        keep = os.environ.get("STUB_KEEP")
        if keep:
            target = os.path.join(keep, str(len(os.listdir(keep))))
            shutil.copytree(d, target)
        print("Your private " + ("Dataset" if op == "create" else "Notebook") + " is being created")
    elif op == "status":
        print(a[2] + ' has status "' + os.environ.get("STUB_STATUS", "complete") + '"')
    elif op == "output":
        src = os.environ["STUB_OUTPUT"]
        shutil.copytree(src, opt("-p"), dirs_exist_ok=True)
    else:
        print("unexpected call", file=sys.stderr)
        sys.exit(9)
    ''')


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


class KaggleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kaggle_test_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        with open(os.path.join(self.bin, "kaggle_stub.py"), "w", encoding="utf-8") as f:
            f.write(STUB)
        if os.name == "nt":
            with open(os.path.join(self.bin, "kaggle.bat"), "w", encoding="utf-8") as f:
                f.write('@"%s" "%%~dp0kaggle_stub.py" %%*\n' % sys.executable)
        else:
            path = os.path.join(self.bin, "kaggle")
            with open(path, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\nexec %s \"$(dirname \"$0\")/kaggle_stub.py\" \"$@\"\n" % sys.executable)
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.log = os.path.join(self.tmp, "calls.log")
        open(self.log, "w").close()
        home = os.path.join(self.tmp, "home")
        os.mkdir(home)
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("KAGGLE")}
        env.update(PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_LOG=self.log, HOME=home, USERPROFILE=home,
                   KAGGLE_CONFIG_DIR=os.path.join(self.tmp, "no-such-kaggle-config"), STUB_DATASETS="", STUB_KERNELS="")
        self.env = env
        self.assert_kaggle_is_stub(env)
        # the made-up token of the tests that need one present: a directory of its own, seen by the stub only
        self.token_dir = os.path.join(self.tmp, "stub-kaggle-config")
        os.mkdir(self.token_dir)
        with open(os.path.join(self.token_dir, "access_token"), "w", encoding="utf-8") as f:
            f.write(TOKEN + "\n")
        self.data = os.path.join(self.tmp, "data", "sheet")
        os.makedirs(self.data)
        for i in range(3):
            with open(os.path.join(self.data, f"part-{i:05d}"), "wb") as f:
                f.write(bytes([i]) * (100 + i))
        self.plan = os.path.join(self.tmp, "plan.json")

    def assert_kaggle_is_stub(self, env):
        """`kaggle` under env must be the stub of this test, or a test would reach the real thing: checked first."""
        found = shutil.which("kaggle", path=env["PATH"])
        self.assertIsNotNone(found)
        self.assertTrue(os.path.dirname(os.path.abspath(found)).lower() == os.path.abspath(self.bin).lower(), found)

    def run_tool(self, *args, token=True, **extra):
        env = dict(self.env, **extra)
        if token:
            env["KAGGLE_CONFIG_DIR"] = self.token_dir
        r = subprocess.run([sys.executable, os.path.join(HERE, "kaggle_run.py"), *args], env=env, capture_output=True,
                           text=True, timeout=120)
        for text in (r.stdout, r.stderr):
            self.assertNotIn(TOKEN, text)  # the token never appears, whatever happens
        return r

    def calls(self):
        return [json.loads(l) for l in open(self.log, encoding="utf-8") if l.strip()]

    def make_plan(self):
        r = self.run_tool("plan", "--name", "bc-short-test", "--data", self.data, "--out", self.plan)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.load(open(self.plan, encoding="utf-8"))

    # ------------------------------------------------------------------ the protection
    def test_no_test_has_a_way_to_the_real_kaggle(self):
        # The environment every test runs the script in: no KAGGLE_* of the caller but a KAGGLE_CONFIG_DIR that does not
        # exist, an empty HOME (no ~/.kaggle), and `kaggle` is the stub (setUp checked it before this test began).
        self.assertEqual(sorted(k for k in self.env if k.upper().startswith("KAGGLE")), ["KAGGLE_CONFIG_DIR"])
        self.assertFalse(os.path.exists(self.env["KAGGLE_CONFIG_DIR"]))
        for var in ("KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY"):
            self.assertNotIn(var, self.env)
        self.assertFalse(os.path.exists(os.path.join(self.env["HOME"], ".kaggle")))
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(kaggle_run.token_status(), "token missing")  # the real token is out of reach
        with self.assertRaises(AssertionError):  # a stub that is not first on the PATH is caught before a run
            self.assert_kaggle_is_stub(dict(self.env, PATH=os.environ["PATH"]))

    def test_the_token_file_is_never_read_only_its_presence_is_told(self):
        real_open = open
        token = os.path.join(self.token_dir, "access_token")

        def guarded(path, *a, **k):
            if os.path.abspath(str(path)) == os.path.abspath(token):
                raise AssertionError("the script opened the token file")
            return real_open(path, *a, **k)
        with mock.patch.dict(os.environ, dict(self.env, KAGGLE_CONFIG_DIR=self.token_dir), clear=True), \
                mock.patch("builtins.open", guarded):
            self.assertEqual(kaggle_run.token_status(), "token present")
        self.make_plan()
        r = self.run_tool("privacy", "--owner", USER, "--i-have-owner-approval", token=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("token missing", r.stdout)
        self.assertEqual(self.calls(), [])  # without a token nothing is called
        r = self.run_tool("privacy", "--owner", USER, "--i-have-owner-approval")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("token present (the token file is never read)", r.stdout)

    def test_without_the_approval_flag_nothing_reaches_kaggle(self):
        self.make_plan()
        for cmd in (("privacy",), ("upload", "--plan", self.plan), ("start", "--plan", self.plan, "--commit", "a" * 40,
                                                                    "--job", "bc-short"),
                    ("fetch", "--plan", self.plan, "--job", "bc-short", "--out", os.path.join(self.tmp, "o"))):
            with self.subTest(cmd=cmd[0]):
                r = self.run_tool(*cmd, "--owner", USER)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("nothing reaches Kaggle without --i-have-owner-approval", r.stdout)
        self.assertEqual(self.calls(), [])

    def test_the_token_never_appears_even_when_the_cli_echoes_it(self):
        self.make_plan()
        r = self.run_tool("privacy", "--owner", USER, "--i-have-owner-approval", STUB_LEAK="1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("<redacted>", r.stderr)

    def test_entries_of_another_account_are_refused(self):
        r = self.run_tool("privacy", "--owner", USER, "--i-have-owner-approval", STUB_DATASETS="someoneelse/duoforge-aaa")
        self.assertEqual(r.returncode, 3)
        self.assertIn("another account than --owner", r.stderr)
        r = self.run_tool("privacy", "--owner", "not a name", "--i-have-owner-approval")
        self.assertEqual(r.returncode, 2)

    # ------------------------------------------------------------------ the plan
    def test_the_plan_lists_every_file_and_names_the_dataset_by_sha256(self):
        p = self.make_plan()
        self.assertEqual([f["path"] for f in p["files"]], ["sheet/part-00000", "sheet/part-00001", "sheet/part-00002"])
        self.assertEqual([f["size"] for f in p["files"]], [100, 101, 102])
        self.assertEqual(p["files"][0]["sha256"], sha(os.path.join(self.data, "part-00000")))
        self.assertEqual({f["origin"] for f in p["files"]}, {"data"})
        self.assertEqual(p["dataset"], "duoforge-" + p["sha256"][:12])
        self.assertEqual(self.calls(), [])

    def test_the_tournament_sun_team_and_repository_files_are_refused(self):
        team = os.path.join(self.tmp, "team.txt")
        with open(team, "w", encoding="utf-8") as f:
            f.write("a team sheet\n")
        with mock.patch.dict(kaggle_run.REFUSED, {sha(team): "the tournament sun team"}):
            with self.assertRaises(SystemExit), mock.patch("sys.stderr") as err:
                kaggle_run.plan("x", [("data", [self.data]), ("config", [team])])
            self.assertIn("the tournament sun team is in the upload list", "".join(c.args[0] for c in err.write.call_args_list))
        self.assertIn("e1060cf46a8f30bc3e56ad6fb1e038a9ed3dafd47a9ec9913b8399542320c281", kaggle_run.REFUSED)
        self.assertEqual(kaggle_run.REFUSED, kaggle_job.REFUSED)
        r = self.run_tool("plan", "--name", "x", "--data", os.path.join(kaggle_run.REPO, "data", "teams"), "--out",
                          self.plan)
        self.assertEqual(r.returncode, 2)
        self.assertIn("inside the repository", r.stderr)

    def test_a_file_changed_after_the_plan_is_refused(self):
        self.make_plan()
        with open(os.path.join(self.data, "part-00001"), "ab") as f:
            f.write(b"x")
        r = self.run_tool("upload", "--plan", self.plan, "--owner", USER, "--i-have-owner-approval")
        self.assertEqual(r.returncode, 2)
        self.assertIn("has another sha256 now", r.stderr)
        self.assertEqual(self.calls(), [])

    # ------------------------------------------------------------------ privacy before and after
    def test_a_public_or_unknown_dataset_or_notebook_stops_before_anything_is_done(self):
        self.make_plan()
        mine = {"STUB_DATASETS": f"{USER}/duoforge-aaa,{USER}/other", "STUB_KERNELS": f"{USER}/duoforge-aaa-bc"}
        for extra, needle in (({"STUB_PUBLIC": f"{USER}/duoforge-aaa"}, f"not private: dataset {USER}/duoforge-aaa"),
                              ({"STUB_PUBLIC": f"{USER}/duoforge-aaa-bc"}, f"not private: notebook {USER}/duoforge-aaa-bc"),
                              ({"STUB_UNKNOWN": f"{USER}/duoforge-aaa"}, "privacy unknown")):
            with self.subTest(needle=needle):
                open(self.log, "w").close()
                r = self.run_tool("upload", "--plan", self.plan, "--owner", USER, "--i-have-owner-approval",
                                  **mine, **extra)
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertIn(needle, r.stderr)
                self.assertFalse([c for c in self.calls() if c[1] in ("create", "push")])  # nothing was created
        # only the PREFIX entries are checked: another dataset of the account is not looked at
        r = self.run_tool("privacy", "--owner", USER, "--i-have-owner-approval", **mine)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse([c for c in self.calls() if c[-1] == f"{USER}/other" and c[1] == "metadata"])

    def test_privacy_is_checked_again_after_each_step(self):
        p = self.make_plan()
        keep = os.path.join(self.tmp, "kept")
        os.mkdir(keep)
        # the upload makes the new dataset appear public: the check after it refuses, by name
        r = self.run_tool("upload", "--plan", self.plan, "--owner", USER, "--i-have-owner-approval",
                          STUB_KEEP=keep, STUB_APPEAR=f"{USER}/{p['dataset']}")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("after upload: not private: dataset %s/%s" % (USER, p["dataset"]), r.stderr)
        ops = [c[:2] for c in self.calls()]
        self.assertEqual(ops[:3], [["datasets", "list"], ["kernels", "list"], ["datasets", "create"]])
        os.remove(self.log + ".appeared")
        open(self.log, "w").close()
        r = self.run_tool("upload", "--plan", self.plan, "--owner", USER, "--i-have-owner-approval",
                          STUB_KEEP=keep)
        self.assertEqual(r.returncode, 0, r.stderr)
        ops = [c[:2] for c in self.calls()]
        self.assertEqual(ops, [["datasets", "list"], ["kernels", "list"], ["datasets", "create"], ["datasets", "list"],
                               ["kernels", "list"]])  # privacy, upload, privacy

    # ------------------------------------------------------------------ upload, start, resume, fetch
    def test_the_upload_is_one_private_dataset_of_the_plans_files(self):
        p = self.make_plan()
        keep = os.path.join(self.tmp, "kept")
        os.mkdir(keep)
        r = self.run_tool("upload", "--plan", self.plan, "--owner", USER, "--i-have-owner-approval", STUB_KEEP=keep)
        self.assertEqual(r.returncode, 0, r.stderr)
        (create,) = [c for c in self.calls() if c[1] == "create"]
        self.assertNotIn("--public", create)
        (made,) = os.listdir(keep)
        meta = json.load(open(os.path.join(keep, made, "dataset-metadata.json"), encoding="utf-8"))
        self.assertEqual(meta["id"], f"{USER}/{p['dataset']}")
        self.assertIs(meta["isPrivate"], True)
        for f in p["files"]:
            self.assertEqual(sha(os.path.join(keep, made, *f["path"].split("/"))), f["sha256"])

    def test_start_pushes_a_private_gpu_notebook_at_the_commit(self):
        p = self.make_plan()
        keep = os.path.join(self.tmp, "kept")
        os.mkdir(keep)
        r = self.run_tool("start", "--plan", self.plan, "--commit", "a" * 40, "--job", "bc-short", "--owner", USER,
                          "--i-have-owner-approval", STUB_KEEP=keep)
        self.assertEqual(r.returncode, 0, r.stderr)
        (made,) = os.listdir(keep)
        meta = json.load(open(os.path.join(keep, made, "kernel-metadata.json"), encoding="utf-8"))
        self.assertIs(meta["is_private"], True)
        self.assertIs(meta["enable_gpu"], True)
        self.assertEqual(meta["dataset_sources"], [f"{USER}/{p['dataset']}"])
        code = open(os.path.join(keep, made, "kaggle_job.py"), encoding="utf-8").read()
        job = json.loads(code.split("\nJOB = ", 1)[1].split("\n", 1)[0])
        self.assertEqual((job["commit"], job["job"], job["plan"]["sha256"], job["state_dataset"]),
                         ("a" * 40, "bc-short", p["sha256"], None))
        self.assertNotIn(TOKEN, code)
        self.assertNotIn(USER, json.dumps(job))
        r = self.run_tool("start", "--plan", self.plan, "--commit", "main", "--job", "bc-short", "--owner", USER,
                          "--i-have-owner-approval")
        self.assertEqual(r.returncode, 2)

    def fetched(self, status, weights=True):
        out = os.path.join(self.tmp, "output")
        os.makedirs(os.path.join(out, "run"), exist_ok=True)
        with open(os.path.join(out, "status.json"), "w", encoding="utf-8") as f:
            json.dump(status, f)
        with open(os.path.join(out, "env.json"), "w", encoding="utf-8") as f:
            json.dump({"jax": "0.4.38", "jaxlib": "0.4.38", "cuda": "12.4", "gpu": "Tesla P100", "python": "3.11"}, f)
        for name in ("bc-state.npz", "bc-log.jsonl") + (("bc.npz",) if weights else ()):
            with open(os.path.join(out, "run", name), "wb") as f:
                f.write(name.encode())
        return out

    def test_a_run_stopped_at_its_deadline_resumes_from_its_state_as_a_dataset_of_its_own(self):
        p = self.make_plan()
        partial = self.fetched({"status": "partial", "plan_sha256": p["sha256"], "commit": "a" * 40,
                                "launches": [{"seconds": 39600.0}]}, weights=False)
        keep = os.path.join(self.tmp, "kept")
        os.mkdir(keep)
        r = self.run_tool("start", "--plan", self.plan, "--commit", "a" * 40, "--job", "bc", "--resume-from", partial,
                          "--owner", USER, "--i-have-owner-approval", STUB_KEEP=keep)
        self.assertEqual(r.returncode, 0, r.stderr)
        state_dir, kernel = sorted(os.listdir(keep))
        state = json.load(open(os.path.join(keep, state_dir, "dataset-metadata.json"), encoding="utf-8"))
        self.assertIs(state["isPrivate"], True)
        self.assertEqual(sorted(os.listdir(os.path.join(keep, state_dir))),
                         ["bc-log.jsonl", "bc-state.npz", "dataset-metadata.json", "status.json"])
        meta = json.load(open(os.path.join(keep, kernel, "kernel-metadata.json"), encoding="utf-8"))
        self.assertEqual(meta["dataset_sources"], [f"{USER}/{p['dataset']}", state["id"]])
        code = open(os.path.join(keep, kernel, "kaggle_job.py"), encoding="utf-8").read()
        job = json.loads(code.split("\nJOB = ", 1)[1].split("\n", 1)[0])
        self.assertEqual(job["state_dataset"], state["id"].split("/")[1])
        r = self.run_tool("start", "--plan", self.plan, "--commit", "b" * 40, "--job", "bc", "--resume-from", partial,
                          "--owner", USER, "--i-have-owner-approval")
        self.assertEqual(r.returncode, 2)
        self.assertIn("ran at another commit", r.stderr)
        done = self.fetched({"status": "done", "plan_sha256": p["sha256"], "commit": "a" * 40})
        r = self.run_tool("start", "--plan", self.plan, "--commit", "a" * 40, "--job", "bc", "--resume-from", done,
                          "--owner", USER, "--i-have-owner-approval")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a partial run of this plan", r.stderr)

    def test_fetch_writes_the_manifest(self):
        p = self.make_plan()
        out = self.fetched({"status": "done", "reason": "none", "commit": "a" * 40, "seed": 1, "seconds": 300.0,
                            "plan_sha256": p["sha256"], "launches": [{"seconds": 300.0, "status": "done"}]})
        dest = os.path.join(self.tmp, "fetched")
        r = self.run_tool("fetch", "--plan", self.plan, "--job", "bc-short", "--out", dest, "--owner", USER,
                          "--i-have-owner-approval", STUB_OUTPUT=out)
        self.assertEqual(r.returncode, 0, r.stderr)
        m = json.load(open(os.path.join(dest, "manifest.json"), encoding="utf-8"))
        self.assertEqual((m["commit"], m["data_sha256"], m["seed"], m["seconds"], m["gpu"], m["jax"], m["cuda"]),
                         ("a" * 40, p["sha256"], 1, 300.0, "Tesla P100", "0.4.38", "12.4"))
        self.assertEqual(m["weights_sha256"], sha(os.path.join(dest, "run", "bc.npz")))
        r = self.run_tool("fetch", "--plan", self.plan, "--job", "bc-short", "--out", dest, "--owner", USER,
                          "--i-have-owner-approval", STUB_OUTPUT=out, STUB_STATUS="running")
        self.assertEqual(r.returncode, 2)
        self.assertIn("still running", r.stderr)


class PseudonymizeTest(unittest.TestCase):
    """pseudonymize.py: the copy for Kaggle without replay ids and player hashes; the maps and the seed apart, local."""

    T0, T, R = 400 * 123456789, 400 * 98765432 + 60, 123456789012347  # one hash of each class (h % 400 = 0, 60, 347)

    def make(self, root, leak=False):
        import numpy as np
        sys.path.insert(0, os.path.join(kaggle_run.REPO, "python"))
        from duoforge_replay.dataset import write_npz
        src = os.path.join(root, "ds")
        os.makedirs(src)
        with open(os.path.join(src, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"parts": [{"part": "part-x-00000"}, {"part": "part-x-00001"}]}, f)
        games = ((["gen9championsvgc2026regmc-1111111111", "gen9championsvgc2026regmc-2222222222"],
                  [[self.T0, self.T], [self.T, self.R]]), ([], np.zeros((0, 2))))
        for k, (ids, players) in enumerate(games):
            part = os.path.join(src, f"part-x-{k:05d}")
            os.makedirs(part)
            write_npz(os.path.join(part, "games.npz"), {"replay_id": np.array(ids, dtype="<U36"),
                                                       "players": np.array(players, np.uint64).reshape(-1, 2)})
            m = {"games_sha256": sha(os.path.join(part, "games.npz")), "unit": f"x-{k:05d}"}
            if leak and k == 0:
                m["note"] = f"player {self.R}"
            with open(os.path.join(part, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(m, f)
        return src

    def run_it(self, tmp, src, name, seed="seed"):
        import pseudonymize
        out = os.path.join(tmp, name)
        maps = os.path.join(tmp, f"{name}-replay-ids.json"), os.path.join(tmp, f"{name}-player-ids.json")
        pseudonymize.pseudonymize(src, out, maps[0], maps[1], os.path.join(tmp, seed))
        return out, maps

    def players(self, out):
        import numpy as np
        with np.load(os.path.join(out, "part-x-00000", "games.npz")) as z:
            return [[int(x) for x in row] for row in z["players"]], list(z["replay_id"])

    def test_the_copy_has_labels_and_class_keeping_ids_and_the_maps_and_seed_stay_apart(self):
        import pseudonymize
        with tempfile.TemporaryDirectory() as tmp:
            src = self.make(tmp)
            out, (rmap, pmap) = self.run_it(tmp, src, "copy")
            players, labels = self.players(out)
            self.assertEqual(labels, ["game-00000-000000", "game-00000-000001"])
            originals = {self.T0, self.T, self.R}
            self.assertFalse({h for row in players for h in row} & originals)  # no player hash is left
            self.assertEqual([[pseudonymize.player_class(h) for h in row] for row in players],
                             [["T0", "T"], ["T", "R"]])  # every row keeps its classes, so its split and sub-bucket
            self.assertEqual(players[0][1], players[1][0])  # one player, one id
            self.assertEqual(json.load(open(rmap, encoding="utf-8"))["replay_ids"]["game-00000-000001"],
                             "gen9championsvgc2026regmc-2222222222")
            self.assertEqual(json.load(open(pmap, encoding="utf-8"))["players"][str(self.R)], str(players[1][1]))
            self.assertRegex(open(os.path.join(tmp, "seed"), encoding="utf-8").read().strip(), r"^[0-9a-f]{64}$")
            m = json.load(open(os.path.join(out, "part-x-00000", "manifest.json"), encoding="utf-8"))
            self.assertEqual(m["games_sha256"], sha(os.path.join(out, "part-x-00000", "games.npz")))
            for d, _, names in os.walk(out):
                for n in names:
                    with open(os.path.join(d, n), "rb") as f:
                        data = f.read()
                    self.assertNotIn(b"2222222222", data)
                    self.assertNotIn(str(self.R).encode(), data)
            self.assertEqual(sorted(os.listdir(out)), ["manifest.json", "part-x-00000", "part-x-00001"])

    def test_the_same_seed_gives_the_same_ids_another_seed_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self.make(tmp)
            a, _ = self.run_it(tmp, src, "a")
            b, _ = self.run_it(tmp, src, "b")  # the seed file of the first run, again
            c, _ = self.run_it(tmp, src, "c", seed="other-seed")
            self.assertEqual(self.players(a), self.players(b))
            self.assertNotEqual(self.players(a)[0], self.players(c)[0])
            with open(os.path.join(a, "part-x-00000", "games.npz"), "rb") as x, \
                    open(os.path.join(b, "part-x-00000", "games.npz"), "rb") as y:
                self.assertEqual(x.read(), y.read())  # byte-identical: a rebuild gives the same copy

    def test_a_hash_left_in_a_file_and_bad_paths_are_refused(self):
        import pseudonymize
        with tempfile.TemporaryDirectory() as tmp:
            src = self.make(tmp, leak=True)
            with self.assertRaisesRegex(SystemExit, "an id of the source is left"):
                self.run_it(tmp, src, "leaky")
            self.assertFalse(os.path.exists(os.path.join(tmp, "leaky")))  # the copy was removed
        with tempfile.TemporaryDirectory() as tmp:
            src = self.make(tmp)
            out, _ = self.run_it(tmp, src, "copy")
            j = lambda *a: os.path.join(tmp, *a)  # noqa: E731
            cases = ((out, j("m1"), j("p1"), j("s1"), "--out exists"),
                     (j("c2"), j("c2", "m"), j("p2"), j("s2"), "--map lies inside --out"),
                     (j("c3"), j("m3"), j("c3", "p"), j("s3"), "--player-map lies inside --out"),
                     (j("c4"), j("m4"), j("p4"), j("c4", "s"), "--seed-file lies inside --out"),
                     (os.path.join(kaggle_run.REPO, "copy-test"), j("m5"), j("p5"), j("s5"), "inside the repository"),
                     (j("c6"), j("m6"), j("p6"), os.path.join(kaggle_run.REPO, "seed-test"), "inside the repository"))
            for dst, rm, pm, seed, message in cases:
                with self.subTest(message=message), self.assertRaisesRegex(SystemExit, message):
                    pseudonymize.pseudonymize(src, dst, rm, pm, seed)
            self.assertFalse(os.path.exists(os.path.join(kaggle_run.REPO, "copy-test")))
            self.assertFalse(os.path.exists(os.path.join(kaggle_run.REPO, "seed-test")))
            with open(j("bad-seed"), "w", encoding="utf-8") as f:
                f.write("not hex\n")
            with self.assertRaisesRegex(SystemExit, "64 hex digits"):
                pseudonymize.pseudonymize(src, j("c7"), j("m7"), j("p7"), j("bad-seed"))


class JobTest(unittest.TestCase):
    """kaggle_job.py's pieces that run without Kaggle: the data check, the job's arguments, the deadline."""

    def test_the_data_check_refuses_a_changed_file_and_the_sun_team(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "sheet"))
            path = os.path.join(tmp, "sheet", "p0")
            with open(path, "wb") as f:
                f.write(b"rows")
            plan = {"files": [{"path": "sheet/p0", "sha256": sha(path), "origin": "data"}]}
            self.assertEqual(kaggle_job.check_data(plan, tmp), [os.path.join(tmp, "sheet")])
            with self.assertRaisesRegex(kaggle_job.JobError, "another sha256"):
                kaggle_job.check_data({"files": [dict(plan["files"][0], sha256="0" * 64)]}, tmp)
            with mock.patch.dict(kaggle_job.REFUSED, {sha(path): "the tournament sun team"}), \
                    self.assertRaisesRegex(kaggle_job.JobError, "the tournament sun team"):
                kaggle_job.check_data(plan, tmp)

    def test_the_full_jobs_arguments_take_no_path_and_no_other_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "cfg"))
            path = os.path.join(tmp, "cfg", "bc-args.json")
            plan = {"files": [{"path": "cfg/bc-args.json", "origin": "config"}]}
            for args, ok in ((["--preset", "M", "--epochs", "20"], True), (["--out", "x"], False),
                             (["--cache", "/tmp/c"], False), (["--format-weight", "a/b=1"], False)):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(args, f)
                with self.subTest(args=args):
                    if ok:
                        self.assertEqual(kaggle_job.bc_args("bc", plan, tmp), args)
                    else:
                        with self.assertRaises(kaggle_job.JobError):
                            kaggle_job.bc_args("bc", plan, tmp)
            self.assertEqual(kaggle_job.bc_args("bc-short", plan, tmp)[:2], ["--preset", "S"])

    def test_the_deadline_stops_the_trainer_and_keeps_its_state(self):
        class Proc:
            def __init__(self, ends):
                self.ends, self.waits, self.stopped = ends, 0, None

            def wait(self, timeout=None):
                self.waits += 1
                if self.stopped or (self.ends is not None and self.waits >= self.ends):
                    return 0 if self.stopped is None else -15
                raise subprocess.TimeoutExpired("bc", timeout)

            def terminate(self):
                self.stopped = "term"

            def kill(self):
                self.stopped = "kill"
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "log")
            clock = iter([0.0, 10.0, 99.0, 101.0, 200.0]).__next__
            proc = Proc(ends=None)
            self.assertEqual(kaggle_job.run_bc(["bc"], {}, log, 100.0, clock=clock, popen=lambda *a, **k: proc, poll=0),
                             "partial")
            self.assertEqual(proc.stopped, "term")
            self.assertEqual(kaggle_job.run_bc(["bc"], {}, log, 100.0, clock=lambda: 0.0,
                                               popen=lambda *a, **k: Proc(ends=2), poll=0), "done")


if __name__ == "__main__":
    unittest.main()
