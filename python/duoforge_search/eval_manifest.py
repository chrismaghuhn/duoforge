"""Moved to duoforge_eval.eval_manifest (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.eval_manifest itself; run as python -m duoforge_search.eval_manifest, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_search.eval_manifest", "duoforge_eval.eval_manifest")
else:
    _forward.alias(__name__, "duoforge_eval.eval_manifest")
