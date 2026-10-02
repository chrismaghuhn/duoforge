# Team registry

One Showdown paste for each team (`<id>.txt`) and an index (`index.json`), shared by the differential loop and the learner.

Ids are stable and never reused, and a file never changes under its id: a correction is a new team with a new id (the old entry gets `superseded_by`). The files are LF (`.gitattributes`), and the `sha256` of the index is that of the text with CRLF turned into LF. Every gender is stated, Level 50, EVs are Stat Points, nothing else is allowed in a set.

The format, the index, the rules and `tools/reference/import_paste.py` (which makes a registry file of any paste) are described in `tools/reference/README.md`, section "The team registry". `python tools/reference/team_registry.py <repo root>` checks the registry.

Teams of the VGCPastes Reg M-C survey of 2026-10-02 have the id `PP_` and the upper case pokepast.es id of their paste (`source.url` is the paste; the survey's own row, `MC<n>`, is in the name and the notes). A re-import on 2026-10-03 (main 0.31.0, steps up to G15) added the teams that had begun to pass; the entries of the first import are untouched. New teams only ever get new ids; `docs/research/expansion/data/registry_blockers.json` lists what keeps the others out.
