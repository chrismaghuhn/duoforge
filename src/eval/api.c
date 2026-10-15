#include "eval/model.h"
duoforge_status duoforge_evaluator_load(const char *path, const uint8_t expected[32],
    const duoforge_context *context, uint32_t version, uint64_t mask,
    duoforge_evaluator **out, duoforge_eval_error *error)
{
    return dfi_eval_load(path, expected, context, version, mask, out, error);
}
void duoforge_evaluator_destroy(duoforge_evaluator *model)
{
    dfi_eval_model_release(model);
}
duoforge_status duoforge_eval_workspace_create(const duoforge_evaluator *model,
    uint32_t capacity, uint32_t workers, duoforge_eval_workspace **out, duoforge_eval_error *error)
{
    return dfi_eval_workspace_create(model, capacity, workers, out, error);
}
duoforge_status duoforge_eval_workspace_destroy(duoforge_eval_workspace *workspace,
    duoforge_eval_error *error)
{
    return dfi_eval_workspace_destroy(workspace, error);
}
