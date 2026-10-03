"""Search on top of the learned policy and value (roadmap M12, decision 0022).

Stage 1 is a one-turn lookahead, measured in the arena (spec
docs/superpowers/specs/2026-10-03-m12-search-stage1-design.md). The engine
copies, reseeds, steps and encodes the leaves; this package chooses the
candidates, builds the table and reduces it, and holds no rule.

matrix and seeds are NumPy-only; lookahead and arena use JAX through
duoforge_learn.policy.Model.
"""
from .errors import SearchError

__all__ = ["SearchError"]
