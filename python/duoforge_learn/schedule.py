"""Piecewise-linear schedules over decisions (decision 0017, spec 12.1).

A schedule is a number ("0.01": constant) or points "d0:v0,d1:v1,..." with
d0 = 0 and strictly rising decision counts (suffixes K, M, G: 10^3, 10^6,
10^9); the value interpolates linearly between points and holds after the
last. Counted in decisions, not time, so machine speed and resumes do not
change it.
"""
import math

_SUFFIX = {"K": 10 ** 3, "M": 10 ** 6, "G": 10 ** 9}


def _count(text, whole):
    t = text.strip()
    scale = 1
    if t and t[-1] in _SUFFIX:
        scale, t = _SUFFIX[t[-1]], t[:-1]
    if not t.isdigit():
        raise ValueError(f"schedule {whole!r}: {text!r} is not a decision count")
    return int(t) * scale


def _value(text, whole):
    try:
        v = float(text)
    except ValueError:
        raise ValueError(f"schedule {whole!r}: {text!r} is not a number") from None
    if not math.isfinite(v) or v < 0:
        raise ValueError(f"schedule {whole!r}: value {text!r} must be finite and at least 0")
    return v


class Schedule:
    def __init__(self, points):
        self.points = tuple(points)

    @staticmethod
    def parse(text):
        if ":" not in text:
            return Schedule([(0, _value(text, text))])
        points = []
        for part in text.split(","):
            if part.count(":") != 1:
                raise ValueError(f"schedule {text!r}: {part!r} is not decisions:value")
            d, v = part.split(":")
            points.append((_count(d, text), _value(v, text)))
        if points[0][0] != 0:
            raise ValueError(f"schedule {text!r}: the first point must be at 0 decisions")
        if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
            raise ValueError(f"schedule {text!r}: the decision counts must rise strictly")
        return Schedule(points)

    def __call__(self, decisions):
        pts = self.points
        if decisions >= pts[-1][0]:
            return pts[-1][1]
        for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
            if decisions < d1:
                return v0 + (v1 - v0) * (decisions - d0) / (d1 - d0)
        return pts[-1][1]

    def __str__(self):
        if len(self.points) == 1:
            return repr(self.points[0][1])
        return ",".join(f"{d}:{v!r}" for d, v in self.points)
