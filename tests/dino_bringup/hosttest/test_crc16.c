/* Host test: src/crc16.c must match microcode_gen.py's CRC-16/CCITT-FALSE
   and the shipped expect header/bins. Run: make test */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../src/crc16.h"
#include "../src/microcode_expect.h"

static uint16_t crc_over(const uint8_t *p, size_t n) {
    uint16_t crc = CRC16_INIT;
    for (size_t i = 0; i < n; i++) crc = crc16_update(crc, p[i]);
    return crc;
}

static uint8_t *load(const char *path, size_t want) {
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "missing %s (run microcode_gen.py)\n", path); exit(1); }
    uint8_t *buf = malloc(want);
    assert(fread(buf, 1, want, f) == want);
    fclose(f);
    return buf;
}

int main(void) {
    /* the one known-answer vector for CRC-16/CCITT-FALSE */
    assert(crc_over((const uint8_t *)"123456789", 9) == 0x29B1);

    /* generated bins vs the header constants the rig compares against */
    struct { const char *path; uint16_t want; } chips[] = {
        {"../../../roms/U9.bin", MC_CRC_U9_REAL},
        {"../../../roms/U15.bin", MC_CRC_U15_REAL},
        {"../../../roms/U23.bin", MC_CRC_U23_REAL},
        {"../../../roms/U9_diag.bin", MC_CRC_U9_DIAG},
        {"../../../roms/U15_diag.bin", MC_CRC_U15_DIAG},
        {"../../../roms/U23_diag.bin", MC_CRC_U23_DIAG},
    };
    for (unsigned i = 0; i < 6; i++) {
        uint8_t *b = load(chips[i].path, 8192);
        assert(crc_over(b, 4096) == chips[i].want);       /* addressable half */
        assert(memcmp(b, b + 4096, 4096) == 0);           /* A12 mirror */
        free(b);
    }

    /* MC_REAL_WORDS table vs the real bins: same image, two encodings.
       THREE bytes since 2026-08-10 -- U23 carries CW16-23, and the table
       widened to uint32_t. The masks matter: `>> 8` alone used to be a
       whole byte and is now sixteen bits, which is exactly how this
       assertion caught the widening. */
    uint8_t *lo = load("../../../roms/U9.bin", 8192);
    uint8_t *hi = load("../../../roms/U15.bin", 8192);
    uint8_t *th = load("../../../roms/U23.bin", 8192);
    for (unsigned a = 0; a < 4096; a++) {
        assert((MC_REAL_WORDS[a] & 0xFF) == lo[a]);
        assert(((MC_REAL_WORDS[a] >> 8) & 0xFF) == hi[a]);
        assert(((MC_REAL_WORDS[a] >> 16) & 0xFF) == th[a]);
    }
    free(lo); free(hi); free(th);

    /* diag word function vs the diag bins */
    lo = load("../../../roms/U9_diag.bin", 8192);
    hi = load("../../../roms/U15_diag.bin", 8192);
    for (unsigned a = 0; a < 4096; a++) {
        uint16_t w = MC_DIAG_WORD(a);
        assert((w & 0xFF) == lo[a] && (w >> 8) == hi[a]);
    }
    free(lo); free(hi);

    printf("OK test_crc16\n");
    return 0;
}
