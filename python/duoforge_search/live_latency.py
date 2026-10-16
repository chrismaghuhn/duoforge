"""Moved to duoforge_eval.live_latency (restructure step 8): a forwarder until no session uses the old name.

Imported, this module is duoforge_eval.live_latency itself; run as python -m duoforge_search.live_latency, it runs the new module.
"""
from duoforge_eval import _forward

if __name__ == "__main__":
    _forward.run("duoforge_search.live_latency", "duoforge_eval.live_latency")
else:
    _forward.alias(__name__, "duoforge_eval.live_latency")
