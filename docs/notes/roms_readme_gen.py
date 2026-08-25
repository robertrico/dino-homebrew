#!/usr/bin/env python3
"""Emit roms/README.md — the inventory of what is physically in the sockets.

WHY THIS IS GENERATED. The hand-maintained version drifted: by 2026-08-23 it
was missing ten of twenty-one images and had never heard of U23, the third
microcode EEPROM. That is the document someone reads AT THE BURNER, so being
wrong there costs a bench session. Every number below is computed from the
same generators that write the images, so the two cannot disagree.

Durable prose lives here as literals, the same way microcode_gen carries the
text of its C header. Per-image history does NOT: "changed on 2026-08-02, was
5+3" is what `git log roms/` is for.

Run:  python3 roms_readme_gen.py
Test: python3 test_roms_readme.py   (regenerates and diffs — fails on drift)
"""
import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import microcode_gen as mc                                    # noqa: E402
import progrom_gen as pr                                      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "roms", "README.md"))

# What each coverage image is FOR. One line each; the full rationale lives in
# progrom_gen.py beside the program itself.
NOTES = {
    "probe": "immediate -> A -> OB, ALU out of the path entirely. The "
             "smallest question worth asking.",
    "adda": "TMP_A alone: value + 0, so the answer IS the operand.",
    "addb": "TMP_B alone: 0 + value, isolating the other shadow latch.",
    "real": "the MILESTONE. Poisons OB, then adds two numbers.",
    "in": "THE INTERACTIVE ONE. B comes off SW1 through the '244, so only "
          "the SOURCE of the operand changed.",
    "alu": "all eight SA codes CHAINED, so a wrong code corrupts the "
           "signature rather than being masked by a later op.",
    "mem": "STA then LDA back through RAM. Uses ONE address twice, so it is "
           "blind to what that address actually was -- see mardisc.",
    "flow": "JMP over a poison HALT, then a JNZ that must NOT be taken.",
    "loop": "the JNZ TAKEN arm, iterated an exact number of times. A wrong "
            "count changes the answer, so the answer proves the count.",
    "mardisc": "TWO DIFFERENT MAR values. Reads back the FIRST of two cells "
               "differing only in MAR_LO, so a collapsed low byte returns "
               "the SECOND value. The question mem cannot ask.",
    "pads": "the PC's LANDING ADDRESS as the observable. Every 4-byte slot "
            "is LDAI <own address>; OUT; HALT.",
    "sp1": "ONE push, ONE pop -- the fewest moving parts that reach the "
           "stack at all. BLIND TO A FROZEN SP by construction: push and pop "
           "use the same cell, so 0x2C comes back whether or not SP ever "
           "moved. It reported a green machine for most of 2026-08-24. Read "
           "it only alongside sp2.",
    "sp2": "the ADDRESS as the observable, not the data. Plants a sentinel "
           "in the cell push #2 must reach, then reads that cell by ABSOLUTE "
           "address so the readback cannot inherit the fault under test. "
           "0x53 = SP moved. 0xA5 = SP never moved and the sentinel "
           "survived. The first image that is not blind to a frozen SP.",
    "sp3": "WHICH cell did the pop read. A different sentinel in each "
           "neighbour: 0x2C correct, 0x11 read one BELOW (increment never "
           "took before the MAR copy), 0x22 read one ABOVE (increment landed "
           "twice). 0x22 is what a ringing CLK edge at U63.2 produced before "
           "the 100R series termination went in.",
    "sp": "SP alone -- LXISP and the counter, without CALL/RET. The phase-B "
          "bench gate.",
    "calladdr": "CALL WITHOUT RET. Reads the pushed return address back out "
                "of RAM by absolute address. 0x5C = both bytes right, 0xC1 = "
                "the LO byte is wrong (U72 / ~PC_LO_OUT), 0xC2 = the HI byte "
                "(U73 / ~PC_HI_OUT). Exercises the CALL-side pins ONLY, so "
                "calladdr passing and call failing puts the fault on the RET "
                "side. NOTE: CALL pushes PC+1, not PC+3 -- RET steps over the "
                "two operand bytes with PC_UP on T12/T13. PHASE C.",
    "callraw": "REPORTS the pushed PC_LO byte raw -- no comparison, no fault "
               "codes. Found phase C's fault when calladdr had misattributed "
               "it: 0x26 was the previous JMP's target, naming U72/U73 as "
               "landed on the PC LOAD path (U11/U12) instead of the Q outputs. "
               "Expect 0x2A. PHASE C.",
    "call": "the RETURN ADDRESS as the observable -- pads, for RET. The "
            "landing site is the ONLY thing that can produce the answer: "
            "0x4B = RET landed on the right byte, 0xFF = it did not (OB is "
            "poisoned first and everything else in the image is HALT). The "
            "0x120 HALTs of padding are LOAD-BEARING: they push the CALL "
            "above 0x00FF so the pushed PC_HI is 0x01, and a U73 that is "
            "dead or stuck low cannot pass by delivering 0x00. PHASE C -- "
            "needs U72/U73.",
    "stack": "LXISP, PUSH, POP, CALL, RET. Pushes two DIFFERENT bytes and "
             "pops them into SWAPPED registers, so LIFO order is observable "
             "rather than decorative -- and the SUB runs INSIDE the callee "
             "with the only OUT after the return, so the answer exists only "
             "if registers, flags and stack all survived the call. PHASE C.",
    "ramexec": "THE MACHINE EXECUTES FROM RAM. No new instruction -- the "
               "new thing is where the instructions come from. ROM plants "
               "LDBI/SUB/OUT/HALT at 0x9000, verifies byte 0 by ABSOLUTE "
               "address (unwritten RAM reads 0x00 = NOP, so a failed store "
               "would NOP-slide 28KB and look like a fetch fault), then "
               "JMPs across 0x8000 and the answer is computed in RAM. "
               "PHASE D.",
}

PROSE_HEAD = """# roms/ — what is physically in the sockets

**GENERATED by `docs/notes/roms_readme_gen.py`. Do not hand-edit.**
Regenerate after any image change; `test_roms_readme.py` fails on drift.

These binaries are TRACKED ON PURPOSE. They were silently untracked in the
old `hardware` repo, swallowed by a bare `*.bin` rule inherited from the MCU
firmware projects. Do not reintroduce that rule — see `.gitignore`.

They are regenerable, but regenerable is not recorded. "What was burned on
2026-07-26" should be a `git show`, not "check out an old commit, re-run the
generator, and hope OPCODES has not moved." Per-image history is deliberately
NOT repeated here — that is what `git log roms/` is for.
"""

PROSE_MICROCODE = """
## Microcode — THREE chips

The control word is 24 bits wide and every image is the 4096-row table split
by byte. A12 is grounded, so each 8KB file is the 4096-byte image mirrored
twice; the CRCs below are over the 4096 ADDRESSABLE bytes.

**Adding or changing an INSTRUCTION means burning all three.** A new opcode
writes rows in every byte of the word. `U9`/`U15` stay untouched only for
changes confined to `CW16-23`.
"""

PROSE_COVERAGE = """
## Progressive ISA-coverage images

The block ladder proves the machine EXECUTES. These prove it executes the
WHOLE of the current ISA. Each ends `OUT; HALT` because OB is the only
datapath observable on the ladder, and every answer is a MIRROR-WITNESS — its
bit-reversed read is a different byte, so a flipped OB ribbon names itself.

Expected OB values are NOT hand-computed. `progrom_gen.simulate()` interprets
the burned microcode rows, so image and hardware cannot disagree by
construction — no eleventh table.
"""

PROSE_SW1 = """
### SW1 is active low, and the DIP label reads backwards from the bus

Netlist: `R17-R24` pull `IS0-7` to +5V and `SW1.9-16` are all GND, so a CLOSED
switch shorts its bit to ground. On a DIP that means **"ON" = 0 and "OFF" =
1** — the silkscreen says ON where the bus reads zero.

To present `0x1E = 0b00011110`: positions 1, 6, 7, 8 ON and 2, 3, 4, 5 OFF.

The position numbering is SILKSCREEN, not copper, so it cannot be
netlist-checked. **Calibrate it:** position 1 ON alone gives `OB 0x2D` if
position 1 is bit 0, or `OB 0xAE` if it is bit 7. Neither reading is
confusable under bit-reversal or nibble-swap.
"""

PROSE_TAIL = """
## Regenerating

    python3 docs/notes/microcode_gen.py     # U9, U15, U23 + diag set
    python3 docs/notes/progrom_gen.py       # PROG, PROG_diag, coverage, cylon
    python3 docs/notes/roms_readme_gen.py   # this file

The tracked generators reproduce these exact files byte-for-byte. If a
regeneration ever changes a byte, the CRCs in
`tests/dino_bringup/src/microcode_expect.h` and `progrom_expect.h` change with
it, and `test_microcode_gen.py`'s pinned CRC literals fail. **A reburn is
always deliberate.** That is the intended failure path.

## Burning

    make -C tests/dino_bringup burn-prog-diag
    make -C tests/dino_bringup burn-prog
    make -C tests/dino_bringup burn-prog-<tag>     # any coverage image

TL866, and Rico does the burning. Tools verify; they never program.

## Deferred hardening

`progrom_gen.py`'s `DIAG_ZERO = 0xA5` is bit-reverse-invariant, which makes
the diag image's byte 0 mirror-blind. Change it to a non-palindrome the next
time the DIAG image is reburned — no reason to reburn just for this.
"""


def microcode_rows():
    real, diag = mc.build_real(), mc.build_diag()
    rows = []
    for tag, words in (("REAL", real), ("DIAG", diag)):
        lo, hi = mc.split(words)
        thd = mc.third(words) if tag == "REAL" else mc.diag_third(words)
        for chip, half, bits in (("U9", lo, "CW0-7"),
                                 ("U15", hi, "CW8-15"),
                                 ("U23", thd, "CW16-23")):
            fn = f"{chip}.bin" if tag == "REAL" else f"{chip}_diag.bin"
            rows.append((fn, bits, tag, mc.crc16(half)))
    return rows


def program_rows():
    rows = [("PROG.bin", "the milestone program", pr.crc16(pr.build_real())),
            ("PROG_diag.bin", "address self-proof, content-addressed",
             pr.crc16(pr.build_diag()))]
    return rows


def coverage_rows():
    rows = []
    for tag, prog in pr.COVERAGE.items():
        if tag == "real":
            continue                      # emitted above as PROG.bin
        img = pr.build_image(prog)
        sw = pr.COVERAGE_SW.get(tag)
        r = pr.simulate(prog, switches=sw or 0x00)
        rows.append((tag, pr.crc16(img), r["out"], r["ends"], sw))
    return rows


def build():
    L = [PROSE_HEAD.rstrip(), PROSE_MICROCODE.rstrip(), ""]
    L.append("    IMAGE            BITS      SET    CRC16")
    for fn, bits, tag, crc in microcode_rows():
        L.append(f"    {fn:<16} {bits:<9} {tag:<6} 0x{crc:04X}")

    L += ["", "## Program ROM (AT28C256, 32KB, ROM 0x0000-0x7FFF)", "",
          "    IMAGE            CRC16   WHAT IT IS"]
    for fn, what, crc in program_rows():
        L.append(f"    {fn:<16} 0x{crc:04X}  {what}")
    L.append("")
    L.append(f"    milestone: LDAI 0x{pr.POISON:02X}; OUT;"
             f" LDAI 0x{pr.ADDEND_A:02X}; LDBI 0x{pr.ADDEND_B:02X};"
             f" ADD; OUT; HALT  -> OB = 0x{pr.EXPECT_SUM:02X}")
    L.append("    The leading LDAI/OUT POISONS OB: U35 has no reset and the")
    L.append("    machine free-runs at power-up, so OB always already holds")
    L.append("    the previous answer. Safe-filled with HALT (0x%02X)."
             % pr.SAFE_FILL)

    L += [PROSE_COVERAGE,
          "    IMAGE            CRC16   OB    ENDS"]
    for tag, crc, ob, ends, sw in coverage_rows():
        swtxt = f"   SW1 = 0x{sw:02X}" if sw is not None else ""
        L.append(f"    PROG_{tag+'.bin':<11} 0x{crc:04X}  0x{ob:02X}  "
                 f"{ends}{swtxt}")
        for line in textwrap.wrap(NOTES.get(tag, ""), 66):
            L.append(f"        {line}")

    cyl = pr.build_image(pr.CYLON_PROGRAM)
    spc = pr.build_image(pr.SPCYLON_PROGRAM)
    swd = pr.build_image(pr.SWDEMO_PROGRAM)
    win = pr.build_window()
    L += ["", "### Soak images — not coverage images", "",
          f"    PROG_cylon.bin   0x{pr.crc16(cyl):04X}  "
          f"{len(pr.assemble(pr.CYLON_PROGRAM))} bytes, NEVER HALTS",
          f"    {len(pr.CYLON_FRAMES)} frames, ~"
          f"{pr.CYLON_OUTER_N * 4.006:.0f}ms each. Deliberately NOT in",
          "    PR_COVERAGE: no (OB, END) fingerprint to match, because it",
          "    never halts. Exercises LDAI/LDA/STA/SUB/JNZ both arms/OUT/JMP",
          "    and two RAM cells continuously — the best transport check the",
          "    machine has, and it needs no rig, no reset and no ROM swap.",
          "",
          f"    PROG_spcylon.bin 0x{pr.crc16(spc):04X}  "
          f"{len(pr.assemble(pr.SPCYLON_PROGRAM))} bytes, NEVER HALTS",
          "    The same sweep, but the frame table IS the stack: the",
          "    outbound half PUSHes each frame as it shows it and the",
          "    return half POPs them back, so LIFO order is the visible",
          "    sweep direction. Ahead of it, every sweep, three boundary",
          "    probes cross one ripple-carry link each:",
          ""] + [
          f"        LXISP 0x{base:04X}  ->  frozen OB 0x{fault:02X}  "
          f"= {name} is dead"
          for (base, fault), name in zip(
              pr.SPCY_PROBES,
              ("U63.15 -> U64.10", "U64.15 -> U65.10", "U65.15 -> U66.10"))
          ] + [
          "",
          "    Dot sweeping = healthy. Dot frozen on 0xE1/0xE2/0xE3 = that",
          "    carry link. Dot scrambled or walking backwards = pop order",
          "    or a stuck direction pin. PHASE B hardware only (U63-U69);",
          "    no CALL/RET, so it does not wait on U72/U73.",
          "",
          f"    PROG_swdemo.bin  0x{pr.crc16(swd):04X}  "
          f"{len(pr.assemble(pr.SWDEMO_PROGRAM))} bytes, NEVER HALTS",
          "    THE FIRST IMAGE THAT ANSWERS TO YOU WHILE IT RUNS. SW1 bit 0",
          "    is read every pass, INSIDE the loop, so flipping the switch",
          "    changes the display at the end of the current pass -- no",
          "    reset, no reburn. Both arms are stack-driven and both balance",
          "    their pushes and pops, so SP returns to where LXISP put it",
          "    every time round.",
          "",
          "        switch 0 OPEN    bit reads 1  ->  cylon sweep",
          f"        switch 0 CLOSED  bit reads 0  ->  0x{pr.SWDEMO_BLINK_B:02X}"
          f" / 0x{pr.SWDEMO_BLINK_A:02X} interleaved blink",
          "",
          "    SW1 IS ACTIVE LOW -- R17-R24 pull IS0-7 up and the switch",
          "    pulls DOWN, so a CLOSED switch reads 0. Bits 1-7 are masked",
          f"    off (LDAI 0x{pr.SWDEMO_MASK:02X}; IN; AND), so the other seven",
          "    switches stay free.",
          "",
          f"    Blink shows 0x{pr.SWDEMO_BLINK_B:02X} FIRST even though"
          f" 0x{pr.SWDEMO_BLINK_A:02X} is pushed first --",
          "    that is LIFO, visible with two frames. Reversed order names a",
          "    stack returning pushes in the order they went in.",
          "", "### The phase E witness \u2014 not a soak image, and not coverage", "",
          f"    PROG_window.bin  0x{pr.crc16(win):04X}  "
          f"BEFORE 0x{pr.WINDOW_SENTINEL:02X} / AFTER 0x{pr.WINDOW_POISON:02X}",
          "        THE PHASE E WITNESS. One burn, read TWICE, with",
          "        ~{ROM_SEL} landed on U24.20 between the readings.",
          "        Not in PR_COVERAGE: two correct answers, so there is no",
          "        single (OB, END) fingerprint for the ladder to match.",
          "        The BEFORE reading cannot be retaken once the window",
          "        exists -- take it first.",
          PROSE_SW1.rstrip(), PROSE_TAIL.rstrip()]
    return "\n".join(L).rstrip() + "\n"


def main():
    text = build()
    with open(OUT, "w") as f:
        f.write(text)
    print(f"wrote {OUT}  ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
