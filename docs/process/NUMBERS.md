# Number blocks

Public values, internal ids and decision entries are handed out in blocks so that lanes working in parallel never pick
the same number. The values actually in use are the ones in the headers (`include/duoforge/`, `src/rng/draw.h`,
`src/combat/residual_order.h`, `src/state/battle_internal.h`) and in decision 0015; this file records only who may hand
out what. The HS keeps it current. "Content" is the former lane A; former lane B is inactive and its free ranges are
HS reserve.

| Family | Owner of the free range | Notes |
|---|---|---|
| Decision 0015 entry ids | Content: 5ea-5ez; Fuzz: 5fa-5fm; HS: the rest | 5do-5dq Fuzz (#605), 5dr-5dz Content |
| Decision note numbers | HS assigns each number | |
| RNG draw sites (`src/rng/draw.h`) | HS: 27-31 | 26 Poison Point (Content, #642) |
| Residual kinds (`src/combat/residual_order.h`) | HS | |
| `DUOFORGE_VOLATILE_*` | Content: 17; HS: the rest | |
| `DUOFORGE_PUBLIC_CAUSE_*` | Content: 512, 1024; HS: the rest | |
| Event kinds (6 bits, 52-63) | HS, one at a time | |
| `POSITION_EXT` bits | Content: 0x01000000-0x04000000; HS: the rest | nearly full; more needs a design |
| Internal `DFI_POSFLAG_*` | full (u8) | a new flag needs a tail revision |
| Tail reserve bytes | HS | per-position reserve full since G96 |

A lane reports every value it takes (value, name, branch, PR) to the HS, who adds it to the headers' history in this file
when the PR merges.
