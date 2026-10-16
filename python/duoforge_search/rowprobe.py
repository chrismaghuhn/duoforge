"""Moved to duoforge_eval.rowprobe (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.rowprobe itself; run as python -m duoforge_search.rowprobe, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_search.rowprobe", "duoforge_eval.rowprobe")
else:
    _forward.alias(__name__, "duoforge_eval.rowprobe")
