/* dfi_event_make stays an export of the shared library (restructure step 4). Its definition is an inline one in
 * src/combat/events.h, forced into every engine caller; events.c holds the one external definition, which the library
 * exports as before. This program links only duoforge_shared and calls the export through the import library, without
 * the inline header: a missing export fails the link (LNK2019, undefined reference), a second definition fails it too
 * (LNK2005, multiple definition). The call's record is checked field by field. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <duoforge/duoforge.h>

duoforge_event dfi_event_make(uint32_t kind, uint32_t position);

int main(void)
{
    const duoforge_event e = dfi_event_make(DUOFORGE_EVENT_FAINT, 2u);
    duoforge_event want;
    memset(&want, 0, sizeof want);
    want.kind = (uint8_t)DUOFORGE_EVENT_FAINT;
    want.position = 2u;
    want.other = (uint8_t)DUOFORGE_NO_POSITION;
    if (memcmp(&e, &want, sizeof e) != 0) {
        fprintf(stderr, "dfi_event_make: kind %u position %u other %u, want %u 2 %u and every other field 0\n",
                (unsigned)e.kind, (unsigned)e.position, (unsigned)e.other, (unsigned)DUOFORGE_EVENT_FAINT,
                (unsigned)DUOFORGE_NO_POSITION);
        return 1;
    }
    printf("dfi_event_make: exported, one definition, the record as specified\n");
    return 0;
}
