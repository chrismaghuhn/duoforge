#!/usr/bin/env python3
"""Moved to tools/coverage/champions_coverage.py (restructure step 8): a forwarder until no session uses the old path.

python3 tools/research/champions_coverage.py ARGS runs python3 tools/coverage/champions_coverage.py ARGS.
"""
import runpy
import sys
from pathlib import Path

NEW = Path(__file__).resolve().parent.parent / "coverage" / "champions_coverage.py"

if __name__ == "__main__":
    print(f"tools/research/champions_coverage.py moved to tools/coverage/champions_coverage.py: run python3 tools/coverage/champions_coverage.py "
          f"(this forwarder will be removed)", file=sys.stderr, flush=True)
    sys.argv[0] = str(NEW)
    sys.path[0] = str(NEW.parent)  # as python3 tools/coverage/champions_coverage.py would have it
    runpy.run_path(str(NEW), run_name="__main__")
