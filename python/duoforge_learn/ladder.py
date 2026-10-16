"""Moved to duoforge_eval.ladder (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.ladder itself; run as python -m duoforge_learn.ladder, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_learn.ladder", "duoforge_eval.ladder")
else:
    _forward.alias(__name__, "duoforge_eval.ladder")
