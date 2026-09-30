/* fixture: exactly one unmarked result cast */
static uint32_t f(uint16_t a, uint16_t b) { return (uint32_t)(a * b); }
static uint8_t g(uint32_t v) { return (uint8_t)(v >> 8); } /* wide-operands-reviewed */
