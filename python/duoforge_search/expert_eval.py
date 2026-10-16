"""Moved to duoforge_eval.expert_eval (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.expert_eval itself; run as python -m duoforge_search.expert_eval, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_search.expert_eval", "duoforge_eval.expert_eval")
else:
    _forward.alias(__name__, "duoforge_eval.expert_eval")
