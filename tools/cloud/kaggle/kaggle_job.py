"""The job of a private Kaggle notebook (kaggle_run.py start): a behavior-cloning run of the public repository at an exact
commit on the plan's private dataset; its output (/kaggle/working, private like the notebook) is fetched by
kaggle_run.py fetch. kaggle_run.py appends the job (JOB = {...}) and the call of main to this file when it starts a
notebook, so the notebook needs no other file.

The steps, each refused by name in status.json (status failed, reason <name>): the repository at the commit
(wrong_commit), its library (build), the plan's files by sha256 in the dataset (data_mismatch; the tournament sun team
by its sha256: refused_file), the environment (env.json: JAX, jaxlib, CUDA, the GPU, Python, the library's sha256), and
`python -m duoforge_learn.bc` with a deadline before the session limit: a run that reaches it is stopped after its last
finished epoch, whose state stays (status partial), and a later start --resume-from continues it (bc --resume) from the
state's dataset (duoforge_learn.bc refuses a resume on other versions of JAX, jaxlib, NumPy or optax or another
device kind: a run continues on the same Kaggle image and accelerator). Nothing here prints a credential: the notebook has none (its datasets are mounted read-only).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

REPO_URL = "https://github.com/chrismaghuhn/duoforge.git"
INPUT, WORK = "/kaggle/input", "/kaggle/working"
DEADLINE_SECONDS = 11 * 3600  # a Kaggle GPU session ends after 12 hours; the state of the last epoch is kept before
REFUSED = {"e1060cf46a8f30bc3e56ad6fb1e038a9ed3dafd47a9ec9913b8399542320c281": "the tournament sun team"}
# The short job proves the chain (minutes): a small model, two epochs. The full job takes its arguments from the plan's
# configuration file bc-args.json: a list of flags of duoforge_learn.bc from ALLOWED, never a path.
SHORT = ["--preset", "S", "--epochs", "2", "--patience", "2", "--batch", "1024",
         "--source-weight", "bo1_belief=1"]  # a Bo1 source needs its weight named (M11 Bo1 spec section 5)
ALLOWED = {"--preset", "--embed", "--member", "--position", "--hidden", "--layers", "--option", "--epochs", "--patience",
           "--batch", "--learning-rate", "--value-coef", "--weights", "--format-weight", "--source-weight",
           "--pick-hypotheses-weight", "--split"}


class JobError(RuntimeError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sh(cmd, log, cwd=None, env=None):
    with open(log, "a", encoding="utf-8") as f:
        f.write("$ " + " ".join(cmd) + "\n")
        f.flush()
        return subprocess.call(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)


def checkout(commit, repo, log):
    os.makedirs(repo, exist_ok=True)
    for cmd in (["git", "init", "-q"], ["git", "remote", "add", "origin", REPO_URL],
                ["git", "fetch", "-q", "--depth", "1", "origin", commit], ["git", "checkout", "-q", "--detach", "FETCH_HEAD"]):
        if sh(cmd, log, cwd=repo) != 0:
            raise JobError("wrong_commit", f"{' '.join(cmd[:2])} failed")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    if head != commit:
        raise JobError("wrong_commit", f"the checkout is at {head}, not {commit}")


def build(repo, work, log):
    b = os.path.join(work, "build")
    for cmd in (["cmake", "-S", repo, "-B", b, "-DCMAKE_BUILD_TYPE=Release"],
                ["cmake", "--build", b, "--target", "duoforge_shared", "-j", str(os.cpu_count() or 2)]):
        if sh(cmd, log) != 0:
            raise JobError("build", f"{cmd[0]} {cmd[1]} failed")
    for d, _, names in os.walk(b):
        if "libduoforge_shared.so" in names:
            return os.path.join(d, "libduoforge_shared.so")
    raise JobError("build", "libduoforge_shared.so was not built")


def check_data(plan, root):
    """The plan's files in the mounted dataset root, each by sha256; the data directories (the top level of the data
    files) in order."""
    dirs = []
    for f in plan["files"]:
        path = os.path.join(root, *f["path"].split("/"))
        if not os.path.isfile(path):
            raise JobError("data_mismatch", f"{f['path']} is not in the dataset")
        digest = sha256(path)
        if digest in REFUSED:
            raise JobError("refused_file", f"{REFUSED[digest]} is in the dataset: it never goes to Kaggle")
        if digest != f["sha256"]:
            raise JobError("data_mismatch", f"{f['path']} has another sha256")
        if f["origin"] == "data":
            top = os.path.join(root, f["path"].split("/")[0])
            if top not in dirs:
                dirs.append(top)
    return dirs


def bc_args(job, plan, root):
    if job == "bc-short":
        return list(SHORT)
    configs = [f for f in plan["files"] if f["origin"] == "config" and f["path"].endswith("bc-args.json")]
    if len(configs) != 1:
        raise JobError("bad_job", "the full job needs exactly one bc-args.json among the plan's configuration files")
    with open(os.path.join(root, *configs[0]["path"].split("/")), encoding="utf-8") as f:
        args = json.load(f)
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise JobError("bad_job", "bc-args.json is not a list of strings")
    flags = [a for a in args if a.startswith("--")]
    bad = [a for a in flags if a not in ALLOWED]
    if bad or any("/" in a or "\\" in a for a in args):
        raise JobError("bad_job", f"bc-args.json holds a flag or a path that the job does not take: {bad}")
    return args


def environment(lib):
    import platform
    info = {"python": platform.python_version(), "library_sha256": sha256(lib) if lib else None}
    try:
        import jax
        import jaxlib
        info.update(jax=jax.__version__, jaxlib=jaxlib.__version__,
                    devices=[str(d) for d in jax.devices()], backend=jax.default_backend())
    except Exception as err:  # noqa: BLE001 -- recorded, the run then fails on its own
        info.update(jax=None, jax_error=type(err).__name__)
    smi = shutil.which("nvidia-smi")
    if smi:
        q = subprocess.run([smi, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                           capture_output=True, text=True)
        info["gpu"] = q.stdout.strip() or None
        v = subprocess.run([smi], capture_output=True, text=True).stdout
        info["cuda"] = next((l.split("CUDA Version:")[1].split()[0] for l in v.splitlines() if "CUDA Version:" in l), None)
    else:
        info.update(gpu=None, cuda=None)
    return info


def run_bc(cmd, env, log, deadline, clock=time.monotonic, popen=subprocess.Popen, poll=30.0):
    """Runs the trainer until it ends or the deadline (seconds of clock) passes: then it is stopped (TERM, then KILL),
    and the state of its last finished epoch stays. Returns "done", "partial" or "failed"."""
    with open(log, "a", encoding="utf-8") as f:
        p = popen(cmd, env=env, stdout=f, stderr=subprocess.STDOUT)
        while True:
            try:
                code = p.wait(timeout=poll)
                return "done" if code == 0 else "failed"
            except subprocess.TimeoutExpired:
                if clock() >= deadline:
                    p.terminate()
                    try:
                        p.wait(timeout=60)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait()
                    return "partial"


def main(job, root=INPUT, work=WORK):
    started = time.monotonic()
    status = {"status": "failed", "reason": "unknown", "commit": job["commit"], "seed": job["seed"],
              "plan_sha256": job["plan"]["sha256"], "job": job["job"], "launches": []}
    log = os.path.join(work, "job.log")
    os.makedirs(work, exist_ok=True)
    run = os.path.join(work, "run")
    try:
        if job.get("state_dataset"):  # the earlier launches of this run, from its state
            state_root = os.path.join(root, job["state_dataset"])
            previous = os.path.join(state_root, "status.json")
            if os.path.isfile(previous):
                status["launches"] = json.load(open(previous, encoding="utf-8")).get("launches", [])
        repo = os.path.join(work, "src")
        checkout(job["commit"], repo, log)
        lib = build(repo, work, log)
        dirs = check_data(job["plan"], os.path.join(root, job["plan"]["dataset"]))
        env_info = environment(lib)
        with open(os.path.join(work, "env.json"), "w", encoding="utf-8") as f:
            json.dump(env_info, f, indent=1)
        args = bc_args(job["job"], job["plan"], os.path.join(root, job["plan"]["dataset"]))
        cmd = [sys.executable, "-m", "duoforge_learn.bc", "--data", *dirs, "--out", run, "--seed", str(job["seed"]),
               *args]
        if job.get("state_dataset"):
            os.makedirs(run, exist_ok=True)
            for name in ("bc-state.npz", "bc-log.jsonl"):
                src = os.path.join(root, job["state_dataset"], name)  # the state's dataset is flat (kaggle_run)
                if not os.path.isfile(src):
                    raise JobError("no_state", f"the state's dataset lacks {name}")
                shutil.copyfile(src, os.path.join(run, name))
            cmd.append("--resume")
        env = dict(os.environ, DUOFORGE_LIBRARY=lib, PYTHONPATH=os.path.join(repo, "python"))
        outcome = run_bc(cmd, env, log, started + DEADLINE_SECONDS)
        status["status"], status["reason"] = outcome, ("none" if outcome == "done" else
                                                       "deadline" if outcome == "partial" else "bc_failed")
    except JobError as err:
        status["reason"] = err.reason
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"REFUSED ({err.reason}): {err}\n")
    finally:
        seconds = time.monotonic() - started
        status["launches"].append({"seconds": seconds, "status": status["status"]})
        status["seconds"] = sum(x["seconds"] for x in status["launches"])
        with open(os.path.join(work, "status.json"), "w", encoding="utf-8") as f:
            json.dump(status, f, indent=1)
        shutil.rmtree(os.path.join(work, "src"), ignore_errors=True)  # the public source is no output
        shutil.rmtree(os.path.join(work, "build"), ignore_errors=True)
    return status
