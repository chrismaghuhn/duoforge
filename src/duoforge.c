#include <duoforge/duoforge.h>

const char *duoforge_version_string(void)
{
    return DUOFORGE_VERSION_STRING;
}

const char *duoforge_status_name(duoforge_status status)
{
    switch (status) {
    case DUOFORGE_OK:
        return "DUOFORGE_OK";
    case DUOFORGE_E_NULL_ARGUMENT:
        return "DUOFORGE_E_NULL_ARGUMENT";
    case DUOFORGE_E_INVALID_ARGUMENT:
        return "DUOFORGE_E_INVALID_ARGUMENT";
    case DUOFORGE_E_CONTEXT_MISMATCH:
        return "DUOFORGE_E_CONTEXT_MISMATCH";
    case DUOFORGE_E_CAPACITY:
        return "DUOFORGE_E_CAPACITY";
    case DUOFORGE_E_MALFORMED:
        return "DUOFORGE_E_MALFORMED";
    case DUOFORGE_E_SCHEMA_MISMATCH:
        return "DUOFORGE_E_SCHEMA_MISMATCH";
    case DUOFORGE_E_SEMANTICS_MISMATCH:
        return "DUOFORGE_E_SEMANTICS_MISMATCH";
    case DUOFORGE_E_INVARIANT:
        return "DUOFORGE_E_INVARIANT";
    case DUOFORGE_E_EXHAUSTED:
        return "DUOFORGE_E_EXHAUSTED";
    case DUOFORGE_E_OUT_OF_MEMORY:
        return "DUOFORGE_E_OUT_OF_MEMORY";
    default:
        return "DUOFORGE_STATUS_UNKNOWN";
    }
}
