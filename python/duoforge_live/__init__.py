"""The Showdown live adapter (decision 0016): the night run's bot plays
challenges on a Pokémon Showdown server.

Units: data and teams (sheets and ids through the converter's tables),
options (a request's slot options), tracker (the protocol folded into
DuoForge's observation), policy (the network in NumPy), game (one battle's
decisions) and client (websocket, login, challenges). Spec:
docs/superpowers/specs/2026-10-02-showdown-live-design.md.
"""
