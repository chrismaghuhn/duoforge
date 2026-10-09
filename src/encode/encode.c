/*
 * The observation encoder (decision 0021): python/duoforge/features.py in C,
 * byte for byte. The reference is the authority; this file follows its
 * structure (global, block, sides, slots, pair mask) and its order of checks,
 * and each value is computed with the reference's recipe:
 *   r64(x, d) = (float)((double)x / d)   a float64 division rounded once,
 *   r32(x, d) = (float)x / (float)d      a float32 division,
 * as the comment of each group says. Only exactly rounded IEEE-754 operations
 * (conversion, division, comparison); no expression multiplies and adds, and
 * nothing may contract: FP_CONTRACT is off here (and -ffp-contract=off in
 * CMakeLists.txt for GCC and Clang), no -ffast-math anywhere, MSVC keeps
 * /fp:precise, and a compiler with excess precision (x87) is refused at
 * compile time, as in src/state/tiebreak.c.
 */
#include <duoforge/duoforge_encode.h>

#include <float.h>
#include <stdbool.h>
#include <string.h>

#include "batch/batch_each.h"
#include "encode/encode_internal.h"

#if defined(FLT_EVAL_METHOD) && FLT_EVAL_METHOD != 0
#error "encode.c needs float32 and float64 arithmetic without excess precision (FLT_EVAL_METHOD 0, SSE2 on x86)"
#endif
#if defined(_M_IX86) && (!defined(_M_IX86_FP) || _M_IX86_FP < 2)
#error "encode.c needs SSE2 on 32-bit x86 (/arch:SSE2), not x87"
#endif
#if defined(__clang__)
#pragma STDC FP_CONTRACT OFF
#elif defined(_MSC_VER)
#pragma fp_contract(off)
#endif

_Static_assert(sizeof(float) == sizeof(uint32_t) && sizeof(double) == sizeof(uint64_t),
               "the encoder needs IEEE-754 binary32 and binary64");

/* features.py sizes: _GLOBAL, _SIDE, _POSITION, _MEMBER, _SIDE_SIZE, BASE_OBS_SIZE, _EXT_SIDE, EXT_SIZE. */
#define DFI_ENC_GLOBAL    15u
#define DFI_ENC_HEAD      8u
#define DFI_ENC_POSITION  24u
#define DFI_ENC_MEMBER    40u
#define DFI_ENC_SIDE      (DFI_ENC_HEAD + DUOFORGE_ACTIVE_PER_SIDE * DFI_ENC_POSITION + DUOFORGE_MAX_ROSTER * DFI_ENC_MEMBER)
#define DFI_ENC_BASE      (DFI_ENC_GLOBAL + DUOFORGE_SIDE_COUNT * DFI_ENC_SIDE)
#define DFI_ENC_EXT_POS   36u
#define DFI_ENC_EXT_MEM   6u
#define DFI_ENC_EXT_SIDE  (7u + DUOFORGE_ACTIVE_PER_SIDE * DFI_ENC_EXT_POS + DUOFORGE_MAX_ROSTER * DFI_ENC_EXT_MEM)
#define DFI_ENC_EXT       (5u + DUOFORGE_SIDE_COUNT * DFI_ENC_EXT_SIDE)
#define DFI_ENC_V3        (DFI_ENC_BASE + DFI_ENC_EXT)
#define DFI_ENC_V4        (DFI_ENC_V3 + DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE * 2u)
#define DFI_ENC_V5        (DFI_ENC_V4 + DUOFORGE_SIDE_COUNT * DUOFORGE_ACTIVE_PER_SIDE * 3u)
/* encoder 3's volatile columns (bits 0 to 19); bit 20 (ROOST) is an appended column of encoder 4 */
#define DFI_ENC_VOLATILES 20u
/* the volatile bits a record may hold: 0 to 21; bit 21 (TRANSFORMED) has columns from encoder 5 only (decision 0028 B) */
#define DFI_ENC_VOLATILE_BITS 22u
#define DFI_ENC_ALL       ((UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_TRANSFORM) - 1u) /* encoder 4: bits 0 to 41 (decision 0028 adds 42 for encoder 5) */
#define DFI_ENC_APPENDED  ((UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_ROOST) | (UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_MOVE_FAILED))
#define DFI_ENC_ALL5      ((UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_COUNT) - 1u) /* encoder 5: all bits through TRANSFORM (42) */

typedef char dfi_enc_size_check[(DFI_ENC_BASE == 607u && DFI_ENC_V3 == 842u && DFI_ENC_V4 == 850u && DFI_ENC_V5 == 862u &&
                                 DUOFORGE_VIEWEXT_FEATURE_COUNT == 43u) ? 1 : -1];

/* The feature bits a version has columns for (features.version_features). */
static uint64_t dfi_version_features(uint32_t version)
{
    return version >= 5u ? DFI_ENC_ALL5 : version == 4u ? DFI_ENC_ALL : version == 3u ? (DFI_ENC_ALL & ~DFI_ENC_APPENDED) : 0u;
}

/* The feature bits read from the observation itself (BASE_VALUE_FEATURES). */
#define DFI_BIT(name) (UINT64_C(1) << DUOFORGE_VIEWEXT_FEATURE_##name)
#define DFI_ENC_BASE_VALUES \
    (DFI_BIT(WEATHER_SAND) | DFI_BIT(WEATHER_SNOW) | DFI_BIT(TERRAIN_ELECTRIC) | DFI_BIT(TERRAIN_MISTY) | DFI_BIT(AILMENT_TOX))

/* The feature of each volatiles bit, bit 0 first (features.VOLATILES). */
static const uint8_t dfi_enc_volatile_feature[DFI_ENC_VOLATILES] = {
    DUOFORGE_VIEWEXT_FEATURE_SUBSTITUTE,   DUOFORGE_VIEWEXT_FEATURE_TAUNT,         DUOFORGE_VIEWEXT_FEATURE_IMPRISON,
    DUOFORGE_VIEWEXT_FEATURE_LEECH_SEED,   DUOFORGE_VIEWEXT_FEATURE_YAWN,          DUOFORGE_VIEWEXT_FEATURE_FOCUS_ENERGY,
    DUOFORGE_VIEWEXT_FEATURE_DRAGON_CHEER, DUOFORGE_VIEWEXT_FEATURE_MUST_RECHARGE, DUOFORGE_VIEWEXT_FEATURE_PARTIAL_TRAP,
    DUOFORGE_VIEWEXT_FEATURE_GLAIVE_RUSH,  DUOFORGE_VIEWEXT_FEATURE_DESTINY_BOND,  DUOFORGE_VIEWEXT_FEATURE_CURSE,
    DUOFORGE_VIEWEXT_FEATURE_NO_RETREAT,   DUOFORGE_VIEWEXT_FEATURE_SALT_CURE,     DUOFORGE_VIEWEXT_FEATURE_CHARGE,
    DUOFORGE_VIEWEXT_FEATURE_HEAL_BLOCK,   DUOFORGE_VIEWEXT_FEATURE_THROAT_CHOP,   DUOFORGE_VIEWEXT_FEATURE_RAGE_POWDER,
    DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE,  DUOFORGE_VIEWEXT_FEATURE_ILLUSION,
};

static float dfi_r64(uint32_t x, double d)
{
    return (float)((double)x / d);
}

static float dfi_r32(uint32_t x, float d)
{
    return (float)x / d;
}

static float dfi_bool(bool b)
{
    return b ? 1.0f : 0.0f;
}

/* One-hot over `count` known values; a value whose feature bit is in `shown`
   (the mask's new values) gives an all-zero row. E_UNSUPPORTED for a new
   value without its bit, E_INVALID_ARGUMENT for any other value. */
typedef struct dfi_enc_values {
    const uint8_t *known;
    uint32_t count;
    const uint8_t *added;     /* the new values of decision 0018 */
    const uint8_t *added_bit; /* their feature bits */
    uint32_t added_count;
} dfi_enc_values;

static duoforge_status dfi_one_hot(const dfi_enc_values *v, uint8_t value, uint64_t mask, float *out)
{
    for (uint32_t k = 0u; k < v->count; ++k) {
        out[k] = 0.0f;
    }
    for (uint32_t k = 0u; k < v->count; ++k) {
        if (v->known[k] == value) {
            out[k] = 1.0f;
            return DUOFORGE_OK;
        }
    }
    for (uint32_t k = 0u; k < v->added_count; ++k) {
        if (v->added[k] == value) {
            return ((mask >> v->added_bit[k]) & 1u) != 0u ? DUOFORGE_OK : DUOFORGE_E_UNSUPPORTED;
        }
    }
    return DUOFORGE_E_INVALID_ARGUMENT;
}

static const uint8_t dfi_boundaries[] = {DUOFORGE_BOUNDARY_TEAM_SELECTION, DUOFORGE_BOUNDARY_TURN,
                                         DUOFORGE_BOUNDARY_REPLACEMENT, DUOFORGE_BOUNDARY_PIVOT,
                                         DUOFORGE_BOUNDARY_TERMINAL};
static const uint8_t dfi_weathers[] = {DUOFORGE_WEATHER_NONE, DUOFORGE_WEATHER_RAIN, DUOFORGE_WEATHER_SUN};
static const uint8_t dfi_weathers_new[] = {DUOFORGE_WEATHER_SAND, DUOFORGE_WEATHER_SNOW};
static const uint8_t dfi_weathers_bit[] = {DUOFORGE_VIEWEXT_FEATURE_WEATHER_SAND, DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW};
static const uint8_t dfi_terrains[] = {DUOFORGE_TERRAIN_NONE, DUOFORGE_TERRAIN_GRASSY, DUOFORGE_TERRAIN_PSYCHIC};
static const uint8_t dfi_terrains_new[] = {DUOFORGE_TERRAIN_ELECTRIC, DUOFORGE_TERRAIN_MISTY};
static const uint8_t dfi_terrains_bit[] = {DUOFORGE_VIEWEXT_FEATURE_TERRAIN_ELECTRIC,
                                           DUOFORGE_VIEWEXT_FEATURE_TERRAIN_MISTY};
static const uint8_t dfi_locations[] = {DUOFORGE_LOCATION_UNDETERMINED, DUOFORGE_LOCATION_BENCH,
                                        DUOFORGE_LOCATION_ACTIVE, DUOFORGE_LOCATION_NOT_BROUGHT};
static const uint8_t dfi_ailments[] = {DUOFORGE_AILMENT_NONE,      DUOFORGE_AILMENT_BURN,  DUOFORGE_AILMENT_FREEZE,
                                       DUOFORGE_AILMENT_PARALYSIS, DUOFORGE_AILMENT_SLEEP, DUOFORGE_AILMENT_POISON};
static const uint8_t dfi_ailments_new[] = {DUOFORGE_AILMENT_TOX};
static const uint8_t dfi_ailments_bit[] = {DUOFORGE_VIEWEXT_FEATURE_AILMENT_TOX};
static const uint8_t dfi_occupants[] = {0u, 1u, 2u, 3u, 4u, 5u, DUOFORGE_ROSTER_NONE};
static const uint8_t dfi_slot_kinds[] = {DUOFORGE_SLOT_NONE, DUOFORGE_SLOT_MOVE, DUOFORGE_SLOT_SWITCH,
                                         DUOFORGE_SLOT_PASS};

static const dfi_enc_values dfi_v_boundary = {dfi_boundaries, 5u, NULL, NULL, 0u};
static const dfi_enc_values dfi_v_weather = {dfi_weathers, 3u, dfi_weathers_new, dfi_weathers_bit, 2u};
static const dfi_enc_values dfi_v_terrain = {dfi_terrains, 3u, dfi_terrains_new, dfi_terrains_bit, 2u};
static const dfi_enc_values dfi_v_location = {dfi_locations, 4u, NULL, NULL, 0u};
static const dfi_enc_values dfi_v_ailment = {dfi_ailments, 6u, dfi_ailments_new, dfi_ailments_bit, 1u};
static const dfi_enc_values dfi_v_occupant = {dfi_occupants, 7u, NULL, NULL, 0u};
static const dfi_enc_values dfi_v_slot_kind = {dfi_slot_kinds, 4u, NULL, NULL, 0u};

/* ------------------------------------------------------------ records */

/* _check_records for one row: whether its record is present (revision 1). */
static duoforge_status dfi_check_record(const duoforge_observation *ob, const duoforge_observation_ext *ext,
                                        uint64_t mask, bool *present)
{
    *present = false;
    if (ext->revision == 0u) {
        const uint8_t *bytes = (const uint8_t *)ext;
        for (size_t k = 0u; k < sizeof *ext; ++k) {
            if (bytes[k] != 0u) {
                return DUOFORGE_E_INVALID_ARGUMENT; /* a revision-0 record must be all zero */
            }
        }
        return DUOFORGE_OK;
    }
    if (ext->revision != DUOFORGE_OBSERVATION_EXT_REVISION) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (ext->player != ob->player || ext->epoch != ob->epoch) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if ((mask & ~ext->supported) != 0u) {
        return DUOFORGE_E_UNSUPPORTED; /* a mask bit the records' library does not support */
    }
    bool bad = ext->field.gravity_turns > 5u;
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT; ++s) {
        const duoforge_side_ext *x = &ext->sides[s];
        bad = bad || x->aurora_veil_turns > 8u || x->stealth_rock > 1u || x->spikes > 3u || x->toxic_spikes > 2u ||
              x->sticky_web > 1u;
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
            const duoforge_position_ext *q = &x->positions[p];
            bad = bad || q->encore_slot > 4u || q->disable_slot > 4u || q->stockpile > 3u || q->perish > 3u ||
                  q->move_failed > 1u || q->ability_now > 255u || q->type_now[0] > 18u || q->type_now[1] > 18u;
        }
    }
    for (uint32_t s = 0u; s < DUOFORGE_SIDE_COUNT && !bad; ++s) {
        const duoforge_side_ext *x = &ext->sides[s];
        bad = (x->guard_flags & ~(DUOFORGE_SIDE_GUARD_WIDE_GUARD | DUOFORGE_SIDE_GUARD_QUICK_GUARD)) != 0u;
        for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE && !bad; ++p) {
            const duoforge_position_ext *q = &x->positions[p];
            bad = (q->volatiles >> DFI_ENC_VOLATILE_BITS) != 0u;
            /* decision 0028 A: a source exactly when TRANSFORMED is set, and the source is side * 6 + roster + 1 with a side of 0 or 1 */
            bad = bad || (q->transform_source != 0u) != ((q->volatiles & DUOFORGE_POSITION_EXT_TRANSFORMED) != 0u) ||
                  q->transform_source > 12u;
            bad = bad || ((q->type_now[0] != 0u || q->type_now[1] != 0u) &&
                          (q->volatiles & DUOFORGE_POSITION_EXT_TYPE_CHANGED) == 0u);
        }
    }
    if (bad) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    *present = true;
    return DUOFORGE_OK;
}

/* ------------------------------------------------------------ the block */

/* Writes value into *o when bit is in mask, else 0 (the block's mask). */
static void dfi_put(float *o, uint64_t mask, uint32_t bit, float value)
{
    *o = ((mask >> bit) & 1u) != 0u ? value : 0.0f;
}

/* One side's block columns (_ext_block) for absolute side `abs`. x NULL: no
   record (ext NULL: zero; empty: the "none" of Encore and Disable). */
static void dfi_ext_side(const duoforge_observation *ob, const duoforge_side_ext *x, bool empty, uint32_t abs,
                         uint64_t mask, float *o)
{
    const uint8_t guards = x != NULL ? x->guard_flags : 0u;
    /* head: r64 for the counts, raw 0/1 values */
    dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_AURORA_VEIL, x != NULL ? dfi_r64(x->aurora_veil_turns, 8.0) : 0.0f);
    dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_STEALTH_ROCK, x != NULL ? (float)x->stealth_rock : 0.0f);
    dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_SPIKES, x != NULL ? dfi_r64(x->spikes, 3.0) : 0.0f);
    dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_TOXIC_SPIKES, x != NULL ? dfi_r64(x->toxic_spikes, 2.0) : 0.0f);
    dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_STICKY_WEB, x != NULL ? (float)x->sticky_web : 0.0f);
    dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_WIDE_GUARD, dfi_bool((guards & DUOFORGE_SIDE_GUARD_WIDE_GUARD) != 0u));
    dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_QUICK_GUARD,
            dfi_bool((guards & DUOFORGE_SIDE_GUARD_QUICK_GUARD) != 0u));
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        const duoforge_position_ext *q = x != NULL ? &x->positions[p] : NULL;
        for (uint32_t b = 0u; b < DFI_ENC_VOLATILES; ++b) {
            dfi_put(o++, mask, dfi_enc_volatile_feature[b], dfi_bool(q != NULL && ((q->volatiles >> b) & 1u) != 0u));
        }
        /* encore and disable slot one-hots: index = slot + 1, 0 = none (an empty record: none) */
        const uint32_t encore = q != NULL ? q->encore_slot : 0u;
        const uint32_t disable = q != NULL ? q->disable_slot : 0u;
        const bool hot = q != NULL || empty;
        for (uint32_t k = 0u; k < 5u; ++k) {
            dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_ENCORE, dfi_bool(hot && encore == k));
        }
        for (uint32_t k = 0u; k < 5u; ++k) {
            dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_DISABLE, dfi_bool(hot && disable == k));
        }
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_STOCKPILE, q != NULL ? dfi_r64(q->stockpile, 3.0) : 0.0f);
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_PERISH, q != NULL ? dfi_r64(q->perish, 3.0) : 0.0f);
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_ABILITY_CHANGE, dfi_bool(q != NULL && q->ability_now != 0u));
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_ABILITY_CHANGE, q != NULL ? dfi_r64(q->ability_now, 255.0) : 0.0f);
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE, q != NULL ? dfi_r64(q->type_now[0], 18.0) : 0.0f);
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_TYPE_CHANGE, q != NULL ? dfi_r64(q->type_now[1], 18.0) : 0.0f);
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        const duoforge_member_ext *r = x != NULL ? &x->members[m] : NULL;
        /* tox: from the observation, record or not */
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_AILMENT_TOX,
                dfi_bool(ob->sides[abs].members[m].status == DUOFORGE_AILMENT_TOX));
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_FORME_CHANGE, dfi_bool(r != NULL && r->forme != 0u));
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_FORME_CHANGE, r != NULL ? dfi_r64(r->forme, 65535.0) : 0.0f);
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE, dfi_bool(r != NULL && r->item_now != 0u));
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE,
                dfi_bool(r != NULL && r->item_now == DUOFORGE_ITEM_NOW_NONE));
        dfi_put(o++, mask, DUOFORGE_VIEWEXT_FEATURE_ITEM_CHANGE, r != NULL ? dfi_r64(r->item_now, 255.0) : 0.0f);
    }
}

static void dfi_block(const duoforge_observation *ob, const duoforge_observation_ext *ext, bool present,
                      uint64_t mask, uint32_t version, float *o)
{
    dfi_put(&o[0], mask, DUOFORGE_VIEWEXT_FEATURE_WEATHER_SAND, dfi_bool(ob->weather == DUOFORGE_WEATHER_SAND));
    dfi_put(&o[1], mask, DUOFORGE_VIEWEXT_FEATURE_WEATHER_SNOW, dfi_bool(ob->weather == DUOFORGE_WEATHER_SNOW));
    dfi_put(&o[2], mask, DUOFORGE_VIEWEXT_FEATURE_TERRAIN_ELECTRIC,
            dfi_bool(ob->terrain == DUOFORGE_TERRAIN_ELECTRIC));
    dfi_put(&o[3], mask, DUOFORGE_VIEWEXT_FEATURE_TERRAIN_MISTY, dfi_bool(ob->terrain == DUOFORGE_TERRAIN_MISTY));
    dfi_put(&o[4], mask, DUOFORGE_VIEWEXT_FEATURE_GRAVITY, present ? dfi_r64(ext->field.gravity_turns, 5.0) : 0.0f);
    const uint32_t viewer = ob->player;
    for (uint32_t k = 0u; k < DUOFORGE_SIDE_COUNT; ++k) {
        const uint32_t abs = k == 0u ? viewer : 1u - viewer; /* own first */
        dfi_ext_side(ob, present ? &ext->sides[abs] : NULL, ext != NULL && !present, abs, mask,
                     &o[5u + k * DFI_ENC_EXT_SIDE]);
    }
    if (version >= 4u) { /* appended by encoder 4: per side (own first) and position, Roost and move_failed */
        float *a = &o[DFI_ENC_EXT];
        for (uint32_t k = 0u; k < DUOFORGE_SIDE_COUNT; ++k) {
            const uint32_t abs = k == 0u ? viewer : 1u - viewer;
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                const duoforge_position_ext *q = present ? &ext->sides[abs].positions[p] : NULL;
                dfi_put(a++, mask, DUOFORGE_VIEWEXT_FEATURE_ROOST,
                        dfi_bool(q != NULL && (q->volatiles & DUOFORGE_POSITION_EXT_ROOST) != 0u));
                dfi_put(a++, mask, DUOFORGE_VIEWEXT_FEATURE_MOVE_FAILED, q != NULL ? (float)q->move_failed : 0.0f);
            }
        }
    }
    if (version >= 5u) { /* appended by encoder 5 (decision 0028 A): per side (own first) and position: transformed, the
                            source is a foe, the source roster / 5; all zero when not transformed */
        float *t = &o[DFI_ENC_EXT + 8u];
        for (uint32_t k = 0u; k < DUOFORGE_SIDE_COUNT; ++k) {
            const uint32_t abs = k == 0u ? viewer : 1u - viewer;
            for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
                const duoforge_position_ext *q = present ? &ext->sides[abs].positions[p] : NULL;
                const bool tr = q != NULL && (q->volatiles & DUOFORGE_POSITION_EXT_TRANSFORMED) != 0u;
                const uint32_t src = tr ? (uint32_t)q->transform_source - 1u : 0u; /* side * 6 + roster */
                dfi_put(t++, mask, DUOFORGE_VIEWEXT_FEATURE_TRANSFORM, dfi_bool(tr));
                dfi_put(t++, mask, DUOFORGE_VIEWEXT_FEATURE_TRANSFORM, dfi_bool(tr && src / 6u != viewer));
                dfi_put(t++, mask, DUOFORGE_VIEWEXT_FEATURE_TRANSFORM, tr ? dfi_r64(src % 6u, 5.0) : 0.0f);
            }
        }
    }
}

/* ------------------------------------------------------------ the sides */

/* _sides for one side view: the head, the positions and the members. tox:
   Tox is a known status. version 1 takes present from the species id. */
static duoforge_status dfi_side(const duoforge_side_view *s, uint64_t mask, uint32_t version, float *o)
{
    /* head: r64, raw values exact */
    o[0] = dfi_r64(s->member_count, 6.0);
    o[1] = (float)s->mega_used;
    o[2] = (float)s->requested;
    o[3] = (float)(s->requested_slots & 1u);
    o[4] = (float)((s->requested_slots >> 1) & 1u);
    o[5] = dfi_r64(s->reflect_turns, 8.0);
    o[6] = dfi_r64(s->light_screen_turns, 8.0);
    o[7] = dfi_r64(s->tailwind_turns, 4.0);
    const uint8_t known_flags =
        DUOFORGE_POSITION_FLAG_FOLLOW_ME | DUOFORGE_POSITION_FLAG_HELPING_HAND | DUOFORGE_POSITION_FLAG_UNBURDEN;
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        if ((s->positions[p].reserved & (uint8_t)~known_flags) != 0u) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        const duoforge_position_view *v = &s->positions[p];
        float *q = &o[DFI_ENC_HEAD + p * DFI_ENC_POSITION];
        for (uint32_t k = 0u; k < 7u; ++k) {
            q[k] = dfi_r32(v->stages[k], 12.0f); /* stages: float32 */
        }
        q[7] = (float)v->confused;
        q[8] = (float)v->charging;
        q[9] = dfi_bool(v->locked_slot != DUOFORGE_MOVE_SLOT_NONE);
        q[10] = (float)v->acted;
        const double chain = (double)v->protect_chain / 3.0;
        q[11] = (float)(chain > 1.0 ? 1.0 : chain);
        q[12] = (float)v->flash_fire;
        q[13] = (float)v->protecting;
        q[14] = dfi_bool((v->reserved & DUOFORGE_POSITION_FLAG_FOLLOW_ME) != 0u);
        q[15] = dfi_bool((v->reserved & DUOFORGE_POSITION_FLAG_HELPING_HAND) != 0u);
        q[16] = dfi_bool((v->reserved & DUOFORGE_POSITION_FLAG_UNBURDEN) != 0u);
    }
    for (uint32_t p = 0u; p < DUOFORGE_ACTIVE_PER_SIDE; ++p) {
        const duoforge_status st =
            dfi_one_hot(&dfi_v_occupant, s->occupant[p], 0u, &o[DFI_ENC_HEAD + p * DFI_ENC_POSITION + 17u]);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    float *members = &o[DFI_ENC_HEAD + DUOFORGE_ACTIVE_PER_SIDE * DFI_ENC_POSITION];
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        const duoforge_status st = dfi_one_hot(&dfi_v_location, s->members[m].location, 0u,
                                               &members[m * DFI_ENC_MEMBER + 2u]);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        const duoforge_status st =
            dfi_one_hot(&dfi_v_ailment, s->members[m].status, mask, &members[m * DFI_ENC_MEMBER + 6u]);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    for (uint32_t m = 0u; m < DUOFORGE_MAX_ROSTER; ++m) {
        const duoforge_member_view *v = &s->members[m];
        float *q = &members[m * DFI_ENC_MEMBER];
        q[0] = dfi_bool(version == 1u ? v->species_id != 0u : v->move_count != 0u);
        q[1] = v->hp_max > 0u ? (float)((double)v->hp / (double)v->hp_max) : 0.0f;
        /* q[2..5] location, q[6..11] status: written above */
        q[12] = (float)v->is_mega;
        q[13] = (float)v->mega_capable;
        q[14] = (float)v->item_used;
        q[15] = dfi_r64(v->item, 255.0);
        q[16] = dfi_r64(v->ability, 255.0);
        q[17] = dfi_r64(v->gender, 3.0);
        q[18] = dfi_r64(v->nature, 24.0);
        q[19] = dfi_r64(v->species_id, 65535.0);
        for (uint32_t k = 0u; k < DUOFORGE_MAX_MOVE_SLOTS; ++k) {
            q[20u + k] = dfi_r32(v->move_ids[k], 65535.0f); /* move ids: float32 */
            q[24u + k] = v->pp_max[k] > 0u ? (float)v->pp[k] / (float)v->pp_max[k] : 0.0f; /* pp: float32 */
        }
        q[28] = dfi_r64(v->move_count, 4.0);
        for (uint32_t k = 0u; k < 6u; ++k) {
            q[29u + k] = dfi_r32(v->stat_points[k], 32.0f); /* stat points: float32 */
        }
        for (uint32_t k = 0u; k < 5u; ++k) {
            const float stat = dfi_r32(v->stats[k], 1000.0f); /* stats: float32, at most 1 */
            q[35u + k] = stat < 1.0f ? stat : 1.0f;
        }
    }
    return DUOFORGE_OK;
}

/* ------------------------------------------------------------ the slots */

static duoforge_status dfi_slots(const duoforge_factored_domain *d, uint32_t viewer, uint32_t version, float *slots,
                                 uint8_t *pair_mask)
{
    const bool is_slots = d->kind == DUOFORGE_CHOICE_SLOTS;
    if (!is_slots) {
        return DUOFORGE_OK; /* all zero */
    }
    for (uint32_t s = 0u; s < DUOFORGE_ACTIVE_PER_SIDE; ++s) {
        if (d->slot_count[s] > DUOFORGE_MAX_SLOT_OPTIONS) {
            return DUOFORGE_E_INVALID_ARGUMENT;
        }
    }
    /* the checks over every valid entry, one kind of check at a time, as the reference */
    for (uint32_t s = 0u; s < DUOFORGE_ACTIVE_PER_SIDE; ++s) {
        for (uint32_t i = 0u; i < d->slot_count[s]; ++i) {
            if (d->slots[s][i].kind == DUOFORGE_SLOT_REVIVE) {
                continue; /* a REVIVE row has no kind column (encoder 5, decision 0028 C); versions 1 to 4 refuse it below */
            }
            const duoforge_status st = dfi_one_hot(&dfi_v_slot_kind, d->slots[s][i].kind, 0u,
                                                   &slots[(s * DUOFORGE_MAX_SLOT_OPTIONS + i) * 12u + 1u]);
            if (st != DUOFORGE_OK) {
                return st;
            }
        }
    }
    for (uint32_t s = 0u; s < DUOFORGE_ACTIVE_PER_SIDE; ++s) {
        for (uint32_t i = 0u; i < d->slot_count[s]; ++i) {
            const duoforge_slot_command *c = &d->slots[s][i];
            if (c->kind == DUOFORGE_SLOT_MOVE && c->move_slot > DUOFORGE_MOVE_SLOT_RECHARGE) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
        }
    }
    for (uint32_t s = 0u; s < DUOFORGE_ACTIVE_PER_SIDE; ++s) {
        for (uint32_t i = 0u; i < d->slot_count[s]; ++i) {
            const duoforge_slot_command *c = &d->slots[s][i];
            if (c->kind == DUOFORGE_SLOT_MOVE && c->target != DUOFORGE_TARGET_NONE && c->target >= 4u) {
                return DUOFORGE_E_INVALID_ARGUMENT;
            }
        }
    }
    for (uint32_t s = 0u; s < DUOFORGE_ACTIVE_PER_SIDE; ++s) {
        for (uint32_t i = 0u; i < d->slot_count[s]; ++i) {
            const duoforge_slot_command *c = &d->slots[s][i];
            float *f = &slots[(s * DUOFORGE_MAX_SLOT_OPTIONS + i) * 12u];
            f[0] = 1.0f;
            if (c->kind == DUOFORGE_SLOT_MOVE) {
                f[5] = dfi_r64(c->move_slot, (double)DUOFORGE_MOVE_SLOT_STRUGGLE);
                if (c->target != DUOFORGE_TARGET_NONE) {
                    const uint32_t rel = (((uint32_t)c->target >> 1) ^ viewer) * 2u + (c->target & 1u);
                    f[6u + rel] = 1.0f;
                }
                f[10] = (float)c->mega;
            } else if (c->kind == DUOFORGE_SLOT_SWITCH || c->kind == DUOFORGE_SLOT_REVIVE) {
                f[11] = dfi_r64(c->reserve, 5.0);
            }
        }
    }
    for (uint32_t i = 0u; i < DUOFORGE_MAX_SLOT_OPTIONS; ++i) {
        for (uint32_t j = 0u; j < DUOFORGE_MAX_SLOT_OPTIONS; ++j) {
            pair_mask[i * DUOFORGE_MAX_SLOT_OPTIONS + j] = (uint8_t)((d->allowed[i] >> j) & 1u); /* wide-operands-reviewed: 0 or 1 */
        }
    }
    if (version < 3u) { /* slots_as_encoder: versions 1 and 2 know no Recharge */
        for (uint32_t s = 0u; s < DUOFORGE_ACTIVE_PER_SIDE; ++s) {
            for (uint32_t i = 0u; i < d->slot_count[s]; ++i) {
                const duoforge_slot_command *c = &d->slots[s][i];
                if (c->kind == DUOFORGE_SLOT_MOVE && c->move_slot == DUOFORGE_MOVE_SLOT_RECHARGE) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
            }
        }
    }
    if (version < 5u) { /* encoder 5 added the REVIVE row (Revival Blessing, decision 0025 item 8); 1 to 4 refuse it */
        for (uint32_t s = 0u; s < DUOFORGE_ACTIVE_PER_SIDE; ++s) {
            for (uint32_t i = 0u; i < d->slot_count[s]; ++i) {
                if (d->slots[s][i].kind == DUOFORGE_SLOT_REVIVE) {
                    return DUOFORGE_E_UNSUPPORTED;
                }
            }
        }
    }
    return DUOFORGE_OK;
}

/* ------------------------------------------------------------ encode */

duoforge_status duoforge_encoder_size(uint32_t version, uint32_t *out_obs_size)
{
    if (out_obs_size == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    if (version < DUOFORGE_ENCODER_MIN || version > DUOFORGE_ENCODER_MAX) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    *out_obs_size = version >= 5u ? DFI_ENC_V5 : version == 4u ? DFI_ENC_V4 : version == 3u ? DFI_ENC_V3 : DFI_ENC_BASE;
    return DUOFORGE_OK;
}

static duoforge_status dfi_encode(uint32_t version, uint64_t mask, const duoforge_observation *ob,
                                  const duoforge_factored_domain *d, const duoforge_observation_ext *ext, float *obs,
                                  float *slots, uint8_t *pair_mask)
{
    if (ob->player > 1u) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    if (ob->epoch != d->epoch || (ob->requested != 0u) != (d->kind != 0u)) {
        return DUOFORGE_E_INVALID_ARGUMENT; /* the domain of another boundary */
    }
    if ((mask & ~dfi_version_features(version)) != 0u) {
        return DUOFORGE_E_INVALID_ARGUMENT; /* a bit the version has no column for */
    }
    if (ext == NULL && (mask & ~DFI_ENC_BASE_VALUES) != 0u) {
        return DUOFORGE_E_NULL_ARGUMENT; /* a record bit needs the records */
    }
    bool present = false;
    if (ext != NULL) {
        const duoforge_status st = dfi_check_record(ob, ext, mask, &present);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    /* global: one-hots, turn clipped, the turn counts r64 */
    duoforge_status st = dfi_one_hot(&dfi_v_boundary, ob->boundary_kind, 0u, &obs[0]);
    if (st != DUOFORGE_OK) {
        return st;
    }
    const double turn = (double)ob->turn / 100.0;
    obs[5] = (float)(turn > 1.0 ? 1.0 : turn);
    st = dfi_one_hot(&dfi_v_weather, ob->weather, mask, &obs[6]);
    if (st != DUOFORGE_OK) {
        return st;
    }
    obs[9] = dfi_r64(ob->weather_turns, 8.0);
    st = dfi_one_hot(&dfi_v_terrain, ob->terrain, mask, &obs[10]);
    if (st != DUOFORGE_OK) {
        return st;
    }
    obs[13] = dfi_r64(ob->terrain_turns, 8.0);
    obs[14] = dfi_r64(ob->trick_room_turns, 5.0);
    if (version >= 3u) {
        dfi_block(ob, ext, present, mask, version, &obs[DFI_ENC_BASE]);
    }
    for (uint32_t k = 0u; k < DUOFORGE_SIDE_COUNT; ++k) {
        const uint32_t abs = k == 0u ? ob->player : 1u - ob->player;
        st = dfi_side(&ob->sides[abs], mask, version, &obs[DFI_ENC_GLOBAL + k * DFI_ENC_SIDE]);
        if (st != DUOFORGE_OK) {
            return st;
        }
    }
    return dfi_slots(d, ob->player, version, slots, pair_mask);
}

duoforge_status duoforge_encode(uint32_t version, uint64_t ext_supported, const duoforge_observation *observation,
                                const duoforge_factored_domain *domain, const duoforge_observation_ext *ext,
                                float *obs, float *slots, uint8_t *pair_mask)
{
    uint32_t size = 0u;
    if (observation == NULL || domain == NULL || obs == NULL || slots == NULL || pair_mask == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    const duoforge_status checked = duoforge_encoder_size(version, &size);
    if (checked != DUOFORGE_OK) {
        return checked;
    }
    memset(obs, 0, (size_t)size * sizeof *obs);
    memset(slots, 0, (size_t)DUOFORGE_ENCODER_SLOT_VALUES * sizeof *slots);
    memset(pair_mask, 0, DUOFORGE_ENCODER_PAIR_VALUES);
    const duoforge_status st = dfi_encode(version, ext_supported, observation, domain, ext, obs, slots, pair_mask);
    if (st != DUOFORGE_OK) { /* a refused row is all zero */
        memset(obs, 0, (size_t)size * sizeof *obs);
        memset(slots, 0, (size_t)DUOFORGE_ENCODER_SLOT_VALUES * sizeof *slots);
        memset(pair_mask, 0, DUOFORGE_ENCODER_PAIR_VALUES);
    }
    return st;
}

/* ------------------------------------------------------------ batch */

typedef struct dfi_encode_job {
    uint32_t version;
    uint64_t mask;
    uint32_t obs_size;
    duoforge_request *requests;
    duoforge_observation *observations;
    duoforge_factored_domain *domains;
    float *obs;
    float *slots;
    uint8_t *pair_mask;
} dfi_encode_job;

/* The rows of a player that failed, or of one after a failed player, are all zero. */
static void dfi_encode_zero(uint32_t obs_size, float *obs, float *slots, uint8_t *pair_mask)
{
    memset(obs, 0, (size_t)obs_size * sizeof *obs);
    memset(slots, 0, (size_t)DUOFORGE_ENCODER_SLOT_VALUES * sizeof *slots);
    memset(pair_mask, 0, DUOFORGE_ENCODER_PAIR_VALUES);
}

duoforge_status dfi_encoder_check(uint32_t version, uint64_t ext_supported, uint32_t *out_obs_size)
{
    uint32_t size = 0u;
    const duoforge_status checked = duoforge_encoder_size(version, &size);
    if (checked != DUOFORGE_OK) {
        return checked;
    }
    if ((ext_supported & ~dfi_version_features(version)) != 0u) {
        return DUOFORGE_E_INVALID_ARGUMENT;
    }
    *out_obs_size = size;
    return DUOFORGE_OK;
}

/* Player p of `battle` as duoforge_batch_query_encoded queries and encodes
   one row: the request, observation and factored domain (into the given
   records, request may be NULL), the view extension when the mask has a
   record bit, then duoforge_encode. A failing query leaves the row all zero,
   as a refused one is. */
static duoforge_status dfi_encode_player(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t p,
                                         uint32_t version, uint64_t ext_supported, uint32_t obs_size,
                                         duoforge_request *request, duoforge_observation *observation,
                                         duoforge_factored_domain *domain, float *obs, float *slots,
                                         uint8_t *pair_mask)
{
    const bool records = (ext_supported & ~DFI_ENC_BASE_VALUES) != 0u;
    duoforge_observation_ext ext;
    /* the query of duoforge_batch_query_factored */
    duoforge_status st = dfi_batch_query_player(ctx, battle, p, request, observation, NULL, NULL, domain);
    if (st == DUOFORGE_OK && records) {
        st = duoforge_battle_observe_ext(ctx, battle, p, &ext);
    }
    if (st != DUOFORGE_OK) {
        dfi_encode_zero(obs_size, obs, slots, pair_mask);
        return st;
    }
    return duoforge_encode(version, ext_supported, observation, domain, records ? &ext : NULL, obs, slots, pair_mask);
}

duoforge_status dfi_encode_leaf(const duoforge_context *ctx, const duoforge_battle *battle, uint32_t p,
                                uint32_t version, uint64_t ext_supported, uint32_t obs_size, void *rows, uint32_t row)
{
    float *obs = (float *)rows + (size_t)row * obs_size;
    float slots[DUOFORGE_ENCODER_SLOT_VALUES];
    uint8_t pair_mask[DUOFORGE_ENCODER_PAIR_VALUES];
    duoforge_observation observation;
    duoforge_factored_domain domain;
    return dfi_encode_player(ctx, battle, p, version, ext_supported, obs_size, NULL, &observation, &domain, obs,
                             slots, pair_mask);
}

void dfi_encode_clear(void *rows, uint32_t obs_size, uint32_t row)
{
    float *obs = (float *)rows + (size_t)row * obs_size;
    memset(obs, 0, (size_t)obs_size * sizeof *obs);
}

/* Query and encode both players of one environment (dfi_batch_each). */
static duoforge_status dfi_encode_env(void *arg, uint32_t env, const duoforge_context *ctx,
                                      const duoforge_battle *battle)
{
    const dfi_encode_job *j = arg;
    duoforge_status st = DUOFORGE_OK;
    for (uint32_t p = 0u; p < DUOFORGE_SIDE_COUNT; ++p) {
        const size_t at = (size_t)env * DUOFORGE_SIDE_COUNT + p;
        float *obs = &j->obs[at * j->obs_size];
        float *slots = &j->slots[at * DUOFORGE_ENCODER_SLOT_VALUES];
        uint8_t *pair_mask = &j->pair_mask[at * DUOFORGE_ENCODER_PAIR_VALUES];
        duoforge_observation own_observation;
        duoforge_factored_domain own_domain;
        duoforge_observation *ob = j->observations != NULL ? &j->observations[at] : &own_observation;
        duoforge_factored_domain *d = j->domains != NULL ? &j->domains[at] : &own_domain;
        if (st == DUOFORGE_OK) {
            st = dfi_encode_player(ctx, battle, p, j->version, j->mask, j->obs_size,
                                   j->requests != NULL ? &j->requests[at] : NULL, ob, d, obs, slots, pair_mask);
        } else { /* rows of a failed environment are all zero */
            dfi_encode_zero(j->obs_size, obs, slots, pair_mask);
        }
    }
    return st;
}

duoforge_status duoforge_batch_query_encoded(duoforge_batch *batch, uint32_t version, uint64_t ext_supported,
                                             duoforge_request *requests, duoforge_observation *observations,
                                             duoforge_factored_domain *domains, float *obs, float *slots,
                                             uint8_t *pair_mask, duoforge_status *statuses)
{
    if (batch == NULL || obs == NULL || slots == NULL || pair_mask == NULL || statuses == NULL) {
        return DUOFORGE_E_NULL_ARGUMENT;
    }
    dfi_encode_job job = {version, ext_supported, 0u, requests, observations, domains, obs, slots, pair_mask};
    const duoforge_status checked = dfi_encoder_check(version, ext_supported, &job.obs_size);
    if (checked != DUOFORGE_OK) {
        return checked;
    }
    return dfi_batch_each(batch, dfi_encode_env, &job, statuses);
}
