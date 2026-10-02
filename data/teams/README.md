# Team registry

One Showdown paste for each team (`<id>.txt`) and an index (`index.json`), shared by the differential loop and the learner.

Ids are stable and never reused, and a file never changes under its id: a correction is a new team with a new id (the old entry gets `superseded_by`). The files are LF (`.gitattributes`), and the `sha256` of the index is that of the text with CRLF turned into LF. Every gender is stated, Level 50, EVs are Stat Points, nothing else is allowed in a set.

The format, the index, the rules and `tools/reference/import_paste.py` (which makes a registry file of any paste) are described in `tools/reference/README.md`, section "The team registry". `python tools/reference/team_registry.py <repo root>` checks the registry.
