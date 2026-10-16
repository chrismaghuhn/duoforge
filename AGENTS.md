# DuoForge agent rules

- DuoForge is an authoritative battle simulation core.
- Correctness comes before optimization.
- Python and bindings must not contain hidden rule implementation.
- Unsupported rules or capacities must fail explicitly; never use silent fallback.
- Do not add heap allocation to future battle hot paths without explicit justification.
- Determinism is a first-class requirement.
- Tests must not be weakened merely to make a change pass.
- Performance claims require measurements.
- A completed task does not authorize unrelated follow-up work.
- Trained weights, checkpoints, league snapshots and run directories are private: never commit them, never upload them as CI artifacts, never publish them (older, nearly as strong checkpoints included) without the owner's explicit decision. Training, evaluation and replay tools write outside the repository.
- Live-play logs contain user and match ids and stay private like weights: never commit them or upload them as CI artifacts; reports may publish aggregate counts only.
- Live play happens only where bots are explicitly welcome (bot arenas such as vgc.bot, or opponents who agreed): never on the official game's ranked ladders, never unannounced on Showdown's human ladders. The project ships an engine and research tools, not tooling to automate the official game client.
