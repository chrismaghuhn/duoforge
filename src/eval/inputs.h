#ifndef DFI_EVAL_INPUTS_H
#define DFI_EVAL_INPUTS_H
#include "eval/arithmetic.h"
#define DFI_EVAL_INPUT_WIDTH 1094u
/* Private grouping IDs, never gameplay/ABI identifiers. */
typedef enum dfi_eval_group {
    DFI_EVAL_GROUP_GLOB, DFI_EVAL_GROUP_SIDE, DFI_EVAL_GROUP_POSITION,
    DFI_EVAL_GROUP_OCCUPANT, DFI_EVAL_GROUP_MEMBER, DFI_EVAL_GROUP_PRESENT,
    DFI_EVAL_GROUP_SPECIES, DFI_EVAL_GROUP_ITEM, DFI_EVAL_GROUP_ABILITY,
    DFI_EVAL_GROUP_NATURE, DFI_EVAL_GROUP_MOVES, DFI_EVAL_GROUP_PP, DFI_EVAL_GROUP_MOVE_COUNT
} dfi_eval_group;
typedef struct dfi_eval_column { const char *name; dfi_eval_group group; uint16_t a, b, c; } dfi_eval_column;
typedef struct dfi_eval_id_capacities { uint32_t species, move, item, ability, nature; } dfi_eval_id_capacities;
typedef struct dfi_eval_inputs {
    /* Categorical/meta slots are zero here; no ID is quantized as a scalar. */
    int16_t scalars[DFI_EVAL_INPUT_WIDTH];
    uint32_t species[2][6], item[2][6], ability[2][6], nature[2][6], moves[2][6][4];
    uint8_t registered[2][6], move_count[2][6], occupant[2][2];
} dfi_eval_inputs;
DFI_PRIVATE const dfi_eval_column *dfi_eval_input_columns(void);
/* Cold exact name/order classification with bounded, named refusals. */
DFI_PRIVATE duoforge_status dfi_eval_input_schema(const char *const *names, uint32_t count, char reason[128]);
/* Raw bits copied in the existing encoder scope; capacity-checked IDs are decoded
   before any scalar quantization. One scale per canonical input column. */
DFI_PRIVATE duoforge_status dfi_eval_prepare_inputs(const uint32_t bits[DFI_EVAL_INPUT_WIDTH],
                                       const dfi_eval_scale scales[DFI_EVAL_INPUT_WIDTH],
                                       dfi_eval_id_capacities capacities, dfi_eval_inputs *out, char reason[128]);
#endif
