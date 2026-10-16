"""Moved to duoforge_eval.bc_eval (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.bc_eval itself; run as python -m duoforge_learn.bc_eval, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_learn.bc_eval", "duoforge_eval.bc_eval")
else:
    _forward.alias(__name__, "duoforge_eval.bc_eval")
