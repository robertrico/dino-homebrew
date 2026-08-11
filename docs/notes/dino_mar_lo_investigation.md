# The MAR fault — post-mortem, 2026-08-03/04

**RESOLVED.** Two board-to-board runs, nine wires, were never landed. Nothing
was broken; two things were absent. Written down because the *shape* of the
fault is a hole in the bring-up ladder, not a one-off.

## Root cause

    ~PC_LOAD  ->  U11.19 / U12.19     never wired
    W[0..7]   ->  U55 / U58 D pins    never wired

`U11`/`U12` are the '245s that pass `M -> PCD -> the '193 parallel-load
inputs`. Their `/OE` is `~PC_LOAD`, from `U62.10`. Unwired, it floats HIGH, so
those '245s were **permanently disabled** while `~PC_LOAD_STABLE` from `U36.8`
reached all four '193s perfectly. **The PC was told to load, and loaded a
floating bus.**

`U55`/`U58` are the MAR latches. Their D inputs are `W0-7`, arriving
board-to-board from the mdr board. Unwired, all eight float — and a floating
LS input reads HIGH — so both latches captured `0xFF` on every load, faithfully
and forever.

    MAR = 0xFFFF -> M = 0xFFFF -> M15 = 1, RAM selected
    JMP T3: PC <- 0xFFFF -> fetch reads RAM[0xFFFF] -> 2-state instruction
            -> PC wraps 0xFFFF -> 0x0000 -> JMP again.  4 + 2 = 6 T-states.

## Why every test in the suite passed anyway

**`PROG_mem` is structurally incapable of failing on this.** `RAM_SCRATCH` is
`0x8000` — bit 15 alone, every other MAR bit zero — and it uses the **same
address for the store and the load**. With MAR stuck at `0xFFFF`, `M15` is
still 1, RAM is still selected, both accesses land on `0xFFFF`, and `0xC5`
round-trips exactly as designed. Mirror-witness, one layer deeper than the rule
was written for.

**The module tests drive those nets from the rig's own pins.** `mar.logic`
does `bus_w_write()` from PORTA and `mar_set()` onto the load strobes;
`pc.load` does `bus_m_drive()`. The rig *is* the source, so the board-to-board
run is never needed and cannot fail.

**The block ladder classifies both as COPPER** — out of one member, into
another, dropped from the rig, wired board-to-board, never sampled.

> A COPPER wire is driven by no test and sampled by no test. **The wire
> between two proven modules is checked by nothing.**

That is the hole. It cost a day.

## MEASURED GOOD before the cause was found — the whole capture path

Every one of these was correct the entire time, which is why the hunt took so
long: there was no faulty element to find.

    CLK (U27.5)                   500ns / 1us / 50.00% exact
    T-state decode (U17.2/4/6/8)  clean 4-state + 2-state, 6T loop
    ~MAR_LO_LOAD (U30.11)         asserts in T1, one full T-state
    LE_MAR_LO (U55.11)            500ns, the CLK-LOW half of T1, falling on
                                  the T1/T2 boundary — correct BY DESIGN
    MAR3/MAR4                     track their D inputs, then hold
    PC_MAR_MUX (U54.19)           HIGH at _MARFILL T1, LOW at T3 and at the
                                  2-state T1 — all correct per microcode
    ~PC_MAR_MUX (U60.13)          correct inverse; U13/U14 released at T3
    U54/U59 DIR                   4.66V
    U55/U58 ~OE                   0V
    VCC / GND                     correct on every chip
    microcode + ISA               verified against the burned image

## Hypotheses eliminated, in order, each by a measurement

 1. Wrong or failed burn / reseat fault — reburned, reseated, reproducible
 2. `~MAR_LO_LOAD` copper open — beeped good
 3. CLK jumper `U60.3`<->`U60.6` open — beeped good, including to the source
 4. `U60` is not a '02 — it is, and gate 3 is `~RAM_EN = NOT(M15)`; a wrong
    part there and the memory map never decodes at all
 5. CLK not gating the NOR — `LE_MAR_LO` measures 500ns inside a CLK-low half
 6. `U55` dead / outputs held down by a `U54` DIR fight — outputs track inputs
 7. Setup/hold violation at LE's falling edge — the closing edge IS the
    T-state boundary by design, and the program ROM's tACC guarantees hold
 8. Non-determinism / a race — loop period is a stable 5.85-5.90us = 6T
 9. `PC_MAR_MUX` wrong at `_MARFILL` T1 — measured HIGH, correct
10. `W` wrong at T1 — `LDAI`'s operand fetch is the SAME microcode row shape
    (`mux_pc=1, pc_up=1, src=ROM`), differing only in DST, and the milestone
    and ALU images pass
11. `CW6` stuck, turning `JNZ` into an unconditional `JMP` — beeped good, and
    `flow` proved the branch correct once W was wired

**Process note, recorded deliberately.** The assistant repeatedly proposed chip
swaps for parts the module tests had already proven, on a machine where nothing
had ever released magic smoke. Rico rejected that line four times — on `U60`
("if it weren't an '02 we'd never have got this far"), on the general principle
("a dead chip would have failed the module tests"), on `W` ("why chase W if
other programs work"), and on `U55` — and was right every time. **The fault was
found by eye, against the schematic.** That is the instrument neither the rig
nor the LA has, and it should be first, not last, when every element measures
good.

## The diagnostic images this produced

    PROG_mardisc.bin  crc=0x2066  OB 0x6B  8 ENDs
        LDAI 0xFF; OUT; LDAI 0x6B; STA 0x8004; LDAI 0x2D; STA 0x8010;
        LDA 0x8004; OUT; HALT
        Two DIFFERENT addresses, read the first back. The question PROG_mem
        structurally cannot ask. No jumps, so it answers regardless of the
        PC_LOAD state.  MEASURED: 0x2D before the fix, 0x6B after.

    PROG_pads.bin     crc=0x749A  OB 0x40  5 ENDs
        Landing-pad grid: every 4-byte slot from 0x0008 is
        `LDAI <own address>; OUT; HALT`, so OB REPORTS where PC_LOAD actually
        went. `JMP 0x0040`; two HALTs at 0x0006/0x0007 trap a JMP that never
        loads.  MEASURED: 0x40.

Both stay in the coverage set permanently. `mardisc` belongs **before**
`PROG_loop` in the standard run — it is the only image that asks MAR to
discriminate.

**Caveat both share: they are permutation-blind.** A consistent bit swap on `W`
is self-cancelling through a store-then-load, so `mardisc` returning `0x6B`
proves MAR *discriminates*, not that the bits are in *order*. Bit order is
proven instead by the absolute-address images: `flow` returning `0x39` requires
`JMP` to land exactly on `0x0004`, and `pads` returning `0x40` requires exactly
`0x0040`.

## Result — the whole ISA has now executed

    mardisc  0x6B    MAR discriminates two distinct addresses
    pads     0x40    PC_LOAD lands exactly on target
    mem      0xC5    MAR as a latch, RAM round trip
    flow     0x39    JMP lands; SUB sets FLAG_Z; JNZ correctly declines
    alu      0x39    all eight SA codes, chained non-maskingly
    loop     0x15    JNZ TAKEN arm x3, two live RAM cells, flags held across
                     STA, exact iteration count (3 x 7 = 21)
    PROG     0x4D    the milestone, unchanged
    cylon    ---     never halts; the soak image

`LDA`, `STA`, `JMP`, `JNZ` and seven of the eight ALU codes were burned and
policed but had **never executed** before 2026-08-04. Only `LDCI` and `NOP`
remain unrun, both unreachable by design — C is write-only until `MOV` exists.

## THE FIX FOR THE PROCESS — copper continuity, generated

`kicad_contracts.py` already emits the exact per-sheet IN/OUT/BIDIR signal list
crossing every sheet boundary. **That list IS a continuity checklist**, and
nothing currently makes anyone walk it.

Proposal: a generated `copper <module>` checklist — every net that leaves the
module's sheet, with its source pin and every destination pin, to be beeped
**before power goes on** when a module joins the ladder. Both faults here would
have been caught in the two minutes before Block 2 was first powered.

Second, smaller: **same-chip jumpers are invisible the same way.** `CLK` at
`U60.3<->U60.6` and `HALT` at `U61.5<->U61.6` are bare pin-to-pin jumpers that
no test drives or samples. `layout_gen.py` knows which wires these are; they
deserve their own line in the same checklist.

## STILL OPEN — two items, neither blocking

**1. HALT does not HOLD.** The machine halts correctly, then escapes after a
few seconds, varying run to run. `CET` on the '163 (`U6.10 = ~HALT` from `U61`
gate 2) is sampled on every clock edge — a million decisions per second — so
one escape in a few million clocks is more likely a level problem than a
logic fault. That is an inference, not a measurement.

Invisible on every other image: their bytes after `HALT` are all `0xFF` fill,
so an escape just re-halts. **`PROG_flow` is the first image in this machine's
life with live, reachable code past a `HALT`** (the `bad:` block), which turns
`0x39` into `0xE7` seconds later. Scope `U61.5/6` (`HALT`) and `U61.4` =
`U6.10` (`~HALT`), and beep the `U61.5<->U61.6` jumper.

**2. Level readings — TAKEN ON THE BROKEN MACHINE, NEVER RE-TAKEN.**

Measured during the hunt:

    W            2.26V
    PC_MAR_MUX   1.0V avg
    MAR3         3.22V     against a healthy LS VOH of 3.4-3.5V

**Re-assessed 2026-08-11, and the conditions matter more than the numbers.**
These were taken while the fault above was still present — that is, while
`W[0..7] -> U55/U58 D pins` was **unwired**. Eight floating inputs, on the
exact bus that read 2.26V. This same document states two paragraphs up that a
floating LS input reads HIGH; `MAR3` is a MAR output, and MAR was latching
`0xFF` from those same floating inputs.

So the most likely reading of this table is that it measured the FAULT, not a
standing property of the machine. It cannot be settled either way from what
was recorded: there is no note of whether the probe was on the driver or the
receiver end, no note of what the machine was executing, and no measurement
after the wires were landed.

**These numbers were being carried in CLAUDE.md as standing fact and used to
justify design decisions** (they were cited as a reason to keep new loads off
`W`). Removed from there 2026-08-11. The design decision they were cited for
stands on other grounds; the numbers do not stand on their own.

What would settle it: scope `VOL`/`VOH` on `W` at `U55.8`, and the other two
nets, on the CURRENT machine, running, with the rig detached — and write down
the conditions. Note that any reading taken with the rig attached is suspect
regardless, because rig lines feed the DUT through clamp diodes (the phantom-
power finding). No such characterisation has ever been done on a healthy
board.

Item 1 above may still be a level problem. That is an inference from "CET is
sampled every clock, so a rare escape is unlikely to be logic" — not a
measurement, and not evidence for this table.
