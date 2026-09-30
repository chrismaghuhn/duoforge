# DuoForge architecture boundaries

Status: placeholder only. The details are not frozen in M0.

The long-term design is expected to keep these concerns separate:

- immutable rules/data context;
- mutable per-battle state;
- decision interface;
- execution core;
- information/observation boundary;
- deterministic RNG/replay;
- batch environments;
- ML bindings.

M0 defines no battle-state layout, rules contract, replay schema, observation encoding, or binding ABI. Those details require their own reviewed, implemented, and tested slices.
