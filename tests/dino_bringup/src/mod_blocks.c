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

   Pin bundles come from `pins block1`..`pins block6` (kicad_contracts.py
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
CAP_PL_LO(cap_pl_pf, _SFR_IO_ADDR(PINF))

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

/* Index of the frame that starts a run.

   ANCHORED ON THE FULL FETCH FRAME — BOTH BYTES, NOT THE ANCHOR ALONE.
   On a four-T instruction the anchor does NOT identify T0: LDA's rows are
   0x600E, 0x600C, 0x600D and ALL THREE carry anchor 0x60, because they are
   all mux_pc+pc_up rows. Matching on the anchor alone latched onto T1 and
   shifted the whole run by one, which is precisely how LDA/STA/JMP/JNZ
   failed while every 1- and 2-T opcode passed (2026-07-30). The fetch row is
   unique only as a PAIR: (60,5F) against T1's (60,77). T0 is the universal FETCH word for
   every opcode (MC_REAL_ROW0), so its anchor byte is the same self-
   synchronising marker regardless of what is being decoded. The previous
   version returned the frame AFTER an END, which depends on END semantics,
   on T actually clearing, and on an off-by-one — and the first Block 1 run
   came back rotated by exactly one frame with no way to tell which of those
   three was at fault (2026-07-30).
   Returns 0xFF if no fetch frame was seen, which is itself a clear failure:
   the machine never executed a recognisable T0. */
static uint8_t run_start(const frame_t *f, uint8_t n,
                         uint8_t fetch_a, uint8_t fetch_b) {
    for (uint8_t i = 0; i < n; i++)
        if (f[i].a == fetch_a && f[i].b == fetch_b) return i;
    return 0xFF;
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
        uart_putsP("     transients are the microcode DECODE GLITCH: the ROM is "
                   "invalid for one\r\n     access time after T changes and the "
                   "'138s decode that garbage. Harmless\r\n     to the machine "
                   "(nothing commits during CLK high) — measure it on the\r\n"
                   "     scope, do NOT gate the '138s. See BRINGUP.md.\r\n");
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
   A real PC drove a real MAR drove a real ROM. The bytes on MDR0-7 are the
   ROM image IN ADDRESS ORDER.

   Run PROG_diag.bin FIRST: pr_diag_byte() is injective over the low addresses,
   so every fetched byte NAMES ITS OWN ADDRESS. MDR is the only address witness
   in this block — M0-15 is copper — and the real image's 0xFF tail names
   nothing. Then re-run on PROG.bin.

   HONEST SCOPE: this does NOT prove PC->MAR->ROM. With no W driver present the
   MAR loads latch garbage; LDA/STA/JMP/JNZ reach MAR only through the absent
   U25 bridge. What it proves is the PC_MAR_MUX handoff and the ROM decode. */
static const char m_block2[] PROGMEM = "block2";

void t_block2_fetch(void) {
    test_begin(m_block2, PSTR("fetch"));
    if (!bind_irb("block2")) { test_end(); return; }
    frame_t f[MAXFR];
    /* NOP holds the machine in a pure fetch loop: T0 fetch (PC++), T1 END.
       Every fetch therefore lands on the next address in order. */
    irb_force(0x00);
    cap_pl_pf();
    uint8_t n = frames(f, MAXFR);
    uint8_t s = run_start(f, n, exp_anchor(MC_REAL_ROW0) & A_MASK,
                          exp_jmp(cw_expect(MC_REAL_ROW0, STRAP_FLAG_Z)));
    if (s == 0xFF) {
        test_check_bool(false, true, PSTR("FETCH_frame_seen_machine_running"));
        test_end(); return;
    }
    /* collect the distinct fetched bytes, in order */
    uint8_t seen[16], ns = 0;
    for (uint8_t i = s; i < n && ns < 16; i++)
        if (ns == 0 || seen[ns - 1] != f[i].b) seen[ns++] = f[i].b;
    test_check_bool(ns >= 3, true, PSTR("saw_several_fetches"));

    /* Which image is seated? Both are legitimate; DIAG is the strong one. */
    bool diag = (ns > 0 && seen[0] == pr_diag_byte(0)) ||
                (ns > 1 && seen[1] == pr_diag_byte(1));
    if (diag) uart_putsP("     image: DIAG (self-naming addresses)\r\n");
    else      uart_putsP("     image: REAL (milestone)\r\n");
    uint8_t bad = 0;
    if (diag) {
        /* find the address whose diag byte matches the first sample, then
           require the rest to follow in strict address order */
        uint16_t a0 = 0xFFFF;
        for (uint16_t a = 0; a < 256; a++)
            if (pr_diag_byte(a) == seen[0]) { a0 = a; break; }
        if (a0 == 0xFFFF) {
            uart_putsP("     first byte 0x"); uart_puthex8(seen[0]);
            uart_putsP(" names no address in the first 256\r\n");
            bad++;
        } else {
            for (uint8_t i = 1; i < ns; i++) {
                uint8_t want = pr_diag_byte((uint16_t)(a0 + i));
                if (seen[i] != want) {
                    uart_putsP("     addr=0x"); uart_puthex8((uint8_t)(a0 + i));
                    uart_putsP(" got=0x"); uart_puthex8(seen[i]);
                    uart_putsP(" want=0x"); uart_puthex8(want);
                    uart_putsP("\r\n");
                    bad++;
                }
            }
        }
    } else {
        for (uint8_t i = 0; i < ns && i < PR_PROGRAM_LEN; i++) {
            uint8_t want = pgm_read_byte(&PR_PROGRAM[i]);
            if (seen[i] != want) {
                uart_putsP("     progaddr="); uart_putc((char)('0' + i));
                uart_putsP(" got=0x"); uart_puthex8(seen[i]);
                uart_putsP(" want=0x"); uart_puthex8(want);
                uart_putsP("\r\n");
                bad++;
            }
        }
    }
    test_check_u16(bad, 0, PSTR("address_order_mismatches"));
    test_end();
}

/* ---- block3 -------------------------------------------------------------
   DRIVEN IS ZERO FROM HERE DOWN. The IR is real and the machine fetches its
   own instruction bytes; IRB0-7 stays in the same holes and flips to sampled.
   Sampling at the CONSUMER end (U16) makes it the MIRROR-WITNESS for the U25
   bridge: block2 read that same byte at MDR, BEFORE it crossed U25 and U34, so
   a permutation that a MDR-side read cancels out shows up here and nowhere
   else.

   This is also the first block where INSTRUCTION LENGTH is observable: block2
   forced IRB constant, so the PC stride was constant and a length error was
   invisible. Here a wrong length desyncs the very next fetch. */
static const char m_block3[] PROGMEM = "block3";

/* Is this byte one of the implemented opcodes? Checked against the generated
   list, because the image cannot answer it — see op_at(). */
static bool op_known(uint8_t op) {
    for (uint8_t i = 0; i < MC_OPCODE_COUNT; i++)
        if (op_at(i) == op) return true;
    return false;
}

/* Walk the burned microcode to get the expected opcode sequence — instruction
   lengths come from PC_UP counts in the ROM, never from a retyped table. */
static uint8_t expect_opcodes(uint8_t *out, uint8_t max) {
    uint16_t pc = 0;
    uint8_t n = 0;
    while (n < max && pc < PR_PROGRAM_LEN) {
        uint8_t op = pgm_read_byte(&PR_PROGRAM[pc]);
        out[n++] = op;
        if (!op_known(op)) break;
        uint16_t adv = 0;
        for (uint8_t t = 0; t < 16; t++) {
            uint16_t w = mc_word(op, t);
            if (w & (1u << 13)) adv++;              /* PC_UP */
            if (w & (1u << 15)) return n;           /* HALT: stream ends */
            if (w & (1u << 12)) break;              /* END */
        }
        pc += adv ? adv : 1;
    }
    return n;
}

void t_block3_opcodes(void) {
    test_begin(m_block3, PSTR("opcodes"));
    pins_idle();   /* driven count is zero from block3 down */
    uart_putsP("     ARM: press RESET (10s)\r\n");
    hwpin_t p_halt;
    if (!sig_lookup("block3", "CW15=HALT", &p_halt)) {
        test_check_bool(false, true, PSTR("HALT_pin_bound"));
        test_end(); return;
    }
    /* the machine sits halted; HALT falling is the run starting */
    if (!await_level(&p_halt, false, 10000)) {
        test_check_bool(false, true, PSTR("run_started_HALT_fell"));
        test_end(); return;
    }
    cap_pl_pk();
    frame_t f[MAXFR];
    uint8_t n = frames(f, MAXFR);
    uint8_t got[16], ng = 0;
    for (uint8_t i = 0; i < n && ng < 16; i++)
        if (ng == 0 || got[ng - 1] != f[i].b) got[ng++] = f[i].b;

    uint8_t want[16];
    uint8_t nw = expect_opcodes(want, 16);
    uint8_t bad = 0;
    for (uint8_t i = 0; i < nw; i++) {
        if (i >= ng) {
            uart_putsP("     missing opcode #"); uart_putc((char)('0' + i));
            uart_putsP(" want=0x"); uart_puthex8(want[i]); uart_putsP("\r\n");
            bad++; continue;
        }
        if (got[i] != want[i]) {
            uart_putsP("     opcode #"); uart_putc((char)('0' + i));
            uart_putsP(" got=0x"); uart_puthex8(got[i]);
            uart_putsP(" want=0x"); uart_puthex8(want[i]); uart_putsP("\r\n");
            bad++;
        }
    }
    test_check_u16(bad, 0, PSTR("opcode_stream_mismatches"));
    test_check_bool(smp(&p_halt), true, PSTR("HALT_high_at_end"));
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
    uart_putsP("     ARM: press RESET (10s)\r\n");
    if (!await_level(&p_halt, false, 10000)) {
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
    test_check_u16(ends, 4, PSTR("END_pulses_one_per_instruction"));
    test_check_bool(end_after_halt, false, PSTR("no_END_after_HALT"));

    /* wait out the run, then read the answer */
    if (!await_level(&p_halt, true, 2000)) {
        test_check_bool(false, true, PSTR("machine_reached_HALT"));
        return;
    }
    uint8_t ob = PINK;
    test_check_u16(ob, PR_EXPECT_SUM, PSTR("OB_is_the_sum"));
    if (ob == 0x10)
        uart_putsP("     NOTE: 0x10 is bit-reversed 0x08 — check the OB ribbon\r\n");

    /* the freeze must be stable, not a droop and not a silent restart */
    for (uint8_t i = 0; i < 10; i++) {
        _delay_ms(100);
        if (!smp(&p_halt) || PINK != PR_EXPECT_SUM) {
            test_check_bool(false, true, PSTR("HALT_and_OB_stable_1s"));
            return;
        }
    }
    test_check_bool(true, true, PSTR("HALT_and_OB_stable_1s"));
    if (ob_before == PR_EXPECT_SUM)
        uart_putsP("     INCONCLUSIVE: OB already held the answer before the "
                   "run — power-cycle and repeat for the strong form\r\n");
}

static const char m_block4[] PROGMEM = "block4";
static const char m_block5[] PROGMEM = "block5";
static const char m_block6[] PROGMEM = "block6";

void t_block4_milestone(void) {
    test_begin(m_block4, PSTR("milestone"));
    milestone_run("block4");
    test_end();
}

void t_block5_run(void) {
    test_begin(m_block5, PSTR("run"));
    uart_putsP("     SW1 must read 0xF7 (switch 3 closed) — the W3 leak "
               "witness. Re-run at 0xFF as the control.\r\n");
    milestone_run("block5");
    test_end();
}

/* Block 6 is the acceptance run: the rig drives nothing, END is gone, and
   HALT alone marks the end. TEN RESETS, TEN 0x08s — at 1.024MHz a marginal
   setup path fails probabilistically and one pass is an anecdote. */
void t_block6_acceptance(void) {
    test_begin(m_block6, PSTR("acceptance"));
    hwpin_t p_halt;
    if (!sig_lookup("block6", "CW15=HALT", &p_halt)) {
        test_check_bool(false, true, PSTR("HALT_pin_bound"));
        test_end(); return;
    }
    pins_idle();
    uint8_t good = 0;
    for (uint8_t run = 0; run < 10; run++) {
        uart_putsP("     run "); uart_putc((char)('0' + run));
        uart_putsP("/10 — ARM: press RESET (20s)\r\n");
        if (!await_level(&p_halt, false, 20000)) {
            uart_putsP("     no start (HALT never fell)\r\n");
            continue;
        }
        if (!await_level(&p_halt, true, 2000)) {
            uart_putsP("     never halted\r\n");
            continue;
        }
        uint8_t ob = PINK;
        uart_putsP("     OB = 0x"); uart_puthex8(ob);
        if (ob == PR_EXPECT_SUM) { good++; uart_putsP("  ok\r\n"); }
        else                     { uart_putsP("  WRONG\r\n"); }
    }
    test_check_u16(good, 10, PSTR("ten_resets_ten_sums"));
    uart_putsP("     and the check that costs nothing: ONE LED LIT, BIT 3\r\n");
    test_end();
}
