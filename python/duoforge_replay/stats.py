"""Stats from the pinned Showdown (M11 spec section 10): Python computes no stat.

StatSource keeps one `node tools/reference/ps_stats.js <checkout> --serve`
process (one per worker) and caches its answers. A stat is Showdown's
Battle.spreadModify of the format, level 50, with Stat Points in the EV
field.
"""
import json
import subprocess

from duoforge_live.data import ROOT


class StatSource:
    def __init__(self, node, ps_dir):
        script = ROOT / "tools" / "reference" / "ps_stats.js"
        self._process = subprocess.Popen([node, str(script), str(ps_dir), "--serve"], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, text=True, encoding="utf-8")
        self._cache = {}

    def stats(self, species, nature, stat_points):
        """[hp, atk, def, spa, spd, spe] of a forme (a Showdown name or id) with a nature and six stat points;
        ValueError for an unknown species or nature."""
        key = (species, nature, tuple(stat_points))
        if key not in self._cache:
            query = {"species": species, "nature": nature, "sp": [int(v) for v in stat_points]}
            self._process.stdin.write(json.dumps([query]) + "\n")
            self._process.stdin.flush()
            answer = self._process.stdout.readline()
            if not answer:
                raise RuntimeError(f"ps_stats.js ended (exit {self._process.poll()})")
            answer = json.loads(answer)
            if isinstance(answer, dict):
                raise ValueError(f"ps_stats.js: {answer['error']}")
            self._cache[key] = answer[0]
        return list(self._cache[key])

    def close(self):
        if self._process.poll() is None:
            self._process.stdin.close()
            self._process.wait(timeout=30)
        self._process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
