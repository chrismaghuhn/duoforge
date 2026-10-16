"""Moved to duoforge_eval.honest_breakdown (restructure step 8): a forwarder until no session uses the old command.

python tools/perf/honest_breakdown.py ARGS (with PYTHONPATH=python, as before) runs python -m duoforge_eval.honest_breakdown
ARGS.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "python"))  # after PYTHONPATH: this checkout's packages
from duoforge_eval import _forward  # noqa: E402

if __name__ == "__main__":
    _forward.run("tools/perf/honest_breakdown.py", "duoforge_eval.honest_breakdown")
