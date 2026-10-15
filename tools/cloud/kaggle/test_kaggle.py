#!/usr/bin/env python3
"""Offline tests of tools/cloud/kaggle, with a stub `kaggle` first on the PATH: nothing here reaches Kaggle (owner rule:
only the HauptSession starts anything there, with the owner). The stub logs every call and answers from STUB_*
variables. Fail closed: setUp checks that `kaggle` is the stub before anything runs, the environment holds no
credential of the caller and no Kaggle configuration (a test checks exactly that), and the key of the tests is a made-up
one that a test searches for in every output."""
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

USER, KEY = "stubuser7", "k3y-" + "9f" * 14  # made up here; searched for in every output
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
    user = os.environ.get("KAGGLE_USERNAME", "")
    if os.environ.get("STUB_LEAK") == "1":  # a CLI that echoes its credentials in an error
        print("error for " + user + " with key " + os.environ.get("KAGGLE_KEY", ""), file=sys.stderr)
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
                   STUB_DATASETS="", STUB_KERNELS="")
        self.env = env
        self.assert_kaggle_is_stub(env)
        self.envfile = os.path.join(self.tmp, "kaggle.env")
        with open(self.envfile, "w", encoding="utf-8") as f:
            f.write(f"# test credentials, made up\nKAGGLE_USERNAME={USER}\nKAGGLE_KEY={KEY}\n")
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

    def run_tool(self, *args, **extra):
        env = dict(self.env, **extra)
        r = subprocess.run([sys.executable, os.path.join(HERE, "kaggle_run.py"), *args], env=env, capture_output=True,
                           text=True, timeout=120)
        for text in (r.stdout, r.stderr):
            self.assertNotIn(KEY, text)  # the key never appears, whatever happens
        return r

    def calls(self):
        return [json.loads(l) for l in open(self.log, encoding="utf-8") if l.strip()]

    def make_plan(self):
        r = self.run_tool("plan", "--name", "bc-short-test", "--data", self.data, "--out", self.plan)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.load(open(self.plan, encoding="utf-8"))

    # ------------------------------------------------------------------ the protection
    def test_no_test_has_a_way_to_the_real_kaggle(self):
        self.assertFalse([k for k in self.env if k.upper().startswith("KAGGLE")])
        self.assertFalse(os.path.exists(os.path.join(self.env["HOME"], ".kaggle")))
        polluted = dict(os.environ, KAGGLE_USERNAME="owner", KAGGLE_KEY="x", KAGGLE_CONFIG_DIR="/real")
        with mock.patch.dict(os.environ, polluted, clear=True), mock.patch("shutil.which", return_value=self.bin + "/kaggle"):
            k = kaggle_run.Kaggle(USER, KEY)
            with mock.patch("subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, "ok", "")
                k.run("datasets", "list")
            env = run.call_args.kwargs["env"]
            self.assertEqual((env["KAGGLE_USERNAME"], env["KAGGLE_KEY"]), (USER, KEY))  # only the env file's
            self.assertNotEqual(env["KAGGLE_CONFIG_DIR"], "/real")
            self.assertEqual(os.listdir(env["KAGGLE_CONFIG_DIR"]), [])  # an empty configuration of its own
            self.assertNotIn(KEY, " ".join(run.call_args.args[0]))  # never on the command line
        with self.assertRaises(AssertionError):  # a stub that is not first on the PATH is caught before a run
            self.assert_kaggle_is_stub(dict(self.env, PATH=os.environ["PATH"]))

    def test_without_the_approval_flag_nothing_reaches_kaggle(self):
        self.make_plan()
        for cmd in (("privacy",), ("upload", "--plan", self.plan), ("start", "--plan", self.plan, "--commit", "a" * 40,
                                                                    "--job", "bc-short"),
                    ("fetch", "--plan", self.plan, "--job", "bc-short", "--out", os.path.join(self.tmp, "o"))):
            with self.subTest(cmd=cmd[0]):
                r = self.run_tool(*cmd, "--env", self.envfile)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("nothing reaches Kaggle without --i-have-owner-approval", r.stdout)
        self.assertEqual(self.calls(), [])

    def test_the_key_never_appears_even_when_the_cli_echoes_it(self):
        self.make_plan()
        r = self.run_tool("privacy", "--env", self.envfile, "--i-have-owner-approval", STUB_LEAK="1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("<key>", r.stderr)
        self.assertNotIn(USER, r.stderr + r.stdout)

    def test_the_env_file_is_read_only_from_outside_the_repository(self):
        bad = os.path.join(self.tmp, "bad.env")
        with open(bad, "w", encoding="utf-8") as f:
            f.write(f"KAGGLE_USERNAME={USER}\n")
        cases = ((os.path.join(self.tmp, "missing.env"), "does not exist"), (bad, "lacks KAGGLE_USERNAME or KAGGLE_KEY"),
                 (os.path.join(kaggle_run.REPO, "kaggle.env"), "inside the repository"))
        for path, message in cases:
            with self.subTest(message=message):
                r = self.run_tool("privacy", "--env", path, "--i-have-owner-approval")
                self.assertEqual(r.returncode, 2)
                self.assertIn(message, r.stderr)
        self.assertEqual(self.calls(), [])

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
        r = self.run_tool("upload", "--plan", self.plan, "--env", self.envfile, "--i-have-owner-approval")
        self.assertEqual(r.returncode, 2)
        self.assertIn("has another sha256 now", r.stderr)
        self.assertEqual(self.calls(), [])

    # ------------------------------------------------------------------ privacy before and after
    def test_a_public_or_unknown_dataset_or_notebook_stops_before_anything_is_done(self):
        self.make_plan()
        mine = {"STUB_DATASETS": f"{USER}/duoforge-aaa,{USER}/other", "STUB_KERNELS": f"{USER}/duoforge-aaa-bc"}
        for extra, needle in (({"STUB_PUBLIC": f"{USER}/duoforge-aaa"}, "not private: dataset <user>/duoforge-aaa"),
                              ({"STUB_PUBLIC": f"{USER}/duoforge-aaa-bc"}, "not private: notebook <user>/duoforge-aaa-bc"),
                              ({"STUB_UNKNOWN": f"{USER}/duoforge-aaa"}, "privacy unknown")):
            with self.subTest(needle=needle):
                open(self.log, "w").close()
                r = self.run_tool("upload", "--plan", self.plan, "--env", self.envfile, "--i-have-owner-approval",
                                  **mine, **extra)
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertIn(needle, r.stderr)
                self.assertFalse([c for c in self.calls() if c[1] in ("create", "push")])  # nothing was created
        # only the PREFIX entries are checked: another dataset of the account is not looked at
        r = self.run_tool("privacy", "--env", self.envfile, "--i-have-owner-approval", **mine)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse([c for c in self.calls() if c[-1] == f"{USER}/other" and c[1] == "metadata"])

    def test_privacy_is_checked_again_after_each_step(self):
        p = self.make_plan()
        keep = os.path.join(self.tmp, "kept")
        os.mkdir(keep)
        # the upload makes the new dataset appear public: the check after it refuses, by name
        r = self.run_tool("upload", "--plan", self.plan, "--env", self.envfile, "--i-have-owner-approval",
                          STUB_KEEP=keep, STUB_APPEAR=f"{USER}/{p['dataset']}")
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("after upload: not private: dataset <user>/%s" % p["dataset"], r.stderr)
        ops = [c[:2] for c in self.calls()]
        self.assertEqual(ops[:3], [["datasets", "list"], ["kernels", "list"], ["datasets", "create"]])
        os.remove(self.log + ".appeared")
        open(self.log, "w").close()
        r = self.run_tool("upload", "--plan", self.plan, "--env", self.envfile, "--i-have-owner-approval",
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
        r = self.run_tool("upload", "--plan", self.plan, "--env", self.envfile, "--i-have-owner-approval", STUB_KEEP=keep)
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
        r = self.run_tool("start", "--plan", self.plan, "--commit", "a" * 40, "--job", "bc-short", "--env", self.envfile,
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
        self.assertNotIn(KEY, code)
        self.assertNotIn(USER, json.dumps(job))
        r = self.run_tool("start", "--plan", self.plan, "--commit", "main", "--job", "bc-short", "--env", self.envfile,
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
                          "--env", self.envfile, "--i-have-owner-approval", STUB_KEEP=keep)
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
                          "--env", self.envfile, "--i-have-owner-approval")
        self.assertEqual(r.returncode, 2)
        self.assertIn("ran at another commit", r.stderr)
        done = self.fetched({"status": "done", "plan_sha256": p["sha256"], "commit": "a" * 40})
        r = self.run_tool("start", "--plan", self.plan, "--commit", "a" * 40, "--job", "bc", "--resume-from", done,
                          "--env", self.envfile, "--i-have-owner-approval")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a partial run of this plan", r.stderr)

    def test_fetch_writes_the_manifest(self):
        p = self.make_plan()
        out = self.fetched({"status": "done", "reason": "none", "commit": "a" * 40, "seed": 1, "seconds": 300.0,
                            "plan_sha256": p["sha256"], "launches": [{"seconds": 300.0, "status": "done"}]})
        dest = os.path.join(self.tmp, "fetched")
        r = self.run_tool("fetch", "--plan", self.plan, "--job", "bc-short", "--out", dest, "--env", self.envfile,
                          "--i-have-owner-approval", STUB_OUTPUT=out)
        self.assertEqual(r.returncode, 0, r.stderr)
        m = json.load(open(os.path.join(dest, "manifest.json"), encoding="utf-8"))
        self.assertEqual((m["commit"], m["data_sha256"], m["seed"], m["seconds"], m["gpu"], m["jax"], m["cuda"]),
                         ("a" * 40, p["sha256"], 1, 300.0, "Tesla P100", "0.4.38", "12.4"))
        self.assertEqual(m["weights_sha256"], sha(os.path.join(dest, "run", "bc.npz")))
        r = self.run_tool("fetch", "--plan", self.plan, "--job", "bc-short", "--out", dest, "--env", self.envfile,
                          "--i-have-owner-approval", STUB_OUTPUT=out, STUB_STATUS="running")
        self.assertEqual(r.returncode, 2)
        self.assertIn("still running", r.stderr)


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
