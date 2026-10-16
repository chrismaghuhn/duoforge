"""Moved to duoforge_eval.tickbench (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.tickbench itself; run as python -m duoforge_search.tickbench, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_search.tickbench", "duoforge_eval.tickbench")
else:
    _forward.alias(__name__, "duoforge_eval.tickbench")
