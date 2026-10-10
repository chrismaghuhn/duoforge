"""The compute ledger of stage 3 P1 (decision 0024; Learner v2 plan 2026-10-08-stage3-p1-learner, task 6): what an
arm spent, measured the same way in the pilot and the continuation control and in M12's generation ledger
(confirmed 2026-10-08).

cpu_core_seconds is the user + system CPU time of this process and its waited-for children (getrusage self +
children; os.times where resource is missing), threads included, so the native batch workers count. gpu_seconds
is the wall time of device sections: from submitting device work until it is ready, JIT included; a section ends
in jax.block_until_ready and sections never nest. The two may overlap. phases breaks both down by name.

A ledger file sums every process that saved into it (a restart adds its process), and it never lies inside the
repository: ledgers name private runs.
"""
import contextlib
import json
import os
import time
from pathlib import Path

try:
    import resource
except ImportError:  # Windows: no getrusage
    resource = None

SCHEMA = 1


def cpu_seconds():
    """User + system CPU seconds of this process and its waited-for children."""
    if resource is not None:
        own, kids = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
        return own.ru_utime + own.ru_stime + kids.ru_utime + kids.ru_stime
    t = os.times()
    return t.user + t.system + t.children_user + t.children_system


class Ledger:
    """The ledger at path for this process: phase(name) and device() measure, save() writes the totals of every
    earlier process plus this one's. path None: this process alone, in memory (totals() only; save refuses)."""

    def __init__(self, path=None):
        from duoforge_replay.dataset import refuse_repository
        self.path = None if path is None else Path(path)
        if self.path is not None:
            refuse_repository(self.path)
        self._base = {"schema": SCHEMA, "cpu_core_seconds": 0.0, "gpu_seconds": 0.0, "processes": 0, "phases": {}}
        if self.path is not None and self.path.exists():
            saved = json.loads(self.path.read_text())
            if saved.get("schema") != SCHEMA:
                raise ValueError(f"{self.path}: ledger schema {saved.get('schema')!r}, expected {SCHEMA}")
            self._base = saved
        self._start = cpu_seconds()
        self._gpu = 0.0
        self._phases = {}
        self._phase = None
        self._in_device = False

    def _bucket(self, name):
        return self._phases.setdefault(name, {"cpu_core_seconds": 0.0, "gpu_seconds": 0.0})

    @contextlib.contextmanager
    def phase(self, name):
        """CPU and device seconds inside the block count toward phase name."""
        outer, self._phase = self._phase, name
        start = cpu_seconds()
        try:
            yield
        finally:
            self._bucket(name)["cpu_core_seconds"] += cpu_seconds() - start
            self._phase = outer

    @contextlib.contextmanager
    def device(self):
        """One device section: its wall time is GPU-seconds. The block must end in jax.block_until_ready."""
        if self._in_device:
            raise RuntimeError("device sections do not nest")
        self._in_device = True
        start = time.perf_counter()
        try:
            yield
        finally:
            spent = time.perf_counter() - start
            self._in_device = False
            self._gpu += spent
            if self._phase is not None:
                self._bucket(self._phase)["gpu_seconds"] += spent

    def totals(self):
        """The ledger as save writes it: earlier processes plus this one."""
        phases = {k: dict(v) for k, v in self._base["phases"].items()}
        for name, mine in self._phases.items():
            row = phases.setdefault(name, {"cpu_core_seconds": 0.0, "gpu_seconds": 0.0})
            row["cpu_core_seconds"] += mine["cpu_core_seconds"]
            row["gpu_seconds"] += mine["gpu_seconds"]
        return {"schema": SCHEMA,
                "cpu_core_seconds": self._base["cpu_core_seconds"] + cpu_seconds() - self._start,
                "gpu_seconds": self._base["gpu_seconds"] + self._gpu,
                "processes": self._base["processes"] + 1,
                "phases": phases}

    def save(self):
        """Writes the totals atomically (a temporary file, then a replace)."""
        if self.path is None:
            raise ValueError("this ledger has no file (Ledger(None) keeps its totals in memory)")
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.totals(), indent=1, sort_keys=True))
        os.replace(tmp, self.path)
