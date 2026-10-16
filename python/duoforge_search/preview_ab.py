"""Moved to duoforge_eval.preview_ab (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.preview_ab itself; run as python -m duoforge_search.preview_ab, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_search.preview_ab", "duoforge_eval.preview_ab")
else:
    _forward.alias(__name__, "duoforge_eval.preview_ab")
