#ifndef DUOFORGE_EVAL_H
#define DUOFORGE_EVAL_H
/* Cold evaluator lifecycle. No trained default, file discovery or inference.
 * DFEVAL v1 contract: docs/superpowers/specs/2026-10-14-dfeval-v1.md. */
#include <duoforge/duoforge_search.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct duoforge_evaluator duoforge_evaluator;
typedef struct duoforge_eval_workspace duoforge_eval_workspace;

/* Caller must keep artifacts outside the repository/CI artifacts.
 * Absolute private path; expected_sha256 is mandatory and hashes all bytes of
 * the actual opened file. context/version/mask must match exactly. Output is
 * untouched on refusal. Production graph registry is intentionally empty until
 * E3g installs reviewed descriptors: otherwise valid files currently refuse
 * E_UNSUPPORTED, eval_graph_unregistered. No artifact's own approval claim is
 * trusted. A loaded model is immutable; context is copied, not borrowed. */
duoforge_status duoforge_evaluator_load(const char *absolute_path,
    const uint8_t expected_sha256[DUOFORGE_DIGEST_SIZE], const duoforge_context *context,
    uint32_t encoder_version, uint64_t ext_supported, duoforge_evaluator **out,
    duoforge_eval_error *out_error);
/* NULL is a no-op. Workspaces retain model storage; releasing this caller's
 * handle does not invalidate them. Destroy/use of the same caller handle must
 * not race. Cold lifecycle operations may allocate/free. */
void duoforge_evaluator_destroy(duoforge_evaluator *model);

/* Bound to model/hash/schema/context, exact workers and leaf capacity. No
 * workers are constructed here. Future expansion must use the existing pool.
 * Explicit descriptor maxima and checked formula govern allocation. */
duoforge_status duoforge_eval_workspace_create(const duoforge_evaluator *model,
    uint32_t leaf_capacity, uint32_t workers, duoforge_eval_workspace **out,
    duoforge_eval_error *out_error);
/* NULL is OK. An acquired workspace refuses E_UNSUPPORTED,
 * eval_workspace_busy, without freeing or modifying it. No other caller may
 * race destruction; shared use is rejected by the private acquire operation. */
duoforge_status duoforge_eval_workspace_destroy(duoforge_eval_workspace *workspace,
    duoforge_eval_error *out_error);
#ifdef __cplusplus
}
#endif
#endif
