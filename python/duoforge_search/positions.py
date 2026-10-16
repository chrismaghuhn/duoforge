"""Moved to duoforge_eval.positions (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.positions itself; run as python -m duoforge_search.positions, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_search.positions", "duoforge_eval.positions")
else:
    _forward.alias(__name__, "duoforge_eval.positions")
