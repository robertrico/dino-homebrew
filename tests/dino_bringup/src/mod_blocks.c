#include <avr/io.h>
#include <avr/pgmspace.h>
#include <util/delay.h>
#include <string.h>
#include "registry.h"
#include "harness.h"
#include "uart.h"
#include "cw_expect.h"
#include "microcode_expect.h"
#include "progrom_expect.h"

/* ---------------------------------------------------------------------------
   BLOCK TESTS — the integration ladder.

   THE BLOCK LAW (BRINGUP.md): sample a signal only if its value depends on
   MORE THAN ONE member of the block. Everything else is copper, strapped, or
   already retired by a module test or an earlier block. These tests therefore
   assert SEAMS, never module logic — mod_control_word.c already proved the
   '138 truth table and mod_root.c already proved the T counter.

   NOTHING IS EVER PULLED. Y1 stays seated, so the machine free-runs at
   1.024MHz in every block and there is no single-stepping anywhere. Reset is
   the physical button on an ARM prompt. Every test is burst-capture-and-decode.

   T0-3 IS NOT SAMPLED — it is copper between root and microcode. The rig cuts
   the captured stream at each END; the frame after a cut is t=0 and POSITION
   WITHIN THE RUN IS t. That asserts ORDER AND RUN LENGTH, which a per-T
   lookup would not: a wrong END row or a skipped state both fail here.

   Pin bundles come from `pins block1`..`pins block5` (kicad_contracts.py
   BLOCKS). Port grouping is deliberate: capture_burst reads WHOLE PORTS, so
   each decoder group sits in exactly one port and the 8 SRC enables share a
   single port — that is what makes block1.onehot a coherent one-read check.
--------------------------------------------------------------------------- */

/* Burst buffers borrow the shared arena (harness.h). One user at a time. */
#define NCAP 1024
#define s_capA (&g_arena[0])        /* the ANCHOR port (PL) — every pass */
#define s_capB (&g_arena[NCAP])     /* the group port for this pass */

/* Anchor port bit positions. PL is the natural home of CW8-15 under
   MEGA_PORT_BY_PREFIX, so the whole sequencing gang lands in one read. */
#define A_CLK  0      /* CAPTURE QUALIFIER, not an assertion — see below */
#define A_SA2  1
#define A_SA1  2
#define A_SA0  3
#define A_END  4
#define A_PCUP 5
#define A_MUX  6
#define A_HALT 7

/* 7 cycles/sample = 437ns for PL+low-port, 8 cycles = 500ns for PL+PK. At
   1.024MHz one T state is 977ns, so every state yields at least one uniform
   sample. Written as asm for the same reason mod_root.c does it: gcc -Os
   emits 10 cycles and the margin matters.

   THE GROUP PORT IS READ FIRST AND CLK/PL SECOND, and the order is the whole
   point. The T boundary is the CLK RISING edge, which ENDS the CLK-low window.

     PL first, group second  -> when PL lands late in CLK-low, the group read
                                falls AFTER the edge, into the next state's ROM
                                ACCESS WINDOW. That is garbage from the wrong T.
     group first, PL second  -> when the pair lands early, the group read falls
                                just BEFORE the falling edge — still the SAME
                                T-state, and by then the ROM has long settled
                                (tACC 250ns << the 488ns CLK-high half).

   So one ordering can only mix two states and the other cannot. Reading PL
   first cost a 38% mixed-frame rate: correct rows paired with the WRONG
   T-state, which showed up as dst reading one T behind the anchor
   (2026-07-30). Also puts the two reads adjacent, cutting the skew from
   187ns to 62ns. */
#define CAP_PL_LO(fn, ioaddr)                                       \
    static void fn(void) {                                          \
        uint8_t *pa = s_capA, *pb = s_capB;                         \
        uint16_t n = NCAP / 2;                                      \
        uint8_t t, u;                                               \
        __asm__ volatile(                                           \
            "1:                     \n\t"                           \
            "in  %[u], %[lo]        \n\t"   /* group FIRST */       \
            "lds %[t], %[pinl]      \n\t"   /* then CLK+anchor */   \
            "st  X+, %[t]           \n\t"                           \
            "st  Z+, %[u]           \n\t"                           \
            "in  %[u], %[lo]        \n\t"                           \
            "lds %[t], %[pinl]      \n\t"                           \
            "st  X+, %[t]           \n\t"                           \
            "st  Z+, %[u]           \n\t"                           \
            "sbiw %[n], 1           \n\t"                           \
            "brne 1b                \n\t"                           \
            : [t] "=&r" (t), [u] "=&r" (u), [n] "+w" (n),           \
              "+x" (pa), "+z" (pb)                                  \
            : [pinl] "i" (_SFR_MEM_ADDR(PINL)), [lo] "I" (ioaddr)   \
            : "memory");                                            \
    }

CAP_PL_LO(cap_pl_pa, _SFR_IO_ADDR(PINA))

static void cap_pl_pk(void) {           /* both extended I/O — lds/lds */
    uint8_t *pa = s_capA, *pb = s_capB;
    uint16_t n = NCAP / 2;
    uint8_t t, u;
    __asm__ volatile(
        "1:                     \n\t"
        "lds %[u], %[pink]      \n\t"   /* group FIRST — see CAP_PL_LO */
        "lds %[t], %[pinl]      \n\t"   /* then CLK+anchor */
        "st  X+, %[t]           \n\t"
        "st  Z+, %[u]           \n\t"
        "lds %[u], %[pink]      \n\t"
        "lds %[t], %[pinl]      \n\t"
        "st  X+, %[t]           \n\t"
        "st  Z+, %[u]           \n\t"
        "sbiw %[n], 1           \n\t"
        "brne 1b                \n\t"
        : [t] "=&r" (t), [u] "=&r" (u), [n] "+w" (n), "+x" (pa), "+z" (pb)
        : [pinl] "i" (_SFR_MEM_ADDR(PINL)), [pink] "i" (_SFR_MEM_ADDR(PINK))
        : "memory");
}

/* ---- frame extraction ---------------------------------------------------
   A frame is a maximal run of identical (anchor, group) samples. Consecutive
   duplicates are the same T state sampled twice; a change is a new state.

   SAMPLES TAKEN WHILE CLK IS HIGH ARE DISCARDED, and that is load-bearing.
   After T changes on the CLK rising edge the microcode ROM outputs are
   invalid for one access time (AT28C64B tACC 150-250ns) and U28/U30 decode
   that garbage into transient enables. The MACHINE does not care — nothing
   state-changing is reachable during CLK high, everything commits on CLK low
   (see BRINGUP.md, the machine invariant). But a blind sampler sees the
   strobes change while the anchor holds steady, emits TWO frames for one
   T-state, and every later index shifts by one — which destroys `t =
   position within the run`, the whole basis of the decode test.
   Block 1's first bench run failed exactly this way: the same opcode read
   0x60, 0x10, 0x60 for the same T across three passes (2026-07-30).
   CLK is RETIRED as an assertion — root.clock owns it. Here it is only a
   timing reference, which is why sampling it costs nothing against the gate.

   Single-sample frames that neither match their neighbours are dropped as
   straddle glitches — the two port reads sit one instruction apart, so a
   transition can fall between them and forge one bogus sample. mod_root.c
   learned this on the T counter and the same physics applies here. */
#define A_MASK ((uint8_t)~(1 << A_CLK))   /* CLK is not part of the frame */
#define MAXFR 40
/* Print enough to NAME THE LYING SIGNAL, then stop. NO BLIND COUNTERS still
   holds — the first lines carry signal, T-position and a diff byte, which is
   what identifies the wire. Printing all 1060 of them (first bench run) is
   its own failure: the operator cannot page back through it. */
#define MAXPRINT 12
typedef struct { uint8_t a, b; } frame_t;

static uint8_t frames(frame_t *out, uint8_t max) {
    uint8_t n = 0;
    uint16_t i = 0;
    /* find the first CLK-low sample to seed from */
    while (i < NCAP && (s_capA[i] & (1 << A_CLK))) i++;
    if (i >= NCAP) return 0;                    /* clock never went low */
    uint8_t ca = s_capA[i] & A_MASK, cb = s_capB[i];
    uint16_t held = 1;
    for (i++; i < NCAP && n < max; i++) {
        if (s_capA[i] & (1 << A_CLK)) continue; /* ROM access window: garbage */
        uint8_t a = s_capA[i] & A_MASK, b = s_capB[i];
        if (a == ca && b == cb) { held++; continue; }
        /* ONE SAMPLE PER STATE IS ALL THERE IS. CLK-low is ~488ns and the
           sample period is ~437-547ns, so a T-state yields about ONE
           CLK-low sample and never two. An earlier version demanded two
           confirming samples and emitted NOTHING — frames=0 on every opcode
           (2026-07-30). CLK gating is what rejects the garbage now: the
           access-window samples are already discarded, so what reaches here
           is settled data. */
        out[n].a = ca; out[n].b = cb; n++;
        ca = a; cb = b; held = 1;
    }
    if (n < max) { out[n].a = ca; out[n].b = cb; n++; }
    (void)held;
    return n;
}

/* ---- expectation --------------------------------------------------------
   The rig's notion of truth stays derived from the burned image and a
   host-tested model. Nothing here is a hand-written table. */

/* THE IMPLEMENTED OPCODES COME FROM THE GENERATED LIST, never from guessing
   at the image. T0 is the universal FETCH row for ALL 256 opcodes, and NOP's
   T1 is a bare END identical to the fill written at every unimplemented one,
   so no inspection of MC_REAL_WORDS can tell them apart. Block 1's first
   bench run walked all 256 and compared 238 of them against fill
   (2026-07-30). */
static uint8_t op_at(uint8_t i) {
    return pgm_read_byte(&MC_OPCODES[i]);
}

static uint16_t mc_word(uint8_t op, uint8_t t) {
    return pgm_read_word(&MC_REAL_WORDS[((uint16_t)op << 4) | (t & 0x0F)]);
}

/* Expected ANCHOR byte (PL) for a microcode word: SA/END/PC_UP/MUX/HALT
   straight off the ROM bits. Bit 0 (CW8) is not wired. */
static uint8_t exp_anchor(uint16_t w) {
    uint8_t v = 0;
    if (w & (1u << 9))  v |= 1 << A_SA2;
    if (w & (1u << 10)) v |= 1 << A_SA1;
    if (w & (1u << 11)) v |= 1 << A_SA0;
    if (w & (1u << 12)) v |= 1 << A_END;
    if (w & (1u << 13)) v |= 1 << A_PCUP;
    if (w & (1u << 14)) v |= 1 << A_MUX;
    if (w & (1u << 15)) v |= 1 << A_HALT;
    return v;
}

/* FLAG_Z is STRAPPED HIGH on the control_word board in blocks 1-3 (it becomes
   real copper from U49.5 at block 4). cw_expect is a CHECKER here, never a
   driver — the real ROM and the real decoder produce these strobes. */
#define STRAP_FLAG_Z 1

/* cw_expect enum bit -> position within its sampled port, per block1's
   PORT-ALIGNED bundle. -1 = not sampled (the U62 arm probes are module-level
   and stay retired to control_word.truth). */
static uint8_t exp_dst(uint32_t cw) {           /* PORTA, D22..D28 */
    return (uint8_t)(
        ((cw >> CWO_REG_A_LOAD_N)  & 1) << 0 |
        ((cw >> CWO_REG_B_LOAD_N)  & 1) << 1 |
        ((cw >> CWO_REG_C_LOAD_N)  & 1) << 2 |
        ((cw >> CWO_MAR_LO_LOAD_N) & 1) << 3 |
        ((cw >> CWO_MAR_HI_LOAD_N) & 1) << 4 |
        ((cw >> CWO_IR_LOAD_N)     & 1) << 5 |
        ((cw >> CWO_RAM_LOAD_N)    & 1) << 6);
}

static uint8_t exp_src(uint32_t cw) {           /* PORTC, D37..D30 (PC0..PC7) */
    return (uint8_t)(
        ((cw >> CWO_SW_OUT_N)    & 1) << 0 |
        ((cw >> CWO_ALU_OUT_N)   & 1) << 1 |
        ((cw >> CWO_REG_C_OUT_N) & 1) << 2 |
        ((cw >> CWO_REG_B_OUT_N) & 1) << 3 |
        ((cw >> CWO_REG_A_OUT_N) & 1) << 4 |
        ((cw >> CWO_RAM_OUT_N)   & 1) << 5 |
        ((cw >> CWO_ROM_OUT_N)   & 1) << 6 |
        ((cw >> CWO_SRC_ACTIVE)  & 1) << 7);
}

static uint8_t exp_jmp(uint32_t cw) {           /* PORTF, A0..A3 */
    return (uint8_t)(
        ((cw >> CWO_PC_CLEAR_N)     & 1) << 0 |
        ((cw >> CWO_MDR_OUT_N)      & 1) << 1 |
        ((cw >> CWO_REG_OUT_LOAD_N) & 1) << 2 |
        ((cw >> CWO_PC_LOAD_N)      & 1) << 3);
}

/* ---- IRB forcing (blocks 1-2 only; blocks 3+ drive nothing) -------------- */
static hwpin_t P_IRB[8];
static bool s_bound;
static uint8_t s_gen;
static const char *s_bound_mod;   /* the cache MUST key on the module too */
static const char m_block1[] PROGMEM = "block1";

static bool bind_irb(const char *mod) {
    if (s_bound && s_gen == g_pin_gen && s_bound_mod == mod) return true;
    char sig[8];
    for (uint8_t i = 0; i < 8; i++) {
        sig[0] = 'I'; sig[1] = 'R'; sig[2] = 'B';
        sig[3] = (char)('0' + i); sig[4] = 0;
        if (!sig_lookup(mod, sig, &P_IRB[i])) {
            uart_putsP("     bind failed: ");
            uart_puts(sig);
            uart_putsP("\r\n");
            return false;
        }
    }
    s_bound = true; s_gen = g_pin_gen; s_bound_mod = mod;
    return true;
}

static void irb_force(uint8_t op) {
    for (uint8_t i = 0; i < 8; i++) drv(&P_IRB[i], (op >> i) & 1);
    settle();
    _delay_ms(2);              /* let the machine cycle the new opcode */
}

/* Report a mismatch with enough detail to name the lying signal.
   NO BLIND COUNTERS — a failing assertion must say what lied. */
static void say_frame(const char *what_P, uint8_t op, uint8_t t,
                      uint8_t got, uint8_t want) {
    uart_putsP("     op=0x"); uart_puthex8(op);
    uart_putsP(" t="); uart_putc((char)('0' + (t & 15)));
    uart_putsP(" "); uart_puts_p(what_P);
    uart_putsP(" got=0x"); uart_puthex8(got);
    uart_putsP(" want=0x"); uart_puthex8(want);
    uart_putsP(" diff=0x"); uart_puthex8((uint8_t)(got ^ want));
    uart_putsP("\r\n");
}

/* ---- block1 -------------------------------------------------------------
   The control unit, real for the first time. Force IRB, free-run, capture,
   cut at END, compare the run against the burned microcode. */

/* ---- SETTLE AND SAMPLE ---------------------------------------------------
   THE SAMPLE LABELS ITSELF. With T0-3 read on PF4-7, every sample carries the
   T-state that produced it, so there is nothing to infer and nothing to align.

   This replaces burst-capture-and-position-inference for the decode walk, and
   it deletes an entire class of bug rather than fixing instances of it:
     - the fetch frame had to be UNIQUE to anchor a run. In the SRC pass it is
       not: LDA's T0/T1/T2 are all mux_pc+pc_up+src=ROM and differ only in DST.
     - a single T-state that got no sample shifted every later index by one.
   Neither can happen when the sample states its own T. (Rico proposed exactly
   this shape at the outset; the free-running clock is what pushed me into
   burst capture, and sampling T is what removes that pressure. 2026-07-30.)

   Bracketed by two CLK reads: the ports are only accepted if CLK was low
   BEFORE and AFTER, so a sample can never straddle the rising edge that
   advances T. A slow loop can afford that; a burst never could. */
typedef struct { uint8_t t, anchor, dst, src, jmp; } samp_t;

/* EXACTLY 7 CYCLES, AND IT HAS TO BE. CLK-low is 488ns = 7.8 cycles at 16MHz,
   so the whole bracketed read must fit inside it or the closing CLK check lands
   after the rising edge and rejects everything. The first C version read five
   ports plus struct stores; gcc emitted far more than 7 cycles and the walk
   collected TWO samples in 68000 attempts (2026-07-30).
   lds(2) + in(1) + in(1) + in(1) + lds(2) = 7 cycles = 437ns, leaving ~51ns of
   margin. Yield is modest — only attempts that begin early in CLK-low survive —
   which is why the loops try thousands of times and assert coverage at the end. */
static bool sample_now(samp_t *o) {
    uint8_t l1, a, c, f, l2;
    __asm__ volatile(
        "lds %[l1], %[pinl] \n\t"
        "in  %[a],  %[pina] \n\t"
        "in  %[c],  %[pinc] \n\t"
        "in  %[f],  %[pinf] \n\t"
        "lds %[l2], %[pinl] \n\t"
        : [l1] "=&r" (l1), [a] "=&r" (a), [c] "=&r" (c),
          [f] "=&r" (f), [l2] "=&r" (l2)
        : [pinl] "i" (_SFR_MEM_ADDR(PINL)),
          [pina] "I" (_SFR_IO_ADDR(PINA)),
          [pinc] "I" (_SFR_IO_ADDR(PINC)),
          [pinf] "I" (_SFR_IO_ADDR(PINF)));
    /* CLK low BEFORE and AFTER: the sample cannot straddle the rising edge
       that advances T, so all five bytes belong to one T-state. */
    if ((l1 | l2) & (1 << A_CLK)) return false;
    o->anchor = l1 & A_MASK;
    o->dst = a;
    o->src = c;
    o->jmp = (uint8_t)(f & 0x0F);
    o->t   = (uint8_t)(f >> 4);                 /* T0 on PF4 -> LSB */
    return true;
}

/* DITHER THE SAMPLE PHASE. The loop has a fixed period against a fixed clock,
   so without this it locks onto one phase and keeps landing on the same
   T-states — LDA/JMP/JNZ never reached T1/T2 and OUT never reached T0, on a
   walk that had 13312 samples and ZERO mismatches (2026-07-30). mod_root.c
   learned the same lesson on its T-counter pair coverage. Varying the period
   by 0-7 cycles walks the phase across the whole instruction. */
static void dither(uint16_t k) {
    /* step by 13, which is coprime with 32, so the phase walks every residue
       instead of cycling through 8 of them. A two-T instruction is ~31 cycles
       long, so a 0-7 range could not escape a lock: SUB and OR still never
       reached T0 on a 15345-sample walk (2026-07-30). */
    switch ((uint8_t)(k * 13u) & 31) {
    case 31: case 30: case 29: case 28:
    case 27: case 26: case 25: case 24:
        __asm__ volatile("nop\n\tnop\n\tnop\n\tnop\n\t"
                         "nop\n\tnop\n\tnop\n\tnop");
        /* fall through */
    case 23: case 22: case 21: case 20:
    case 19: case 18: case 17: case 16:
        __asm__ volatile("nop\n\tnop\n\tnop\n\tnop\n\t"
                         "nop\n\tnop\n\tnop\n\tnop");
        /* fall through */
    case 15: case 14: case 13: case 12:
    case 11: case 10: case 9: case 8:
        __asm__ volatile("nop\n\tnop\n\tnop\n\tnop");
        /* fall through */
    default: break;
    }
    switch (k & 7) {
    case 7: __asm__ volatile("nop"); /* fall through */
    case 6: __asm__ volatile("nop"); /* fall through */
    case 5: __asm__ volatile("nop"); /* fall through */
    case 4: __asm__ volatile("nop"); /* fall through */
    case 3: __asm__ volatile("nop"); /* fall through */
    case 2: __asm__ volatile("nop"); /* fall through */
    case 1: __asm__ volatile("nop"); /* fall through */
    default: break;
    }
}

/* T-states this opcode should reach: 0 up to and including its END/HALT row. */
static uint16_t reachable_ts(uint8_t op) {
    uint16_t m = 0;
    for (uint8_t t = 0; t < 16; t++) {
        uint16_t w = mc_word(op, t);
        m |= (uint16_t)(1u << t);
        if (w & ((1u << 12) | (1u << 15))) break;
    }
    return m;
}

void t_block1_decode(void) {
    test_begin(m_block1, PSTR("decode"));
    if (!bind_irb("block1")) { test_end(); return; }
    uint16_t bad = 0, checked = 0, transient = 0, sys_bad = 0;
    uint8_t shown = 0, cover_fail = 0;

    for (uint8_t oi = 0; oi < MC_OPCODE_COUNT; oi++) {
        uint8_t op = op_at(oi);
        if (op == MC_HALT_OPCODE) continue;     /* no END row; block1.seq owns it */
        irb_force(op);
        uint16_t want_ts = reachable_ts(op), seen = 0, stray = 0;
        /* PER-T TALLIES. A wiring fault is wrong on EVERY sample of that
           T-state; the microcode decode glitch is wrong on a handful. Counting
           both separately is the difference between "the board is broken" and
           "one read landed in the ROM access window" — and BRINGUP.md is
           explicit that the latter is a SUPPLY question, never a correctness
           one, because nothing state-changing is reachable during CLK high. */
        uint8_t n_samp[16], n_bad[16];
        for (uint8_t i = 0; i < 16; i++) { n_samp[i] = 0; n_bad[i] = 0; }
        samp_t s;
        for (uint16_t k = 0; k < 8000; k++) {
            dither(k);
            if (!sample_now(&s)) continue;
            uint16_t w = mc_word(op, s.t);
            uint32_t cw = cw_expect(w, STRAP_FLAG_Z);
            seen |= (uint16_t)(1u << s.t);
            if (!((want_ts >> s.t) & 1)) { stray |= (uint16_t)(1u << s.t); continue; }
            checked++;
            if (n_samp[s.t & 15] < 255) n_samp[s.t & 15]++;
            uint8_t before = bad;
            uint8_t wa = exp_anchor(w) & A_MASK;
            if (s.anchor != wa) {
                if (shown < MAXPRINT) { say_frame(PSTR("anchor"), op, s.t, s.anchor, wa); shown++; }
                if (bad < 0xFFFF) bad++;
            }
            uint8_t wd = exp_dst(cw);
            if (s.dst != wd) {
                if (shown < MAXPRINT) { say_frame(PSTR("dst"), op, s.t, s.dst, wd); shown++; }
                if (bad < 0xFFFF) bad++;
            }
            uint8_t ws = exp_src(cw);
            if (s.src != ws) {
                if (shown < MAXPRINT) { say_frame(PSTR("src"), op, s.t, s.src, ws); shown++; }
                if (bad < 0xFFFF) bad++;
            }
            uint8_t wj = exp_jmp(cw);
            if (s.jmp != wj) {
                if (shown < MAXPRINT) { say_frame(PSTR("jmp"), op, s.t, s.jmp, wj); shown++; }
                if (bad < 0xFFFF) bad++;
            }
            if ((uint8_t)bad != before && n_bad[s.t & 15] < 255) n_bad[s.t & 15]++;
        }
        /* classify every T-state that disagreed at all */
        for (uint8_t t = 0; t < 16; t++) {
            if (!n_bad[t]) continue;
            bool systematic = (n_bad[t] * 2 > n_samp[t]);
            uart_putsP("     op=0x"); uart_puthex8(op);
            uart_putsP(" t="); uart_putc((char)('0' + t));
            if (systematic) uart_putsP(" SYSTEMATIC ");
            else            uart_putsP(" transient ");
            uart_putdec(n_bad[t]); uart_putsP(" of "); uart_putdec(n_samp[t]);
            uart_putsP(" samples\r\n");
            if (systematic) sys_bad++; else transient++;
        }
        /* COVERAGE: a walk that never reached a T-state proved nothing about
           it. NO BLIND COUNTERS — silence is not a pass. */
        if ((seen & want_ts) != want_ts) {
            uart_putsP("     op=0x"); uart_puthex8(op);
            uart_putsP(" never reached T-states 0x"); uart_puthex8((uint8_t)((want_ts & ~seen) & 0xFF));
            uart_putsP("\r\n");
            cover_fail++;
        }
        /* END must clear T. Reaching a state past the END row says it did not. */
        if (stray) {
            uart_putsP("     op=0x"); uart_puthex8(op);
            uart_putsP(" reached T past its END row, mask 0x");
            uart_puthex8((uint8_t)(stray >> 4)); uart_puthex8((uint8_t)(stray & 0xFF));
            uart_putsP(" — END did not clear T\r\n");
            if (bad < 0xFFFF) bad++;
        }
    }
    if (bad > shown) {
        uart_putsP("     ("); uart_putdec((uint16_t)(bad - shown));
        uart_putsP(" further mismatches not printed)\r\n");
    }
    uart_putsP("     samples compared: "); uart_putdec(checked);
    uart_putsP("   transient T-states: "); uart_putdec(transient);
    uart_putsP("\r\n");
    if (transient)
        uart_putsP("     microcode DECODE GLITCH — measure on the scope. "
                   "Do NOT gate the '138s.\r\n     See BRINGUP.md.\r\n");
    test_check_bool(checked > 0, true, PSTR("samples_were_taken"));
    test_check_u16(cover_fail, 0, PSTR("every_T_state_reached"));
    test_check_u16(sys_bad, 0, PSTR("no_systematic_decode_faults"));
    test_end();
}

/* Never two SRC enables low at once, never two DST loads low at once.
   Active low, and SRC_ACTIVE (PC7) is NOT an enable, so mask it out. The rig
   sees SUSTAINED overlap only; the transient is the scope's job (BRINGUP.md,
   block1 LA check). With T sampled, an overlap now NAMES THE T-STATE it
   happened in, which is the difference between "something overlapped" and a
   line you can go and probe. */
static uint8_t count_low(uint8_t v, uint8_t mask) {
    uint8_t n = 0;
    for (uint8_t i = 0; i < 8; i++)
        if ((mask & (1 << i)) && !(v & (1 << i))) n++;
    return n;
}

void t_block1_onehot(void) {
    test_begin(m_block1, PSTR("onehot"));
    if (!bind_irb("block1")) { test_end(); return; }
    uint16_t bad = 0, checked = 0;
    uint8_t shown = 0;
    for (uint8_t oi = 0; oi < MC_OPCODE_COUNT; oi++) {
        uint8_t op = op_at(oi);
        if (op == MC_HALT_OPCODE) continue;
        irb_force(op);
        samp_t s;
        for (uint16_t k = 0; k < 4000; k++) {
            dither(k);
            if (!sample_now(&s)) continue;
            checked++;
            uint8_t cs = count_low(s.src, 0x7F);   /* PC0..PC6, not SRC_ACTIVE */
            uint8_t cd = count_low(s.dst, 0x7F);   /* PA0..PA6 */
            if (cs > 1) {
                if (shown < MAXPRINT) {
                    uart_putsP("     op=0x"); uart_puthex8(op);
                    uart_putsP(" t="); uart_putc((char)('0' + (s.t & 15)));
                    uart_putsP(" SRC overlap port=0x"); uart_puthex8(s.src);
                    uart_putsP(" enables_low="); uart_putc((char)('0' + cs));
                    uart_putsP("\r\n"); shown++;
                }
                if (bad < 0xFFFF) bad++;
            }
            if (cd > 1) {
                if (shown < MAXPRINT) {
                    uart_putsP("     op=0x"); uart_puthex8(op);
                    uart_putsP(" t="); uart_putc((char)('0' + (s.t & 15)));
                    uart_putsP(" DST overlap port=0x"); uart_puthex8(s.dst);
                    uart_putsP(" loads_low="); uart_putc((char)('0' + cd));
                    uart_putsP("\r\n"); shown++;
                }
                if (bad < 0xFFFF) bad++;
            }
        }
    }
    if (bad > shown) {
        uart_putsP("     ("); uart_putdec((uint16_t)(bad - shown));
        uart_putsP(" further overlaps not printed)\r\n");
    }
    test_check_bool(checked > 0, true, PSTR("samples_were_taken"));
    test_check_u16(bad, 0, PSTR("enable_overlaps"));
    test_end();
}

/* HALT freezes the sequencer, and with T sampled we can say WHERE.
   Previously this inferred a freeze from "one frame, HALT set". Now it asserts
   the T-state the machine parked on, which is the row that actually carries
   the HALT bit — a stronger claim, and one that names the fault if the counter
   stops somewhere unexpected. */
void t_block1_seq(void) {
    test_begin(m_block1, PSTR("seq"));
    if (!bind_irb("block1")) { test_end(); return; }

    /* which T carries HALT for opcode 0xFF, straight from the burned image */
    uint8_t halt_t = 0xFF;
    for (uint8_t t = 0; t < 16; t++)
        if (mc_word(MC_HALT_OPCODE, t) & (1u << 15)) { halt_t = t; break; }
    test_check_bool(halt_t != 0xFF, true, PSTR("microcode_has_a_HALT_row"));

    irb_force(MC_HALT_OPCODE);
    samp_t s;
    uint16_t n = 0, wrong_t = 0, no_halt = 0, saw_end = 0;
    for (uint16_t k = 0; k < 6000; k++) {
        dither(k);
        if (!sample_now(&s)) continue;
        n++;
        if (s.t != halt_t) wrong_t++;
        if (!(s.anchor & (1 << A_HALT))) no_halt++;
        if (s.anchor & (1 << A_END)) saw_end++;
    }
    test_check_bool(n > 0, true, PSTR("samples_were_taken"));
    if (wrong_t) {
        uart_putsP("     froze at the wrong T: expected "); uart_putdec(halt_t);
        uart_putsP(", saw a different one "); uart_putdec(wrong_t);
        uart_putsP(" times\r\n");
    }
    test_check_u16(wrong_t, 0, PSTR("T_frozen_on_the_HALT_row"));
    test_check_u16(no_halt, 0, PSTR("HALT_asserted_and_held"));
    test_check_u16(saw_end, 0, PSTR("no_END_while_halted"));

    /* RESET RECOVERY — IRB MUST NOT CHANGE. HALT is a FIXED POINT, NOT A
       LATCH: nothing stores it. T sits frozen on a row that asserts HALT and
       ~HALT holds U6.CET there. Move the ROM address off that row by ANY
       means and the machine resumes, so an earlier version that forced a live
       opcode here un-halted the machine itself and passed WITHOUT THE BUTTON
       BEING PRESSED. Rico caught it by noticing he was never prompted.
       Holding IRB at HALT, the only escape is clearing T — and now we can
       watch T go to 0 directly rather than infer it from HALT falling. */
    uart_putsP("     ARM: press RESET (10s) — IRB stays at HALT\r\n");
    bool saw_t0 = false;
    for (uint16_t ms = 0; ms < 10000 && !saw_t0; ms++) {
        for (uint8_t k = 0; k < 40; k++)
            if (sample_now(&s) && s.t == 0) { saw_t0 = true; break; }
        _delay_ms(1);
    }
    test_check_bool(saw_t0, true, PSTR("RESET_cleared_T_to_zero"));

    /* and it must refreeze on the HALT row, not run away.
       WAIT OUT THE RC STRETCH. RESET stays asserted well after the button is
       released — measured 0.25-2.2s, bench-dependent — and while it is held,
       ~{END_OR_RESET} keeps clearing T, so the machine cannot refreeze. Polling
       for a few milliseconds gave up long before that and reported a failure
       that was purely my impatience (2026-07-30). root's tests wait ON THE
       LINE, never on a timer; this waits up to 5s for the same reason. */
    bool back = false;
    for (uint16_t ms = 0; ms < 5000 && !back; ms++) {
        for (uint8_t k = 0; k < 60; k++) {
            dither(k);
            if (sample_now(&s) && s.t == halt_t && (s.anchor & (1 << A_HALT))) {
                back = true; break;
            }
        }
        _delay_ms(1);
    }
    test_check_bool(back, true, PSTR("machine_refroze_on_the_HALT_row"));
    test_end();
}

/* A DIAGNOSTIC, NOT A GATE. Dumps the raw frame sequence with no
   interpretation, so alignment questions are READ rather than inferred. The
   first bench run left three live hypotheses — rotation, straddle, or T not
   clearing on END — and the mismatch lines could not tell them apart because
   they only print frames that DISAGREE. This prints all of them, in order,
   with what the microcode says each T should be beside it. */
void t_block1_frames(void) {
    test_begin(m_block1, PSTR("frames"));
    if (!bind_irb("block1")) { test_end(); return; }
    frame_t f[MAXFR];
    static const uint8_t SHOW[] PROGMEM = {0x00, 0x11, 0x41};
    for (uint8_t k = 0; k < sizeof SHOW; k++) {
        uint8_t op = pgm_read_byte(&SHOW[k]);
        irb_force(op);
        cap_pl_pa();
        uint8_t n = frames(f, MAXFR);
        uart_putsP("     op=0x"); uart_puthex8(op);
        uart_putsP("  frames="); uart_putdec(n);
        uart_putsP("   (anchor,dst) as captured:\r\n       ");
        for (uint8_t i = 0; i < n && i < 14; i++) {
            uart_putc('('); uart_puthex8(f[i].a);
            uart_putc(','); uart_puthex8(f[i].b); uart_putc(')');
            uart_putc(' ');
        }
        uart_putsP("\r\n       microcode says: ");
        for (uint8_t t = 0; t < 6; t++) {
            uint16_t w = mc_word(op, t);
            uart_putc('t'); uart_putc((char)('0' + t)); uart_putc('=');
            uart_putc('('); uart_puthex8(exp_anchor(w) & A_MASK);
            uart_putc(','); uart_puthex8(exp_dst(cw_expect(w, STRAP_FLAG_Z)));
            uart_putsP(") ");
            if (w & ((1u << 12) | (1u << 15))) break;   /* END or HALT */
        }
        uart_putsP("\r\n");
    }
    /* diagnostic: never fails, it only reports */
    test_check_bool(true, true, PSTR("frame_dump_printed"));
    test_end();
}

/* READ THE ROM'S EFFECTIVE OPCODE MAP OFF THE HARDWARE.

   Force all 256 IRB values and report which produce a T1 row that differs from
   the FILL word. This is the instrument that found the reversed IRB ribbon:
   every responder decoded as bit N landing on bit 7-N, and only 0x00 and 0xFF
   — the two bit-reversal-invariant bytes — ever behaved, which is exactly why
   HALT=0xFF masked the fault and block1.seq passed throughout (2026-07-30).

   Each fault has its own signature here:
     responds == MC_OPCODES        address path sound; look at decode
     only 0xFF responds            address lines tied together
     a SHIFTED set responds        ribbon offset, or an address permutation
     every responder shares a bit  that line is stuck high; the mask names it
     no responder has a bit        that line is stuck low
     nothing responds              IRB is not arriving at all

   NOW COMPARES ALL FOUR SAMPLED BYTES, not the anchor alone. Anchor-only had
   six blind spots: LDA/STA/JMP/JNZ share FETCH's anchor and CLR/OUT share
   FILL's, so 6 of 17 real opcodes were invisible and the scan could only ever
   report 11. Sampling T means we can look at T1 specifically instead of
   hunting for a distinctive frame, and comparing dst/src/jmp too makes every
   implemented opcode detectable. */
void t_block1_opmap(void) {
    test_begin(m_block1, PSTR("opmap"));
    if (!bind_irb("block1")) { test_end(); return; }
    const uint32_t fill = cw_expect(0x1000, STRAP_FLAG_Z);
    const uint8_t f_a = exp_anchor(0x1000) & A_MASK, f_d = exp_dst(fill),
                  f_s = exp_src(fill), f_j = exp_jmp(fill);
    uint16_t n_resp = 0, shown = 0;
    uint8_t and_mask = 0xFF, or_mask = 0x00;
    samp_t s;

    uart_putsP("     responders (opcode:anchor):\r\n       ");
    for (uint16_t op = 0; op < 256; op++) {
        irb_force((uint8_t)op);
        uint8_t got = 0, ga = 0;
        for (uint16_t k = 0; k < 3000 && !got; k++) {
            dither(k);
            if (!sample_now(&s) || s.t != 1) continue;
            if (s.anchor != f_a || s.dst != f_d || s.src != f_s || s.jmp != f_j) {
                got = 1; ga = s.anchor;
            } else {
                got = 2;                     /* T1 seen and it IS the fill row */
            }
        }
        if (got != 1) continue;
        n_resp++;
        and_mask &= (uint8_t)op;
        or_mask  |= (uint8_t)op;
        if (shown < 24) {
            uart_puthex8((uint8_t)op); uart_putc(':'); uart_puthex8(ga);
            uart_putc(' ');
            if ((++shown % 8) == 0) uart_putsP("\r\n       ");
        }
    }
    uart_putsP("\r\n");
    if (n_resp > shown) {
        uart_putsP("     ("); uart_putdec((uint16_t)(n_resp - shown));
        uart_putsP(" more not printed)\r\n");
    }
    uart_putsP("     responders="); uart_putdec(n_resp);
    uart_putsP("  expected="); uart_putdec(MC_OPCODE_COUNT - 1);
    uart_putsP(" (MC_OPCODES minus NOP, whose T1 IS the fill row)\r\n");
    uart_putsP("     bits set in EVERY responder = 0x"); uart_puthex8(and_mask);
    uart_putsP("   bits set in ANY = 0x"); uart_puthex8(or_mask);
    uart_putsP("\r\n");
    if (n_resp && and_mask)
        uart_putsP("     ^ a bit set in every responder may be an address line "
                   "STUCK HIGH\r\n");
    if (n_resp && or_mask != 0xFF)
        uart_putsP("     ^ a bit set in no responder may be an address line "
                   "STUCK LOW\r\n");
    /* now that every implemented opcode is detectable, this can ASSERT */
    test_check_u16(n_resp, (uint16_t)(MC_OPCODE_COUNT - 1), PSTR("opcode_map_complete"));
    test_end();
}

void t_block1_stability(void) {
    test_begin(m_block1, PSTR("stability"));
    if (!bind_irb("block1")) { test_end(); return; }
    /* COMPARE A PER-T TABLE, NOT A FRAME SEQUENCE. The machine free-runs, so
       captures start at arbitrary phases and raw sequences are rotations of
       one another — diffing rotations reported divergence on identical,
       correct data. Indexing by the sampled T removes phase from the question
       entirely. */
    samp_t s;
    uint8_t seen[16], a[16], d[16], c[16], j[16];
    uint16_t bad = 0, checked = 0;
    irb_force(0x11);
    for (uint8_t i = 0; i < 16; i++) seen[i] = 0;
    for (uint8_t rep = 0; rep < 8; rep++) {
        for (uint16_t k = 0; k < 3000; k++) {
            dither(k);
            if (!sample_now(&s)) continue;
            uint8_t t = s.t & 15;
            if (!seen[t]) {
                seen[t] = 1; a[t] = s.anchor; d[t] = s.dst;
                c[t] = s.src; j[t] = s.jmp;
                continue;
            }
            checked++;
            if (a[t] != s.anchor || d[t] != s.dst ||
                c[t] != s.src || j[t] != s.jmp) {
                if (bad < 8) {
                    uart_putsP("     t="); uart_putc((char)('0' + t));
                    uart_putsP(" drifted: anchor 0x"); uart_puthex8(a[t]);
                    uart_putsP("->0x"); uart_puthex8(s.anchor);
                    uart_putsP("  dst 0x"); uart_puthex8(d[t]);
                    uart_putsP("->0x"); uart_puthex8(s.dst);
                    uart_putsP("\r\n");
                }
                if (bad < 0xFFFF) bad++;
            }
        }
    }
    test_check_bool(checked > 0, true, PSTR("samples_were_taken"));
    test_check_u16(bad, 0, PSTR("repeat_divergences"));
    test_end();
}

/* ---- block2 -------------------------------------------------------------
   A real PC drove a real MAR drove a real ROM. With T sampled, this is an
   ADDRESS-ORDER PROOF rather than "the bytes look plausible": capture a run of
   consecutive FETCH bytes, then search the ROM image for the one address whose
   walk reproduces that exact run at the instruction's own stride.

   The stride comes from the microcode — the PC_UP count of the forced opcode —
   so a wrong PC advance fails even when every individual byte is correct. That
   is the fault an unordered check cannot see.

   The search also IDENTIFIES THE SEATED IMAGE: whichever of DIAG or REAL
   reproduces the run is the one in the socket. No guessing, and no separate
   presence test.

   HONEST SCOPE: this does NOT prove PC -> MAR -> ROM. With no W driver present
   the MAR loads latch garbage, and LDA/STA/JMP/JNZ reach MAR only through the
   absent U25 bridge. What it proves is the PC_MAR_MUX handoff on M, the
   ~{RAM_EN} = INV(M15) decode, and the ROM read path onto MDR. See the named
   gap in BRINGUP.md. */
static const char m_block2[] PROGMEM = "block2";

#define NFETCH 6

/* ROM content at an address, for whichever image is seated. */
static uint8_t rom_byte(uint8_t real, uint16_t a) {
    if (!real) return pr_diag_byte(a);
    return (a < PR_PROGRAM_LEN) ? pgm_read_byte(&PR_PROGRAM[a]) : PR_SAFE_FILL;
}

/* Total PC_UP count for an opcode = how far the PC advances per instruction. */
static uint8_t pc_stride(uint8_t op) {
    uint8_t n = 0;
    for (uint8_t t = 0; t < 16; t++) {
        uint16_t w = mc_word(op, t);
        if (w & (1u << 13)) n++;
        if (w & ((1u << 12) | (1u << 15))) break;
    }
    return n ? n : 1;
}

/* ADDRESS ORDER, PROVEN FROM INSIDE ONE INSTRUCTION.

   LDA reads ROM at T0, T1 and T2 — three reads at PC, PC+1, PC+2, CONSECUTIVE
   BY CONSTRUCTION because they are rows of one instruction. Three bytes at
   three known-consecutive addresses pins the PC's low bits, the M bus, the ROM
   decode and the read path together; a wrong address line changes at least one.

   ADJACENCY COMES FROM A BURST, NOT FROM LUCK. Two earlier attempts failed on
   this: comparing successive FETCH samples assumed they were one instruction
   apart (they sit 2-3 apart at ~21% yield), and requiring two consecutive
   polled attempts to succeed never fired at all — the poll loop is ~15-19
   cycles against a 977ns clock, so the phase drifts and a success is almost
   never followed by another (2026-08-01).
   A burst samples at a FIXED interval into the arena, so consecutive buffer
   entries are consecutive in time by construction and the T-states between
   them cannot have slipped past unseen. */
#define B2CAP 600                      /* 3 bytes each: PINL, PINA, PINF */

static void cap3(void) {
    uint8_t *p = g_arena;
    uint16_t n = B2CAP / 4;
    uint8_t l, a, f;
    __asm__ volatile(
        "1:                     \n\t"
        ".rept 4                \n\t"
        "lds %[l], %[pinl]      \n\t"   /* CLK + END/HALT */
        "in  %[a], %[pina]      \n\t"   /* MDR0-7 in block2 */
        "in  %[f], %[pinf]      \n\t"   /* T0-3 in the top nibble */
        "st  X+, %[l]           \n\t"
        "st  X+, %[a]           \n\t"
        "st  X+, %[f]           \n\t"
        ".endr                  \n\t"
        "sbiw %[n], 1           \n\t"
        "brne 1b                \n\t"
        : [l] "=&r" (l), [a] "=&r" (a), [f] "=&r" (f), [n] "+w" (n), "+x" (p)
        : [pinl] "i" (_SFR_MEM_ADDR(PINL)),
          [pina] "I" (_SFR_IO_ADDR(PINA)),
          [pinf] "I" (_SFR_IO_ADDR(PINF))
        : "memory");
}

void t_block2_fetch(void) {
    test_begin(m_block2, PSTR("fetch"));
    if (!bind_irb("block2")) { test_end(); return; }

    const uint8_t op = 0x21;                 /* LDA: ROM reads at T0,T1,T2 */
    /* confirm from the BURNED MICROCODE that those rows read ROM and advance
       the PC — never assume the opcode table */
    for (uint8_t t = 0; t < 3; t++) {
        uint16_t w = mc_word(op, t);
        if (((w >> 3) & 7) != 1 || !((w >> 13) & 1)) {
            uart_putsP("     LDA row t="); uart_putc((char)('0' + t));
            uart_putsP(" is not a PC-advancing ROM read; pick another opcode\r\n");
            test_check_bool(false, true, PSTR("opcode_reads_ROM_at_T0_T1_T2"));
            test_end(); return;
        }
    }
    irb_force(op);

    uint8_t b[3], have = 0;
    for (uint8_t attempt = 0; attempt < 12 && have < 3; attempt++) {
        cap3();
        /* walk the buffer for T=0,1,2 in CLK-low entries that are CLOSE
           TOGETHER. A gap of more than 4 buffer slots could hide a T-state,
           so it does not count as contiguous. */
        int16_t i0 = -1, i1 = -1;
        for (uint16_t i = 0; i < B2CAP; i++) {
            uint8_t l = g_arena[i * 3], f = g_arena[i * 3 + 2];
            if (l & (1 << A_CLK)) continue;          /* ROM still settling */
            uint8_t t = (uint8_t)(f >> 4);
            uint8_t mdr = g_arena[i * 3 + 1];
            if (t == 0) { i0 = (int16_t)i; i1 = -1; b[0] = mdr; continue; }
            if (t == 1 && i0 >= 0 && (int16_t)i - i0 <= 4) {
                i1 = (int16_t)i; b[1] = mdr; continue;
            }
            if (t == 2 && i1 >= 0 && (int16_t)i - i1 <= 4) {
                b[2] = mdr; have = 3; break;
            }
            i0 = -1; i1 = -1;
        }
    }
    test_check_u16(have, 3, PSTR("captured_T0_T1_T2_contiguously"));
    if (have < 3) {
        uart_putsP("     no contiguous T0/T1/T2 in 12 bursts. Burst period "
                   "~687ns vs a 977ns\r\n     T-state. Halve the clock at the "
                   "U20 divider and re-run.\r\n");
        test_end(); return;
    }
    uart_putsP("     consecutive ROM reads: ");
    for (uint8_t k = 0; k < 3; k++) { uart_puthex8(b[k]); uart_putc(' '); }
    uart_putsP("\r\n");

    uint16_t found = 0xFFFF, nmatch = 0;
    uint8_t real_img = 0;
    for (uint8_t img = 0; img < 2; img++)
        for (uint32_t a = 0; a + 2 < PR_SIZE; a++)
            if (rom_byte(img, (uint16_t)a) == b[0] &&
                rom_byte(img, (uint16_t)(a + 1)) == b[1] &&
                rom_byte(img, (uint16_t)(a + 2)) == b[2]) {
                if (found == 0xFFFF) { found = (uint16_t)a; real_img = img; }
                if (nmatch < 0xFFFF) nmatch++;
            }

    if (found == 0xFFFF) {
        uart_putsP("     that triple appears at NO consecutive addresses in "
                   "either image — the\r\n     fetch path is delivering bytes "
                   "the ROM does not contain at PC, PC+1, PC+2\r\n");
    } else {
        uart_putsP("     matches the ");
        if (real_img) uart_putsP("REAL"); else uart_putsP("DIAG");
        uart_putsP(" image at 0x");
        uart_puthex8((uint8_t)(found >> 8)); uart_puthex8((uint8_t)found);
        uart_putsP(", and at "); uart_putdec(nmatch);
        uart_putsP(" address(es) in total\r\n");
    }
    test_check_bool(found != 0xFFFF, true, PSTR("reads_are_ROM_at_PC_PC1_PC2"));
    /* THE THRESHOLD IS GENERATED, NOT GUESSED. Three consecutive diag bytes
       do not identify a unique address: the byte truncates to 8 bits, so the
       triple leaves a 4-fold ambiguity almost everywhere and 8-fold in places.
       A hand-picked 4 would have false-failed on 3% of positions. What the
       match DOES prove is that the three bytes are consecutive ROM content at
       PC, PC+1, PC+2 — a 1-in-4096 discrimination, which is the claim. */
    test_check_bool(nmatch > 0 && nmatch <= PR_DIAG_TRIPLE_MAX, true,
                    PSTR("match_is_within_the_images_own_ambiguity"));
    test_end();
}

/* Diagnostic: what the rig actually sees, per T-state. Never fails. */
void t_block2_dump(void) {
    test_begin(m_block2, PSTR("dump"));
    if (!bind_irb("block2")) { test_end(); return; }
    static const uint8_t SHOW[] PROGMEM = {0x00, 0x11, 0x21};
    samp_t s;
    for (uint8_t i = 0; i < sizeof SHOW; i++) {
        uint8_t op = pgm_read_byte(&SHOW[i]);
        irb_force(op);
        uint8_t seen[16], mdr[16];
        for (uint8_t t = 0; t < 16; t++) seen[t] = 0;
        for (uint16_t k = 0; k < 8000; k++) {
            dither(k);
            if (!sample_now(&s)) continue;
            if (!seen[s.t & 15]) { seen[s.t & 15] = 1; mdr[s.t & 15] = s.dst; }  /* PORTA = MDR here */
        }
        uart_putsP("     op=0x"); uart_puthex8(op);
        uart_putsP(" stride="); uart_putdec(pc_stride(op));
        uart_putsP("  MDR by T: ");
        for (uint8_t t = 0; t < 16; t++) {
            if (!seen[t]) continue;
            uart_putc('t'); uart_putc((char)('0' + t)); uart_putc('=');
            uart_puthex8(mdr[t]); uart_putc(' ');
        }
        uart_putsP("\r\n");
    }
    test_check_bool(true, true, PSTR("dump_printed"));
    test_end();
}

/* ---- block3 -------------------------------------------------------------
   DRIVEN IS ZERO FROM HERE DOWN. The IR is real, so the machine fetches its
   own instruction bytes and IRB0-7 stops being forced — it stays in the SAME
   HOLES at U16 and flips from rig output to rig input.

   Sampling at the CONSUMER end is what makes it the MIRROR-WITNESS for the U25
   bridge: block2 read that same byte at MDR, BEFORE it crossed U25 and U34. A
   bridge or IR permutation that a MDR-side read cancels out shows up here and
   nowhere else. That is the fault class that flipped-PORTF hid from every
   round-trip test on the registers board.

   THE WALK IS SELF-STRIDING, and that is the point. Each fetched byte
   determines its OWN instruction length via its PC_UP count, so the expected
   next address depends on what was just fetched: 0x41 advances 1, 0x11
   advances 2, 0x22 advances 3. A sequence of four fetches therefore encodes
   both the bytes AND the lengths, and block2 could not test lengths at all
   because it forced IRB constant. A wrong instruction length desyncs the very
   next fetch. */
static const char m_block3[] PROGMEM = "block3";

#define B3CAP 600

/* NO CLK QUALIFICATION HERE, AND THAT IS THE POINT.
   U6 is a '163, so T holds for the whole T-state. U34 (the IR) is a 74LS373,
   which is a TRANSPARENT LATCH, not a register — and LE_IR = NOR(CLK,
   ~{IR_LOAD}) at U22 gate 1, so it is open only while CLK is LOW during T0,
   the one T-state that asserts IR_LOAD:

       T0, CLK high   latch closed   IRB = the PREVIOUS opcode
       T0, CLK low    latch OPEN     IRB follows W, the new opcode
       T1..Tn         latch closed   IRB = the current opcode

   SO IRB IS SAMPLED AT T1, NOT T0. At T0 it changes MID-T-STATE and an
   unqualified read returns the previous instruction's opcode about half the
   time, which would look like random corruption in the walk. At T1 the latch
   is shut and holds the current opcode unambiguously, with no CLK needed —
   and every instruction has a T1, since the shortest is fetch plus an END row.
   (Rico caught this by asking whether LE_IR was really derived from CLK and
   ~{IR_LOAD}; I had called the IR "registered" without working through the
   transparency window. 2026-08-02.)

   Dropping CLK takes the burst from three ports to two — 7 cycles, 437ns —
   which is 2.24 samples per T-state instead of 0.71. That is the difference
   between seeing EVERY T-state and seeing half of them. At 0.71 the sampler
   missed roughly half, so two consecutive T0 captures could be two
   INSTRUCTIONS apart and the walk would silently compare non-adjacent fetches
   while looking perfectly healthy.

   CLK and T0-3 stay wired — they are the standing timing set and other tests
   use them. This burst simply does not need CLK. */
static void cap2_pk(void) {
    uint8_t *p = g_arena;
    uint16_t n = B3CAP / 4;
    uint8_t k, f;
    __asm__ volatile(
        "1:                     \n\t"
        ".rept 4                \n\t"
        "lds %[k], %[pink]      \n\t"   /* IRB0-7 at U16, the consumer end */
        "in  %[f], %[pinf]      \n\t"   /* T0-3 in the top nibble */
        "st  X+, %[k]           \n\t"
        "st  X+, %[f]           \n\t"
        ".endr                  \n\t"
        "sbiw %[n], 1           \n\t"
        "brne 1b                \n\t"
        : [k] "=&r" (k), [f] "=&r" (f), [n] "+w" (n), "+x" (p)
        : [pink] "i" (_SFR_MEM_ADDR(PINK)), [pinf] "I" (_SFR_IO_ADDR(PINF))
        : "memory");
}

#define NOPS 4                          /* four fetches = 32 bits of constraint */

/* Search both images for the start address whose walk reproduces the stream.
   Shared by block3.free and block3.clocked so the two runs make EXACTLY the
   same claim and differ only in how the stream was collected. */
static uint16_t walk_match(const uint8_t *ops, uint8_t n, uint16_t *nmatch_out)
{
    uint16_t found = 0xFFFF, nmatch = 0;
    uint8_t real_img = 0;
    for (uint8_t img = 0; img < 2; img++)
        for (uint32_t a = 0; a < PR_SIZE; a++) {
            uint16_t pc = (uint16_t)a;
            uint8_t ok = 1;
            for (uint8_t i = 0; i < n; i++) {
                uint8_t b = rom_byte(img, pc);
                if (b != ops[i]) { ok = 0; break; }
                if (b == MC_HALT_OPCODE) { ok = (i == n - 1); break; }
                uint8_t jmp = 0;
                for (uint8_t t = 0; t < 16; t++) {
                    uint16_t w = mc_word(b, t);
                    if (((w >> 6) & 7) == 2) jmp = 1;            /* misc=PC_LOAD */
                    if (w & ((1u << 12) | (1u << 15))) break;
                }
                if (jmp)                                          /* PC <- MAR */
                    pc = (uint16_t)(rom_byte(img, (uint16_t)(pc + 1)) |
                                    ((uint16_t)rom_byte(img, (uint16_t)(pc + 2)) << 8));
                else
                    pc = (uint16_t)(pc + pc_stride(b));
            }
            if (!ok) continue;
            if (found == 0xFFFF) { found = (uint16_t)a; real_img = img; }
            if (nmatch < 0xFFFF) nmatch++;
        }
    if (found == 0xFFFF) {
        uart_putsP("     no start address reproduces that stream in either "
                   "image. Either the IR is\r\n     latching the wrong byte "
                   "(U25 bridge or U34), or an instruction LENGTH is\r\n"
                   "     wrong and the PC lands off the next opcode.\r\n");
    } else {
        uart_putsP("     self-striding walk matches the ");
        if (real_img) uart_putsP("REAL"); else uart_putsP("DIAG");
        uart_putsP(" image from 0x");
        uart_puthex8((uint8_t)(found >> 8)); uart_puthex8((uint8_t)found);
        uart_putsP(", at "); uart_putdec(nmatch);
        uart_putsP(" address(es)\r\n");
    }
    if (nmatch_out) *nmatch_out = nmatch;
    return found;
}

void t_block3_free(void) {
    test_begin(m_block3, PSTR("free"));
    pins_idle();                        /* the rig drives NOTHING from here down */

    uint8_t ops[NOPS], have = 0, tseq[NOPS];
    for (uint8_t attempt = 0; attempt < 8 && have < NOPS; attempt++) {
        cap2_pk();
        have = 0;
        /* ACCEPT ON SEQUENCE, NOT ON SAMPLE COUNT. T is a '163 output, so it
           can only advance by +1 or wrap to 0. Judging a T-state by how many
           samples it got is wrong here: the burst is unrolled .rept 4 with the
           loop overhead OUTSIDE, so the intervals are 437,437,437,687ns — NOT
           uniform. A T-state landing on the long gap gets ONE sample instead of
           two, a count-based debounce rejects it, `stable` never leaves 1, and
           the NEXT T1 is discarded as a repeat. An entire INSTRUCTION vanishes
           and the walk silently compares N against N+2.
           That is exactly the ~30% pass rate seen on the bench — it worked
           whenever four consecutive instructions dodged the long gap, and when
           it did pass it matched at 4 addresses, the image's own structural
           ambiguity, which is a genuine hit (2026-08-02).
           The +1 rule tolerates a one-sample T-state and still rejects a
           straddle caught while the '163 outputs settle, since a straddled read
           almost never lands on precisely the next value. */
        uint8_t last = 0xFF;
        for (uint16_t x = 0; x < B3CAP && have < NOPS; x++) {
            uint8_t t = (uint8_t)(g_arena[x * 2 + 1] >> 4);
            if (t == last) continue;                 /* same T-state, still */
            if (!(last == 0xFF || t == (uint8_t)(last + 1) || t == 0))
                continue;                            /* out of sequence: straddle */
            last = t;
            /* IRB is read at T1, where the IR latch is shut and holds the
               current opcode — at T0 it is transparent for half the T-state. */
            if (t == 1) { tseq[have] = t; ops[have] = g_arena[x * 2]; have++; }
        }
    }
    (void)tseq;
    uart_putsP("     opcode stream: ");
    for (uint8_t i = 0; i < have; i++) { uart_puthex8(ops[i]); uart_putc(' '); }
    uart_putsP("\r\n");
    test_check_u16(have, NOPS, PSTR("captured_consecutive_fetches"));
    if (have < NOPS) {
        uart_putsP("     could not catch four consecutive instructions. Each is "
                   "read at T1, where\r\n     the IR latch is shut and holds "
                   "the current opcode.\r\n");
        test_end(); return;
    }

    uint16_t nmatch = 0;
    uint16_t found = walk_match(ops, NOPS, &nmatch);
    test_check_bool(found != 0xFFFF, true, PSTR("IR_fetches_ROM_with_right_lengths"));
    test_check_bool(nmatch > 0 && nmatch <= PR_DIAG_TRIPLE_MAX, true,
                    PSTR("match_is_within_the_images_own_ambiguity"));
    test_end();
}

/* THE STEPPED TWIN. Same claim as block3.free, taken deterministically.

   The rig drives CLKIN (A0 -> U20.2) with Y1 disabled at its EN pin, so it owns
   the clock. U20's Q0 is /2 and U27's FF-A is /2, giving CLK = pulses/4 — but
   step() SYNCS on CLK rather than counting, because U20's ~MR is tied high so
   the divider has no reset and its power-up phase is arbitrary.

   THIS IS AN INSTRUMENT, NOT THE ACCEPTANCE PATH. It drives one wire, so a
   stepped run is 1 driven where the acceptance ladder is 0; the gate governs
   acceptance, exactly as it does for the LA and the scope. Acceptance stays
   free-run, because only free-run can retire timing.

   What it buys over block3.free: every T-state is visited by construction, so
   there is no sampling race, no adjacency question and no dropped instruction.
   If free passes and clocked fails, the fault is in the rig's sampling. If
   clocked passes and free fails INTERMITTENTLY, that is the sampler too. If
   clocked fails outright, the machine is wrong — and that is a much stronger
   statement than a free-run failure, because nothing was inferred. */
static hwpin_t P_CLKIN, P_CLK;

static bool bind_step(void) {
    if (!sig_lookup("block3", "CLKIN", &P_CLKIN)) {
        uart_putsP("     CLKIN not in the bundle\r\n");
        return false;
    }
    if (!sig_lookup("block3", "CLK", &P_CLK)) {
        uart_putsP("     CLK not in the bundle\r\n");
        return false;
    }
    return true;
}

static bool step_edge(void);

/* A RUNNING Y1 LOOKS EXACTLY LIKE A WORKING STEP, and step_edge() cannot tell
   the difference: it returns the moment CLK differs from its previous value,
   and a 1.024MHz oscillator changes CLK every 488ns. So it answers "the rig
   owns the clock" on the first read, always, while the machine free-runs past
   every sample the test believes it is placing.

   The bench trace that exposed this (2026-08-02, immediately after a free run,
   Y1 still enabled) showed ONE frame: T=1, HALT, 0 END pulses. The program had
   finished microseconds earlier; every "step" sampled a machine already parked.
   The old failure message had it backwards — it said Y1 would keep CLK from
   FOLLOWING, when in fact Y1 makes CLK follow ITSELF and the test passes.

   The discriminating question is not "does CLK move?" but "does CLK HOLD STILL
   when I stop asking?" Hold CLKIN and watch. Anything that moves is not us. */
static bool rig_owns_clock(void) {
    drv(&P_CLKIN, false);
    settle();
    bool lvl = smp(&P_CLK);
    for (uint16_t i = 0; i < 3000; i++)      /* >> 976ns, so a live Y1 cannot hide */
        if (smp(&P_CLK) != lvl) return false;
    return true;
}

/* Both halves, in the order that names the fault. */
static bool bind_clock(void) {
    if (!rig_owns_clock()) {
        uart_putsP("     CLK moves while CLKIN is held — Y1 still running. "
                   "Disable Y1 at its EN\r\n     pin (or open the "
                   "Y1.8->U20.2 header). Leave the CLKIN jumper on U20.2.\r\n");
        test_check_bool(false, true, PSTR("Y1_is_disabled"));
        return false;
    }
    if (!step_edge()) {
        uart_putsP("     CLK did not follow CLKIN in 64 pulses. The rig's "
                   "CLKIN jumper is not\r\n     on U20.2, or the divider is "
                   "not passing edges.\r\n");
        test_check_bool(false, true, PSTR("rig_owns_the_clock"));
        return false;
    }
    return true;
}

/* One CLK EDGE: pulse the divider until CLK changes. Only meaningful once
   rig_owns_clock() has established that nothing ELSE can move CLK. */
static bool step_edge(void) {
    bool before = smp(&P_CLK);
    for (uint8_t i = 0; i < 64; i++) {
        drv(&P_CLKIN, true);  settle();
        drv(&P_CLKIN, false); settle();
        if (smp(&P_CLK) != before) return true;
    }
    return false;
}

void t_block3_clocked(void) {
    test_begin(m_block3, PSTR("clocked"));
    if (!bind_step()) { test_end(); return; }

    /* Y1 MUST BE OFF, and "off" has to be PROVEN by stillness, not inferred
       from CLK moving — a live Y1 moves it for us. See bind_clock(). */
    if (!bind_clock()) { test_end(); return; }

    /* THE DIVIDER RATIO, which root.clock cannot test: it measures the
       resulting frequency but cannot say which stage is wrong. Two pulses per
       CLK edge is U20's Q0 (/2) feeding U27's toggle. */
    uint8_t pulses = 0;
    bool before = smp(&P_CLK);
    for (uint8_t i = 0; i < 16 && pulses < 16; i++) {
        drv(&P_CLKIN, true);  settle();
        drv(&P_CLKIN, false); settle();
        pulses++;
        if (smp(&P_CLK) != before) break;
    }
    uart_putsP("     pulses per CLK edge: "); uart_putdec(pulses);
    uart_putsP("  (U20 Q0 /2 then U27 /2)\r\n");
    test_check_u16(pulses, 2, PSTR("divider_is_two_pulses_per_CLK_edge"));

    /* Walk four instructions, reading IRB at T1 where the IR latch is shut. */
    uint8_t ops[NOPS], have = 0, last = 0xFF;
    for (uint16_t guard = 0; guard < 4000 && have < NOPS; guard++) {
        if (!step_edge()) break;
        uint8_t t = (uint8_t)(PINF >> 4);
        if (t == last) continue;
        last = t;
        if (t == 1) ops[have++] = PINK;
    }
    uart_putsP("     opcode stream: ");
    for (uint8_t i = 0; i < have; i++) { uart_puthex8(ops[i]); uart_putc(' '); }
    uart_putsP("\r\n");
    test_check_u16(have, NOPS, PSTR("stepped_four_instructions"));
    if (have < NOPS) { test_end(); return; }

    uint16_t nm = 0;
    uint16_t found = walk_match(ops, NOPS, &nm);
    test_check_bool(found != 0xFFFF, true, PSTR("IR_fetches_ROM_with_right_lengths"));
    test_check_bool(nm > 0 && nm <= PR_DIAG_TRIPLE_MAX, true,
                    PSTR("match_is_within_the_images_own_ambiguity"));
    test_end();
}

/* Diagnostic: IRB by T-state, plus whether the machine is halted. */
void t_block3_dump(void) {
    test_begin(m_block3, PSTR("dump"));
    pins_idle();
    cap2_pk();
    uint8_t seen[16], irb[16];
    for (uint8_t t = 0; t < 16; t++) seen[t] = 0;
    uint16_t nsamp = 0;
    for (uint16_t i = 0; i < B3CAP; i++) {
        uint8_t t = (uint8_t)(g_arena[i * 2 + 1] >> 4);
        nsamp++;
        if (!seen[t]) { seen[t] = 1; irb[t] = g_arena[i * 2]; }
    }
    /* HALT is read live rather than from the burst — this burst carries only
       IRB and T, since both are registered and need no CLK qualification. */
    hwpin_t p_halt;
    uint8_t halted = sig_lookup("block3", "CW15=HALT", &p_halt) && smp(&p_halt);
    uart_putsP("     samples: "); uart_putdec(nsamp);
    uart_putsP("   HALT now: "); uart_putc(halted ? '1' : '0');
    uart_putsP("\r\n     IRB by T: ");
    for (uint8_t t = 0; t < 16; t++) {
        if (!seen[t]) continue;
        uart_putc('t'); uart_putc((char)('0' + t)); uart_putc('=');
        uart_puthex8(irb[t]); uart_putc(' ');
    }
    uart_putsP("\r\n");
    if (halted)
        uart_putsP("     machine HALTED. For a long free run seat PROG_diag: "
                   "make -C tests/dino_bringup burn-prog-diag\r\n");
    test_check_bool(true, true, PSTR("dump_printed"));
    test_end();
}

/* ---- blocks 4/5/6 -------------------------------------------------------
   The milestone: 4 END pulses (LDAI, LDBI, ADD, OUT), then HALT forever and
   END never again — HALT's row is 0x8000 and carries no END bit. OB reads
   PR_EXPECT_SUM.

   U35 HAS NO RESET, so on a re-run OB may already hold the answer before the
   program starts, which degenerates "OB became 0x08" into "OB is 0x08".
   POWER CYCLE for the strong form. If OB already reads the answer at trigger,
   print INCONCLUSIVE — never PASS. NO BLIND COUNTERS.

   bit-reverse(0x08) = 0x10, so a flipped OB ribbon reads 0x10 and self-names.
   The milestone value is self-witnessing; most bytes are not. */
/* WHEN HALT WILL NOT SIT STILL, SAY WHICH FAULT IT IS. A machine that was
   reset again dips once; a machine whose T-counter is not frozen at HALT runs
   the safe-fill row after it (0x1000, END), clears T, re-fetches the HALT
   opcode and pulses HALT every couple of T-states. Those need opposite
   repairs, and "unstable" names neither. Counting edges separates them. */
static void halt_shape(const hwpin_t *p) {
    uint16_t edges = 0, highs = 0;
    bool prev = smp(p);
    for (uint16_t k = 0; k < 20000u; k++) {
        bool cur = smp(p);
        if (cur != prev) edges++;
        if (cur) highs++;
        prev = cur;
    }
    uart_putsP("     HALT over 20000 samples: "); uart_putdec(edges);
    uart_putsP(" edges, high "); uart_putdec((uint16_t)(highs / 200u));
    uart_putsP("%\r\n");
    if (edges > 50u)
        uart_putsP("     HALT OSCILLATING — T is not frozen. Check CW15 -> "
                   "the '163 CET.\r\n");
    else if (edges > 0u)
        uart_putsP("     single event, not a loop — reset again after "
                   "halting\r\n");
}

/* Print every reading of `ob` that a known image would explain: the byte
   itself, its bit-reversal (flipped ribbon — the fault registers.outreg was
   built to catch), and its nibble swap — a transposed 4-bit half, which is
   what a two-connector OB ribbon can do and a mirror check cannot see.

   A permuted byte is not a wrong answer, and the two must never look alike:
   one is a ribbon, the other is the ALU. This is why every coverage answer is
   chosen to be neither mirror- nor nibble-swap-invariant — the permutations
   are only nameable if the byte survives them as something distinguishable. */
static void name_ob_permutations(uint8_t ob) {
    uint8_t rev = 0;
    for (uint8_t b = 0; b < 8; b++)
        if (ob & (1u << b)) rev |= (uint8_t)(0x80u >> b);
    uint8_t swap = (uint8_t)((ob << 4) | (ob >> 4));
    for (uint8_t i = 0; i < PR_COV_COUNT; i++) {
        uint8_t want = PR_COVERAGE[i].expect_ob;
        const char *how = NULL;
        if      (want == rev)  how = PSTR(" is BIT-REVERSED 0x");
        else if (want == swap) how = PSTR(" has its NIBBLES SWAPPED vs 0x");
        else continue;
        uart_putsP("     NOTE: 0x"); uart_puthex8(ob);
        uart_puts_p(how); uart_puthex8(want);
        uart_putsP(" (PROG_"); uart_puts(PR_COVERAGE[i].name);
        uart_putsP(") — check the OB ribbon\r\n");
    }
}

static void milestone_run(const char *mod)
{
    pins_idle();   /* rig drives NOTHING from block3 down — release before reading */
    hwpin_t p_halt;
    if (!sig_lookup(mod, "CW15=HALT", &p_halt)) {
        test_check_bool(false, true, PSTR("HALT_pin_bound"));
        return;
    }
    uint8_t ob_before = PINK;
    uart_putsP("     OB before run = 0x"); uart_puthex8(ob_before); uart_putsP("\r\n");

    /* CHECK THE PRECONDITION, DO NOT RUN BLIND. The trigger below waits for
       HALT to FALL, which only means "the run started" if the machine is
       HALTED when you arm. With the milestone image it is: it runs five
       instructions, fetches 0xFF and parks. With PROG_diag seated it never
       halts — the diag bytes execute as a long random program — so HALT is
       already low, the wait returns INSTANTLY, and the ARM prompt flies past
       without the operator ever pressing anything. That is what happened on
       the bench (2026-08-02): 20 END pulses, OB never the sum, and no chance
       to press the button. */
    /* IS THERE A CLOCK AT ALL? A free-run test needs Y1 running, and the
       step-clock tests need it OFF — so the bench alternates between the two
       and arrives here with Y1 still pulled. A stopped machine is not halted,
       so the check below fires and blames the ROM. It cost a round of beeping
       for a missing oscillator. CLK toggling shows as BOTH levels in a tight
       poll; a stopped clock shows one. */
    hwpin_t p_clk;
    if (sig_lookup(mod, "CLK", &p_clk)) {
        uint8_t seen = 0;
        for (uint16_t i = 0; i < 4000 && seen != 3; i++)
            seen |= smp(&p_clk) ? 1 : 2;
        if (seen != 3) {
            uart_putsP("     CLK is STUCK — Y1 is not running. This is a "
                       "FREE-RUN test: seat Y1 and\r\n     unplug the rig's "
                       "CLKIN jumper from U20.2.\r\n");
            test_check_bool(false, true, PSTR("Y1_is_running"));
            return;
        }
    }

    if (!smp(&p_halt)) {
        uart_putsP("     machine NOT HALTED — nothing to arm against. Needs "
                   "the MILESTONE image:\r\n     make -C tests/dino_bringup "
                   "burn-prog\r\n");
        test_check_bool(false, true, PSTR("machine_is_halted_before_arming"));
        return;
    }

    /* AND CHECK THE RIGHT IMAGE IS IN THE SOCKET. This test is pinned to the
       milestone, but the ROM is swapped constantly for coverage images, and a
       seated PROG_wide makes it print four FAILs — wrong END count, END after
       HALT, wrong OB, unstable freeze — none of which is a machine fault. Four
       lies teach the operator to skim the FAIL lines, which is exactly how a
       real failure gets waved through. OB is already parked at the previous
       run's answer here, so the wrong image is identifiable BEFORE arming. */
    for (uint8_t i = 0; i < PR_COV_COUNT; i++) {
        if (PR_COVERAGE[i].expect_ob != ob_before) continue;
        if (ob_before == PR_EXPECT_SUM) break;   /* ambiguous, let it run */
        uart_putsP("     OB is parked at PROG_"); uart_puts(PR_COVERAGE[i].name);
        uart_putsP("'s answer — that image is seated; this test needs "
                   "PROG.bin\r\n     make -C tests/dino_bringup burn-prog"
                   "   (or use block4.stepped)\r\n");
        test_check_bool(false, true, PSTR("milestone_image_seated"));
        return;
    }

    uart_putsP("     ARM: press RESET (30s)\r\n");
    if (!await_level(&p_halt, false, 30000)) {
        uart_putsP("     HALT never fell — the button was not pressed, or "
                   "RESET is not reaching\r\n     the T counter.\r\n");
        test_check_bool(false, true, PSTR("run_started_HALT_fell"));
        return;
    }
    cap_pl_pk();
    frame_t f[MAXFR];
    uint8_t n = frames(f, MAXFR);

    uint8_t ends = 0;
    bool end_after_halt = false, halted = false;
    for (uint8_t i = 0; i < n; i++) {
        if (f[i].a & (1 << A_HALT)) halted = true;
        if (f[i].a & (1 << A_END)) {
            ends++;
            if (halted) end_after_halt = true;
        }
    }
    /* INFORMATION, NOT AN ASSERTION. These counts cannot be measured from a
       free run and must never fail one. The trigger is HALT FALLING, which is
       RESET ASSERTING; the RC stretch then holds the machine 0.25-2.2s while
       this burst finishes in a few hundred us. The capture is over long before
       the program is released, and the program itself is ten T-states — about
       10us. The window and the run never overlap.

       So the number below is whatever the capture landed on: the bench has
       seen 5, 6 and 20 across runs of a CORRECT machine. Asserting on it was
       the same defect block1 was fixed for — measuring the test instead of the
       machine. block4.stepped counts ENDs for real, because there the rig owns
       the clock and the machine cannot move between samples. */
    uart_putsP("     capture landed on "); uart_putdec(ends);
    uart_putsP(" END pulses");
    if (end_after_halt) uart_putsP(", some after HALT");
    uart_putsP("  (not an assertion — see comment)\r\n");

    /* ACCEPT THE RISE ONLY IF IT HOLDS. await_level() returns on the first
       HIGH it sees, and a HIGH that lasts one T-state is not the machine
       parking — it is the machine passing through. Reading OB off a transient
       returns the PREVIOUS run's answer, because U35 has no reset, and that
       reads as a pass. Require the level to survive 5ms, which is 5000 CLK
       periods; nothing in a ten-T-state program is high that long. */
    /* NO HURRY. The old form waited 2s for HALT to rise and gave up on the
       first timeout — but the RESET RC stretch alone is 0.25-2.2s before a
       finger is accounted for, so a normal press could expire it. A timeout
       here is not evidence of anything; only the deadline running out is.
       `continue`, not `break`: keep waiting up to ~40s. */
    bool risen = false;
    for (uint8_t tries = 0; tries < 40 && !risen; tries++) {
        if (!await_level(&p_halt, true, 1000)) continue;
        risen = true;
        for (uint8_t k = 0; k < 50; k++) {
            _delay_us(100);
            if (!smp(&p_halt)) { risen = false; break; }
        }
    }
    if (!risen) {
        uart_putsP("     HALT rises and falls again — not parking at HALT\r\n");
        test_check_bool(false, true, PSTR("machine_reached_HALT"));
        halt_shape(&p_halt);
        return;
    }
    uint8_t ob = PINK;
    test_check_u16(ob, PR_EXPECT_SUM, PSTR("OB_is_the_sum"));
    if (ob == PR_POISON) {
        uart_putsP("     OB is the POISON value — run started, never reached "
                   "the second OUT\r\n");
    } else if (ob != PR_EXPECT_SUM) {
        name_ob_permutations(ob);
        uart_putsP("     verify the seated ROM: run memory.romcrc "
                   "(expects PR_CRC_REAL)\r\n");
    }

    /* THE FREEZE MUST BE STABLE — not a droop, not a silent restart. NAME THE
       SIGNAL THAT MOVED: "unstable" is two very different faults and reporting
       one bit for both is the blind-counter rule broken. HALT going low means
       the machine left HALT, which it cannot do (HALT is a fixed point) unless
       something reset it — or unless the trigger fired on a transient and the
       REAL run is only now happening. OB changing under a still-high HALT is
       the opposite: the machine is parked and something else is driving OB.

       Compared against `ob` as read, not against PR_EXPECT_SUM: correctness is
       OB_is_the_sum's job, and folding the two makes a wrong-but-steady answer
       report as instability. */
    bool stable = true;
    for (uint8_t i = 0; i < 10 && stable; i++) {
        _delay_ms(100);
        bool h = smp(&p_halt);
        uint8_t v = PINK;
        if (h && v == ob) continue;
        stable = false;
        uart_putsP("     at +"); uart_putdec((uint16_t)(i + 1) * 100);
        uart_putsP("ms: ");
        if (!h) {
            uart_putsP("HALT went LOW — the machine left HALT\r\n");
        } else {
            uart_putsP("OB changed 0x"); uart_puthex8(ob);
            uart_putsP(" -> 0x"); uart_puthex8(v);
            uart_putsP(" with HALT still high\r\n");
        }
    }
    test_check_bool(stable, true, PSTR("HALT_and_OB_stable_1s"));
    /* THE STALE-ANSWER PROBLEM IS GONE, AND NOT BECAUSE THE TEST GOT CLEVERER.
       The program now writes 0xFF to OB before it computes anything, so any run
       that starts destroys the previous answer. OB can only read the sum if
       THIS run reached the second OUT. The old INCONCLUSIVE note fired whenever
       OB already held the answer — which was ALWAYS, since the machine
       free-runs at power-up and parks on its own result, and U35 has no reset
       for a power-cycle to clear. */
    (void)ob_before;
}

static const char m_block4[] PROGMEM = "block4";
static const char m_block5[] PROGMEM = "block5";

/* THE MILESTONE, STEPPED. This is the one that can actually be run.

   The free-run version cannot work and no amount of window-widening fixes it:
   the program is five instructions, TEN T-STATES, about 10us at 1.024MHz. By
   the time await_level() notices HALT fall and a burst starts, the run is over.
   That is why the bench saw 6 and 20 END pulses — the capture was landing
   around the run, not on it (2026-08-02).

   With the rig owning the clock the race disappears completely, because THE
   MACHINE IS FROZEN between pulses. Rico can press RESET whenever he likes;
   nothing advances until the rig says so. That is the real payoff of the
   CLKIN wire, and it is worth more here than anywhere else on the ladder.

   RESET IS SELF-DETECTING, so no RESET wire is needed. U6's ~MR is SYNCHRONOUS,
   so while RESET is held the counter clears on every edge and T sits at 0 —
   and the PC is held at 0 too, since RESET is one of its inputs. The moment T
   first advances 0 -> 1, RESET has released and execution has begun. That also
   waits out the RC stretch (0.25-2.2s) for free: with the clock stopped, a
   stretch costs nothing. */
static bool step_and_read(uint8_t *t, uint8_t *ob, uint8_t *anchor) {
    if (!step_edge()) return false;
    *t = (uint8_t)(PINF >> 4);
    *ob = PINK;
    *anchor = (uint8_t)(PINL & A_MASK);
    return true;
}

void t_block4_stepped(void) {
    test_begin(m_block4, PSTR("stepped"));
    pins_idle();
    if (!bind_step()) { test_end(); return; }

    if (!bind_clock()) { test_end(); return; }

    uint8_t ob_before = PINK;
    uart_putsP("     OB before run = 0x"); uart_puthex8(ob_before);
    uart_putsP("\r\n     PRESS AND RELEASE RESET\r\n");

    /* Hold at T=0 until RESET releases. While it is asserted the synchronous
       clear pins T to 0 on every edge; the first 0 -> 1 IS the release. */
    uint8_t t = 0xFF, ob = 0, anchor = 0;
    uint16_t held = 0;
    bool started = false;
    for (uint32_t k = 0; k < 2000000UL && !started; k++) {
        if (!step_and_read(&t, &ob, &anchor)) break;
        if (t == 0) { if (held < 0xFFFF) held++; }
        else if (held >= 4) started = true;      /* was pinned, now advancing */
        else held = 0;
    }
    test_check_bool(started, true, PSTR("RESET_held_T_at_zero_then_released"));
    if (!started) {
        uart_putsP("     never saw T pinned at 0 then advance. Was RESET "
                   "pressed?\r\n");
        test_end(); return;
    }

    /* Walk the program. THE FIRST T-STATE MUST BE EXAMINED TOO: `started` goes
       true once T has ALREADY advanced out of the reset hold, so it is sitting
       on T1 of the first instruction — and T1 is where LDAI carries its END.
       Seeding last_t from it skipped that, counting LDBI+ADD+OUT = 3 instead
       of 4 (bench 2026-08-02). last_t starts deliberately unequal. */
    uint8_t ends = 0, halted = 0, end_after_halt = 0, last_t = 0xFF;
    uint8_t ob_at_halt = 0;
    bool saw_poison = false;
    uart_putsP("     trace  T anchor OB\r\n");
    for (uint16_t k = 0; k < 400 && !halted; k++) {
        if (t != last_t) {
            /* NAME THE LYING SIGNAL: every T-state of a ten-state program is
               cheap to print, and it is the difference between "OB was 0x00"
               and knowing which instruction failed to change it. */
            uart_putsP("            "); uart_putc((char)('0' + (t & 15)));
            uart_putsP("   0x"); uart_puthex8(anchor);
            uart_putsP("  0x"); uart_puthex8(ob);
            if (anchor & (1 << A_END))  uart_putsP("  END");
            if (anchor & (1 << A_HALT)) uart_putsP("  HALT");
            uart_putsP("\r\n");
            if (anchor & (1 << A_END)) {
                ends++;
                if (halted) end_after_halt = 1;
            }
            if (ob == PR_POISON) saw_poison = true;
            if (anchor & (1 << A_HALT)) { halted = 1; ob_at_halt = ob; break; }
            last_t = t;
        }
        if (!step_and_read(&t, &ob, &anchor)) break;
    }

    uart_putsP("     END pulses: "); uart_putdec(ends);
    uart_putsP("   halted: "); uart_putc(halted ? '1' : '0');
    uart_putsP("   OB at HALT = 0x"); uart_puthex8(ob_at_halt);
    uart_putsP("\r\n");

    test_check_bool(halted, true, PSTR("machine_reached_HALT"));
    test_check_u16(end_after_halt, 0, PSTR("no_END_after_HALT"));

    /* WHICH IMAGE IS SEATED? The rig cannot read the program ROM here — MDR
       is not sampled in this block — so it cannot simply ask. But every
       coverage image has a distinct (OB, END-count) fingerprint, and BOTH
       halves come from simulate() walking the burned microcode. Matching the
       pair is a real assertion, not a shrug: the machine executed a KNOWN
       program, retired the right number of instructions, and produced that
       program's exact answer.

       This replaces a hard-coded 0x08 and a hard-coded 4. Every coverage
       image runs through this test, so pinning it to the milestone made a
       correct run of PROG_wide print FAIL. A test that cries wolf whenever a
       different-but-correct image is seated trains the operator to skip its
       FAIL line — which is exactly how a real failure gets waved through.
       `t_block4_milestone` still pins PROG.bin specifically; that is where
       the milestone claim belongs. */
    /* PROG.bin is NOT in PR_COVERAGE — the milestone is emitted separately,
       so it must be matched separately or a correct milestone run FAILS. */
    bool known = (ob_at_halt == PR_EXPECT_SUM && ends == PR_EXPECT_ENDS);
    if (known) uart_putsP("     seated image: PROG (the milestone)\r\n");
    int8_t img = -1;
    for (uint8_t i = 0; i < PR_COV_COUNT; i++) {
        if (PR_COVERAGE[i].expect_ob == ob_at_halt &&
            PR_COVERAGE[i].expect_ends == ends) { img = (int8_t)i; break; }
    }
    if (img >= 0) {
        known = true;
        uart_putsP("     seated image: PROG_");
        uart_puts(PR_COVERAGE[img].name);
        uart_putsP("\r\n");
    } else if (!known) {
        /* Name the near-misses. Half a fingerprint is the useful diagnosis:
           right OB + wrong END count means the machine computed the answer
           but did not retire cleanly; right END count + wrong OB points at
           the datapath or the OB ribbon. */
        if ((ob_at_halt == PR_EXPECT_SUM) != (ends == PR_EXPECT_ENDS)) {
            uart_putsP("     PROG (the milestone) matches on ");
            if (ob_at_halt == PR_EXPECT_SUM) {
                uart_putsP("OB but wants "); uart_putdec(PR_EXPECT_ENDS);
                uart_putsP(" ENDs\r\n");
            } else {
                uart_putsP("ENDs but wants OB 0x");
                uart_puthex8(PR_EXPECT_SUM); uart_putsP("\r\n");
            }
        }
        for (uint8_t i = 0; i < PR_COV_COUNT; i++) {
            bool ob_ok = PR_COVERAGE[i].expect_ob == ob_at_halt;
            bool en_ok = PR_COVERAGE[i].expect_ends == ends;
            if (ob_ok == en_ok) continue;
            uart_putsP("     PROG_"); uart_puts(PR_COVERAGE[i].name);
            if (ob_ok) uart_putsP(" has this OB but wants ");
            else       uart_putsP(" has this END count but wants OB 0x");
            if (ob_ok) { uart_putdec(PR_COVERAGE[i].expect_ends);
                         uart_putsP(" ENDs\r\n"); }
            else       { uart_puthex8(PR_COVERAGE[i].expect_ob);
                         uart_putsP("\r\n"); }
        }
        /* the flipped-OB-ribbon check, against EVERY image rather than 0x08 */
        uint8_t rev = 0;
        for (uint8_t b = 0; b < 8; b++)
            if (ob_at_halt & (1u << b)) rev |= (uint8_t)(0x80u >> b);
        for (uint8_t i = 0; i < PR_COV_COUNT; i++) {
            if (PR_COVERAGE[i].expect_ob != rev) continue;
            uart_putsP("     NOTE: 0x"); uart_puthex8(ob_at_halt);
            uart_putsP(" is bit-reversed 0x"); uart_puthex8(rev);
            uart_putsP(" (PROG_"); uart_puts(PR_COVERAGE[i].name);
            uart_putsP(") — check the OB ribbon\r\n");
            break;
        }
    }
    test_check_bool(known, true, PSTR("OB_and_ENDs_match_a_known_image"));
    /* THE STRONG FORM, WITNESSED — no longer a warning. This trace watched OB
       go answer -> POISON -> answer, so the byte at HALT was computed by THIS
       run. U35 has no reset and the machine free-runs at power-up, so OB
       ALWAYS already holds the previous answer; the old INCONCLUSIVE note
       fired every single time and told the operator nothing. The program's
       leading LDAI 0xFF; OUT is what makes the claim provable, and a stepped
       run can see it happen rather than infer it.

       Only asserted for the milestone: the coverage images do not poison. */
    if (known && ob_at_halt == PR_EXPECT_SUM && ends == PR_EXPECT_ENDS)
        test_check_bool(saw_poison, true, PSTR("OB_passed_through_the_poison"));
    else
        (void)saw_poison;

    test_end();
}

void t_block4_milestone(void) {
    test_begin(m_block4, PSTR("milestone"));
    milestone_run("block4");
    test_end();
}

void t_block5_run(void) {
    test_begin(m_block5, PSTR("run"));
    uart_putsP("     SW1 = 0xF7 (switch 3 closed). Re-run at 0xFF as the "
               "control.\r\n");
    milestone_run("block5");
    test_end();
}


