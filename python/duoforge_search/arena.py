"""Moved to duoforge_eval.arena (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.arena itself; run as python -m duoforge_search.arena, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_search.arena", "duoforge_eval.arena")
else:
    _forward.alias(__name__, "duoforge_eval.arena")
