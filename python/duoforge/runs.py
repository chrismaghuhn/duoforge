"""Runs: one place, one format (restructure step 8, plan section "Runs").

A run is anything that produces results instead of checking code: training, evaluations and arenas, benchmarks,
coverage measurements, fuzz campaigns, cloud runs. Their outputs never land in a work tree of this repository
(AGENTS.md: run directories, weights and live logs are private):

- out_dir(): the run's output directory, --out or the default $DUOFORGE_RUNS/<kind>/<date>-<name>/; a directory
  inside a work tree of this repository is refused, and so is a missing default (no silent fallback).
- Manifest: manifest.json of one run: the code (commit and dirty flag), the full arguments, the seeds, the machine,
  start and end; for evaluation and coverage runs also the format (duoforge.formats.record), which a run must name.

This module imports nothing of the learn, search or eval packages: every run tool may use it.
"""
import datetime
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

RUNS_ENV = "DUOFORGE_RUNS"
KINDS = ("train", "eval", "bench", "coverage", "fuzz", "cloud")
MANIFEST = "manifest.json"
MANIFEST_VERSION = 1
FORMAT_KINDS = ("eval", "coverage")  # plan "Format axis": their manifests name the format (duoforge.formats)
ROOT = Path(__file__).resolve().parents[2]  # the work tree this code runs from


def _git(args, cwd=None, git_dir=None, work_tree=None):
    """git's stdout, or None when git is missing or fails."""
    cmd = ["git"]
    if git_dir is not None:
        cmd += [f"--git-dir={git_dir}", f"--work-tree={work_tree}"]
    elif cwd is not None:
        cmd += ["-C", str(cwd)]
    try:
        out = subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def _common_dir(path):
    """The git common directory of the work tree that holds path (its nearest existing ancestor), or None."""
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    out = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=path)
    return Path(out.strip()).resolve() if out and out.strip() else None


def inside_repository(path, root=ROOT):
    """Whether path lies in a work tree of this repository: the checkout of this code, its main checkout or any
    worktree (they share one git common directory)."""
    path = Path(path).resolve()
    root = Path(root).resolve()
    if path == root or root in path.parents:
        return True
    ours = _common_dir(root)
    return ours is not None and _common_dir(path) == ours


def refuse_repository(path, root=ROOT):
    """SystemExit when path lies in a work tree of this repository: run outputs are private (AGENTS.md)."""
    if inside_repository(path, root):
        raise SystemExit(f"the output {Path(path).resolve()} is inside the repository: run outputs never go there "
                         f"(AGENTS.md)")


def default_out(kind, name, environ=None, today=None):
    """$DUOFORGE_RUNS/<kind>/<date>-<name>: SystemExit when DUOFORGE_RUNS is not set (no silent fallback) or when that
    directory already holds files (a second run of the day takes an explicit --out)."""
    if kind not in KINDS:
        raise ValueError(f"unknown run kind {kind!r} (one of {', '.join(KINDS)})")
    if not name or os.sep in name or "/" in name:
        raise ValueError(f"a run name is one path component (got {name!r})")
    environ = os.environ if environ is None else environ
    base = environ.get(RUNS_ENV, "")
    if not base:
        raise SystemExit(f"no output directory: pass --out, or set {RUNS_ENV} to the private runs directory "
                         f"(outside the repository)")
    today = datetime.date.today() if today is None else today
    path = Path(base) / kind / f"{today.isoformat()}-{name}"
    if path.is_dir() and any(path.iterdir()):  # a second run of the day: never mixed into the first one's outputs
        raise SystemExit(f"the default output {path} already holds a run: pass --out with a new directory")
    return path


def out_dir(out, kind, name, environ=None, today=None, root=ROOT):
    """The run's output directory: out (--out) or default_out(kind, name); refused inside the repository."""
    path = Path(out) if out else default_out(kind, name, environ, today)
    refuse_repository(path, root)
    return path


def _worktree_git_dir(root):
    """The git directory of a worktree whose .git file names a gitdir that does not resolve here (a worktree made
    under another path, such as a Windows path seen from WSL, #411): <main>/.git/worktrees/<name> of the nearest
    ancestor that has it, or None."""
    dot_git = Path(root) / ".git"
    if not dot_git.is_file():
        return None
    text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
    if not text.startswith("gitdir:"):
        return None
    named = text[len("gitdir:"):].strip()
    if Path(named).is_dir():
        return None  # it resolves: plain git works (or fails for another reason)
    leaf = named.replace("\\", "/").rstrip("/").split("/")[-1]
    for parent in Path(root).resolve().parents:
        candidate = parent / ".git" / "worktrees" / leaf
        if candidate.is_dir():
            return candidate
    return None


def code(root=ROOT, environ=None):
    """{"commit", "dirty"} of the code that runs, never None (HauptSession, 2026-10-13): from git in the work tree;
    for a worktree whose gitdir does not resolve, from its git directory under the main checkout (git --git-dir);
    else from DUOFORGE_COMMIT and DUOFORGE_DIRTY ("0" or "1", a copy without git). SystemExit when none names it."""
    environ = os.environ if environ is None else environ
    attempts = [{"cwd": root}]
    git_dir = _worktree_git_dir(root)
    if git_dir is not None:
        attempts.append({"git_dir": git_dir, "work_tree": root})
    for where in attempts:
        head = _git(["rev-parse", "HEAD"], **where)
        status = _git(["status", "--porcelain", "--untracked-files=no"], **where)
        if head and head.strip() and status is not None:
            return {"commit": head.strip(), "dirty": bool(status.strip())}
    commit, dirty = environ.get("DUOFORGE_COMMIT", ""), environ.get("DUOFORGE_DIRTY", "")
    if not commit or dirty not in ("0", "1"):
        raise SystemExit("no commit to name: run from a git checkout, or set DUOFORGE_COMMIT and DUOFORGE_DIRTY (0 or 1)")
    return {"commit": commit, "dirty": dirty == "1"}


def machine():
    """The host the run ran on (no user names or paths)."""
    return {"host": platform.node(), "system": platform.system(), "release": platform.release(),
            "machine": platform.machine(), "processors": os.cpu_count(), "python": platform.python_version()}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Manifest:
    """The manifest of one run: made when it begins, write(out) when its outputs are written.

    tool: the module that runs (its python -m name); argv: the full arguments; seeds: the seeds by name. A run of
    FORMAT_KINDS names its format (set_format, as soon as it knows it): its manifest is never written without one."""

    def __init__(self, kind, tool, argv, seeds=None, root=ROOT, environ=None):
        if kind not in KINDS:
            raise ValueError(f"unknown run kind {kind!r} (one of {', '.join(KINDS)})")
        self.record = {"manifest": MANIFEST_VERSION, "kind": kind, "tool": tool,
                       "argv": [str(a) for a in (sys.argv[1:] if argv is None else argv)],
                       "seeds": dict(seeds or {}), "code": code(root, environ), "machine": machine(),
                       "start": _now(), "end": None}

    def set_format(self, record):
        """The format the run plays: {"id", "showdown_format_id"} (duoforge.formats.record and its lookups)."""
        if not isinstance(record, dict) or set(record) != {"id", "showdown_format_id"}:
            raise ValueError(f"a format record is {{'id', 'showdown_format_id'}} (got {record!r})")
        self.record["format"] = dict(record)

    def write(self, out, **extra):
        """Writes OUT/manifest.json with the end time (and extra fields); returns its path."""
        if self.record["kind"] in FORMAT_KINDS and "format" not in self.record:
            raise RuntimeError(f"a {self.record['kind']} run names its format (Manifest.set_format) before its manifest "
                               f"is written")
        self.record["end"] = _now()
        self.record.update(extra)
        path = Path(out) / MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(MANIFEST + ".tmp")
        tmp.write_text(json.dumps(self.record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return path
