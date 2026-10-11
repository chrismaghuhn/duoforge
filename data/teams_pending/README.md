# Pending teams

The pastes of the teams of the VGCPastes Repository that are legal in Reg M-C but need a mechanic the library does not support yet: the engine's setup under the POOL kind refuses them as unsupported. One registry paste for each team (`PP_<upper case pokepast.es id>.txt`, in the form of `data/teams`) and an index (`index.json`) with each team's entry as the registry writes it (name, source link, event, placing, notes with the sheet row and the author, every change `import_paste.py` made, `sha256`) plus its `blockers`.

**This is not the registry.** No run, no pool and no search reads it:

- `tools/reference/import_vgcpastes.py --pending-dir` writes it, and every import writes it whole again: it is the snapshot of the last import. A team whose blockers fell goes into the registry (`--write`, as a `PP_` team with the same id) and leaves this directory; the other way round never happens.
- The honest search does not read it either: its belief is pinned (`data/teams/README.md`, section "The belief of the honest search", owner decision of 2026-10-09). A team of this directory can become a belief source only once it is playable, and only when the owner says so.
- `import_vgcpastes.pending_problems` (test `duoforge.reference.import_vgcpastes`) holds it to its index: an entry for every file and a file for every entry, the `sha256` of each file, no team the registry has, blockers named, and pastes in the registry's form that the converter reads.

The import of 2026-10-09 (`main` with library 0.43.0) left **1,239** teams here; `import_vgcpastes.py --recheck-pending` on `main` at `fac0dab6` (2026-10-11) decided them again, moved the **648** that the engine's setup accepts now into the registry and left **591**, whose `blockers` in `index.json` are the current ones (the first is the first refusal reason; the index date is that of the re-check). A later re-check does the same for the rest. Which mechanics block them, and how many teams each one blocks, is in `docs/research/expansion/data/vgcpastes_pending.json`. Credits: `data/teams/README.md` and `THIRD_PARTY_NOTICES.md`.
