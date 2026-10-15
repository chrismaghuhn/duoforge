#!/usr/bin/env python3
"""Training runs on Kaggle (owner OK, HauptSession 2026-10-15): private datasets, a private notebook at a fixed commit,
the weights back, and a manifest. Only the HauptSession runs the commands that reach Kaggle, with the owner present;
without --i-have-owner-approval nothing reaches Kaggle, the command only shows what it would do.

    python tools/cloud/kaggle/kaggle_run.py plan --name NAME --data DIR... [--net FILE...] [--config FILE...] --out PLAN
    python tools/cloud/kaggle/kaggle_run.py privacy --env ENV [--i-have-owner-approval]
    python tools/cloud/kaggle/kaggle_run.py upload --plan PLAN --env ENV [--i-have-owner-approval]
    python tools/cloud/kaggle/kaggle_run.py start --plan PLAN --commit SHA --job JOB --env ENV [--resume-from DIR]
        [--i-have-owner-approval]
    python tools/cloud/kaggle/kaggle_run.py fetch --plan PLAN --env ENV --out DIR [--i-have-owner-approval]

plan       the content list of a run's dataset: every file with its size, sha256 and origin (training data, networks,
           configurations). Nothing is uploaded before the HauptSession has released this list (README). The
           tournament sun team is refused by name: it never goes to Kaggle (the exception of 2026-10-15 is AWS and #458
           only), nor does any file inside the repository or any file under a private run directory that is no input.
privacy    every dataset and notebook of the account whose name starts with PREFIX, each must be private, else a named
           refusal (exit 3). It runs before and after every upload, start and fetch.
upload     the plan's files as ONE private dataset named after the plan's sha256 (PREFIX + the first 12 digits), after
           checking each file's sha256 again.
start      a private notebook (GPU, internet for the public repository) that runs kaggle_job.py with the plan's dataset
           at the exact commit; --resume-from (a directory fetched from an earlier run that stopped at its deadline)
           adds its state as a private dataset of its own, and the job continues the run from it.
fetch      the notebook's output to --out, its weights' sha256 and a manifest.json: the commit, the data's sha256 (the
           plan's), the weights' sha256, the versions of JAX and CUDA, the GPU, the seed, the run time and the launches.

The key: read only from --env, a file outside the repository (default C:\\Users\\chris\\.duoforge-kaggle.env) with the
lines KAGGLE_USERNAME=... and KAGGLE_KEY=...; it goes to the Kaggle CLI in its environment only, never on a command
line, and every output of the CLI is masked (the key and the username never appear in a log or an error). The CLI's
own configuration directory is an empty temporary one, so no other credentials are used.
Weights, checkpoints and data stay private (AGENTS.md): nothing of them goes into the repository.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PREFIX = "duoforge-"
DEFAULT_ENV = r"C:\Users\chris\.duoforge-kaggle.env"
# The tournament sun team (a private file): never to Kaggle, by its sha256 (Owner/HauptSession 2026-10-15).
REFUSED = {"e1060cf46a8f30bc3e56ad6fb1e038a9ed3dafd47a9ec9913b8399542320c281": "the tournament sun team"}
ORIGINS = ("data", "net", "config", "state")
JOBS = ("bc-short", "bc")
SHA = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
APPROVAL = "--i-have-owner-approval"


class Refused(SystemExit):
    """A named refusal: exit 2 (a bad call or input) or 3 (something on Kaggle is not private)."""

    def __init__(self, message, code=2):
        print(f"kaggle_run: refused: {message}", file=sys.stderr)
        super().__init__(code)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def inside(path, root):
    path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    return path == root or path.startswith(root + os.sep)


# ----------------------------------------------------------------------------------------------- the plan
def plan(name, groups):
    """The content list: groups = [(origin, [path, ...])]; each path a file or a directory (all its files)."""
    if not NAME.match(name):
        raise Refused(f"--name {name!r}: lowercase letters, digits and dashes")
    files = []
    for origin, paths in groups:
        for path in paths:
            if not os.path.exists(path):
                raise Refused(f"a {origin} path does not exist (#{len(files) + 1})")
            if inside(path, REPO):
                raise Refused(f"a {origin} path is inside the repository: Kaggle data come from outside it")
            if os.path.isdir(path):
                found = [os.path.join(d, n) for d, _, ns in os.walk(path) for n in sorted(ns)]
                base = os.path.dirname(os.path.abspath(path))
            else:
                found, base = [path], os.path.dirname(os.path.abspath(path))
            for f in sorted(found):
                digest = sha256(f)
                if digest in REFUSED:
                    raise Refused(f"{REFUSED[digest]} is in the upload list: it never goes to Kaggle")
                files.append({"path": os.path.relpath(os.path.abspath(f), base).replace(os.sep, "/"),
                              "source": os.path.abspath(f), "size": os.path.getsize(f), "sha256": digest,
                              "origin": origin})
    if not files:
        raise Refused("the plan holds no file")
    rels = [f["path"] for f in files]
    if len(set(rels)) != len(rels):
        raise Refused("two files of the plan have one path in the dataset")
    digest = hashlib.sha256(json.dumps([[f["path"], f["sha256"]] for f in files]).encode()).hexdigest()
    return {"name": name, "sha256": digest, "dataset": f"{PREFIX}{digest[:12]}", "files": files,
            "bytes": sum(f["size"] for f in files)}


def show_plan(p):
    print(f"plan {p['name']}: dataset {p['dataset']} (private), {len(p['files'])} files, {p['bytes']} bytes, "
          f"sha256 {p['sha256']}")
    for f in p["files"]:
        print(f"  {f['origin']:6} {f['size']:>12} {f['sha256']}  {f['path']}")


def check_plan_files(p):
    """Every file of the plan still has its sha256 (and none is refused)."""
    for f in p["files"]:
        if not os.path.isfile(f["source"]):
            raise Refused(f"the plan's file {f['path']} is gone")
        digest = sha256(f["source"])
        if digest in REFUSED:
            raise Refused(f"{REFUSED[digest]} is in the upload list: it never goes to Kaggle")
        if digest != f["sha256"]:
            raise Refused(f"the plan's file {f['path']} has another sha256 now: make the plan again")


# ----------------------------------------------------------------------------------------------- the key
def read_env(path):
    """(username, key) from the env file outside the repository; Refused without naming any value."""
    if inside(path, REPO):
        raise Refused("the env file is inside the repository: keep it outside")
    if not os.path.isfile(path):
        raise Refused("the env file does not exist")
    values = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep:
                raise Refused("the env file has a line that is not KEY=VALUE (not shown)")
            values[key.strip()] = value.strip().strip('"').strip("'")
    user, key = values.get("KAGGLE_USERNAME", ""), values.get("KAGGLE_KEY", "")
    if not user or not key:
        raise Refused("the env file lacks KAGGLE_USERNAME or KAGGLE_KEY")
    if not re.match(r"^[A-Za-z0-9_-]{1,64}$", user):
        raise Refused("KAGGLE_USERNAME in the env file is not a Kaggle user name (not shown)")
    return user, key


class Kaggle:
    """The Kaggle CLI (`kaggle` on the PATH), with the key in its environment only and every output masked."""

    def __init__(self, user, key, log=print):
        self.user, self.key, self.log = user, key, log
        self.cli = shutil.which("kaggle")
        if self.cli is None:
            raise Refused("the Kaggle CLI (`kaggle`) is not on the PATH")
        self.config = tempfile.mkdtemp(prefix="duoforge-kaggle-config-")

    def mask(self, text):
        for secret, shown in ((self.key, "<key>"), (self.user, "<user>")):
            if secret:
                text = text.replace(secret, shown)
        return text

    def run(self, *args, check=True):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("KAGGLE")}
        env.update(KAGGLE_USERNAME=self.user, KAGGLE_KEY=self.key, KAGGLE_CONFIG_DIR=self.config)
        r = subprocess.run([self.cli, *args], env=env, capture_output=True, text=True)
        if check and r.returncode != 0:
            out, err = self.mask(r.stdout), self.mask(r.stderr)
            shown = " ".join(self.mask(a) for a in args[:2])
            raise Refused(f"kaggle {shown} failed (exit {r.returncode}): {err.strip()[-400:] or out.strip()[-400:]}")
        return r.stdout  # unmasked for the parsing here: whatever is shown goes through mask()

    def ref(self, slug):
        return f"{self.user}/{slug}"

    # ---- privacy: every dataset and notebook of PREFIX, by its own metadata; a missing field is a refusal
    def mine(self, kind):
        out = self.run(kind, "list", "--mine", "--csv", "--page-size", "100")
        lines = [l for l in out.splitlines() if l.strip()]
        if not lines or not lines[0].lower().startswith("ref"):
            raise Refused(f"kaggle {kind} list gave no table: cannot check privacy", 3)
        refs = [l.split(",")[0].strip() for l in lines[1:]]
        return [r for r in refs if r.split("/")[-1].startswith(PREFIX)]

    def dataset_private(self, ref):
        with tempfile.TemporaryDirectory() as tmp:
            self.run("datasets", "metadata", "-p", tmp, ref)
            path = os.path.join(tmp, "dataset-metadata.json")
            meta = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
        value = meta.get("isPrivate")
        if value is None:
            raise Refused(f"dataset {self.mask(ref)}: its metadata names no isPrivate: privacy unknown", 3)
        return value is True

    def kernel_private(self, ref):
        with tempfile.TemporaryDirectory() as tmp:
            self.run("kernels", "pull", "-p", tmp, "-m", ref)
            path = os.path.join(tmp, "kernel-metadata.json")
            meta = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
        value = meta.get("is_private")
        if value is None:
            raise Refused(f"notebook {self.mask(ref)}: its metadata names no is_private: privacy unknown", 3)
        return value in (True, "true", "True")

    def check_privacy(self, when):
        """Refused (exit 3) unless every PREFIX dataset and notebook of the account is private. Kaggle's visibility is
        the dataset's or the notebook's: its versions and a notebook's outputs have no visibility of their own."""
        datasets, kernels = self.mine("datasets"), self.mine("kernels")
        public = [f"dataset {self.mask(r)}" for r in datasets if not self.dataset_private(r)]
        public += [f"notebook {self.mask(r)}" for r in kernels if not self.kernel_private(r)]
        if public:
            raise Refused(f"{when}: not private: {', '.join(public)}: make it private by hand and check", 3)
        self.log(f"privacy {when}: {len(datasets)} dataset(s) and {len(kernels)} notebook(s) of {PREFIX}*, all private")


# ----------------------------------------------------------------------------------------------- the commands
def dataset_dir(tmp, p, user, title):
    """A dataset directory: the plan's files at their paths, and its metadata (private: no `--public` is ever given)."""
    for f in p["files"]:
        target = os.path.join(tmp, *f["path"].split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(f["source"], target)
    meta = {"title": title, "id": f"{user}/{p['dataset']}", "licenses": [{"name": "other"}], "isPrivate": True}
    with open(os.path.join(tmp, "dataset-metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)


def kernel_dir(tmp, p, user, commit, job, state_dataset, seed):
    """A notebook directory: kaggle_job.py and its job.json, and the notebook's metadata (private, GPU, internet for the
    public repository, the plan's dataset and the state's)."""
    shutil.copyfile(os.path.join(HERE, "kaggle_job.py"), os.path.join(tmp, "kaggle_job.py"))
    sources = [f"{user}/{p['dataset']}"] + ([f"{user}/{state_dataset}"] if state_dataset else [])
    with open(os.path.join(tmp, "job.json"), "w", encoding="utf-8") as f:
        json.dump({"commit": commit, "job": job, "seed": seed, "plan": {"name": p["name"], "sha256": p["sha256"],
                   "dataset": p["dataset"], "files": [{k: x[k] for k in ("path", "size", "sha256", "origin")}
                                                      for x in p["files"]]},
                   "state_dataset": state_dataset}, f, indent=1)
    # The notebook reads job.json from its own directory: Kaggle runs the code file with its directory's files only
    # when they are inlined, so the job is embedded into the code file as well (kaggle_job.py reads either).
    with open(os.path.join(tmp, "kaggle_job.py"), "a", encoding="utf-8") as f:
        f.write("\nJOB = " + json.dumps(json.load(open(os.path.join(tmp, "job.json"), encoding="utf-8"))) + "\n")
        f.write("if __name__ == '__main__':\n    main(JOB)\n")
    meta = {"id": f"{user}/{p['dataset']}-{job}", "title": f"{p['dataset']}-{job}", "code_file": "kaggle_job.py",
            "language": "python", "kernel_type": "script", "is_private": True, "enable_gpu": True,
            "enable_internet": True, "dataset_sources": sources, "competition_sources": [], "kernel_sources": []}
    with open(os.path.join(tmp, "kernel-metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    return meta["id"].split("/")[1]


def load_plan(path):
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    for key in ("name", "sha256", "dataset", "files"):
        if key not in p:
            raise Refused(f"the plan file lacks {key}")
    return p


def state_plan(directory, p, commit):
    """The plan of a fetched run's state (its resume files: duoforge_learn.bc's bc-state.npz and its log) as a private
    dataset of its own. The resumed run must be at the same commit: the trainer's code is not part of what bc --resume
    compares."""
    files = [os.path.join(directory, "run", n) for n in ("bc-state.npz", "bc-log.jsonl")]
    files.append(os.path.join(directory, "status.json"))  # its launches so far
    missing = [os.path.basename(f) for f in files if not os.path.isfile(f)]
    if missing:
        raise Refused(f"--resume-from holds no state ({', '.join(missing)} missing)")
    status = json.load(open(os.path.join(directory, "status.json"), encoding="utf-8"))
    if status.get("status") != "partial" or status.get("plan_sha256") != p["sha256"]:
        raise Refused("--resume-from is not a partial run of this plan")
    if status.get("commit") != commit:
        raise Refused("--resume-from ran at another commit: a run continues at its own commit")
    return plan(f"{p['name']}-state", [("state", files)])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kaggle_run.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("plan")
    a.add_argument("--name", required=True)
    a.add_argument("--data", nargs="+", required=True)
    a.add_argument("--net", nargs="*", default=[])
    a.add_argument("--config", nargs="*", default=[])
    a.add_argument("--out", required=True)
    for name in ("privacy", "upload", "start", "fetch"):
        b = sub.add_parser(name)
        b.add_argument("--env", default=DEFAULT_ENV)
        b.add_argument(APPROVAL, dest="approved", action="store_true")
        if name != "privacy":
            b.add_argument("--plan", required=True)
    sub.choices["start"].add_argument("--commit", required=True)
    sub.choices["start"].add_argument("--job", required=True, choices=JOBS)
    sub.choices["start"].add_argument("--seed", type=int, default=1)
    sub.choices["start"].add_argument("--resume-from", default=None)
    sub.choices["fetch"].add_argument("--out", required=True)
    sub.choices["fetch"].add_argument("--job", required=True, choices=JOBS)
    args = ap.parse_args(argv)

    if args.command == "plan":
        if inside(args.out, REPO):
            raise Refused("--out is inside the repository: plans name private files")
        p = plan(args.name, [("data", args.data), ("net", args.net), ("config", args.config)])
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(p, f, indent=1)
        show_plan(p)
        print("\nnothing was uploaded: send this list to the HauptSession; upload only after its release.")
        return 0

    p = load_plan(args.plan) if args.command != "privacy" else None
    if p:
        check_plan_files(p)
    if args.command == "start" and not SHA.match(args.commit):
        raise Refused("--commit: the exact 40-digit sha of a commit on main")
    if not args.approved:
        print(f"{args.command}: nothing reaches Kaggle without {APPROVAL} (the default). It would:")
        if p:
            show_plan(p)
        print(f"  check privacy, {args.command}, check privacy again (env file: outside the repository, never shown)")
        return 0
    user, key = read_env(args.env)
    k = Kaggle(user, key)
    k.check_privacy(f"before {args.command}")
    if args.command == "privacy":
        return 0
    if args.command == "upload":
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir(tmp, p, user, p["dataset"])
            print(k.mask(k.run("datasets", "create", "-p", tmp, "-r", "zip").strip()))  # never --public: private
        k.check_privacy("after upload")
        return 0
    if args.command == "start":
        state = None
        if args.resume_from:
            sp = state_plan(args.resume_from, p, args.commit)
            with tempfile.TemporaryDirectory() as tmp:
                dataset_dir(tmp, sp, user, sp["dataset"])
                print(k.mask(k.run("datasets", "create", "-p", tmp, "-r", "zip").strip()))
            state = sp["dataset"]
            k.check_privacy("after the state's upload")
        with tempfile.TemporaryDirectory() as tmp:
            slug = kernel_dir(tmp, p, user, args.commit, args.job, state, args.seed)
            print(k.mask(k.run("kernels", "push", "-p", tmp).strip()))
        k.check_privacy("after start")
        print(f"started notebook {slug} (private) at {args.commit}; fetch with: fetch --plan {args.plan} --job {args.job}")
        return 0
    if args.command == "fetch":
        if inside(args.out, REPO):
            raise Refused("--out is inside the repository: weights are private")
        slug = f"{p['dataset']}-{args.job}"
        status = k.run("kernels", "status", k.ref(slug))
        if "complete" not in status and "error" not in status and "cancel" not in status:
            raise Refused(f"notebook {slug} is still running: {k.mask(status.strip())}")
        os.makedirs(args.out, exist_ok=True)
        k.run("kernels", "output", k.ref(slug), "-p", args.out)
        k.check_privacy("after fetch")
        print(json.dumps(write_manifest(args.out, p, args.job), indent=1))
        return 0
    return 2


def write_manifest(out, p, job):
    """manifest.json of a fetched run from its status.json and env.json (written by kaggle_job.py)."""
    def load(name):
        path = os.path.join(out, name)
        return json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else None
    status, env = load("status.json"), load("env.json")
    if status is None or env is None:
        raise Refused("the notebook's output lacks status.json or env.json")
    if status.get("plan_sha256") != p["sha256"]:
        raise Refused("the notebook's output is of another plan")
    weights = os.path.join(out, "run", "bc.npz")
    manifest = {"plan": p["name"], "data_sha256": p["sha256"], "dataset": p["dataset"], "job": job,
                "commit": status.get("commit"), "status": status.get("status"), "reason": status.get("reason"),
                "seed": status.get("seed"), "seconds": status.get("seconds"), "launches": status.get("launches"),
                "weights_sha256": sha256(weights) if os.path.isfile(weights) else None,
                "jax": env.get("jax"), "jaxlib": env.get("jaxlib"), "cuda": env.get("cuda"), "gpu": env.get("gpu"),
                "python": env.get("python"), "library_sha256": env.get("library_sha256"),
                "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    return manifest


if __name__ == "__main__":
    sys.exit(main())
