"""Restructure step 8 (fuzz): a dry run of tools/cloud/aws_fuzz/launch.sh against the stub aws, nothing reaches AWS.

    python3 tools/restructure/fuzz_dryrun.py --tools SHA --commit SHA [--campaign weather-sand-snow]

A clone of this repository in a temporary directory is checked out at --tools (the launch scripts that run) and its
origin/main is set to the newer of --tools and --commit, so the real git checks of launch.sh run (commit on main,
the campaign's campaign.conf at --commit). `aws` is the stub of tools/cloud/aws_fuzz/test_guards.py (it logs the
calls and answers from fixed values), the AWS environment is emptied (aws_safe_env) and no launch flag is given, so
launch.sh stops after its checks with "nothing was launched". Prints the exit status, the output (temporary paths
shortened) and the stub's calls. Used to show the move of campaigns/ to runs/fuzz/ before and after, and the old
path read for a commit from before the move.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def stub_text(tools_dir):
    """The STUB and aws_safe_env of test_guards.py at the launch scripts' commit (read, not imported: the test module
    of an old commit would also import its own helpers)."""
    namespace = {"__file__": os.path.join(tools_dir, "test_guards.py")}
    source = open(os.path.join(tools_dir, "test_guards.py"), encoding="utf-8").read()
    head = source[:source.index("@unittest.skipIf")]
    exec(compile(head, "test_guards.py", "exec"), namespace)  # constants and helpers only: no test runs
    return namespace["STUB"], namespace["aws_safe_env"], namespace["ACCOUNT"]


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 tools/restructure/fuzz_dryrun.py", description=__doc__.split("\n")[0])
    p.add_argument("--tools", required=True, help="the commit whose launch scripts run")
    p.add_argument("--commit", required=True, help="the campaign's commit (launch.sh --commit)")
    p.add_argument("--campaign", default="weather-sand-snow")
    args = p.parse_args(argv)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    with tempfile.TemporaryDirectory(prefix="aws_fuzz_test_dryrun_") as tmp:
        repo = os.path.join(tmp, "repo")
        subprocess.run(git + ["clone", "-q", "--shared", "--no-checkout", ROOT, repo], check=True)
        sha = {}
        for name in ("tools", "commit"):
            sha[name] = subprocess.run(git + ["-C", repo, "rev-parse", getattr(args, name) + "^{commit}"],
                                       check=True, capture_output=True, text=True).stdout.strip()
        newer = sha["tools"]
        if subprocess.run(git + ["-C", repo, "merge-base", "--is-ancestor", sha["tools"], sha["commit"]]).returncode == 0:
            newer = sha["commit"]
        subprocess.run(git + ["-C", repo, "checkout", "-q", "--detach", sha["tools"]], check=True)
        subprocess.run(git + ["-C", repo, "update-ref", "refs/remotes/origin/main", newer], check=True)
        tools_dir = os.path.join(repo, "tools", "cloud", "aws_fuzz")
        stub, aws_safe_env, account = stub_text(tools_dir)
        bin_dir = os.path.join(tmp, "bin")
        os.mkdir(bin_dir)
        with open(os.path.join(bin_dir, "aws"), "w", newline="\n") as f:
            f.write(stub)
        os.chmod(os.path.join(bin_dir, "aws"), 0o755)
        log = os.path.join(tmp, "calls.log")
        open(log, "w").close()
        env = aws_safe_env(dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"], STUB_LOG=log,
                                STUB_ARN="arn:aws:iam::%s:user/pokeengine" % account, STUB_ACCOUNT=account,
                                DUOFORGE_FUZZ_NO_GIT_CHECK="", LC_ALL="C"), os.path.join(tmp, "none"))
        env.pop("DUOFORGE_FUZZ_BUCKET", None)
        assert shutil.which("aws", path=env["PATH"]) == os.path.join(bin_dir, "aws"), "the stub must be the aws"
        run = subprocess.run(["bash", os.path.join(tools_dir, "launch.sh"), "--campaign", args.campaign, "--commit",
                              sha["commit"], "--bucket", "my-fuzz-bucket"], env=env, capture_output=True, text=True,
                             timeout=300)
        short = lambda text: text.replace(tmp, "TMP")  # noqa: E731
        print(f"tools {sha['tools']}  commit {sha['commit']}  campaign {args.campaign}")
        print(f"exit {run.returncode}")
        print("--- stdout\n" + short(run.stdout).rstrip())
        print("--- stderr\n" + short(run.stderr).rstrip())
        print("--- stub aws calls\n" + short(open(log, encoding="utf-8").read()).rstrip())
        return run.returncode


if __name__ == "__main__":
    sys.exit(main())
