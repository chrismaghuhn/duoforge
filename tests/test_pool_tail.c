/*
 * duoforge.state.pool_tail (white-box): the POOL state tail of decision 0015 section 7, schema 0x0503 = "v3 + pool
 * tail rev 5".
 *
 * The tail is part of the state under the two POOL kinds only: 348 more bytes (1357 in all) that the encoder, the
 * decoder, the digest, equal, the invariants, clone and copy all carry; under CLOSURE, CLOSURE_DEV, TEAM_C and
 * TEAM_C_DEV it is absent (all zero in memory, not in the encoding) and the states of those kinds are byte for byte
 * what they were: the digests below were taken from the tree before the tail existed. Rev 1 (schema 0x0103, 42
 * bytes) is not decodable: pool states are not frozen, there is no migration. Rev 2 adds the volatile, side and
 * field conditions and the member overrides that decision 0018 declares as view fields; rev 3 the Protect variant; rev 4
 * the move result, the single-turn markers, the hits taken, the ability state, the lock counter, Quick Guard, the second
 * type and the member flags (tail-rev4-proposal.md, cut B); rev 5 (the 60-byte block after the rev 4 part) the Illusion
 * state per side (decision 0026) and the two lane A bytes per position, with 16 reserve bytes. Rev 4 and rev 5 have no
 * mechanic yet, so the tests set their fields by hand, and the rev 5 bytes can only be zero: any other value is refused.
 *
 * The independent oracle is tools/state_model/state_v3_model.py (run with --pool-tail): the envelope, the 348 tail
 * bytes of the example and, for every tail byte, how many of the 255 other values the decoder accepts or refuses
 * with which invariant, are its output.
 */
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

#include "codec/state_codec.h"
#include "core/sha256.h"
#include "data/pool_tables.h"
#include "state/battle_internal.h"
#include "state/closure_member.h"
#include "state/context_internal.h"
#include "state/identity.h"
#include "state/invariants.h"
#include "support/check.h"
#include "support/fixtures.h"
#include "support/pool.h"
#include "support/team_c.h"

/* The model's envelope of a POOL state (tools/state_model, "pool_tail envelope"): magic, kind 2, schema 0x0503,
 * semantics 3, length 1357. */
static const char ENVELOPE_HEX[] = "8944554f0d0a1a0a02000305030000004d050000";
/* The model's tail bytes of the example below ("pool_tail example"). */
static const char TAIL_HEX[] =
    "05d10800d108000001080201030101b10102030205030403050100060301040201030203010014002500000602060603"
    "000000000500000102010100000001000000000000010100000101000000000f000101010000000005002c01050c0012"
    "0100d7005a0112ff00ff00000000010000a6000001000000000000010000000000000000000000000000000000000000"
    "000000000000000001000001040401000300000000000000000001010000000000000000000000040003000000000000"
    "000000000000000000000001030000000000000000000000ff0100090200000000000000010000000100000100000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000700006400000100"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000";

/* The maximum HP of the members 0 and 1 of both sides at the first TURN boundary (the Substitute bound is a quarter
 * of it): the model's LEAD_HP_MAX, asserted below. */
static const unsigned lead_hp_max[2][2] = {{193, 192}, {197, 182}};

/* For every tail byte of the example: how many of the 255 other values give OK, TAIL_SIDE, TAIL_POSITION,
 * TAIL_MEMBER, TAIL_FIELD and TAIL_RESERVED ("pool_tail_sweep_c" of the model). */
enum { SWEEP_COLUMNS = 8 }; /* step G46: TAIL_PARTY is the seventh; step G56: a lock without its locked move is VOLATILE, the eighth */
static const unsigned sweep[DFI_ENC_TAIL_SIZE][SWEEP_COLUMNS] = {
    {5, 0, 0, 0, 250, 0, 0, 0},
    {5, 0, 0, 0, 0, 0, 250, 0},
    {0, 0, 0, 0, 0, 0, 255, 0},
    {0, 0, 0, 0, 0, 0, 255, 0},
    {5, 0, 0, 0, 0, 0, 250, 0},
    {0, 0, 0, 0, 0, 0, 255, 0},
    {0, 0, 0, 0, 0, 0, 255, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {1, 254, 0, 0, 0, 0, 0, 0},
    {8, 247, 0, 0, 0, 0, 0, 0},
    {1, 254, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {2, 253, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {1, 254, 0, 0, 0, 0, 0, 0},
    {23, 232, 0, 0, 0, 0, 0, 0},
    {5, 0, 250, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {5, 0, 250, 0, 0, 0, 0, 0},
    {4, 0, 251, 0, 0, 0, 0, 0},
    {4, 0, 251, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {4, 0, 251, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {7, 0, 248, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {48, 0, 207, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {254, 0, 1, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {15, 0, 240, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {6, 0, 249, 0, 0, 0, 0, 0},
    {6, 0, 249, 0, 0, 0, 0, 0},
    {2, 0, 252, 0, 0, 0, 0, 1},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {5, 0, 250, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {5, 0, 250, 0, 0, 0, 0, 0},
    {4, 0, 251, 0, 0, 0, 0, 0},
    {4, 0, 251, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {48, 0, 207, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {15, 0, 240, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {6, 0, 249, 0, 0, 0, 0, 0},
    {6, 0, 249, 0, 0, 0, 0, 0},
    {2, 0, 252, 0, 0, 0, 0, 1},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {215, 0, 0, 40, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {90, 0, 0, 165, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {18, 0, 0, 237, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {19, 0, 0, 236, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {215, 0, 0, 40, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {90, 0, 0, 165, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {18, 0, 0, 237, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {19, 0, 0, 236, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {1, 254, 0, 0, 0, 0, 0, 0},
    {8, 247, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {1, 254, 0, 0, 0, 0, 0, 0},
    {2, 253, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {1, 254, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {5, 0, 250, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {5, 0, 250, 0, 0, 0, 0, 0},
    {4, 0, 251, 0, 0, 0, 0, 0},
    {4, 0, 251, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {49, 0, 206, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {15, 0, 240, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {6, 0, 249, 0, 0, 0, 0, 0},
    {6, 0, 249, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {5, 0, 250, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {5, 0, 250, 0, 0, 0, 0, 0},
    {4, 0, 251, 0, 0, 0, 0, 0},
    {4, 0, 251, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {7, 0, 248, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {2, 0, 253, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {3, 0, 252, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {45, 0, 210, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {15, 0, 240, 0, 0, 0, 0, 0},
    {1, 0, 254, 0, 0, 0, 0, 0},
    {6, 0, 249, 0, 0, 0, 0, 0},
    {6, 0, 249, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {215, 0, 0, 40, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {18, 0, 0, 237, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {19, 0, 0, 236, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {215, 0, 0, 40, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {18, 0, 0, 237, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {19, 0, 0, 236, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {255, 0, 0, 0, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {167, 0, 0, 88, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {0, 0, 0, 255, 0, 0, 0, 0},
    {1, 0, 0, 254, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 255, 0, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 255, 0, 0, 0, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
    {0, 0, 0, 0, 0, 255, 0, 0},
};

/* Digests of the states of the four other kinds (Team A against B, or against Team C), at creation, after team
 * selection and after the first turn: taken from the tree before the POOL tail existed. */
static const struct {
    const char *kind;
    const char *point;
    const char *hex;
} before_the_tail[] = {
    {"CLOSURE", "created", "5af24be1c7439f0dd611e9e3b78711f007945abbe06e3637d4f163088232656c"},
    {"CLOSURE", "teams", "0b3fc1af884ad1255b177d27105ded8bbb86aefbc9190448975f21788b43fa4c"},
    {"CLOSURE", "turn1", "b3b20b79bcbbf1f6c989131f9bd439a94d09755d25d7fe7e3015b73d089ada80"},
    {"CLOSURE_DEV", "created", "eb90a7f7bf3057d0f43efeb01dd6229b26ee9fb8b83d63b66581204990b81c0c"},
    {"CLOSURE_DEV", "teams", "41a4977c5a594fa3ff3fcd41307e824030bbe97970457b28a1fc5be4197a7898"},
    {"CLOSURE_DEV", "turn1", "0859fe52c16fffe0eea65d6d0ca82725e4a28555d6a9fb22d2e445adfcd0d6e7"},
    {"TEAM_C", "created", "629f0ce576f616dbaf12e6d6e63fbfb9c4a09c973a1145aaaa06afa10a8ef629"},
    {"TEAM_C", "teams", "455cd10551e6c1a7e0a9c79b916eade004844b7166f5d06fa3559a913e052d9a"},
    {"TEAM_C", "turn1", "74108fd1935f4e516b2636d391535dd9aeeaea3f55a46c7587c26255a4862371"},
    {"TEAM_C_DEV", "created", "c85ba8c7e50aa37d9426d1a619bde9b5101f63db54d05b6517cf74ca53d7d6d1"},
    {"TEAM_C_DEV", "teams", "edb5bdf6376eee8c41535e75f6f5cc5fe1869aa54fd22f1926f7c1995676f722"},
    {"TEAM_C_DEV", "turn1", "8c1d956b020a13e14be5d7b60681f43ba9dc729753c94dd8843ca24627dd1430"}
};

static void team_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_TEAM_SELECTION;
        c->pick_count = 4u;
        for (uint32_t i = 0u; i < 4u; ++i) {
            c->picks[i] = (uint8_t)i;
        }
    }
}

/* Turn 1 of the reference teams' leads (valid for any items). */
static void turn_bundle(duoforge_decision_bundle *bd, const duoforge_battle *b)
{
    static const uint8_t plan[2][2][2] = {{{0u, 2u}, {0u, 3u}}, {{0u, 0u}, {0u, 1u}}}; /* move slot, target */
    memset(bd, 0, sizeof *bd);
    bd->epoch = b->request_epoch;
    bd->response_mask = 3u;
    for (uint32_t side = 0u; side < 2u; ++side) {
        duoforge_side_choice *c = &bd->responses[side];
        c->epoch = b->request_epoch;
        c->side = (uint8_t)side;
        c->kind = (uint8_t)DUOFORGE_CHOICE_SLOTS;
        for (uint32_t slot = 0u; slot < 2u; ++slot) {
            c->slots[slot].kind = (uint8_t)DUOFORGE_SLOT_MOVE;
            c->slots[slot].move_slot = plan[side][slot][0];
            c->slots[slot].target = plan[side][slot][1];
        }
    }
}

static void step_ok(df_test *t, const duoforge_context *ctx, duoforge_battle *b, const duoforge_decision_bundle *bd,
                    const char *what)
{
    duoforge_step_result res;
    if (!DF_CHECK(t, duoforge_battle_step(ctx, b, bd, &res) == DUOFORGE_OK)) {
        fprintf(stderr, "  step %s failed\n", what);
    }
}

/* A battle of `ctx` at the first TURN boundary: Team A against B, or against Team C for the TEAM_C kinds. */
static duoforge_battle *turn_battle(df_test *t, const duoforge_context *ctx, bool team_c)
{
    duoforge_battle_setup s;
    df_setup_teams(&s);
    if (team_c) {
        df_put_team_c(&s.sides[1]);
    }
    duoforge_battle *b = df_make_battle(ctx, &s);
    duoforge_decision_bundle bd;
    team_bundle(&bd, b);
    step_ok(t, ctx, b, &bd, "team selection");
    return b;
}

/* The example of the model: a value in every field that a state can hold, valid for the leads 0 and 1 of both sides.
 * Flat positions: side 0 is 0 and 1, side 1 is 2 and 3. The toxic stages stay zero: no state has the status they
 * need (DFI_TAIL_TOXIC_STATUS). */
static void set_example_tail(duoforge_battle *b)
{
    /* step G46: the party order is the pick order of the team selection, not part of the example: kept. */
    uint8_t party[DUOFORGE_SIDE_COUNT][DFI_PARTY_BYTES_PER_SIDE];
    memcpy(party, b->tail.party_order, sizeof party);
    memset(&b->tail, 0, sizeof b->tail);
    /* step G56: a lockedmove needs its locked move in the active slot (the invariant of the lock), here the leads' first move. */
    b->sides[0].positions[0].locked_move = 1u;
    b->sides[0].positions[1].locked_move = 1u;
    memcpy(b->tail.party_order, party, sizeof party);
    b->tail.gravity_turns = 5u;
    dfi_tail_side *a = &b->tail.sides[0];
    a->wide_guard = 1u;
    a->aurora_veil_turns = 8u;
    a->toxic_spikes = 2u;
    a->stealth_rock = 1u;
    a->spikes = 3u;
    a->sticky_web = 1u;
    a->quick_guard = 1u;
    /* all four hazards up, created in the order Spikes, Stealth Rock, Sticky Web, Toxic Spikes */
    a->hazard_order = (uint8_t)(DFI_HAZARD_SPIKES | (DFI_HAZARD_STEALTH_ROCK << 2u) | (DFI_HAZARD_STICKY_WEB << 4u) |
                                (DFI_HAZARD_TOXIC_SPIKES << 6u));
    a->positions[0] = (dfi_tail_pos){.substitute_hp = 20u, .trap_move = 37u, .last_move = 1u, .encore_slot = 2u,
                                     .encore_turns = 3u, .throat_chop_turns = 2u, .heal_block_turns = 5u,
                                     .perish = 3u, .taunt_turns = 4u, .disable_slot = 3u, .disable_turns = 5u,
                                     .imprison = 1u, .trap_turns = 6u, .trap_source = 3u, .trap_band = 1u,
                                     .leech_seed_source = 4u, .yawn_turns = 2u, .focus_energy = 1u,
                                     .stockpile = 3u, .stockpile_def = 2u, .stockpile_spd = 3u, .charge = 1u,
                                     .move_result = 6u, .single_turn = DFI_SINGLE_TURN_ROOST, .hits_taken = 6u,
                                     .ability_state = 6u, .lock_turns = 3u};
    a->positions[1] = (dfi_tail_pos){.substitute_hp = 1u, .last_move = 5u, .throat_chop_turns = 1u,
                                     .heal_block_turns = 2u, .perish = 1u, .taunt_turns = 1u, .must_recharge = 1u,
                                     .stockpile = 1u, .stockpile_def = 1u, .glaive_rush = 1u, .move_result = 15u,
                                     .hits_taken = 1u, .ability_state = 1u, .lock_turns = 1u};
    a->ability_now[0] = 5u;
    a->ability_now[1] = DFI_POOL_ABILITY_COUNT;
    a->forme_now[0] = 300u;
    a->forme_now[1] = DFI_POOL_FORME_COUNT;
    a->forme_now[2] = 1u;
    a->soak_type[0] = 5u;
    a->soak_type[1] = 18u;
    a->item_now[0] = 12u;
    a->item_now[1] = DFI_TAIL_ITEM_NONE;
    a->item_now[2] = DFI_POOL_ITEM_COUNT;
    a->item_now[3] = 1u;
    a->type2[0] = 18u;
    a->type2[1] = DFI_TAIL_TYPE2_TYPELESS;
    a->member_flags[0] = DFI_TAIL_MEMBER_FLAG_HERO_SHOWN;
    a->member_flags[2] = DFI_TAIL_MEMBER_FLAG_HERO_SHOWN;
    dfi_tail_side *c = &b->tail.sides[1];
    c->spikes = 1u;
    c->hazard_order = (uint8_t)DFI_HAZARD_SPIKES;
    c->positions[0] = (dfi_tail_pos){.last_move = 4u, .encore_slot = 4u, .encore_turns = 1u, .heal_block_turns = 3u,
                                     .leech_seed_source = 1u, .yawn_turns = 1u, .move_result = 4u, .hits_taken = 3u};
    c->positions[1] = (dfi_tail_pos){.trap_move = DFI_POOL_MOVE_COUNT, .trap_turns = 1u, .trap_source = 3u,
                                     .move_result = 9u, .single_turn = DFI_SINGLE_TURN_ROOST};
    c->ability_now[0] = 1u;
    c->forme_now[5] = 7u;
    c->soak_type[0] = 1u;
    c->item_now[5] = 100u;
    c->type2[0] = 1u;
    c->member_flags[5] = DFI_TAIL_MEMBER_FLAG_HERO_SHOWN;
}

static void digest_of(df_test *t, const duoforge_context *ctx, const duoforge_battle *b, uint8_t out[DUOFORGE_DIGEST_SIZE])
{
    DF_CHECK(t, duoforge_battle_digest(ctx, b, out) == DUOFORGE_OK);
}

static void check_hex(df_test *t, const uint8_t *got, const char *hex, size_t n, const char *what)
{
    uint8_t want[DFI_STATE_ENCODED_MAX];
    DF_CHECK(t, n <= sizeof want && df_hex_to_bytes(hex, want, n));
    DF_CHECK_BYTES(t, got, want, n, what);
}

/* The decode of `bytes` under `ctx` through both entry points: they agree, and nothing is written on failure. */
static duoforge_status decode_both(df_test *t, const duoforge_context *ctx, const uint8_t *bytes, size_t size,
                                   dfi_invariant *inv)
{
    uint8_t *in = df_heap_copy(bytes, size);
    duoforge_battle *made = NULL;
    const duoforge_status s1 = duoforge_battle_create_decoded(ctx, in, size, &made);
    duoforge_battle_destroy(made);
    duoforge_battle tmp;
    memset(&tmp, 0xA5, sizeof tmp);
    dfi_invariant got = DFI_INV_NONE;
    const duoforge_status s2 = dfi_decode_state(ctx, in, size, &tmp, &got);
    DF_CHECK(t, s1 == s2);
    df_free(in);
    if (inv != NULL) {
        *inv = got;
    }
    return s2;
}

/* The bytes of the tail of a state in memory (the structs have no padding: every field is a byte or an aligned u16). */
static uint8_t *tail_byte(duoforge_battle *b, size_t i)
{
    return &((uint8_t *)&b->tail)[i];
}

static const char *inv_name(dfi_invariant inv)
{
    return dfi_invariant_name(inv);
}

/* Patches the envelope of an artifact: schema and total length. */
static void set_envelope(uint8_t *bytes, uint32_t schema, uint32_t length)
{
    bytes[DFI_ENVELOPE_SCHEMA_OFF] = (uint8_t)(schema & 0xFFu);
    bytes[DFI_ENVELOPE_SCHEMA_OFF + 1u] = (uint8_t)((schema >> 8u) & 0xFFu);
    bytes[DFI_ENVELOPE_LENGTH_OFF] = (uint8_t)(length & 0xFFu);
    bytes[DFI_ENVELOPE_LENGTH_OFF + 1u] = (uint8_t)((length >> 8u) & 0xFFu);
    bytes[DFI_ENVELOPE_LENGTH_OFF + 2u] = 0u;
    bytes[DFI_ENVELOPE_LENGTH_OFF + 3u] = 0u;
}

/* One single setting for the digest test: up to four writes (an offset within the tail, 1 or 2 bytes, little
 * endian) that make one field nonzero together with whatever it needs to be valid on its own (a pair that is zero
 * together, a source that is another position). */
typedef struct tail_write {
    size_t off;
    unsigned size; /* 0: not used */
    unsigned value;
} tail_write;
typedef struct tail_setting {
    const char *what;
    tail_write w[4];
} tail_setting;

static void put_write(uint8_t *tail, const tail_write *w)
{
    if (w->size == 0u) {
        return;
    }
    tail[w->off] = (uint8_t)(w->value & 0xFFu);
    if (w->size == 2u) {
        tail[w->off + 1u] = (uint8_t)((w->value >> 8u) & 0xFFu);
    }
}

#define W1(off, v) {(off), 1u, (v)}
#define W2(off, v) {(off), 2u, (v)}
#define NO_WRITE {0u, 0u, 0u}

/* Every field of the tail that a state can hold on its own, one at a time: 167 settings (the toxic stage is not one:
 * it needs a status that no state has; Rage Powder's single-turn bit is not one either, it needs the Follow Me flag). */
enum { SETTINGS_MAX = 200 };
static size_t build_settings(tail_setting *out)
{
    size_t n = 0u;
    out[n++] = (tail_setting){"gravity", {W1(DFI_ENC_TAIL_FIELD_GRAVITY_OFF, 1u), NO_WRITE, NO_WRITE}};
    for (uint32_t s = 0u; s < 2u; ++s) {
        const size_t so = DFI_ENC_TAIL_SIDES_OFF + s * DFI_ENC_TAIL_SIDE_SIZE;
        out[n++] = (tail_setting){"wide_guard", {W1(so + DFI_ENC_TAIL_WIDE_GUARD_OFF, 1u), NO_WRITE, NO_WRITE}};
        out[n++] = (tail_setting){"aurora_veil", {W1(so + DFI_ENC_TAIL_AURORA_VEIL_OFF, 1u), NO_WRITE, NO_WRITE}};
        /* a hazard that is up has its kind in the first slot of hazard_order (Stealth Rock is code 0, so it needs no write) */
        out[n++] = (tail_setting){"toxic_spikes", {W1(so + DFI_ENC_TAIL_TOXIC_SPIKES_OFF, 1u),
                                                   W1(so + DFI_ENC_TAIL_HAZARD_ORDER_OFF, DFI_HAZARD_TOXIC_SPIKES), NO_WRITE}};
        out[n++] = (tail_setting){"stealth_rock", {W1(so + DFI_ENC_TAIL_STEALTH_ROCK_OFF, 1u), NO_WRITE, NO_WRITE}};
        out[n++] = (tail_setting){"spikes", {W1(so + DFI_ENC_TAIL_SPIKES_OFF, 1u),
                                             W1(so + DFI_ENC_TAIL_HAZARD_ORDER_OFF, DFI_HAZARD_SPIKES), NO_WRITE}};
        out[n++] = (tail_setting){"sticky_web", {W1(so + DFI_ENC_TAIL_STICKY_WEB_OFF, 1u),
                                                 W1(so + DFI_ENC_TAIL_HAZARD_ORDER_OFF, DFI_HAZARD_STICKY_WEB), NO_WRITE}};
        /* two hazards, each order: Spikes then Stealth Rock (1 | 0 << 2), Stealth Rock then Spikes (0 | 1 << 2) */
        out[n++] = (tail_setting){"hazard_order_spikes_first", {W1(so + DFI_ENC_TAIL_SPIKES_OFF, 1u),
                                                                W1(so + DFI_ENC_TAIL_STEALTH_ROCK_OFF, 1u),
                                                                W1(so + DFI_ENC_TAIL_HAZARD_ORDER_OFF, DFI_HAZARD_SPIKES)}};
        out[n++] = (tail_setting){"hazard_order_stealth_rock_first", {W1(so + DFI_ENC_TAIL_SPIKES_OFF, 1u),
                                                                      W1(so + DFI_ENC_TAIL_STEALTH_ROCK_OFF, 1u),
                                                                      W1(so + DFI_ENC_TAIL_HAZARD_ORDER_OFF,
                                                                         DFI_HAZARD_STEALTH_ROCK | (DFI_HAZARD_SPIKES << 2u))}};
        out[n++] = (tail_setting){"quick_guard", {W1(so + DFI_ENC_TAIL_QUICK_GUARD_OFF, 1u), NO_WRITE, NO_WRITE}};
        for (uint32_t p = 0u; p < 2u; ++p) {
            const size_t po = so + DFI_ENC_TAIL_POS_OFF + p * DFI_ENC_TAIL_POS_SIZE;
            const unsigned other = 2u * s + p == 3u ? 1u : 4u; /* a source that is another position */
            out[n++] = (tail_setting){"last_move", {W1(po + DFI_ENC_TAIL_POS_LAST_MOVE_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"encore", {W1(po + DFI_ENC_TAIL_POS_ENCORE_SLOT_OFF, 1u),
                                                 W1(po + DFI_ENC_TAIL_POS_ENCORE_TURNS_OFF, 1u), NO_WRITE}};
            out[n++] = (tail_setting){"throat_chop", {W1(po + DFI_ENC_TAIL_POS_THROAT_CHOP_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"heal_block", {W1(po + DFI_ENC_TAIL_POS_HEAL_BLOCK_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"perish", {W1(po + DFI_ENC_TAIL_POS_PERISH_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"taunt", {W1(po + DFI_ENC_TAIL_POS_TAUNT_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"disable", {W1(po + DFI_ENC_TAIL_POS_DISABLE_SLOT_OFF, 1u),
                                                  W1(po + DFI_ENC_TAIL_POS_DISABLE_TURNS_OFF, 1u), NO_WRITE}};
            out[n++] = (tail_setting){"imprison", {W1(po + DFI_ENC_TAIL_POS_IMPRISON_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"must_recharge", {W1(po + DFI_ENC_TAIL_POS_MUST_RECHARGE_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"trap", {W1(po + DFI_ENC_TAIL_POS_TRAP_TURNS_OFF, 1u),
                                               W1(po + DFI_ENC_TAIL_POS_TRAP_SOURCE_OFF, other),
                                               W2(po + DFI_ENC_TAIL_POS_TRAP_MOVE_OFF, 1u)}};
            out[n++] = (tail_setting){"trap_band", {W1(po + DFI_ENC_TAIL_POS_TRAP_TURNS_OFF, 1u),
                                                    W1(po + DFI_ENC_TAIL_POS_TRAP_SOURCE_OFF, other),
                                                    W2(po + DFI_ENC_TAIL_POS_TRAP_MOVE_OFF, 1u),
                                                    W1(po + DFI_ENC_TAIL_POS_TRAP_BAND_OFF, 1u)}};
            out[n++] = (tail_setting){"leech_seed", {W1(po + DFI_ENC_TAIL_POS_LEECH_SEED_OFF, other), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"yawn", {W1(po + DFI_ENC_TAIL_POS_YAWN_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"focus_energy", {W1(po + DFI_ENC_TAIL_POS_FOCUS_ENERGY_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"stockpile", {W1(po + DFI_ENC_TAIL_POS_STOCKPILE_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"stockpile_def", {W1(po + DFI_ENC_TAIL_POS_STOCKPILE_OFF, 1u),
                                                        W1(po + DFI_ENC_TAIL_POS_STOCKPILE_DEF_OFF, 1u), NO_WRITE}};
            out[n++] = (tail_setting){"stockpile_spd", {W1(po + DFI_ENC_TAIL_POS_STOCKPILE_OFF, 1u),
                                                        W1(po + DFI_ENC_TAIL_POS_STOCKPILE_SPD_OFF, 1u), NO_WRITE}};
            out[n++] = (tail_setting){"charge", {W1(po + DFI_ENC_TAIL_POS_CHARGE_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"glaive_rush", {W1(po + DFI_ENC_TAIL_POS_GLAIVE_RUSH_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"substitute_hp", {W2(po + DFI_ENC_TAIL_POS_SUBSTITUTE_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"move_result", {W1(po + DFI_ENC_TAIL_POS_MOVE_RESULT_OFF, 9u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"single_turn", {W1(po + DFI_ENC_TAIL_POS_SINGLE_TURN_OFF, DFI_SINGLE_TURN_ROOST), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"hits_taken", {W1(po + DFI_ENC_TAIL_POS_HITS_TAKEN_OFF, 1u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"ability_state", {W1(po + DFI_ENC_TAIL_POS_ABILITY_STATE_OFF, 1u), NO_WRITE, NO_WRITE}};
        }
        for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
            const size_t mo = so + DFI_ENC_TAIL_MEMBER_OFF + m * DFI_ENC_TAIL_MEMBER_SIZE;
            out[n++] = (tail_setting){"forme_now", {W2(mo + DFI_ENC_TAIL_MEMBER_FORME_OFF, 2u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"item_now", {W1(mo + DFI_ENC_TAIL_MEMBER_ITEM_OFF, 3u), NO_WRITE, NO_WRITE}};
            out[n++] = (tail_setting){"member_flags", {W1(mo + DFI_ENC_TAIL_MEMBER_FLAGS_OFF, DFI_TAIL_MEMBER_FLAG_HERO_SHOWN), NO_WRITE, NO_WRITE}};
            if (m < 2u) {
                out[n++] = (tail_setting){"type2", {W1(mo + DFI_ENC_TAIL_MEMBER_TYPE2_OFF, DFI_TAIL_TYPE2_TYPELESS), NO_WRITE, NO_WRITE}};
                out[n++] = (tail_setting){"ability_now", {W2(mo + DFI_ENC_TAIL_MEMBER_ABILITY_OFF, 1u), NO_WRITE, NO_WRITE}};
                out[n++] = (tail_setting){"soak_type", {W1(mo + DFI_ENC_TAIL_MEMBER_SOAK_OFF, 1u), NO_WRITE, NO_WRITE}};
            }
        }
    }
    return n;
}

/* The cases of the in-memory invariant test: a mutation of a tail of the first TURN boundary of a POOL battle. The
 * first lead of side 0 is `p0`, `ts` the tail of that side. A case with `short_side` uses the battle whose side 1
 * lead has two moves. */
typedef void (*tail_mutation)(duoforge_battle *y, dfi_tail_side *ts, dfi_tail_pos *p0);
typedef struct tail_case {
    const char *what;
    dfi_invariant inv;
    bool short_side;
    tail_mutation apply;
} tail_case;

#define MUT(name, ...)                                                                                                \
    static void name(duoforge_battle *y, dfi_tail_side *ts, dfi_tail_pos *p0)                                          \
    {                                                                                                                  \
        (void)y;                                                                                                       \
        (void)ts;                                                                                                      \
        (void)p0;                                                                                                      \
        __VA_ARGS__;                                                                                                   \
    }

MUT(m_gravity, y->tail.gravity_turns = 6u)
MUT(m_field_pad, y->tail.field_pad = 1u)
/* step G46, party_order (the brought members are 0..3 on both sides, the leads 0 and 1): */
MUT(m_party_dup, dfi_party_put(&y->tail, 0u, 1u, dfi_party_entry(&y->tail, 0u, 0u)))  /* the lead twice */
MUT(m_party_hole, dfi_party_put(&y->tail, 1u, 0u, 0u))                              /* an empty lead */
MUT(m_party_bench_filled, dfi_party_put(&y->tail, 0u, 4u, 5u))                      /* a fifth entry for four brought */
MUT(m_party_not_brought, dfi_party_put(&y->tail, 0u, 3u, 6u))                       /* roster 5, not brought */
MUT(m_party_bits_high, y->tail.party_order[1][2] = 0x04u)                           /* bit 18, above the entries */
MUT(m_wide_guard, ts->wide_guard = 2u)
MUT(m_aurora, ts->aurora_veil_turns = 9u)
MUT(m_toxic_spikes, ts->toxic_spikes = 3u)
MUT(m_stealth_rock, ts->stealth_rock = 2u)
MUT(m_spikes, ts->spikes = 4u)
MUT(m_sticky_web, ts->sticky_web = 2u)
MUT(m_quick_guard, ts->quick_guard = 2u)
MUT(m_hazard_no_hazard, ts->hazard_order = 1u) /* nothing is up: the byte is 0 */
MUT(m_hazard_missing_kind, {
    ts->spikes = 1u; /* Spikes is up and its slot says Stealth Rock (code 0) */
    ts->hazard_order = 0u;
})
MUT(m_hazard_duplicate, {
    ts->spikes = 1u;
    ts->stealth_rock = 1u;
    ts->hazard_order = (uint8_t)(DFI_HAZARD_SPIKES | (DFI_HAZARD_SPIKES << 2u)); /* Spikes twice */
})
MUT(m_hazard_slot_beyond, {
    ts->spikes = 1u;
    ts->hazard_order = (uint8_t)(DFI_HAZARD_SPIKES | (DFI_HAZARD_STICKY_WEB << 2u)); /* a second slot with one kind up */
})
MUT(m_hazard_absent_kind, {
    ts->spikes = 1u;
    ts->sticky_web = 1u;
    ts->hazard_order = (uint8_t)(DFI_HAZARD_SPIKES | (DFI_HAZARD_TOXIC_SPIKES << 2u)); /* Toxic Spikes is not up */
})
MUT(m_hazard_dropped_gap, {
    ts->spikes = 1u;
    ts->sticky_web = 1u;
    ts->toxic_spikes = 1u;
    ts->hazard_order = (uint8_t)(DFI_HAZARD_SPIKES | (DFI_HAZARD_STICKY_WEB << 2u)); /* three kinds up, two slots */
})
MUT(m_hazard_extra_slot, {
    ts->stealth_rock = 1u;
    ts->hazard_order = (uint8_t)(DFI_HAZARD_STEALTH_ROCK | (DFI_HAZARD_SPIKES << 2u)); /* a slot after the only kind */
})
MUT(m_last_above, p0->last_move = 6u)
MUT(m_last_beyond, p0->last_move = 3u) /* the short lead has two moves */
MUT(m_encore_beyond, {
    p0->encore_slot = 3u;
    p0->encore_turns = 1u;
})
MUT(m_encore_no_turns, p0->encore_slot = 1u)
MUT(m_encore_no_slot, p0->encore_turns = 1u)
MUT(m_encore_slot5, {
    p0->encore_slot = 5u;
    p0->encore_turns = 1u;
})
MUT(m_encore_turns5, {
    p0->encore_slot = 1u;
    p0->encore_turns = 5u;
})
MUT(m_throat, p0->throat_chop_turns = 3u)
MUT(m_heal_block, p0->heal_block_turns = 6u)
MUT(m_perish, p0->perish = 5u)
MUT(m_taunt, p0->taunt_turns = 5u)
MUT(m_yawn, p0->yawn_turns = 3u)
MUT(m_disable_slot5, {
    p0->disable_slot = 5u;
    p0->disable_turns = 1u;
})
MUT(m_disable_beyond, {
    p0->disable_slot = 3u; /* the short lead has two moves */
    p0->disable_turns = 1u;
})
MUT(m_disable_no_turns, p0->disable_slot = 1u)
MUT(m_disable_no_slot, p0->disable_turns = 1u)
MUT(m_disable_turns6, {
    p0->disable_slot = 1u;
    p0->disable_turns = 6u;
})
MUT(m_imprison, p0->imprison = 2u)
MUT(m_recharge, p0->must_recharge = 2u)
MUT(m_focus, p0->focus_energy = 2u)
MUT(m_charge, p0->charge = 2u)
MUT(m_glaive, p0->glaive_rush = 2u)
MUT(m_protect_above, {
    y->sides[0].positions[0].flags = (uint8_t)(y->sides[0].positions[0].flags | DFI_VOL_PROTECT);
    p0->protect_kind = 2u;
})
MUT(m_protect_no_volatile, p0->protect_kind = 1u) /* the volatile is down */
MUT(m_move_result_high, p0->move_result = 0x10u) /* bits 4-7 are zero */
MUT(m_single_turn_bit2, p0->single_turn = 4u)
MUT(m_rage_no_follow_me, p0->single_turn = DFI_SINGLE_TURN_RAGE_POWDER) /* the Follow Me flag is down */
MUT(m_hits_taken7, p0->hits_taken = 7u)
MUT(m_ability_state7, p0->ability_state = 7u)
MUT(m_lock_turns4, p0->lock_turns = 4u)
MUT(m_lock_no_move, p0->lock_turns = 2u) /* a lock whose move is not in the slot (step G56): the body has none here */
MUT(m_substitute_above, p0->substitute_hp = (uint16_t)(y->sides[0].members[y->sides[0].positions[0].occupant].hp_max / 4u + 1u))
MUT(m_trap_turns_only, p0->trap_turns = 1u)
MUT(m_trap_source_only, p0->trap_source = 2u)
MUT(m_trap_move_only, p0->trap_move = 1u)
MUT(m_trap_no_move, {
    p0->trap_turns = 1u;
    p0->trap_source = 2u;
})
MUT(m_trap_no_source, {
    p0->trap_turns = 1u;
    p0->trap_move = 1u;
})
MUT(m_trap_turns9, {
    p0->trap_turns = 9u;
    p0->trap_source = 2u;
    p0->trap_move = 1u;
})
MUT(m_trap_source5, {
    p0->trap_turns = 1u;
    p0->trap_source = 5u;
    p0->trap_move = 1u;
})
MUT(m_trap_own, {
    p0->trap_turns = 1u;
    p0->trap_source = 1u; /* flat position 0 + 1: the occupant itself */
    p0->trap_move = 1u;
})
MUT(m_trap_move_beyond, {
    p0->trap_turns = 1u;
    p0->trap_source = 2u;
    p0->trap_move = DFI_POOL_MOVE_COUNT + 1u;
})
MUT(m_trap_band2, {
    p0->trap_turns = 1u;
    p0->trap_source = 2u;
    p0->trap_move = 1u;
    p0->trap_band = 2u;
})
MUT(m_trap_band_alone, p0->trap_band = 1u)
MUT(m_leech5, p0->leech_seed_source = 5u)
MUT(m_leech_own, p0->leech_seed_source = 1u)
MUT(m_stockpile4, p0->stockpile = 4u)
MUT(m_stockpile_def, {
    p0->stockpile = 1u;
    p0->stockpile_def = 2u;
})
MUT(m_stockpile_spd, p0->stockpile_spd = 1u) /* no layers */
MUT(m_empty_pos, {
    dfi_slot_clear(&y->sides[0].positions[1]);
    y->sides[0].requested_slots = 1u; /* the occupied mask */
    ts->positions[1].heal_block_turns = 1u;
})
MUT(m_empty_pos_substitute, {
    dfi_slot_clear(&y->sides[0].positions[1]);
    y->sides[0].requested_slots = 1u;
    ts->positions[1].substitute_hp = 1u;
})
MUT(m_fainted_pos, {
    y->sides[0].members[1].hp = 0u;
    df_knowledge_refresh_active(y);
    ts->positions[1].throat_chop_turns = 1u;
})
MUT(m_fainted_pos_taunt, {
    y->sides[0].members[1].hp = 0u;
    df_knowledge_refresh_active(y);
    ts->positions[1].taunt_turns = 1u;
})
MUT(m_soak19, ts->soak_type[0] = 19u)
MUT(m_soak_reserve, ts->soak_type[3] = 1u)
MUT(m_soak_fainted, {
    y->sides[0].members[1].hp = 0u;
    df_knowledge_refresh_active(y);
    ts->soak_type[1] = 1u;
})
MUT(m_soak_mega, {
    (void)dfi_closure_member_mega_evolve(&y->sides[0].members[1]);
    y->sides[0].mega_used = 1u;
    y->sides[1].knowledge[1].revealed = (uint8_t)(y->sides[1].knowledge[1].revealed | DFI_REVEALED_MEGA);
    ts->soak_type[1] = 1u;
})
MUT(m_soak_left, ts->soak_type[2] = 1u) /* member 2 is a reserve */
MUT(m_ability_above, ts->ability_now[0] = DFI_POOL_ABILITY_COUNT + 1u)
MUT(m_ability_reserve, ts->ability_now[2] = 1u)
MUT(m_ability_fainted, {
    y->sides[0].members[1].hp = 0u;
    df_knowledge_refresh_active(y);
    ts->ability_now[1] = 1u;
})
MUT(m_forme_above, ts->forme_now[0] = DFI_POOL_FORME_COUNT + 1u)
MUT(m_item_above, ts->item_now[0] = DFI_POOL_ITEM_COUNT + 1u)
MUT(m_item_254, ts->item_now[3] = 254u)
MUT(m_toxic_no_status, ts->toxic_stage[0] = 1u) /* no state has the status Tox yet */
MUT(m_toxic_16, ts->toxic_stage[0] = 16u)
MUT(m_toxic_reserve, ts->toxic_stage[3] = 1u)
MUT(m_type2_19, ts->type2[0] = 19u)
MUT(m_type2_254, ts->type2[0] = 254u)
MUT(m_type2_reserve, ts->type2[3] = 1u)
MUT(m_type2_fainted, {
    y->sides[0].members[1].hp = 0u;
    df_knowledge_refresh_active(y);
    ts->type2[1] = 1u;
})
MUT(m_member_flags2, ts->member_flags[0] = 2u)
/* rev 5 (decision 0026; nothing writes these yet): every byte of the Illusion state and of the two position bytes is refused */
MUT(m_ill_shown, ts->illusion.shown = 1u)
MUT(m_ill_override, ts->illusion.override[3] = 1u)
MUT(m_ill_snapshot, ts->illusion.snapshot[8] = 1u)
MUT(m_ill_pending, ts->illusion.pending[0] = 1u)
MUT(m_slot_pending, p0->slot_pending = 1u)
MUT(m_future_sight, p0->future_sight = 1u)
MUT(m_member_flags_high, ts->member_flags[3] = 0x80u)
/* Valid: the edges. */
MUT(v_struggle, p0->last_move = 5u)
MUT(v_encore_edge, {
    p0->encore_slot = 4u;
    p0->encore_turns = 1u;
})
MUT(v_maxima, {
    y->tail.gravity_turns = 5u;
    y->sides[0].positions[0].locked_move = 1u; /* the lock of the lead's position needs its move (step G56) */
    *ts = (dfi_tail_side){.wide_guard = 1u, .aurora_veil_turns = 8u, .toxic_spikes = 2u, .stealth_rock = 1u,
                          .spikes = 3u, .sticky_web = 1u, .quick_guard = 1u,
                          .hazard_order = (uint8_t)(DFI_HAZARD_TOXIC_SPIKES | (DFI_HAZARD_STICKY_WEB << 2u) |
                                                    (DFI_HAZARD_SPIKES << 4u) | (DFI_HAZARD_STEALTH_ROCK << 6u))};
    ts->positions[0] = (dfi_tail_pos){.substitute_hp = 1u, .trap_move = DFI_POOL_MOVE_COUNT, .last_move = 5u,
                                      .encore_slot = 4u, .encore_turns = 4u, .throat_chop_turns = 2u,
                                      .heal_block_turns = 5u, .perish = 4u, .taunt_turns = 4u, .disable_slot = 4u,
                                      .disable_turns = 5u, .imprison = 1u, .must_recharge = 1u, .trap_turns = 8u,
                                      .trap_source = 4u, .trap_band = 1u, .leech_seed_source = 4u, .yawn_turns = 2u,
                                      .focus_energy = 1u, .stockpile = 3u, .stockpile_def = 3u,
                                      .stockpile_spd = 3u, .charge = 1u, .glaive_rush = 1u, .move_result = 0x0Fu,
                                      .single_turn = DFI_SINGLE_TURN_ROOST, .hits_taken = 6u, .ability_state = 6u,
                                      .lock_turns = 3u};
    ts->ability_now[0] = DFI_POOL_ABILITY_COUNT;
    ts->forme_now[5] = DFI_POOL_FORME_COUNT;
    ts->item_now[2] = DFI_POOL_ITEM_COUNT;
    ts->item_now[3] = DFI_TAIL_ITEM_NONE;
    ts->soak_type[1] = 18u;
    ts->type2[0] = DFI_TAIL_TYPE2_TYPELESS;
    ts->type2[1] = 18u;
    ts->member_flags[0] = DFI_TAIL_MEMBER_FLAG_HERO_SHOWN;
    ts->member_flags[4] = DFI_TAIL_MEMBER_FLAG_HERO_SHOWN; /* a reserve keeps it: the message was shown once for the battle */
})
/* No valid case for Rage Powder's marker: the Follow Me flag it needs lives only at a PIVOT boundary, and these states are at a
 * TURN one; the invalid case above (the marker without the flag) and the model say what the rule is. */
MUT(v_move_result_null, p0->move_result = (uint8_t)((DFI_MOVE_RESULT_NULL << DFI_MOVE_RESULT_LAST_SHIFT) | DFI_MOVE_RESULT_FALSE))
MUT(v_hazard_order_two, {
    ts->spikes = 2u;
    ts->toxic_spikes = 1u;
    ts->hazard_order = (uint8_t)(DFI_HAZARD_TOXIC_SPIKES | (DFI_HAZARD_SPIKES << 2u)); /* Toxic Spikes first */
})
MUT(v_hazard_order_gone, {
    ts->sticky_web = 1u; /* an ended kind leaves, the later ones shift down: Sticky Web alone in slot 0 */
    ts->hazard_order = (uint8_t)DFI_HAZARD_STICKY_WEB;
})
MUT(v_substitute_quarter, p0->substitute_hp = (uint16_t)(y->sides[0].members[y->sides[0].positions[0].occupant].hp_max / 4u))
MUT(v_bench_overrides, {
    /* the current item and forme outlive the field: a reserve and a fainted member keep them */
    y->sides[0].members[1].hp = 0u;
    df_knowledge_refresh_active(y);
    ts->item_now[1] = 5u;
    ts->forme_now[1] = 5u;
    ts->item_now[3] = DFI_TAIL_ITEM_NONE;
    ts->forme_now[3] = 9u;
})
MUT(v_protect_variant, {
    y->sides[0].positions[0].flags = (uint8_t)(y->sides[0].positions[0].flags | DFI_VOL_PROTECT);
    p0->protect_kind = DFI_PROTECT_SPIKY_SHIELD;
})
MUT(v_ally_trap, {
    p0->trap_turns = 5u;
    p0->trap_source = 2u; /* the ally, flat position 1 */
    p0->trap_move = 1u;
})

static const tail_case cases[] = {
    {"gravity above 5", DFI_INV_TAIL_FIELD, false, m_gravity},
    {"the pad byte of the field block", DFI_INV_TAIL_FIELD, false, m_field_pad},
    {"a lead twice in the party order (step G46)", DFI_INV_TAIL_PARTY, false, m_party_dup},
    {"an empty lead in the party order", DFI_INV_TAIL_PARTY, false, m_party_hole},
    {"a bench entry for a fifth member of four brought", DFI_INV_TAIL_PARTY, false, m_party_bench_filled},
    {"a party entry for a member that is not brought", DFI_INV_TAIL_PARTY, false, m_party_not_brought},
    {"a party bit above the six entries", DFI_INV_TAIL_PARTY, false, m_party_bits_high},
    {"wide guard above 1", DFI_INV_TAIL_SIDE, false, m_wide_guard},
    {"aurora veil above 8", DFI_INV_TAIL_SIDE, false, m_aurora},
    {"toxic spikes above 2", DFI_INV_TAIL_SIDE, false, m_toxic_spikes},
    {"stealth rock above 1", DFI_INV_TAIL_SIDE, false, m_stealth_rock},
    {"spikes above 3", DFI_INV_TAIL_SIDE, false, m_spikes},
    {"sticky web above 1", DFI_INV_TAIL_SIDE, false, m_sticky_web},
    {"quick guard above 1", DFI_INV_TAIL_SIDE, false, m_quick_guard},
    {"a hazard order with no hazard up", DFI_INV_TAIL_SIDE, false, m_hazard_no_hazard},
    {"a hazard that is up whose slot names another kind", DFI_INV_TAIL_SIDE, false, m_hazard_missing_kind},
    {"a hazard order that names a kind twice", DFI_INV_TAIL_SIDE, false, m_hazard_duplicate},
    {"a hazard order with a slot beyond the kinds that are up", DFI_INV_TAIL_SIDE, false, m_hazard_slot_beyond},
    {"a hazard order that names a kind that is not up", DFI_INV_TAIL_SIDE, false, m_hazard_absent_kind},
    {"a hazard order that misses a kind that is up", DFI_INV_TAIL_SIDE, false, m_hazard_dropped_gap},
    {"a hazard order with a nonzero slot after the only kind", DFI_INV_TAIL_SIDE, false, m_hazard_extra_slot},
    {"last move above Struggle", DFI_INV_TAIL_POSITION, false, m_last_above},
    {"last move beyond the move count", DFI_INV_TAIL_POSITION, true, m_last_beyond},
    {"Encore slot beyond the move count", DFI_INV_TAIL_POSITION, true, m_encore_beyond},
    {"Encore without turns", DFI_INV_TAIL_POSITION, false, m_encore_no_turns},
    {"Encore turns without a slot", DFI_INV_TAIL_POSITION, false, m_encore_no_slot},
    {"Encore slot above 4", DFI_INV_TAIL_POSITION, false, m_encore_slot5},
    {"Encore turns above 4", DFI_INV_TAIL_POSITION, false, m_encore_turns5},
    {"Throat Chop above 2", DFI_INV_TAIL_POSITION, false, m_throat},
    {"Heal Block above 5", DFI_INV_TAIL_POSITION, false, m_heal_block},
    {"Perish above 4", DFI_INV_TAIL_POSITION, false, m_perish},
    {"Taunt above 4", DFI_INV_TAIL_POSITION, false, m_taunt},
    {"Yawn above 2", DFI_INV_TAIL_POSITION, false, m_yawn},
    {"Disable slot above 4", DFI_INV_TAIL_POSITION, false, m_disable_slot5},
    {"Disable slot beyond the move count", DFI_INV_TAIL_POSITION, true, m_disable_beyond},
    {"Disable slot without turns", DFI_INV_TAIL_POSITION, false, m_disable_no_turns},
    {"Disable turns without a slot", DFI_INV_TAIL_POSITION, false, m_disable_no_slot},
    {"Disable turns above 5", DFI_INV_TAIL_POSITION, false, m_disable_turns6},
    {"Imprison above 1", DFI_INV_TAIL_POSITION, false, m_imprison},
    {"must recharge above 1", DFI_INV_TAIL_POSITION, false, m_recharge},
    {"Focus Energy above 1", DFI_INV_TAIL_POSITION, false, m_focus},
    {"Charge above 1", DFI_INV_TAIL_POSITION, false, m_charge},
    {"Glaive Rush above 1", DFI_INV_TAIL_POSITION, false, m_glaive},
    {"protect kind above 1", DFI_INV_TAIL_POSITION, false, m_protect_above},
    {"protect kind without the Protect volatile", DFI_INV_TAIL_POSITION, false, m_protect_no_volatile},
    {"a move result above its two nibbles", DFI_INV_TAIL_POSITION, false, m_move_result_high},
    {"a single-turn bit that is not defined", DFI_INV_TAIL_POSITION, false, m_single_turn_bit2},
    {"Rage Powder's marker without the Follow Me flag", DFI_INV_TAIL_POSITION, false, m_rage_no_follow_me},
    {"hits taken above 6", DFI_INV_TAIL_POSITION, false, m_hits_taken7},
    {"an ability state above 6", DFI_INV_TAIL_POSITION, false, m_ability_state7},
    {"lock turns above 3", DFI_INV_TAIL_POSITION, false, m_lock_turns4},
    {"lock turns without the locked move in the slot", DFI_INV_TAIL_POSITION, false, m_lock_no_move},
    {"a Substitute above a quarter of the maximum HP", DFI_INV_TAIL_POSITION, false, m_substitute_above},
    {"a trap with turns alone", DFI_INV_TAIL_POSITION, false, m_trap_turns_only},
    {"a trap with a source alone", DFI_INV_TAIL_POSITION, false, m_trap_source_only},
    {"a trap with a move alone", DFI_INV_TAIL_POSITION, false, m_trap_move_only},
    {"a trap without its move", DFI_INV_TAIL_POSITION, false, m_trap_no_move},
    {"a trap without its source", DFI_INV_TAIL_POSITION, false, m_trap_no_source},
    {"a trap above 8 turns", DFI_INV_TAIL_POSITION, false, m_trap_turns9},
    {"a trap source above 4", DFI_INV_TAIL_POSITION, false, m_trap_source5},
    {"a trap whose source is the occupant", DFI_INV_TAIL_POSITION, false, m_trap_own},
    {"a trap move beyond the table", DFI_INV_TAIL_POSITION, false, m_trap_move_beyond},
    {"a Binding Band flag above 1", DFI_INV_TAIL_POSITION, false, m_trap_band2},
    {"a Binding Band flag without a trap", DFI_INV_TAIL_POSITION, false, m_trap_band_alone},
    {"a Leech Seed source above 4", DFI_INV_TAIL_POSITION, false, m_leech5},
    {"a Leech Seed whose source is the occupant", DFI_INV_TAIL_POSITION, false, m_leech_own},
    {"stockpile above 3", DFI_INV_TAIL_POSITION, false, m_stockpile4},
    {"stockpile Defense boosts above the layers", DFI_INV_TAIL_POSITION, false, m_stockpile_def},
    {"stockpile Special Defense boosts without layers", DFI_INV_TAIL_POSITION, false, m_stockpile_spd},
    {"a tail at an empty position", DFI_INV_TAIL_POSITION, false, m_empty_pos},
    {"a Substitute at an empty position", DFI_INV_TAIL_POSITION, false, m_empty_pos_substitute},
    {"a tail at a fainted occupant", DFI_INV_TAIL_POSITION, false, m_fainted_pos},
    {"a Taunt at a fainted occupant", DFI_INV_TAIL_POSITION, false, m_fainted_pos_taunt},
    {"a soak type above 18", DFI_INV_TAIL_MEMBER, false, m_soak19},
    {"a soak type on a reserve", DFI_INV_TAIL_MEMBER, false, m_soak_reserve},
    {"a soak type on a fainted member", DFI_INV_TAIL_MEMBER, false, m_soak_fainted},
    {"a soak type on a Mega Evolved member is valid (Soak after the Mega Evolution, step G11)", DFI_INV_NONE, false, m_soak_mega},
    {"a soak type on a member that has left the field", DFI_INV_TAIL_MEMBER, false, m_soak_left},
    {"a current ability beyond the table", DFI_INV_TAIL_MEMBER, false, m_ability_above},
    {"a current ability on a reserve", DFI_INV_TAIL_MEMBER, false, m_ability_reserve},
    {"a current ability on a fainted member", DFI_INV_TAIL_MEMBER, false, m_ability_fainted},
    {"a current forme beyond the table", DFI_INV_TAIL_MEMBER, false, m_forme_above},
    {"a current item beyond the table", DFI_INV_TAIL_MEMBER, false, m_item_above},
    {"a current item 254 (the table has 166)", DFI_INV_TAIL_MEMBER, false, m_item_254},
    {"a toxic stage without the status Tox", DFI_INV_TAIL_MEMBER, false, m_toxic_no_status},
    {"a toxic stage above 15", DFI_INV_TAIL_MEMBER, false, m_toxic_16},
    {"a toxic stage on a reserve", DFI_INV_TAIL_MEMBER, false, m_toxic_reserve},
    {"a second type above 18 that is not the typeless value", DFI_INV_TAIL_MEMBER, false, m_type2_19},
    {"a second type 254", DFI_INV_TAIL_MEMBER, false, m_type2_254},
    {"a second type on a reserve", DFI_INV_TAIL_MEMBER, false, m_type2_reserve},
    {"a second type on a fainted member", DFI_INV_TAIL_MEMBER, false, m_type2_fainted},
    {"member flags with an undefined bit", DFI_INV_TAIL_MEMBER, false, m_member_flags2},
    {"member flags with the top bit", DFI_INV_TAIL_MEMBER, false, m_member_flags_high},
    {"Illusion shown index (rev 5)", DFI_INV_TAIL_SIDE, false, m_ill_shown},
    {"Illusion override byte (rev 5)", DFI_INV_TAIL_SIDE, false, m_ill_override},
    {"Illusion snapshot byte (rev 5)", DFI_INV_TAIL_SIDE, false, m_ill_snapshot},
    {"Illusion pending byte (rev 5)", DFI_INV_TAIL_SIDE, false, m_ill_pending},
    {"slot pending bit at a standing lead (rev 5)", DFI_INV_TAIL_POSITION, false, m_slot_pending},
    {"Future Sight byte at a standing lead (rev 5)", DFI_INV_TAIL_POSITION, false, m_future_sight},
    {"Struggle as the last move is valid for any move count", DFI_INV_NONE, false, v_struggle},
    {"the last Encore turn and slot 4 are valid", DFI_INV_NONE, false, v_encore_edge},
    {"every maximum at once is valid", DFI_INV_NONE, false, v_maxima},
    {"two hazards in either order are valid", DFI_INV_NONE, false, v_hazard_order_two},
    {"a hazard alone in the first slot is valid", DFI_INV_NONE, false, v_hazard_order_gone},
    {"a Substitute of exactly a quarter is valid", DFI_INV_NONE, false, v_substitute_quarter},
    {"the item and forme of a reserve and a fainted member are valid", DFI_INV_NONE, false, v_bench_overrides},
    {"a trap by the ally is valid", DFI_INV_NONE, false, v_ally_trap},
    {"a Protect variant under its volatile is valid", DFI_INV_NONE, false, v_protect_variant},
    {"a move result of this turn false and last turn null is valid", DFI_INV_NONE, false, v_move_result_null}};

/* True iff the byte at `off` of the encoded tail is a reserved one (by the layout alone). */
static bool is_reserved_offset(size_t off)
{
    if (off >= DFI_ENC_TAIL_REV4_SIZE) { /* the rev 5 block: its 16 reserve bytes are the last ones */
        return off - DFI_ENC_TAIL_REV4_SIZE >= DFI_ENC_TAIL5_RESERVED_OFF;
    }
    if (off < DFI_ENC_TAIL_FIELD_SIZE) {
        return off >= DFI_ENC_TAIL_FIELD_RESERVED_OFF;
    }
    const size_t in_side = (off - DFI_ENC_TAIL_SIDES_OFF) % DFI_ENC_TAIL_SIDE_SIZE;
    if (in_side < DFI_ENC_TAIL_POS_OFF) {
        return in_side >= DFI_ENC_TAIL_SIDE_RESERVED_OFF;
    }
    if (in_side < DFI_ENC_TAIL_MEMBER_OFF) {
        return (in_side - DFI_ENC_TAIL_POS_OFF) % DFI_ENC_TAIL_POS_SIZE >= DFI_ENC_TAIL_POS_RESERVED_OFF;
    }
    return (in_side - DFI_ENC_TAIL_MEMBER_OFF) % DFI_ENC_TAIL_MEMBER_SIZE == DFI_ENC_TAIL_MEMBER_RESERVED_OFF;
}

int main(void)
{
    df_test t;
    df_test_begin(&t, "duoforge.state.pool_tail");
    duoforge_context *k1 = df_make_context(&df_config_k1);
    duoforge_context *k2 = df_make_context(&df_config_k2);
    duoforge_context *kc = df_make_context(&df_config_team_c);
    duoforge_context *kd = df_make_context(&df_config_team_c_dev);
    duoforge_context *kp = df_make_context(&df_config_pool);
    duoforge_context *kq = df_make_context(&df_config_pool_dev);
    duoforge_context *c1 = df_make_context(&df_config_c1);

    /* The layout: sizes, schema ids, which kinds carry the tail. */
    {
        DF_CHECK_EQ_U64(&t, DFI_STATE_POOL_ENCODED_SIZE, 1357u);
        DF_CHECK_EQ_U64(&t, DFI_STATE_ENCODED_MAX, DF_STATE_ENCODED_MAX);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_OFF, 1009u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_SIZE, 348u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_REV4_SIZE, 288u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL5_SIZE, 60u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL5_RESERVED_OFF, 44u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_RESERVED_COUNT, 45u); /* step G46: party_order takes 6 of the 7 field bytes (35 before); rev 5: 16 more */
        DF_CHECK_EQ_U64(&t, DFI_STATE_SCHEMA_V3, 3u);
        DF_CHECK_EQ_U64(&t, DFI_STATE_SCHEMA_POOL_TAIL_REV5, 0x0503u);
        DF_CHECK_EQ_U64(&t, DFI_STATE_SCHEMA_POOL_TAIL_REV4, 0x0403u); /* refused since rev 5 */
        DF_CHECK_EQ_U64(&t, DFI_STATE_SCHEMA_POOL_TAIL_REV3, 0x0303u); /* refused since rev 4 */
        DF_CHECK_EQ_U64(&t, DFI_STATE_SCHEMA_POOL_TAIL_REV2, 0x0203u); /* refused since rev 3 */
        DF_CHECK_EQ_U64(&t, DFI_STATE_SCHEMA_POOL_TAIL_REV1, 0x0103u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_POS_PROTECT_KIND_OFF, 26u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_POS_MOVE_RESULT_OFF, 27u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_POS_LOCK_TURNS_OFF, 31u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_QUICK_GUARD_OFF, 6u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_HAZARD_ORDER_OFF, 7u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_SIDE_RESERVED_SIZE, 0u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_MEMBER_TYPE2_OFF, 7u);
        DF_CHECK_EQ_U64(&t, DFI_ENC_TAIL_MEMBER_FLAGS_OFF, 8u);
        DF_CHECK(&t, DFI_STATE_SCHEMA_POOL_TAIL_REV5 != 4u); /* schema 4 stays free: certified pool teams */
        /* The tail in memory: the encoded size without the reserved bytes, and the one pad byte of the field block. */
        DF_CHECK_EQ_U64(&t, sizeof(dfi_pool_tail), 304u); /* a position and a side have none; step G46 adds party_order (6); rev 5 adds the Illusion state and the 2 position bytes */
        DF_CHECK_EQ_U64(&t, sizeof(dfi_tail_side), 148u);
        DF_CHECK_EQ_U64(&t, sizeof(dfi_tail_pos), 34u);
        DF_CHECK_EQ_U64(&t, sizeof(dfi_tail_illusion), 18u);
        unsigned reserved = 0u;
        for (size_t off = 0u; off < DFI_ENC_TAIL_SIZE; ++off) {
            reserved += is_reserved_offset(off) ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, reserved, 45u);
        const duoforge_context *with[] = {kp, kq};
        const duoforge_context *without[] = {k1, k2, kc, kd, c1};
        for (size_t i = 0u; i < 2u; ++i) {
            DF_CHECK(&t, dfi_context_has_pool_tail(with[i]));
            DF_CHECK_EQ_U64(&t, dfi_state_schema_of(with[i]), 0x0503u);
            DF_CHECK_EQ_U64(&t, dfi_state_encoded_size_of(with[i]), 1357u);
        }
        for (size_t i = 0u; i < 5u; ++i) {
            DF_CHECK(&t, !dfi_context_has_pool_tail(without[i]));
            DF_CHECK_EQ_U64(&t, dfi_state_schema_of(without[i]), 3u);
            DF_CHECK_EQ_U64(&t, dfi_state_encoded_size_of(without[i]), 1009u);
        }
    }

    /* The other four kinds are byte for byte what they were: size 1009, schema 3, and the digests of three states
     * of each, taken before the tail existed. A tail in memory is refused there (below). */
    {
        const duoforge_context *kinds[4] = {k1, k2, kc, kd};
        static const char *const names[4] = {"CLOSURE", "CLOSURE_DEV", "TEAM_C", "TEAM_C_DEV"};
        for (size_t i = 0u; i < 4u; ++i) {
            duoforge_battle_setup s;
            df_setup_teams(&s);
            if (i >= 2u) {
                df_put_team_c(&s.sides[1]);
            }
            duoforge_battle *b = df_make_battle(kinds[i], &s);
            uint8_t enc[DF_STATE_ENCODED_MAX];
            uint8_t d[DUOFORGE_DIGEST_SIZE];
            for (unsigned point = 0u; point < 3u; ++point) {
                if (point == 1u) {
                    duoforge_decision_bundle bd;
                    team_bundle(&bd, b);
                    step_ok(&t, kinds[i], b, &bd, "team selection");
                } else if (point == 2u) {
                    duoforge_decision_bundle bd;
                    turn_bundle(&bd, b);
                    step_ok(&t, kinds[i], b, &bd, "turn 1");
                }
                DF_CHECK_EQ_U64(&t, df_encode_n(kinds[i], b, enc), 1009u);
                DF_CHECK(&t, enc[DFI_ENVELOPE_SCHEMA_OFF] == 3u && enc[DFI_ENVELOPE_SCHEMA_OFF + 1u] == 0u);
                digest_of(&t, kinds[i], b, d);
                size_t found = 0u;
                for (size_t k = 0u; k < sizeof before_the_tail / sizeof before_the_tail[0]; ++k) {
                    static const char *const points[3] = {"created", "teams", "turn1"};
                    if (strcmp(before_the_tail[k].kind, names[i]) == 0 && strcmp(before_the_tail[k].point, points[point]) == 0) {
                        check_hex(&t, d, before_the_tail[k].hex, DUOFORGE_DIGEST_SIZE, "digest before the tail");
                        ++found;
                    }
                }
                DF_CHECK_EQ_U64(&t, found, 1u);
            }
            duoforge_battle_destroy(b);
        }
    }

    /* The state of a POOL battle at its first TURN boundary, with and without the example tail. */
    duoforge_battle *w = turn_battle(&t, kp, false);
    uint8_t zero_enc[DF_STATE_ENCODED_MAX];
    uint8_t enc[DF_STATE_ENCODED_MAX];
    uint8_t d0[DUOFORGE_DIGEST_SIZE];
    uint8_t d1[DUOFORGE_DIGEST_SIZE];
    {
        /* The example is valid because of who stands on the field: members 0 and 1 of both sides, standing, with
         * four moves, no Mega forme and no ailment (the model's state), and the Substitute bound is a quarter of the
         * maximum HP of those four. */
        for (uint32_t s = 0u; s < 2u; ++s) {
            DF_CHECK_EQ_U64(&t, w->sides[s].member_count, 6u);
            DF_CHECK(&t, w->sides[s].positions[0].occupant == 0u && w->sides[s].positions[1].occupant == 1u);
            for (uint32_t m = 0u; m < 6u; ++m) {
                DF_CHECK(&t, w->sides[s].members[m].hp != 0u && w->sides[s].members[m].move_count == 4u &&
                                 w->sides[s].members[m].is_mega == 0u && w->sides[s].members[m].status == 0u);
                if (m < 2u && !DF_CHECK(&t, w->sides[s].members[m].hp_max == lead_hp_max[s][m])) {
                    fprintf(stderr, "  hp_max of side %u member %u is %u\n", (unsigned)s, (unsigned)m,
                            (unsigned)w->sides[s].members[m].hp_max);
                }
            }
        }
        uint8_t zero_tail[DFI_ENC_TAIL_SIZE];
        memset(zero_tail, 0, sizeof zero_tail);
        /* step G46: after team selection the party order holds the pick order of the 4 brought members (the leads, then the
         * bench); the rest of the tail is zero. */
        {
            dfi_pool_tail pt;
            memset(&pt, 0, sizeof pt);
            for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
                for (uint32_t k = 0u; k < 4u; ++k) {
                    dfi_party_put(&pt, s, k, (uint32_t)w->sides[s].brought_order[k] + 1u);
                }
            }
            memcpy(zero_tail + DFI_ENC_TAIL_FIELD_PARTY_OFF, pt.party_order, sizeof pt.party_order);
        }
        DF_CHECK_EQ_U64(&t, df_encode_n(kp, w, zero_enc), 1357u);
        DF_CHECK_BYTES(&t, zero_enc + DFI_ENC_TAIL_OFF, zero_tail, sizeof zero_tail,
                       "a tail after team selection: zero but the party order (step G46)");
        digest_of(&t, kp, w, d0);

        set_example_tail(w);
        const size_t n = df_encode_n(kp, w, enc);
        DF_CHECK_EQ_U64(&t, n, 1357u);
        check_hex(&t, enc, ENVELOPE_HEX, DFI_ENVELOPE_SIZE, "envelope of a POOL state (model)");
        check_hex(&t, enc + DFI_ENC_TAIL_OFF, TAIL_HEX, DFI_ENC_TAIL_SIZE, "tail of the example (model)");
        /* The rest of the state is untouched by the tail. */
        /* The body is the same, but for the two locked moves of the example's leads (step G56): a lock needs its move in the
         * slot, the body's half of the pairing that the tail refuses without it (as Rage Powder's Follow Me flag). */
        unsigned body_diffs = 0u;
        for (size_t k = DFI_ENVELOPE_SIZE; k < DFI_ENC_TAIL_OFF; ++k) {
            if (enc[k] != zero_enc[k]) {
                body_diffs += 1u;
                DF_CHECK_EQ_U64(&t, enc[k], 1u); /* the locked move: its slot plus one */
            }
        }
        DF_CHECK_EQ_U64(&t, body_diffs, 2u);
        /* The reserved bytes are zero. */
        unsigned nonzero = 0u;
        for (size_t off = 0u; off < DFI_ENC_TAIL_SIZE; ++off) {
            nonzero += is_reserved_offset(off) && enc[DFI_ENC_TAIL_OFF + off] != 0u ? 1u : 0u;
        }
        DF_CHECK_EQ_U64(&t, nonzero, 0u);
        DF_CHECK(&t, duoforge_battle_check(kp, w) == DUOFORGE_OK);
        digest_of(&t, kp, w, d1);
        DF_CHECK(&t, memcmp(d0, d1, sizeof d0) != 0);
        size_t size = 0u;
        DF_CHECK(&t, duoforge_battle_encoded_size(kp, w, &size) == DUOFORGE_OK && size == 1357u);
    }

    /* Round trip, equality, clone, copy, load into an existing handle; nothing of the tail is lost. */
    {
        uint8_t *in = df_heap_copy(enc, DFI_STATE_POOL_ENCODED_SIZE);
        duoforge_battle *d = NULL;
        DF_CHECK(&t, duoforge_battle_create_decoded(kp, in, DFI_STATE_POOL_ENCODED_SIZE, &d) == DUOFORGE_OK && d != NULL);
        bool eq = false;
        DF_CHECK(&t, duoforge_battle_equal(kp, w, d, &eq) == DUOFORGE_OK && eq);
        DF_CHECK(&t, memcmp(&d->tail, &w->tail, sizeof w->tail) == 0);
        uint8_t again[DF_STATE_ENCODED_MAX];
        DF_CHECK_EQ_U64(&t, df_encode_n(kp, d, again), 1357u);
        DF_CHECK_BYTES(&t, again, enc, DFI_STATE_POOL_ENCODED_SIZE, "decode then encode");
        uint8_t dd[DUOFORGE_DIGEST_SIZE];
        digest_of(&t, kp, d, dd);
        DF_CHECK_BYTES(&t, dd, d1, sizeof dd, "digest of the decoded state");
        duoforge_battle_destroy(d);

        duoforge_battle *k = NULL;
        DF_CHECK(&t, duoforge_battle_clone(kp, w, &k) == DUOFORGE_OK && k != NULL);
        DF_CHECK(&t, duoforge_battle_equal(kp, w, k, &eq) == DUOFORGE_OK && eq);
        DF_CHECK(&t, memcmp(&k->tail, &w->tail, sizeof w->tail) == 0);
        /* copy into a handle that holds another tail (the empty one), and load into one. */
        duoforge_battle *other = turn_battle(&t, kp, false);
        DF_CHECK(&t, duoforge_battle_equal(kp, w, other, &eq) == DUOFORGE_OK && !eq); /* the tail alone differs */
        DF_CHECK(&t, duoforge_battle_copy(kp, other, w) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_equal(kp, w, other, &eq) == DUOFORGE_OK && eq);
        memset(&other->tail, 0, sizeof other->tail);
        DF_CHECK(&t, duoforge_battle_decode(kp, other, in, DFI_STATE_POOL_ENCODED_SIZE) == DUOFORGE_OK);
        DF_CHECK(&t, duoforge_battle_equal(kp, w, other, &eq) == DUOFORGE_OK && eq);
        /* A refused load changes nothing (atomic): a reserved byte of the tail that is not zero. */
        uint8_t bad[DF_STATE_ENCODED_MAX];
        memcpy(bad, enc, DFI_STATE_POOL_ENCODED_SIZE);
        bad[DFI_ENC_TAIL_OFF + 1u] = 1u;
        uint8_t *bad_in = df_heap_copy(bad, DFI_STATE_POOL_ENCODED_SIZE);
        uint8_t before[DF_STATE_ENCODED_MAX];
        uint8_t after[DF_STATE_ENCODED_MAX];
        (void)df_encode_n(kp, other, before);
        DF_CHECK(&t, duoforge_battle_decode(kp, other, bad_in, DFI_STATE_POOL_ENCODED_SIZE) == DUOFORGE_E_MALFORMED);
        (void)df_encode_n(kp, other, after);
        DF_CHECK_BYTES(&t, after, before, DFI_STATE_POOL_ENCODED_SIZE, "a refused load changes nothing");
        df_free(bad_in);
        df_free(in);
        duoforge_battle_destroy(other);
        duoforge_battle_destroy(k);
    }

    /* The digest changes if and only if the tail changes: every field that a state can hold on its own, set one at a
     * time (a pair that is zero together, with its partner), gives its own digest, different from every other
     * setting's and from the empty tail's; each setting is a valid tail (the decoder takes it and encodes it back),
     * and clearing it brings the digest back. */
    {
        static tail_setting settings[SETTINGS_MAX];
        static uint8_t digests[SETTINGS_MAX][DUOFORGE_DIGEST_SIZE];
        const size_t count = build_settings(settings);
        /* 163: the lock is not a setting (step G56): its count needs the locked move in the body, which the settings
         * do not carry; the lock cases below and the example cover it (a lock is refused without its move, TAIL_POSITION). */
        DF_CHECK_EQ_U64(&t, count, 163u);
        duoforge_battle *x = turn_battle(&t, kp, false);
        uint8_t base[DUOFORGE_DIGEST_SIZE];
        digest_of(&t, kp, x, base);
        for (size_t i = 0u; i < count; ++i) {
            uint8_t art[DF_STATE_ENCODED_MAX];
            memcpy(art, zero_enc, DFI_STATE_POOL_ENCODED_SIZE);
            for (size_t k = 0u; k < 4u; ++k) {
                put_write(art + DFI_ENC_TAIL_OFF, &settings[i].w[k]);
            }
            dfi_invariant inv = DFI_INV_NONE;
            duoforge_battle y;
            uint8_t *in = df_heap_copy(art, DFI_STATE_POOL_ENCODED_SIZE);
            const duoforge_status st = dfi_decode_state(kp, in, DFI_STATE_POOL_ENCODED_SIZE, &y, &inv);
            df_free(in);
            if (!DF_CHECK(&t, st == DUOFORGE_OK)) {
                fprintf(stderr, "  setting %u (%s): %s (%s)\n", (unsigned)i, settings[i].what, duoforge_status_name(st),
                        inv_name(inv));
                continue;
            }
            uint8_t back[DF_STATE_ENCODED_MAX];
            DF_CHECK_EQ_U64(&t, dfi_encode_unchecked(kp, &y, back), DFI_STATE_POOL_ENCODED_SIZE);
            DF_CHECK_BYTES(&t, back, art, DFI_STATE_POOL_ENCODED_SIZE, "a single setting encodes back");
            DF_CHECK(&t, memcmp(&y.tail, &x->tail, sizeof y.tail) != 0);
            digest_of(&t, kp, &y, digests[i]);
            DF_CHECK(&t, memcmp(digests[i], base, sizeof base) != 0);
            for (size_t j = 0u; j < i; ++j) {
                if (!DF_CHECK(&t, memcmp(digests[i], digests[j], sizeof base) != 0)) {
                    fprintf(stderr, "  settings %u (%s) and %u (%s) have one digest\n", (unsigned)i, settings[i].what,
                            (unsigned)j, settings[j].what);
                }
            }
            y.tail = x->tail;
            uint8_t again[DUOFORGE_DIGEST_SIZE];
            digest_of(&t, kp, &y, again);
            DF_CHECK_BYTES(&t, again, base, sizeof again, "the digest comes back with the empty tail");
        }
        duoforge_battle_destroy(x);
    }

    /* Mutation of the artifact: every byte of the tail to every other value. The decoder accepts the value or
     * refuses it with the invariant that the model names, and the counts per byte are the model's. */
    {
        unsigned wrong = 0u;
        unsigned all_reserved = 0u;
        for (size_t off = 0u; off < DFI_ENC_TAIL_SIZE; ++off) {
            unsigned got[SWEEP_COLUMNS] = {0u, 0u, 0u, 0u, 0u, 0u, 0u, 0u};
            uint8_t m[DF_STATE_ENCODED_MAX];
            memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
            for (unsigned v = 0u; v < 256u; ++v) {
                if (v == enc[DFI_ENC_TAIL_OFF + off]) {
                    continue;
                }
                m[DFI_ENC_TAIL_OFF + off] = (uint8_t)v;
                dfi_invariant inv = DFI_INV_NONE;
                const duoforge_status st = decode_both(&t, kp, m, DFI_STATE_POOL_ENCODED_SIZE, &inv);
                if (st == DUOFORGE_OK) {
                    got[0] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_SIDE) {
                    got[1] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_POSITION) {
                    got[2] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_MEMBER) {
                    got[3] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_FIELD) {
                    got[4] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_RESERVED) {
                    got[5] += 1u;
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_PARTY) {
                    got[6] += 1u; /* step G46: a party order bit or entry that is not a permutation of the brought members */
                } else if (st == DUOFORGE_E_MALFORMED && inv == DFI_INV_VOLATILE) {
                    got[7] += 1u; /* step G56: a locked move of the body whose lock is cleared (its owner is the lock) */
                } else {
                    DF_CHECK(&t, false);
                    fprintf(stderr, "  tail byte %u = %u: %s (%s)\n", (unsigned)off, v, duoforge_status_name(st), inv_name(inv));
                }
            }
            if (memcmp(got, sweep[off], sizeof got) != 0) {
                ++wrong;
                fprintf(stderr, "  tail byte %u: ok %u side %u position %u member %u field %u reserved %u\n", (unsigned)off,
                        got[0], got[1], got[2], got[3], got[4], got[5]);
            }
            /* The reserved bytes (by the layout) accept nothing but zero, and no other byte is reserved. */
            if (is_reserved_offset(off)) {
                all_reserved += got[5] == 255u ? 1u : 0u;
            } else {
                DF_CHECK_EQ_U64(&t, got[5], 0u);
            }
        }
        DF_CHECK_EQ_U64(&t, wrong, 0u);
        DF_CHECK_EQ_U64(&t, all_reserved, 45u); /* 29 reserved bytes of the rev 4 part (the field block's +1..+6 are party_order) and 16 of rev 5 */
    }

    /* The schema is the one of the context's kind; sizes, schema ids and truncations. */
    {
        uint8_t m[DF_STATE_ENCODED_MAX + 1u]; /* one byte past a state, for the length check */
        dfi_invariant inv = DFI_INV_NONE;
        /* A POOL state with the schema and length of schema 3 and without its tail. */
        memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
        set_envelope(m, 3u, 1009u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1009u, &inv) == DUOFORGE_E_MALFORMED && inv == DFI_INV_TAIL_SCHEMA);
        DF_CHECK(&t, decode_both(&t, kq, m, 1009u, &inv) == DUOFORGE_E_CONTEXT_MISMATCH); /* the POOL fingerprint */
        /* Pool schema and no tail; schema 3 with a tail. */
        memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
        set_envelope(m, 0x0503u, 1009u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1009u, &inv) == DUOFORGE_E_MALFORMED && inv == DFI_INV_NONE);
        memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
        set_envelope(m, 3u, 1357u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1357u, &inv) == DUOFORGE_E_MALFORMED && inv == DFI_INV_NONE);
        /* Rev 1 is refused, explicitly: a genuine rev 1 artifact (the 1009 bytes of schema 3, schema 0x0103, 42 more
         * bytes, length 1051) under either POOL kind, and under the other kinds; its schema is no schema of this
         * build. The same bytes with the schema of rev 2 are the wrong size. */
        memcpy(m, enc, 1009u);
        memset(m + 1009u, 0, 42u);
        set_envelope(m, 0x0103u, 1051u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1051u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH && inv == DFI_INV_NONE);
        DF_CHECK(&t, decode_both(&t, kq, m, 1051u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        DF_CHECK(&t, decode_both(&t, k1, m, 1051u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        set_envelope(m, 0x0503u, 1051u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1051u, &inv) == DUOFORGE_E_MALFORMED && inv == DFI_INV_NONE);
        /* Rev 2 is refused the same way (schema 0x0203): a genuine rev 2 artifact is the 1009 bytes of schema 3 and the 248
         * bytes of the rev 2 tail, length 1257, under either POOL kind and under the other kinds. */
        memcpy(m, enc, 1009u);
        memset(m + 1009u, 0, 248u);
        set_envelope(m, 0x0203u, 1257u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1257u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH && inv == DFI_INV_NONE);
        DF_CHECK(&t, decode_both(&t, kq, m, 1257u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        DF_CHECK(&t, decode_both(&t, k1, m, 1257u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        /* Rev 3 is refused by name since rev 4 (schema 0x0303, 1257 bytes: the same tail without the rev 4 fields): a genuine
         * rev 3 artifact under either POOL kind and under the other kinds, and the same bytes with the schema of rev 4 are
         * the wrong size. */
        set_envelope(m, 0x0303u, 1257u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1257u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH && inv == DFI_INV_NONE);
        DF_CHECK(&t, decode_both(&t, kq, m, 1257u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        DF_CHECK(&t, decode_both(&t, k1, m, 1257u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        DF_CHECK(&t, decode_both(&t, kc, m, 1257u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        set_envelope(m, 0x0503u, 1257u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1257u, &inv) == DUOFORGE_E_MALFORMED && inv == DFI_INV_NONE);
        /* Rev 4 (0x0403) is refused by name since rev 5: a genuine rev 4 artifact is the 1009 bytes of schema 3 and the 288
         * bytes of the rev 4 part (the same bytes as the first 288 of the rev 5 tail), length 1297, under either POOL kind
         * and under the other kinds. */
        memcpy(m, enc, DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_REV4_SIZE);
        set_envelope(m, 0x0403u, 1297u);
        DF_CHECK(&t, decode_both(&t, kp, m, 1297u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH && inv == DFI_INV_NONE);
        DF_CHECK(&t, decode_both(&t, kq, m, 1297u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        DF_CHECK(&t, decode_both(&t, k1, m, 1297u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        /* A rev 5 state that says rev 1, 2, 3 or 4 is refused too, whatever the length says. */
        static const uint32_t older[] = {0x0103u, 0x0203u, 0x0303u, 0x0403u};
        for (size_t i = 0u; i < sizeof older / sizeof older[0]; ++i) {
            memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
            set_envelope(m, older[i], 1357u);
            DF_CHECK(&t, decode_both(&t, kp, m, 1357u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        }
        static const uint32_t unknown[] = {0u,      1u,      2u,      4u,      0x0100u, 0x0103u, 0x0104u, 0x0204u,
                                           0x0203u, 0x0303u, 0x0404u, 0x0504u, 0x0603u, 0x8203u, 0x8503u, 0xFFFFu};
        for (size_t i = 0u; i < sizeof unknown / sizeof unknown[0]; ++i) {
            memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
            set_envelope(m, unknown[i], 1357u);
            DF_CHECK(&t, decode_both(&t, kp, m, 1357u, &inv) == DUOFORGE_E_SCHEMA_MISMATCH);
        }
        /* Every length from 0 to 1356 bytes, and one byte more, is malformed (the length field says 1357). */
        unsigned not_malformed = 0u;
        for (size_t n = 0u; n <= 1356u; ++n) {
            not_malformed += decode_both(&t, kp, enc, n, NULL) != DUOFORGE_E_MALFORMED ? 1u : 0u;
        }
        memcpy(m, enc, DFI_STATE_POOL_ENCODED_SIZE);
        m[DFI_STATE_POOL_ENCODED_SIZE] = 0u;
        not_malformed += decode_both(&t, kp, m, DFI_STATE_POOL_ENCODED_SIZE + 1u, NULL) != DUOFORGE_E_MALFORMED ? 1u : 0u;
        DF_CHECK_EQ_U64(&t, not_malformed, 0u);
        /* An artifact of a POOL state is not the state of another kind: the fingerprint is. */
        DF_CHECK(&t, decode_both(&t, k1, enc, DFI_STATE_POOL_ENCODED_SIZE, NULL) == DUOFORGE_E_CONTEXT_MISMATCH);
        DF_CHECK(&t, decode_both(&t, kq, enc, DFI_STATE_POOL_ENCODED_SIZE, NULL) == DUOFORGE_E_CONTEXT_MISMATCH);

        /* A state of another kind with a tail appended and the pool schema: refused by the invariant, whatever the
         * tail holds (the all-zero one included), and the other way round for POOL. */
        const duoforge_context *kinds[4] = {k1, k2, kc, kd};
        for (size_t i = 0u; i < 4u; ++i) {
            duoforge_battle *b = turn_battle(&t, kinds[i], i >= 2u);
            uint8_t base[DF_STATE_ENCODED_MAX];
            DF_CHECK_EQ_U64(&t, df_encode_n(kinds[i], b, base), 1009u);
            for (unsigned with_tail = 0u; with_tail < 2u; ++with_tail) {
                memcpy(m, base, 1009u);
                memset(m + 1009u, 0, DFI_ENC_TAIL_SIZE);
                if (with_tail != 0u) {
                    DF_CHECK(&t, df_hex_to_bytes(TAIL_HEX, m + 1009u, DFI_ENC_TAIL_SIZE));
                }
                set_envelope(m, 0x0503u, 1357u);
                DF_CHECK(&t, decode_both(&t, kinds[i], m, 1357u, &inv) == DUOFORGE_E_MALFORMED &&
                                 inv == DFI_INV_TAIL_SCHEMA);
            }
            duoforge_battle_destroy(b);
        }
    }

    /* A tail in memory under the four other kinds (and the SYNTHETIC one): every byte of it is refused. The checker
     * says E_INVARIANT / TAIL_KIND, and check, encode and digest follow; with the byte cleared all of them pass. */
    {
        const duoforge_context *kinds[5] = {k1, k2, kc, kd, c1};
        for (size_t i = 0u; i < 5u; ++i) {
            duoforge_battle *b = i < 4u ? turn_battle(&t, kinds[i], i >= 2u) : df_make_f1(c1);
            unsigned refused = 0u;
            for (size_t k = 0u; k < sizeof b->tail; ++k) {
                *tail_byte(b, k) = 1u;
                dfi_invariant inv = DFI_INV_NONE;
                uint8_t out[DF_STATE_ENCODED_MAX];
                uint8_t dg[DUOFORGE_DIGEST_SIZE];
                size_t written = 77u;
                size_t size = 0u;
                if (dfi_state_check(kinds[i], b, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_TAIL_KIND &&
                    duoforge_battle_check(kinds[i], b) == DUOFORGE_E_INVARIANT &&
                    duoforge_battle_encode(kinds[i], b, out, sizeof out, &written) == DUOFORGE_E_INVARIANT &&
                    duoforge_battle_digest(kinds[i], b, dg) == DUOFORGE_E_INVARIANT &&
                    duoforge_battle_encoded_size(kinds[i], b, &size) == DUOFORGE_OK && size == 1009u && written == 77u) {
                    ++refused;
                }
                *tail_byte(b, k) = 0u;
            }
            DF_CHECK_EQ_U64(&t, refused, sizeof b->tail);
            DF_CHECK(&t, duoforge_battle_check(kinds[i], b) == DUOFORGE_OK);
            duoforge_battle_destroy(b);
        }
    }

    /* Under POOL the checks of the tail: a value out of range, a pair that is not zero together, a tail at a position
     * without a standing occupant, a member override where it cannot be. Each is E_INVARIANT with its id, the same
     * through the public check, and a step refuses it atomically. */
    {
        duoforge_battle *x = turn_battle(&t, kp, false);
        duoforge_battle *short_moves = NULL; /* side 1's lead has two moves: Politoed with Weather Ball and Muddy Water */
        {
            duoforge_battle_setup s;
            df_setup_teams(&s);
            s.sides[1].members[0].move_count = 2u;
            s.sides[1].members[0].moves[2].move_id = 0u;
            s.sides[1].members[0].moves[3].move_id = 0u;
            short_moves = df_make_battle(kp, &s);
            duoforge_decision_bundle bd;
            team_bundle(&bd, short_moves);
            step_ok(&t, kp, short_moves, &bd, "team selection (two moves)");
        }
        for (size_t i = 0u; i < sizeof cases / sizeof cases[0]; ++i) {
            duoforge_battle *y = NULL;
            DF_CHECK(&t, duoforge_battle_clone(kp, cases[i].short_side ? short_moves : x, &y) == DUOFORGE_OK && y != NULL);
            dfi_tail_side *ts = cases[i].short_side ? &y->tail.sides[1] : &y->tail.sides[0];
            cases[i].apply(y, ts, &ts->positions[0]);
            dfi_invariant inv = DFI_INV_NONE;
            const duoforge_status st = dfi_state_check(kp, y, &inv);
            const bool want_ok = cases[i].inv == DFI_INV_NONE;
            if (!DF_CHECK(&t, want_ok ? st == DUOFORGE_OK : (st == DUOFORGE_E_INVARIANT && inv == cases[i].inv))) {
                fprintf(stderr, "  %s: %s (%s), expected %s\n", cases[i].what, duoforge_status_name(st), inv_name(inv),
                        inv_name(cases[i].inv));
            }
            /* The same through the public API, and a step refuses it atomically. */
            DF_CHECK(&t, (duoforge_battle_check(kp, y) == DUOFORGE_OK) == want_ok);
            if (!want_ok) {
                uint8_t before[DF_STATE_ENCODED_MAX];
                uint8_t after[DF_STATE_ENCODED_MAX];
                const size_t n = dfi_encode_unchecked(kp, y, before);
                duoforge_decision_bundle bd;
                turn_bundle(&bd, y);
                duoforge_step_result res;
                DF_CHECK(&t, duoforge_battle_step(kp, y, &bd, &res) == DUOFORGE_E_INVARIANT);
                DF_CHECK_EQ_U64(&t, dfi_encode_unchecked(kp, y, after), n);
                DF_CHECK_BYTES(&t, after, before, n, "a refused step changes nothing");
            }
            duoforge_battle_destroy(y);
        }
        /* step G56: a lock without its locked move is refused by the decoder as the tail's (TAIL_POSITION), as Rage Powder's
         * marker without its Follow Me flag: the encoded lock of a battle whose slot holds no locked move. */
        {
            duoforge_battle *z = NULL;
            DF_CHECK(&t, duoforge_battle_clone(kp, x, &z) == DUOFORGE_OK && z != NULL);
            z->tail.sides[0].positions[0].lock_turns = 2u;
            uint8_t enc_z[DF_STATE_ENCODED_MAX];
            const size_t nz = dfi_encode_unchecked(kp, z, enc_z);
            dfi_invariant inv_z = DFI_INV_NONE;
            DF_CHECK_EQ_U64(&t, decode_both(&t, kp, enc_z, nz, &inv_z), DUOFORGE_E_MALFORMED);
            DF_CHECK_EQ_U64(&t, inv_z, DFI_INV_TAIL_POSITION);
            duoforge_battle_destroy(z);
        }
        duoforge_battle_destroy(short_moves);
        duoforge_battle_destroy(x);
    }

    /* A position without a standing occupant has no tail at all: every byte of a position's tail, set alone at an
     * empty and at a fainted position, is TAIL_POSITION. */
    {
        duoforge_battle *x = turn_battle(&t, kp, false);
        unsigned refused = 0u;
        for (unsigned fainted = 0u; fainted < 2u; ++fainted) {
            for (size_t k = 0u; k < sizeof(dfi_tail_pos); ++k) {
                duoforge_battle *y = NULL;
                DF_CHECK(&t, duoforge_battle_clone(kp, x, &y) == DUOFORGE_OK && y != NULL);
                if (fainted != 0u) {
                    y->sides[0].members[1].hp = 0u;
                    df_knowledge_refresh_active(y);
                } else {
                    dfi_slot_clear(&y->sides[0].positions[1]);
                    y->sides[0].requested_slots = 1u;
                }
                ((uint8_t *)&y->tail.sides[0].positions[1])[k] = 1u;
                dfi_invariant inv = DFI_INV_NONE;
                refused += dfi_state_check(kp, y, &inv) == DUOFORGE_E_INVARIANT && inv == DFI_INV_TAIL_POSITION ? 1u : 0u;
                duoforge_battle_destroy(y);
            }
        }
        DF_CHECK_EQ_U64(&t, refused, 2u * sizeof(dfi_tail_pos));
        duoforge_battle_destroy(x);
    }

    /* What leaves with the occupant (dfi_tail_clear_occupant): the position, the soak type, the current ability and
     * the toxic stage of the member; the current item and forme stay. */
    {
        duoforge_battle *x = turn_battle(&t, kp, false);
        set_example_tail(x);
        const uint32_t occupant = x->sides[0].positions[0].occupant;
        x->tail.sides[0].toxic_stage[occupant] = 7u; /* not valid as a state, but what the clearing must reach */
        dfi_tail_clear_occupant(x, 0u);
        const dfi_tail_side *ts = &x->tail.sides[0];
        const dfi_tail_pos zero = {0};
        DF_CHECK(&t, memcmp(&ts->positions[0], &zero, sizeof zero) == 0);
        DF_CHECK(&t, memcmp(&ts->positions[1], &zero, sizeof zero) != 0); /* the ally keeps its tail */
        DF_CHECK(&t, ts->soak_type[occupant] == 0u && ts->ability_now[occupant] == 0u && ts->toxic_stage[occupant] == 0u);
        /* tail rev 4: the second type goes with the occupant, the ally's stays, the member flags outlive the field */
        DF_CHECK(&t, ts->type2[occupant] == 0u && ts->type2[1] == DFI_TAIL_TYPE2_TYPELESS);
        DF_CHECK(&t, ts->member_flags[occupant] == DFI_TAIL_MEMBER_FLAG_HERO_SHOWN);
        DF_CHECK(&t, ts->item_now[occupant] == 12u && ts->forme_now[occupant] == 300u);
        DF_CHECK(&t, ts->soak_type[1] == 18u && ts->ability_now[1] == DFI_POOL_ABILITY_COUNT); /* the ally's member */
        DF_CHECK(&t, x->tail.sides[1].positions[0].last_move == 4u && x->tail.gravity_turns == 5u && ts->spikes == 3u);
        duoforge_battle_destroy(x);
    }

    /* A valid tail passes through a step: the residual counts the Throat Chop and Heal Block timers of every position
     * down by one (step G8) and ends the wide guard of both sides (step G7: a side condition of duration 1), and
     * nothing else of it changes (the field, the other side conditions, the other volatiles and the member overrides
     * stay: nothing in this turn ends them). The last move and Encore are written by the step too (step G9: every move
     * used sets the last move, an Encore locks the request to its slot and counts down): the example of this block has
     * neither, they are tested in test_pool_g9.c; nor does it have a Pokemon that must recharge (step G17, test_pool_g17.c:
     * its request is the recharge turn alone). The soak types of the example (Fighting and Water on the leads, which
     * the types now read: step G11) keep the turn from ending in a knock-out before its residual. */
    {
        duoforge_battle *x = turn_battle(&t, kp, false);
        set_example_tail(x);
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                dfi_tail_pos *tp = &x->tail.sides[s].positions[p];
                tp->last_move = 0u;
                tp->encore_slot = 0u;
                tp->encore_turns = 0u;
                tp->must_recharge = 0u; /* step G17: a Pokemon that must recharge is offered the recharge only */
                tp->glaive_rush = 0u;   /* step G19: the first BeforeMove of a Pokemon ends it (test_pool_g19.c) */
                /* step G56: the example's locks are not this step's turn (a locked move is forced, and its count goes down; the
                 * lock is tested by test_pool_g56.c): the lock and its move in the body are cleared together. */
                tp->lock_turns = 0u;
                x->sides[s].positions[p].locked_move = 0u;
                if (tp->perish == 1u) {
                    tp->perish = 0u; /* step G26: a count of 1 ends in the residual: the holder faints (test_pool_g26.c) */
                }
            }
        }
        dfi_pool_tail want = x->tail;
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            want.sides[s].wide_guard = 0u;
            /* step G20: Aurora Veil counts down in the residual (the example's 8 turns are 7 after the turn) */
            want.sides[s].aurora_veil_turns = (uint8_t)(want.sides[s].aurora_veil_turns != 0u ? want.sides[s].aurora_veil_turns - 1u : 0u);
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                dfi_tail_pos *tp = &want.sides[s].positions[p];
                tp->throat_chop_turns = (uint8_t)(tp->throat_chop_turns != 0u ? tp->throat_chop_turns - 1u : 0u);
                tp->heal_block_turns = (uint8_t)(tp->heal_block_turns != 0u ? tp->heal_block_turns - 1u : 0u);
                /* step G31: Taunt and Yawn count down in the residual (a Yawn that runs out puts its holder to sleep) */
                tp->taunt_turns = (uint8_t)(tp->taunt_turns != 0u ? tp->taunt_turns - 1u : 0u);
                tp->yawn_turns = (uint8_t)(tp->yawn_turns != 0u ? tp->yawn_turns - 1u : 0u);
                tp->perish = (uint8_t)(tp->perish != 0u ? tp->perish - 1u : 0u); /* step G26: the residual's count */
                /* step G27: Disable counts down in the residual (the example's 5 turns are 4 after the turn, its slot stays) */
                tp->disable_turns = (uint8_t)(tp->disable_turns != 0u ? tp->disable_turns - 1u : 0u);
            }
        }
        duoforge_decision_bundle bd;
        turn_bundle(&bd, x);
        /* step G48: timesAttacked, the tail's hits_taken, counts the damaging hits of a move on the position it hit (saturating
         * at 6). The hits are the step's own move damage: the public DAMAGE events with cause NONE (the events are public, so
         * player 0's buffer has every one of them). */
        static duoforge_event hit_ev[2][DUOFORGE_MAX_EVENTS];
        duoforge_event_buffer hit_buffers[2] = {{hit_ev[0], DUOFORGE_MAX_EVENTS, 0u}, {hit_ev[1], DUOFORGE_MAX_EVENTS, 0u}};
        duoforge_step_result hit_res;
        DF_CHECK(&t, duoforge_battle_step_events(kp, x, &bd, &hit_res, hit_buffers) == DUOFORGE_OK);
        uint32_t landed[DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE] = {0u, 0u, 0u, 0u};
        for (uint32_t k = 0u; k < hit_buffers[0].count; ++k) {
            const duoforge_event *e = &hit_buffers[0].events[k];
            if (e->kind == (uint8_t)DUOFORGE_EVENT_DAMAGE && e->cause == (uint8_t)DUOFORGE_CAUSE_NONE && e->position < 4u) {
                landed[e->position] += 1u;
            }
        }
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                const uint32_t before_hits = want.sides[s].positions[p].hits_taken;
                const uint32_t after_hits = before_hits + landed[s * DUOFORGE_ACTIVE_PER_SIDE + p];
                want.sides[s].positions[p].hits_taken = (uint8_t)(after_hits > DFI_TAIL_HITS_TAKEN_MAX ? DFI_TAIL_HITS_TAKEN_MAX : after_hits);
                /* each position that acted used slot 0 (turn_bundle's plan): last_move 1; one that did not has none */
                DF_CHECK(&t, x->tail.sides[s].positions[p].last_move <= 1u);
                want.sides[s].positions[p].last_move = x->tail.sides[s].positions[p].last_move;
            }
        }
        DF_CHECK(&t, memcmp(&x->tail, &want, sizeof want) == 0);
        DF_CHECK(&t, duoforge_battle_check(kp, x) == DUOFORGE_OK);
        duoforge_battle_destroy(x);
    }

    /* The rev 5 block (tail rev 5, decision 0026): the codec's own mapping carries every byte of it to its place. The checked
     * encoder never writes these bytes (no state can hold them: the invariant refuses them), so this uses the unchecked one,
     * whose output the decoder then refuses byte by byte in the sweep above. Every byte of the Illusion state of each side and
     * the two lane A bytes of each position, with a distinct nonzero value. */
    {
        duoforge_battle *x = turn_battle(&t, kp, false);
        uint8_t out[DF_STATE_ENCODED_MAX];
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            uint8_t *ill = (uint8_t *)&x->tail.sides[s].illusion;
            for (uint32_t i = 0u; i < sizeof x->tail.sides[s].illusion; ++i) {
                ill[i] = (uint8_t)(0x40u + 0x10u * s + i);
            }
        }
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            dfi_tail_pos *tp = &x->tail.sides[p / DUOFORGE_ACTIVE_PER_SIDE].positions[p % DUOFORGE_ACTIVE_PER_SIDE];
            tp->slot_pending = (uint8_t)(0x80u + p);
            tp->future_sight = (uint8_t)(0xC0u + p);
        }
        DF_CHECK_EQ_U64(&t, dfi_encode_unchecked(kp, x, out), DFI_STATE_POOL_ENCODED_SIZE);
        const size_t r5 = DFI_ENC_TAIL_OFF + DFI_ENC_TAIL_REV4_SIZE;
        for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
            const uint8_t *ill = (const uint8_t *)&x->tail.sides[s].illusion;
            DF_CHECK_BYTES(&t, out + r5 + DFI_ENC_TAIL5_SIDES_OFF + s * DFI_ENC_TAIL5_SIDE_SIZE, ill, DFI_ENC_TAIL5_SIDE_SIZE,
                           "the Illusion state of a side, at its place of the rev 5 block");
        }
        for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const dfi_tail_pos *tp = &x->tail.sides[p / DUOFORGE_ACTIVE_PER_SIDE].positions[p % DUOFORGE_ACTIVE_PER_SIDE];
            const uint8_t *po = out + r5 + DFI_ENC_TAIL5_POS_OFF + p * DFI_ENC_TAIL5_POS_SIZE;
            DF_CHECK(&t, po[DFI_ENC_TAIL5_SLOT_PENDING_OFF] == tp->slot_pending);
            DF_CHECK(&t, po[DFI_ENC_TAIL5_FUTURE_SIGHT_OFF] == tp->future_sight);
        }
        /* and the reserve after them is zero, whatever the block holds */
        for (uint32_t i = 0u; i < DFI_ENC_TAIL5_RESERVED_SIZE; ++i) {
            DF_CHECK(&t, out[r5 + DFI_ENC_TAIL5_RESERVED_OFF + i] == 0u);
        }
        /* the state holds values that no state can yet: the checked path refuses it */
        DF_CHECK(&t, dfi_state_check(kp, x, NULL) == DUOFORGE_E_INVARIANT);
        duoforge_battle_destroy(x);
    }

    /* Capacity: a POOL state needs its 1357 bytes, the others 1009; POOL_DEV is a POOL kind. */
    {
        uint8_t big[DF_STATE_ENCODED_MAX];
        size_t written = 0u;
        DF_CHECK(&t, duoforge_battle_encode(kp, w, big, 1009u, &written) == DUOFORGE_E_CAPACITY);
        DF_CHECK(&t, duoforge_battle_encode(kp, w, big, 1051u, &written) == DUOFORGE_E_CAPACITY); /* rev 1's size */
        DF_CHECK(&t, duoforge_battle_encode(kp, w, big, 1257u, &written) == DUOFORGE_E_CAPACITY); /* rev 3's size */
        DF_CHECK(&t, duoforge_battle_encode(kp, w, big, 1297u, &written) == DUOFORGE_E_CAPACITY); /* rev 4's size */
        DF_CHECK(&t, duoforge_battle_encode(kp, w, big, 1356u, &written) == DUOFORGE_E_CAPACITY);
        DF_CHECK(&t, duoforge_battle_encode(kp, w, big, 1357u, &written) == DUOFORGE_OK && written == 1357u);
        duoforge_battle *q = turn_battle(&t, kq, false);
        set_example_tail(q);
        DF_CHECK(&t, duoforge_battle_encode(kq, q, big, 1357u, &written) == DUOFORGE_OK && written == 1357u);
        DF_CHECK(&t, duoforge_battle_check(kq, q) == DUOFORGE_OK);
        duoforge_battle_destroy(q);
        duoforge_battle *b1 = turn_battle(&t, k1, false);
        DF_CHECK(&t, duoforge_battle_encode(k1, b1, big, 1008u, &written) == DUOFORGE_E_CAPACITY);
        DF_CHECK(&t, duoforge_battle_encode(k1, b1, big, 1009u, &written) == DUOFORGE_OK && written == 1009u);
        duoforge_battle_destroy(b1);
    }

    duoforge_battle_destroy(w);
    duoforge_context_destroy(k1);
    duoforge_context_destroy(k2);
    duoforge_context_destroy(kc);
    duoforge_context_destroy(kd);
    duoforge_context_destroy(kp);
    duoforge_context_destroy(kq);
    duoforge_context_destroy(c1);
    return df_test_end(&t);
}
