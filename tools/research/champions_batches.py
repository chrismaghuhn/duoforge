#!/usr/bin/env python3
"""Moved to tools/coverage/champions_batches.py (restructure step 8): a forwarder until no session uses the old path.

python3 tools/research/champions_batches.py ARGS runs python3 tools/coverage/champions_batches.py ARGS.
"""
import runpy
import sys
from pathlib import Path

NEW = Path(__file__).resolve().parent.parent / "coverage" / "champions_batches.py"

if __name__ == "__main__":
    print(f"tools/research/champions_batches.py moved to tools/coverage/champions_batches.py: run python3 tools/coverage/champions_batches.py "
          "(this forwarder will be removed)", file=sys.stderr, flush=True)
    sys.argv[0] = str(NEW)
    sys.path[0] = str(NEW.parent)  # as python3 tools/coverage/champions_batches.py would have it
    runpy.run_path(str(NEW), run_name="__main__")
