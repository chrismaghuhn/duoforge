/* fixture: banned call on line 4 after a continued macro */
#define DF_FIXTURE_MACRO(x) \
    (x)
static void f(void) { (void)time(0); }
