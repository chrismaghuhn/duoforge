/* The public header must compile on its own and tolerate double inclusion. */
#include "duoforge/duoforge.h"
#include "duoforge/duoforge.h"

const char *duoforge_header_check_anchor(void);

const char *duoforge_header_check_anchor(void)
{
    return DUOFORGE_VERSION_STRING;
}
