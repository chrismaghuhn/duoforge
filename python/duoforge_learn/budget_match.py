"""The continuation control's budget matching (stage 3 P1; train --update-gpu-share match): a closed loop that
chooses each update's device from the compute ledger, so that the control's CPU core-seconds and GPU-seconds both
end within 5 % of the pilot's (expert_eval.validate_compute), whatever the JIT, restarts and per-update costs.

A step is what the ledger books from one decision point (after an update) to the next: the next collection plus
the update on the chosen device. Before each step:
  - matched: both axes at FLOOR (0.95) of the pilot or above: stop;
  - a device fits when its expected step keeps both axes at CEILING (1.05) or below; the expected step is the most
    expensive one measured for that device: among the warm steps once the device ran in this process, among the
    first steps (JIT, and a resumed process's start-up) before that; unmeasured: UNKNOWN_SHARE of each axis it
    spends;
  - the lagging axis goes first: the GPU when its share is below the CPU's, else the CPU; the other device if the
    preferred one does not fit;
  - incomplete: no device fits: stop (the plan's "unable to match": re-plan, never a silent overrun).
The device sequence depends on measured costs, so it is logged per update (update_device), not reproduced by a seed.
"""
import json

FLOOR = 0.95
CEILING = 1.05
UNKNOWN_SHARE = 0.25  # an unmeasured step's assumed cost, per axis (the L4's GPU JIT step is 22 % of the GPU axis)
DEVICES = ("cpu", "default")


class Costs:
    """The steps measured per device: first (a device's first update in its process) and warm."""

    def __init__(self):
        self.first = {d: [] for d in DEVICES}
        self.warm = {d: [] for d in DEVICES}
        self.used = set()  # the devices that ran an update in the current process

    def observe(self, device, cpu, gpu):
        (self.warm if device in self.used else self.first)[device].append((float(cpu), float(gpu)))
        self.used.add(device)

    def new_process(self):
        self.used = set()

    def estimate(self, device):
        """The expected (cpu, gpu) of a step on device, None when no such step was measured."""
        steps = (self.warm if device in self.used else self.first)[device]
        if not steps:
            return None
        return max(c for c, _ in steps), max(g for _, g in steps)

    @classmethod
    def from_log(cls, lines):
        """The costs of a run's log.jsonl lines (train's records with "ledger" and "update_device"; "init" and
        "resume" lines start a process), for the process that resumes it: a new process."""
        book, prev = cls(), (0.0, 0.0)
        for line in lines:
            r = json.loads(line) if isinstance(line, str) else line
            if "resume" in r or "init" in r:
                book.new_process()
                continue
            if "ledger" not in r or r.get("update_device") not in DEVICES:
                continue
            now = (r["ledger"]["cpu_core_seconds"], r["ledger"]["gpu_seconds"])
            book.observe(r["update_device"], now[0] - prev[0], now[1] - prev[1])
            prev = now
        book.new_process()
        return book


def choose(totals, targets, costs):
    """(device, None) for the next update, or (None, "matched" | "incomplete") to stop. totals and targets:
    (cpu_core_seconds, gpu_seconds), targets both positive."""
    c, g = totals
    pc, pg = targets
    fc, fg = c / pc, g / pg
    if fc >= FLOOR and fg >= FLOOR:
        return None, "matched"

    def fits(device):
        step = costs.estimate(device)
        if step is None:
            step = (UNKNOWN_SHARE * pc, UNKNOWN_SHARE * pg if device == "default" else 0.0)
        return (c + step[0]) / pc <= CEILING and (g + step[1]) / pg <= CEILING

    for device in (("default", "cpu") if fg < fc else ("cpu", "default")):
        if fits(device):
            return device, None
    return None, "incomplete"
