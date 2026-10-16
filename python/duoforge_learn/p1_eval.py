"""Moved to duoforge_eval.p1_eval (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.p1_eval itself; run as python -m duoforge_learn.p1_eval, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_learn.p1_eval", "duoforge_eval.p1_eval")
else:
    _forward.alias(__name__, "duoforge_eval.p1_eval")
