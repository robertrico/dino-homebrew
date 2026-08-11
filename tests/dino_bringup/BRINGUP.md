# DINO bring-up bible

The sit-down-and-read companion for bench sessions. One section per stage:
what to wire, where, what to type, what you should see, and what a failure
means. Deeper rationale lives in `../../docs/notes/dino_test_bringup_design.md`
(the spec); this document is the bench procedure.

## STATUS 2026-08-10 — THE RIG IS DETACHED. READ THIS FIRST.

**The Mega is unwired.** No stage in this document can be run as written.
Everything below describes the rig-driven procedure and is preserved as the
record of how the ten modules and five blocks were proven — it is history, not
a runnable procedure, until instrumentation returns.

**The workflow changed.** Schematics are always first now: draw everything,
verify on the FPGA, find logic errors, refine, and only then hardware.

**What replaces the rig, for the schematic phase committed as `9dc7217`:**

    TL866 read-back      proves the CHIP        (against MC_CRC_U23_REAL)
    continuity, DEAD     proves the WIRES       (beep, board unpowered)
    coverage ROMs        proves the MACHINE     (8 known OB values, on LEDs)
    cocotb / FPGA        proves the LOGIC       (exhaustive, off-bench)

**Test the wire, not the part.** A '138's decode *and enable* behaviour is
already covered exhaustively in sim (`dino_fpga_vplan.md` BUS-03,
`fpga/ttl/test_msi.py::decoder_truth_table`). Re-asking it on the bench is
re-proving a datasheet. Bench effort belongs on wires nothing else checks —
which is exactly where the MAR-lo run went missing.

**Twelve new chips are in the schematic and none of them has run.** `U23`
(third microcode EEPROM), `U70`/`U71` (SRC/DST bank-1 '138s), `U63`-`U66`
(the '169 stack pointer), `U67`/`U68` (SP readback '245s), `U69` ('08),
`U72`/`U73` (PC->MDR '245s). `microcode_gen` still emits a 16-bit word, so no
row asserts any new bit.

**Two new bench-critical traps, both invisible to a round-trip test:**

1. **'169 pin 1 is `U/~D`, not `~MR`.** Both '163s on this board (`U6`, `U20`)
   wire pin 1 as a clear, one of them strapped to `+5V`. Doing that on a '169
   hardwires SP to count up only — `~{SP_DOWN}` asserts and does nothing.
   PUSH never decrements; a single PUSH/POP pair still works because the byte
   goes to a slot and comes back from the same slot. Nested calls corrupt.
2. **`P` and `Q` number in opposite directions** (`P0-P3` = 3,4,5,6 ascending;
   `Q0-Q3` = 14,13,12,11 descending). On a DIP16 those pins sit directly
   opposite each other, so wiring by *position* is safe and wiring by *pin
   number sequence* gives a whole-nibble reversal.

   Both need a **mirror-witness** to catch: push two DIFFERENT values and pop
   them in the order LIFO demands. A round trip is self-consistent under either.

**Also: `avr-gcc` is broken in this environment** — missing
`/opt/homebrew/opt/isl/lib/libisl.23.dylib`. `brew reinstall isl` before the
rig ever comes back.

---

## STACK + THIRD EEPROM BRING-UP — DRAFT, needs refining at the bench

**Status: schematic and simulation only.** Twelve chips, seven instructions,
zero seconds on real silicon. `make -C fpga verify` is green (147/147 host,
20/20 fuzz, 40/40 cocotb) and every image synthesizes and closes timing, but
that is a statement about a netlist and a simulator.

This section is a SKELETON, deliberately. It carries the facts that are
already derivable and marks the rest as open, so it can be refined with the
board in front of you rather than guessed at now.

### Order

    1  COPPER        land and beep every new wire      <- start here
    2  BURN          three ROMs, not one
    3  LA            watch the stack instructions execute
    4  SHOWCASE      an LED program that makes it visible   <- to design

### 1. Copper — generated, walk it with the board OFF

The list comes from the netlist, never a reading. That is the whole lesson of
the MAR-lo fault: two runs, nine wires, never landed, and nothing caught them
because a copper wire is driven by no test and sampled by no test. The fix is
a meter and a list that cannot be incomplete.

    python3 docs/notes/kicad_contracts.py --continuity \
        U23 U63 U64 U65 U66 U67 U68 U69 U70 U71 U72 U73

**73 nets, 154 pins**, plus a NO-CONNECT footer of 6 (`CW16`, `CW19-23` — U23
outputs with no consumer; correct, not missing wires). Each line names the NEW
pins to land and the existing pins to beep them against. Beep each new pin
against its own NEIGHBOURS too — a one-hole slip on an adjacent gate pin is
this board's most common fault.

That was 39/94 until 2026-08-11. The extra 34 nets are not new work; they are
work the tool could not see — nets whose label set differed between sheets
(`M15/ROM_EN`, `CW17`, `CW18`) and sheet-internal nets like `~{TC1}`,
`~{SP_CE}` and `SP0-15`. Both blind spots are closed and regression-tested.

Then run the change list, which the continuity walk cannot show — it filters
to nets touching the NEW chips, so a pin on an EXISTING chip that moved
underneath you never appears:

    python3 docs/notes/kicad_contracts.py --since 2fe4d7c^

    COPPER     U28.6  +5V -> CW17/~{SRC_BANK}    lift the strap
               U30.6  +5V -> CW18/~{DST_BANK}    lift the strap
    NEW_WIRE   U29.7  -> ~{SP_DOWN}    U29.10 -> ~{SP_UP}

`U28.6` and `U30.6` are decoder ENABLES on a working board — the worst class
under the block law, and the whole reason that flag exists.

Two traps specific to these parts, both invisible to a round-trip test:

- **'169 pin 1 is `U/~D`, not `~MR`.** Both '163s on this board (`U6`, `U20`)
  wire pin 1 as a clear, and `U20`'s is strapped to `+5V`. Doing that here
  hardwires SP to count up only: `~{SP_DOWN}` asserts and nothing happens.
  PUSH never decrements, so a single PUSH/POP pair still works perfectly and
  nested calls corrupt.
- **`P` and `Q` number in opposite directions** (`P0-P3` = 3,4,5,6 ascending;
  `Q0-Q3` = 14,13,12,11 descending). On a DIP16 those pins sit directly
  opposite each other, so wiring by POSITION is safe and wiring by
  pin-number sequence gives a whole-nibble reversal.

### 2. Burn — three ROMs

Adding instructions writes rows in every byte of the 24-bit word, so `U9` and
`U15` are no longer "never leave their sockets" for this change.

    python3 docs/notes/microcode_gen.py     # prints all six CRCs
    python3 docs/notes/progrom_gen.py       # PROG_stack.bin among others

Verify each with the TL866's own read-back after burning. CRCs are pinned as
literals in `test_microcode_gen.py`, so if the generator ever prints
something different, that is a deliberate change or a bug — not drift.

`U23_diag.bin` exists but there is currently nothing that can walk 4096 rows
in-circuit (that was the rig). Burn the real image; the diag pair is there
for when instrumentation returns.

### 3. LA — what to watch, and what it should show

The T-state traces below are generated from the microcode, not transcribed:

    LXISP   T1 ROM->SP_LO   T2 ROM->SP_HI, END
    PUSHA   T1 SP_LO->MAR_LO  T2 SP_HI->MAR_HI  T3 A->RAM  T4 SP_DOWN, END
    POPA    T1 SP_UP  T2 SP_LO->MAR_LO  T3 SP_HI->MAR_HI  T4 RAM->A, END
    CALL    T1-T4  push PC_HI   T5-T8  push PC_LO
            T9/T10 ROM->MAR_LO/HI (PC++ on both)   T11 PC_LOAD, END
    RET     T1 SP_UP  T2/T3 SP->MAR  T4 RAM->C
            T5 SP_UP  T6/T7 SP->MAR  T8 RAM (parks in MDR)
            T9 MDR_OUT->MAR_HI   T10 C->MAR_LO
            T11 PC_LOAD   T12/T13 PC_UP x2, END

Regenerate any time:

    python3 -c "import sys;sys.path.insert(0,'docs/notes');import microcode_gen as g;\
    print(g.INSTRUCTIONS['RET'])"

**Two rows are worth a channel each.** Not because they are suspect — the
committed microcode passes on the gate model, `PROG_stack` lands `OB=0x27` —
but because they are where a COPPER fault would be most legible:

- **`RET` T8/T9 is the tightest sequential dependency in the ISA.** T8 parks
  the return address's HI byte in MDR; T9 replays it into `MAR_HI`. MDR holds
  for exactly ONE state: `LE_MDR = NAND(~{RAM_LOAD}, READS_IDLE)` falls at
  the T-state boundary and can latch whatever the next source turns on. One
  state of slack, so MDR-side wiring trouble surfaces here first.
- **`CALL` T3/T7 is the only place `PC0-15` is used.** Sixteen new wires,
  exercised by exactly these two rows. They push `PC_HI` then `PC_LO`, in
  that order, read from `PC0-15` and NOT from `M` — the address bus is
  carrying MAR (the stack slot) during both.

For the record, since the traces above may look fussy: both constraints exist
because EARLIER DRAFTS of this microcode violated them and the gate model
refused. Draft 1 of `RET` used `src=RAM, dst=MAR_HI` in one word, closing a
live loop `MAR -> M -> RAM -> MDR -> U25 -> W -> MAR`, and hung with the PC
at `0x8D00`. Draft 2 parked in MDR but moved another byte before replaying,
and loaded the PC with `0x0C0C` instead of `0x000C`. Both are now
`check_word`/`check_table` rules; neither can be re-encoded.

**OPEN — which 16 channels.** Not decided. Candidates: `T0-3` + `CLK` as the
frame (5), leaving 11 for some mix of `~{SP_LO_OUT}`, `~{SP_HI_OUT}`,
`~{SP_LO_LOAD}`, `~{SP_HI_LOAD}`, `~{SP_UP}`, `~{SP_DOWN}`, `~{PC_LO_OUT}`,
`~{PC_HI_OUT}`, `~{RAM_LOAD}`, `~{MDR_OUT}` and `HALT`. Decide at the bench
against what actually needs discriminating.

**OPEN — STEP-CLOCK has no driver.** It was the rig's, injected at `CLKIN`
(`U20.2`) with Y1 disabled. A debounced button ('14 + RC) restores it. With
the clock stopped a DMM and one probe see everything, one net at a time,
which is most of what a wide bus watcher would buy.

### 4. Showcase program — TO DESIGN

`PROG_stack` exists and is the correctness witness: two different bytes
pushed, popped back into swapped registers, subtracted inside a subroutine,
one `OUT` after the `RET`. `OB = 0x27` if everything worked; `0xD9` means the
pops came back in the wrong order; no `OUT` at all means `CALL`/`RET` never
returned.

That proves it. It does not SHOW it — one number at the end.

**Open: a demonstration image.** Something that makes the stack legible on
eight LEDs while it runs — nested calls at visible depth, or a pattern that
could only be produced by correct LIFO. `PROG_cylon` is the precedent for
"an image whose job is to be watched." Design it at the bench, against what
is actually readable at 1.024MHz.

### What is NOT verified by any of this

The FPGA cannot see analog levels, real propagation on breadboard wire,
fan-out, or whether a wire was landed. Those are bench questions.

Note also that this machine's recorded bus levels were all taken during a
debugging session on a board with a known fault — see
`docs/notes/dino_mar_lo_investigation.md`. A healthy-bus characterisation has
never been done and is its own initiative.

---

STATUS 2026-08-02: all ten module stages AND all five integration
blocks are DONE, and the ISA has its first interactive instruction (`IN`,
opcode 0x52). Timing is retired — blocks 4 and 5 free-run at 1.024MHz with
Y1 seated. The original module status follows (bench-proven by
2026-07-26); stage 1 is closed as a diagnostic, not a gate. Live work is
the integration BLOCK model at the end of this file. The per-stage
"Approve the stage" footers below still name the retired INT-A..INT-E
ladder — those stages are complete, the footers are history, and the
name mapping to blocks is in the integration section.

HOOKUP TABLES ARE SNAPSHOTS of the generated pinmap (2026-07-15). After ANY
schematic change: regenerate (`python3 ../../docs/notes/kicad_contracts.py
--pinmap`), rebuild/reflash, and trust the rig's own `pins <mod>` /
`selftest <mod>` printouts over this file. The firmware resolves pins at
runtime from the same tables, so IT can't drift — paper can.

## Bench ground rules (non-negotiable, learned the hard way)

1. Bench 5V powers the CPU boards. Mega on USB. Grounds commoned at ONE point.
2. Bulk cap per breadboard rail AND across every board boundary the
   supply/return loop crosses (hot+gnd routed as a pair onto each board).
   Skipping the cross-board cap cost a full day — see the 2026-07-14 bench
   ledger in dino_session_state.md.
3. 220-470R series resistor in every rig-DRIVEN jumper (the `O` rows below).
   Sampled lines (`I` rows) connect direct.
4. Y1 stays OUT of its socket until the free-run stage. The rig is the clock.
5. Every jumper bundle's first wire is GND.
6. Selftest jumpers and DUT wiring are mutually exclusive. Never `run
   selftest`/`selftest <mod>` with a DUT attached.
7. Before calling a signal stuck, say out loud what it should REST at.
   (RESET rests LOW. Ask me how we know.)

## Machine invariant: EVERYTHING COMMITS ON CLK LOW

Written out in English so nobody re-derives it. Netlist-verified
2026-07-28; to re-check, do not reason about it — run the tool:

    python3 -c "import sys;sys.path.insert(0,'docs/notes');\
    from kicad_netlist import build_report;\
    print(*build_report('dino_v0_0_2/program_counter.kicad_sch')[0],sep='\n')"

### The fact

The T-state counter (U6 '163) is clocked by CLK, so T changes on the CLK
RISING edge. The microcode ROM address changes with it, and for one ROM
access time the ROM outputs are GARBAGE — which the three control_word
'138s (U28/U29/U30) will happily decode into transient enable pulses.

That garbage cannot hurt anything, because EVERY PATH THAT CHANGES STATE
IS QUALIFIED BY THE CLOCK, and all of them commit while CLK is LOW —
which is the phase AFTER the ROM has settled.

    WHAT CHANGES STATE          HOW IT IS QUALIFIED           WHERE
    -------------------------   ---------------------------   ------------
    register / IR / MAR / ALU   LE = NOR(~{LOAD}, CLK)        U57, U22, U50
      shadow loads
    RAM write pulse             NAND(WRITE_DIR, ~{CLK})       memory
                                (this replaced the '121)
    PC load                     NAND(PC_LOAD, ~{CLK})         U36 gate3
                                = ~{PC_LOAD_STABLE}
    PC clear                    NOR(~{PC_CLEAR}, CLK)         U10 gate1
    PC count                    NAND(PC_UP, ~{CLK})           U36 gate1
                                = PC_UP_STABLE
    T-state clear / hold        '163 SYNCHRONOUS clear+CET    U6
                                (~{MR} = NOR(RESET, END),
                                 CET = ~{HALT}, both U61)

    NOT gated, and correctly so:
      RESET -> '193 CLR      reset must be immediate and asynchronous
      bus output enables     U28's ~{ROM_OUT} / ~{RAM_OUT} / ~{REG_x_OUT} /
                             ~{ALU_OUT} / ~{SW_OUT}, and ~{MDR_OUT}

### Why the ungated ones do not matter

An output enable does not change state — it puts data on a bus. During
CLK high no latch is open, no counter input can be reached, and no RAM
write can fire. A transient double-enable is two drivers briefly fighting:
a CURRENT SPIKE AND SUPPLY NOISE, never wrong data.

CONSEQUENCE, and this is the part worth remembering: a decode glitch on
this machine is a SUPPLY question, not a CORRECTNESS question. When the
integration blocks put the LA on two source enables, you are measuring for
noise, not for corruption. Do not "fix" it by gating the '138s unless the
supply actually misbehaves — the machine's designer already solved this in
five places, and the sixth is a place where the consequence does not land.

### Corollary for reading failures

If a value is wrong, the cause is NOT a decode glitch. Look at the CLK-low
window instead: was the data valid before the latch closed, was the enable
asserted at all, is the stamp gate wired to the right leg.

## The flash/monitor cycle

    cd tests/dino_bringup   # from the repo root
    source env.sh          # picks up /dev/tty.usbmodem*
    build                  # avr-gcc, -Werror
    flash                  # exits with "Resource busy"? screen still owns
                           #   the port: screen -ls; screen -X -S <id> quit
    monitor                # 115200; exit with ctrl-a k, y
                           # (opening monitor resets the board — normal)

Shell commands: `list`, `run all`, `run <mod>`, `run <mod>.<test>`,
`pins <mod>`, `selftest <mod>`, `help`.

Output: `PASS <mod>.<test>` / `FAIL <mod>.<test> <label> want=0x.. got=0x..`
then `SUMMARY: n pass, m fail`. Tests continue after FAIL — read every line;
one wiring fault often explains a whole block of them.

---

## Stage 1 — rig self-test — NOT A GATE. Diagnostic only.

CLOSED 2026-07-28. This was never run on the bench and it isn't owed.
The module tests validate the rig more completely than a loopback jumper
does: selftest proves pin->jumper->pin, while a module test proves
pin->ribbon->strip->chip and back. All ten modules green already means
every pin in those bundles drives, reads, and maps to the net the pinmap
claims — a dead pin or a wrong pinmap entry cannot survive a module going
green.

"What tests the tester" terminates at independent agreement, not at
self-inspection: host-tested expect models (no AVR, no rig), assertions
derived from the netlist, a generated pinmap, and ten modules agreeing
with all three after first going RED on real faults.

WHEN TO ACTUALLY RUN IT: a freshly wired board comes up all-red and you
want to rule out the rig side before beeping chips. One command, ~6
jumpers, answers "rig or DUT". That is its whole job. Note you have been
resolving that question with probes and FAIL-pattern fingerprinting
instead, which also works — this is the fallback, not the routine.

## Stage 1a — per-module flavor (the one worth running)

No DUT. Jumper ONLY the pins the next module uses. `selftest root` prints
its own pair list; for reference, today's root pairing (6 jumpers, plain
wire, no resistors):

    D45 <-> D42        (END / HALT pins)
    D38 <-> D39        (CLK / RESET pins)
    D40 <-> D41        (T0 / T1 pins)
    D50 <-> D51        (T2 / T3 pins)
    D52 <-> D53        (~CLK / ~RESET pins)
    D18 <-> D19        (CLKIN / RST_FORCE, rig-side extras)

Run: `selftest root` → expect `PASS selftest.root`, `SUMMARY: 1 pass, 0 fail`.

FAIL on one pair = that jumper or one of its two header pins. FAIL on
everything = no jumpers installed (floating pins read stale values — you'll
see `got` trailing one pattern behind `want`).

THEN PULL ALL SIX JUMPERS.

## Stage 1b — full rig self-test (rarely worth it)

`run selftest` — all-pin version: PA<->PF bytewise (D22->A0 ... D29->A7),
PC<->PL bytewise (D30->D42 ... D37->D49), plus 11 pool pairs it prints.
27 jumpers. Worth doing once per rig, not per session.

---

## Stage 2 — root boards (clock divider + T-state + reset + END/HALT gates)

PASSED ON BENCH 2026-07-15 (5/5). This stage runs LIVE — the exception to
the rig-is-the-clock rule.

Physical prep on the DUT side:
- Y1 IN its socket — the DUT free-runs at 4.096MHz/4 = ~1.024MHz CLK.
- Reset board + T-phase board powered per ground rules above.
- Nothing else attached downstream (PC/ALU/etc. boards disconnected).
- You operate the physical reset button when a test prints `ARM ...`
  (10s window). RESET stays asserted for the RC stretch after release
  (0.25-2.2s measured, bench-dependent); tests wait on the line.

Wiring (GND first; `O` = rig drives, series R required; `I` = rig samples,
direct). `pins root` prints the live version of this table — 10 contract
jumpers + GND, nothing else (no CLKIN injection, no RC force wire).

    Mega pin   dir  DINO net      where on the boards
    GND        —    GND rail      first wire, always
    D45        O    END           the END tap net (feeds U61 pin 3)
    D42        O    HALT          the HALT tap net (feeds U61 pins 5/6)
    D38        I    CLK           U27A output side (CLK distribution net)
    D39        I    RESET         U27B pin 9 net
    D40        I    T0            U6 Q0 net
    D41        I    T1            U6 Q1 net
    D50        I    T2            U6 Q2 net
    D51        I    T3            U6 Q3 net
    D52        I    ~{CLK}        U27A ~Q side
    D53        I    ~{RESET}      U27B pin 8 net

Run: `run root`. Expect 5 PASS. Two tests are armed — press the reset
button when told.

What each test proves / what its FAIL means:

    root.clock    hardware edge count (Timer0 on D38): CLK = 1024kHz +/-2%,
                  ~CLK toggling. FAIL kHz: Y1/divider chain (U20/U27A).
                  FAIL CLKN: ~CLK wiring.
    root.tstates  burst capture (2+ samples per T state), then every state
                  change must be +1 mod 16 with rollover — prints the
                  sequence. FAIL steps: T not advancing (U6 clock/MR).
                  FAIL violations: counting order (Q wiring, bit swap).
    root.reset    armed. Hold: RESET/~RESET complementary, T frozen at 0.
                  Release: complements flip after the RC stretch, T counts.
    root.halt     HALT freezes T (any value); resumes on release; then
                  reset-while-halted clears to 0 (sync-MR beats CET).
                  FAIL T_frozen: CET path/U61 gate 2. FAIL reset_beats_halt:
                  MR wiring.
    root.end      END high pins T at 0 (U61 gate 1 + '163 sync MR, cleared
                  every edge); counting resumes when released.

Approve the stage: check the box in README.md, move on.

---

## Stage 7 — program counter (4x '193 + load/count gating + '245 mux)

Rig is the clock again (Y1 rule back in force): PC board standalone, all
inputs rig-driven, fully deterministic. `selftest pc` first, then wire per
`pins pc` — 23 contract jumpers + GND (M bus is 16 of them: PORTC = M0-7,
PORTL = M8-15).

Netlist facts the tests lean on (program_counter.kicad_sch, verified):

    U10 '02   CLR = OR(NOR(~PC_CLEAR, CLK), RESET) — decoder clear lands
              only while CLK is LOW; the RESET leg is NOT gated.
    U36 '00   UP pin = NAND(PC_UP, ~CLK) — counts on CLK rising.
              ~PC_LOAD_STABLE = NAND(PC_LOAD, ~CLK) — load lands only
              while CLK is LOW (NOT async, despite the '193 pin name).
    U11/U12   '245 A->B: M -> PCD (load path), enabled by ~PC_LOAD.
    U13/U14   '245 B->A: PC -> M, enabled by ~PC_MAR_MUX.

Protocol rules the firmware obeys (mirror them when hand-probing):
- PC_UP changes only while CLK is HIGH — deasserting during CLK-low fires
  a spurious count through U36.
- Never drive M with ~PC_MAR_MUX low — U13/U14 fight you through the
  series resistors.

Run: `run pc`. Expect 8 PASS, no button work.

    pc.presence    reset -> 0, one step -> 1. Wired at all?
    pc.count       prints the 16-step walk; then 8 clocks with PC_UP low —
                   no creep. FAIL walk: U36 gate 1 / '193 chain. FAIL hold:
                   PC_UP net stuck.
    pc.carry       00FF->0100, 0FFF->1000, 7FFF->8000, FFFF->0000; ROM_EN
                   (M15) flips exactly at 0x8000. FAIL: ~CO cascade between
                   the '193s.
    pc.load        patterns + walking 1s/0s through the M->PCD path; plus
                   ~PC_LOAD strobed with CLK HIGH must NOT land (U36 gate 3).
    pc.clear       ~PC_CLEAR blocked at CLK high, lands at CLK low (U10
                   NOR); RESET clears at either phase (un-gated leg).
    pc.mux         ~PC_MAR_MUX high -> all 16 M lines float (checked
                   individually); low -> PC drives again.
    pc.phase       PC_UP toggled during CLK-high -> no count; falling edge
                   -> no count; rising edge -> exactly +1.
    pc.precedence  clear beats load ('193 CLR dominance); load lands after
                   clear releases; RESET beats a count in flight; counting
                   continues from a loaded value (JMP-then-fetch seam).

Approve the stage: check the box in README.md, move on.

---

## Stage 4 — microcode (2x AT28C64B + U16/U17 address buffers)

Rig is the clock rule is moot here — this board has NO clock at all, pure
combinational ROM. Rig owns the whole address side.

### Burn first (TL866, blank chips)

Generate images + CRCs (also refreshes the rig's expect header — reflash
the rig after regenerating):

    python3 ../../docs/notes/microcode_gen.py

Emits to `dino/roms/`, all 8192 bytes (A12 is grounded on the board, so
the 4K image is mirrored into both halves — a mis-strapped A12 still reads
the same image):

    U9_diag.bin / U15_diag.bin   diag burn: word = own address, inverted
                                 top nibble in [15:12] — burn this FIRST
    U9.bin / U15.bin             real microcode (instruction table)

    U9  = word[7:0]  = CW0-7   (low byte)
    U15 = word[15:8] = CW8-15  (high byte)
    CRCs printed by the generator; the rig carries the same constants.

Burn/verify via make (minipro, chip in the TL866 one at a time):

    make burn-diag-u9      then swap chips ->  make burn-diag-u15
    make id-rom            names whatever chip is in the socket
    make verify-diag-u9    explicit read+compare (also real variants:
                           burn-real-u9/u15, verify-real-u9/u15)

Label the chips physically (U9/U15) before they leave the programmer —
id-rom can always tell you which is which later.

CHIP ORDER MATTERS — U9 gets the low byte. The docs had these roles
swapped until 2026-07-14; `microcode.split` exists to catch exactly this,
so if you doubt the sockets, run the suite before re-burning anything.

Fill rule (hard, from the registers-undefined-at-power-up decision): ALL
4096 rows programmed, no gaps — unused rows are 0x1000 (END), T0 of every
opcode is the universal fetch 0x600E, HALT word is 0x8000 with NO END bit.
The generator enforces all of it (builder asserts); don't hand-patch bins.

### Wire

`selftest microcode` first (rig-only, jumper the printed pairs), then pull
jumpers and wire per `pins microcode` — 28 contract jumpers + GND
(IRB = PORTK = Mega A8-A15, CW low byte = D37-D30, CW high byte = D49-D42).

STRIKE-7 TAP RULE: sample CW9-15 at the FAR ends of their tap runs — the
consumer-board ends (SA0-2 at the ALU header, END/HALT at root's header,
PC_UP at the PC header, PC_MAR_MUX at the MAR header). CW0-8 connect at
the control-word-bound header. Wired this way, every test in the suite
also proves the physical tap wires; `microcode.taps` then swings each tap
both ways deliberately.

    Mega pin   dir  DINO net    Mega pin   dir  DINO net
    GND        —    GND rail (first wire, always)
    A8-A15     O    IRB0-IRB7 (series R)
    D38        O    T0          D39        O    T1
    D40        O    T2          D41        O    T3   (series R)
    D37-D30    I    CW0-CW7     (U9 side, control-word header)
    D49        I    CW8         D48        I    CW9=SA2
    D47        I    CW10=SA1    D46        I    CW11=SA0
    D45        I    CW12=END    D44        I    CW13=PC_UP
    D43        I    CW14=PC_MAR_MUX        D42  I    CW15=HALT

### Run

`run microcode` with the DIAG burn seated, fix/approve, then re-burn the
REAL pair and run it again. Tests auto-detect the burn from row 0
(DIAG=0xF000, REAL=0x600E) and print which image they saw.

What each test proves / what its FAIL means:

    microcode.warmup     readiness probe (same lesson as pc.warmup):
                         row-0/row-0xFFF readback until stable 4x, prints
                         settle ms + detected image. FAIL: no valid burn
                         signature — wrong bins, chips absent, or power.
    microcode.presence   chips in place: a floating CW byte names its
                         socket (U9_drives_CW0_7 / U15_drives_CW8_15 —
                         EEPROM outputs are always enabled here). Then
                         row-0 signature. FAIL float: unseated chip or
                         dead tap run. FAIL signature: wrong/blank burn.
    microcode.order      DIAG burn: walking-1 through all 12 address
                         lines (T0->A0 .. IRB7->A11); a mis-mapped line
                         prints the row it actually decoded. Retires the
                         mirror-reversal bug class. REAL burn: weaker
                         distinctive-row spot check (says so).
                         FAIL: U16/U17 buffer wiring or A-line swap.
    microcode.split      byte roles on rows whose halves differ; prints
                         a loud note if U9/U15 are simply SWAPPED.
    microcode.crc        all 4096 rows, CRC16 PER CHIP vs the generator's
                         constants — a mismatch names the chip to reburn.
                         Prints computed CRCs; copy them into the log.
    microcode.taps       CW9-15 each driven high AND low, checked by name
                         at the tap far ends. FAIL on one line: that tap
                         run (wire, not chip — crc already passed the
                         data). Stuck line never toggles: `..._toggles`.
    microcode.stability  edge stress: repeated reads, 0xAAA/0x555
                         alternation, 0x000/0xFFF slam. ANY flicker is
                         electrical (seating, floating address line,
                         supply/ground — see the bench ledger smell).

Approve the stage: check the box in README.md. INT-A (control_word +
microcode, rig drives IRB+T only) comes after control_word passes.

---

## Stage 3 — control word (U30/U28/U29 '138s + U62 COND gates)

No CLK on this sheet — pure combinational, rig drives everything.
`selftest control_word` first (33 pins — odd count, so the firmware
prints one unpaired pin; that one gets a float-only check). Then pull
jumpers and wire per `pins control_word` — the printout IS the complete
hookup, probes included; the table below matches it.

PIN LAYOUT: ONE UNBROKEN DESCENT D53 -> D22, ONE CONTIGUOUS BLOCK PER
CHIP (hand-tuned in kicad_contracts.py PIN_ASSIGN/PIN_PROBES,
2026-07-17). Grab a chip, wire straight down: each block starts with the
chip's three driven CW address pins (chip pins 1,2,3), then its outputs
in descending chip-pin order. The 33rd wire spills to D19 (D21/D20 are
banned: clone I2C pullups break float checks). CW0-8 are deliberately
NOT on the PORTC byte here — each CW bit sits with its decoder; the rig
drives them per-pin. Four wires are rig-internal PROBES on nets that
never leave this board (U29's two U62-bound outputs, U62's two gate
outputs) — they make a cond.truth FAIL name the exact lying gate.

Netlist facts the tests lean on (control_word.kicad_sch, verified
2026-07-17):

    U30 '138  dst, address CW2:CW1:CW0.  O1..O7 = ~REG_A_LOAD,
              ~REG_B_LOAD, ~REG_C_LOAD, ~MAR_LO_LOAD, ~MAR_HI_LOAD,
              ~IR_LOAD, ~RAM_LOAD. O0 (NONE) is NC.
    U28 '138  src, address CW5:CW4:CW3.  O0 pin 15 = SRC_ACTIVE — a real
              contract net since the bug-4 U25 bridge fix: LOW only on
              src=NONE, HIGH whenever any source drives W. O1..O7 =
              ~ROM_OUT, ~RAM_OUT, ~REG_A_OUT, ~REG_B_OUT, ~REG_C_OUT,
              ~ALU_OUT, ~SW_OUT.
    U29 '138  address CW8:CW7:CW6.  O1 = ~PC_CLEAR, O2 = ~PC_LOAD_JMP,
              O3 = ~COND, O4 = ~MDR_OUT, O6 = ~REG_OUT_LOAD; O0/O5/O7 NC.
    All three: E1=E2=GND, E3=+5V — ALWAYS enabled, totem-pole outputs
              (the old NONE/NC tie-together bus fight is why the NC pins
              are individually open now).
    U62 '02   COND_TAKEN  = NOR(~COND, FLAG_Z)           (pin 1)
              PC_LOAD_JMP = INV(~PC_LOAD_JMP)            (pin 4)
              ~PC_LOAD    = NOR(COND_TAKEN, PC_LOAD_JMP) (pin 10)
              gate 4 spare: inputs GND, output NC.

Expectations are computed by src/cw_expect.h — a host-tested model
(hosttest/test_cw_expect.c, `make -C hosttest test`) — and EVERY on-bench
check compares all 23 sampled signals at once, so cross-group isolation
is baked into every assert.

Wiring (GND first; `O` = rig drives, series R; `I` = rig samples, direct;
"probe" = rig-internal net, still just a sampled wire). 34 wires total
with GND:

    Mega pin   dir  DINO net           where on the board
    GND        —    GND rail           first wire, always
    -- D53-D46: U29 '138 --
    D53        O    CW6                U29 pin 1  (A0)
    D52        O    CW7                U29 pin 2  (A1)
    D51        O    CW8                U29 pin 3  (A2)
    D50        I    ~{PC_CLEAR}        U29 pin 14
    D49        I    ~{PC_LOAD_JMP}     U29 pin 13  (probe)
    D48        I    ~{COND}            U29 pin 12  (probe)
    D47        I    ~{MDR_OUT}         U29 pin 11
    D46        I    ~{REG_OUT_LOAD}    U29 pin 9
    -- D45-D42: U62 '02 quad NOR --
    D45        I    COND_TAKEN         U62 pin 1   (probe)
    D44        O    FLAG_Z             U62 pin 3 net (ALU-bound header)
    D43        I    PC_LOAD_JMP        U62 pin 4   (probe)
    D42        I    ~{PC_LOAD}         U62 pin 10
    -- D41-D31: U28 '138 --
    D41        O    CW3                U28 pin 1  (A0)
    D40        O    CW4                U28 pin 2  (A1)
    D39        O    CW5                U28 pin 3  (A2)
    D38        I    SRC_ACTIVE         U28 pin 15
    D37        I    ~{ROM_OUT}         U28 pin 14
    D36        I    ~{RAM_OUT}         U28 pin 13
    D35        I    ~{REG_A_OUT}       U28 pin 12
    D34        I    ~{REG_B_OUT}       U28 pin 11
    D33        I    ~{REG_C_OUT}       U28 pin 10
    D32        I    ~{ALU_OUT}         U28 pin 9
    D31        I    ~{SW_OUT}          U28 pin 7
    -- D30-D22: U30 '138 --
    D30        O    CW0                U30 pin 1  (A0)
    D29        O    CW1                U30 pin 2  (A1)
    D28        O    CW2                U30 pin 3  (A2)
    D27        I    ~{REG_A_LOAD}      U30 pin 14
    D26        I    ~{REG_B_LOAD}      U30 pin 13
    D25        I    ~{REG_C_LOAD}      U30 pin 12
    D24        I    ~{MAR_LO_LOAD}     U30 pin 11
    D23        I    ~{MAR_HI_LOAD}     U30 pin 10
    D22        I    ~{IR_LOAD}         U30 pin 9
    -- the spill (D21/D20 banned) --
    D19        I    ~{RAM_LOAD}        U30 pin 7

Run: `run control_word`. Expect 7 PASS, no button work.

What each test proves / what its FAIL means:

    control_word.warmup     readiness probe (same bench lesson as pc/
                            microcode): NONE + all-groups-active vectors
                            until stable 4x, prints settle ms.
    control_word.presence   nothing here is ever high-Z, so a floating
                            line = missing chip or dead jumper — the FAIL
                            names the wire.
    control_word.walk       dec.walk: each '138 group through all 8 codes
                            (others at NONE), then three all-groups-active
                            combos. Every check asserts all 23 signals, so
                            a stray assertion in ANOTHER group fails under
                            the stray signal's name. FAIL one signal at
                            one code: that output wire. FAIL a pattern of
                            codes: address-pin order on that decoder
                            (e.g. want at code 2, got at code 4 = A0/A2
                            swapped — compare which codes light which
                            outputs against the netlist table above).
    control_word.none       dec.none: 000 in every group, both Z — no
                            named output low. SRC_ACTIVE rests LOW here
                            by design (it IS the src NONE decode).
    control_word.truth      cond.truth, the 4 U62 rows: /COND+Z=0 ->
                            ~PC_LOAD low (JNZ taken); /COND+Z=1 -> high;
                            JMP code -> low regardless of Z; idle -> high.
                            U62 inputs AND outputs probed, so the FAIL
                            names the lying part: ~COND/~PC_LOAD_JMP
                            wrong = U29; COND_TAKEN wrong with good
                            inputs = gate 1 (or the FLAG_Z wire);
                            PC_LOAD_JMP wrong = gate 2; only ~PC_LOAD
                            wrong = gate 3.
    control_word.sweep      exhaustive: all 512 CW codes x both Z, full
                            23-signal compare. Catches what walking can't:
                            a CW bit feeding two address pins only shows
                            when both groups run non-walking codes. First
                            mismatching states print their signals.
    control_word.stability  edge stress: repeats, complementary
                            alternation, 000<->1FF slam. ANY flicker is
                            electrical (seating, supply/ground — bench
                            ledger smell).

Approve the stage: check the box in README.md, then INT-A (control_word +
microcode: rig drives IRB+T only, samples decoder outputs — the
highest-risk seam).

---

## Stage 10 — mdr (MDR register + IR + the W<->MDR bridge)

Rig is the clock (CLK only gates the IR latch here — no free-running
logic). `selftest mdr` first, then wire per `pins mdr` — the printout IS
the complete hookup, probes included; 39 wires with GND, three runs,
each unbroken: controls D53-D40, W bus D22-D29, MDR+IRB on the analog
header A0-A15.

Netlist facts the tests lean on (mdr.kicad_sch, verified 2026-07-20):

    U18 '373  MDR register — D and Q pinned to the SAME MDR0-7 nets
              (bus-hold latch): grabs the MDR bus while LE_MDR is high,
              re-drives it when ~MDR_OUT drops. LE_MDR = NAND(~RAM_LOAD,
              READS_IDLE): transparent during a RAM write or any memory
              read strobe, latched at idle. NOT clock-gated.
    U34 '373  IR: D = W0-7, Q = IRB0-7, OE grounded (IRB never floats).
              LE_IR = NOR(CLK, ~IR_LOAD) — loads only while CLK is LOW,
              same stamp gate as the register file.
    U25 '245  the ONE W<->MDR bridge. DIR = BUS_DIR = NAND(~ALU_OUT,
              ~SW_OUT): high = W->MDR exactly when a W-side source
              drives (bug-4 fix: direction is a property of the SOURCE).
              CE = ~MDR_EN = NOR(SRC_ACTIVE, MDR_OUT): bridge on when
              ANY source is active or the MDR replay strobe is down.
    U37 '04   WRITE_DIR = INV(~RAM_LOAD); MDR_OUT = INV(~MDR_OUT);
              READS_IDLE = INV(NAND(~ROM_OUT, ~RAM_OUT)) [U39 gate 1].

ROGUE STATE — DO NOT HAND-WIRE IT: ~MDR_OUT low while a W-side source
(~ALU_OUT or ~SW_OUT) is asserted puts U25 and U18 on the MDR bus at
once. Real microcode never encodes it; `mdr.logic` skips those states
(and says how many).

Bus discipline (the firmware obeys this — mirror it when hand-probing):
release the bus the DUT is about to drive BEFORE asserting the enable;
never drive MDR while U18/U25 drives it; never drive W while the bridge
points MDR->W.

Gate expectations come from src/mdr_expect.h — host-tested model
(hosttest/test_mdr_expect.c, `make -C hosttest test`). Four probes give
full steering observability: LE_IR (U22.1), ~MDR_EN (U22.4), LE_MDR
(U39.6), BUS_DIR (U39.8) — a FAIL names the lying gate.

    Mega pin   dir  DINO net           where on the board
    GND        —    GND rail           first wire, always
    -- D53-D49: U22 '02, pins 1..5 --
    D53        I    LE_IR              U22 pin 1  (probe)
    D52        O    CLK                U22 pin 2
    D51        O    ~{IR_LOAD}         U22 pin 3
    D50        I    ~{MDR_EN}          U22 pin 4  (probe)
    D49        O    SRC_ACTIVE         U22 pin 5
    -- D48-D47: U37 '04 --
    D48        I    WRITE_DIR          U37 pin 4
    D47        O    ~{MDR_OUT}         U37 pin 5
    -- D46-D40: U39 '00, pins 1,2,4,6,8,9,10 --
    D46        O    ~{ROM_OUT}         U39 pin 1
    D45        O    ~{RAM_OUT}         U39 pin 2
    D44        O    ~{RAM_LOAD}        U39 pin 4  (same net as U37 pin 3)
    D43        I    LE_MDR             U39 pin 6  (probe)
    D42        I    BUS_DIR            U39 pin 8  (probe)
    D41        O    ~{ALU_OUT}         U39 pin 9
    D40        O    ~{SW_OUT}          U39 pin 10
    -- D29-D22: W bus (PORTA) --
    D29-D22    B    W7-W0              U25 A side / U34 D side
    -- A8-A15: IRB (PORTK) --
    A8-A15     I    IRB0-IRB7          U34 Q side
    -- A0-A7: MDR bus (PORTF) --
    A0-A7      B    MDR0-MDR7          U18 / U25 B side

Run: `run mdr`. Expect 8 PASS, no button work.

    mdr.warmup     readiness probe: idle gates + IR load + MDR capture
                   until stable 4x, prints settle ms.
    mdr.presence   always-driven lines (5 gate outputs + IRB0-7) must
                   not float — FAIL names the wire. W/MDR are covered by
                   tristate instead.
    mdr.logic      dir.logic, exhaustive: all 512 input states x all 5
                   gate signals vs the model (fight states skipped,
                   count printed). FAIL on one signal at one state:
                   that gate/wire — compare against the equations above.
    mdr.capture    MDR '373 through all three LE paths (~RAM_LOAD,
                   ~ROM_OUT, ~RAM_OUT), hold-against-overwrite, U18
                   replay readback, per-bit walk. FAIL walk bit: that
                   latch bit or MDR wire.
    mdr.ir         ir.snoop: patterns + walking 1s/0s land in IRB;
                   holds after W changes; ~IR_LOAD with CLK HIGH must
                   NOT land (U22 gate 1); transparent-follow while the
                   latch is open.
    mdr.tristate   everything idle, SRC_ACTIVE low: all 16 W+MDR lines
                   float individually (bug-4's quiescent contract).
    mdr.bridge     bridge.route — retires schematic bug 4 on real
                   copper: (a) W->MDR with src=ALU (and src=SW spot
                   row), (b) MDR->W with an MDR-side source, (c) U18
                   replay crosses to W with SRC_ACTIVE low, (d) bridge
                   OFF -> W floats while MDR is driven. Walking-1 per
                   row: a stuck '245 bit names itself.
    mdr.stability  gate flicker + capture/replay slam. Any flicker is
                   electrical (seating, supply/ground — bench ledger).

Approve the stage: check the box in README.md. INT-B2 (real-bridge
rerun of the registers+ALU seam) becomes possible once registers and
ALU pass their stages.

---

## Stage 5 — registers (A/B/C file + OUT exposure register)

Rig is the clock (CLK only gates the LE stamps). Registers live on the
MDR BUS — W never appears on this board (the W side exists only via the
mdr sheet's U25 bridge, tested there). `selftest registers` first, then
wire per `pins registers` — the printout IS the complete hookup, probes
included; 32 wires with GND, three runs, each unbroken: controls
D53-D39, OB on A8-A15, MDR on A0-A7.

NB: the MDR rows print as DUT-outputs but the rig DRIVES them during
loads — series R on the MDR jumpers too.

Netlist facts the tests lean on (registers_a_b.kicad_sch, verified
2026-07-20, post-U66-consolidation):

    U31/32/33 '373  A/B/C — bus-hold latches (D=Q on private buses
              AB/BB/CB), LE = ~{REG_x_LE} (ACTIVE HIGH despite the
              name), OE = ~{REG_x_OUT} (register drives its private
              bus only while read).
    U41/42/43 '245  register ports: A side = MDR, B = private bus.
              DIR = ~{REG_x_OUT} (high: MDR->reg = load; low:
              reg->MDR = read). CE = ~{x_EN}.
    U5 '08    ~{x_EN} = AND(~{REG_x_LOAD}, ~{REG_x_OUT}) — port open
              on load OR read, closed at idle.
    U57 '02   all four LE stamps: ~{REG_x_LE} = NOR(~{REG_x_LOAD},
              CLK) — loads land only while CLK is LOW.
    U44 '245  OUT path: MDR -> U35's D pins, DIR strapped, CE =
              ~{REG_OUT_LOAD} directly.
    U35 '373  OUT register, OE grounded — OB0-7 never float.

FIGHT RULE: never assert two /OUTs at once (two '245s onto MDR — the
one-hot src decoder can't encode it; `registers.logic` skips those
states and says how many). One /OUT + another register's /LOAD is the
LEGAL transfer row and is tested deliberately.

Gate expectations come from src/reg_expect.h — host-tested model
(hosttest/test_reg_expect.c). Seven probes = full stamp/steering
observability: 4 LE nets + 3 EN nets; a FAIL names the lying gate.

    Mega pin   dir  DINO net           where on the board
    GND        —    GND rail           first wire, always
    -- D53-D45: U57 '02, pins 1..13 (all four LE stamps) --
    D53        I    ~{REG_A_LE}        U57 pin 1   (probe)
    D52        O    ~{REG_A_LOAD}      U57 pin 2
    D51        O    CLK                U57 pin 3 (any of the 4 CLK legs)
    D50        I    ~{REG_B_LE}        U57 pin 4   (probe)
    D49        O    ~{REG_B_LOAD}      U57 pin 5
    D48        O    ~{REG_C_LOAD}      U57 pin 8
    D47        I    ~{REG_C_LE}        U57 pin 10  (probe)
    D46        O    ~{REG_OUT_LOAD}    U57 pin 11
    D45        I    ~{REG_OUT_LE}      U57 pin 13  (probe)
    -- D44-D39: U5 '08, pins 2,3,5,6,8,10 (the '245 CE gates) --
    D44        O    ~{REG_A_OUT}       U5 pin 2
    D43        I    ~{A_EN}            U5 pin 3    (probe)
    D42        O    ~{REG_B_OUT}       U5 pin 5
    D41        I    ~{B_EN}            U5 pin 6    (probe)
    D40        I    ~{C_EN}            U5 pin 8    (probe)
    D39        O    ~{REG_C_OUT}       U5 pin 10
    -- A8-A15: OB (PORTK) --
    A8-A15     I    OB0-OB7            U35 Q side
    -- A0-A7: MDR bus (PORTF) --
    A0-A7      B    MDR0-MDR7          U41-44 A sides (series R!)

Run: `run registers`. Expect 9 PASS, no button work.

    registers.warmup     readiness probe + conditions the power-up-
                         undefined latches; prints settle ms.
    registers.presence   7 gate outputs + OB0-7 must not float — FAIL
                         names the wire.
    registers.logic      stamp.gate + EN truth, exhaustive: 256 states
                         x 7 signals vs the model (fight states
                         skipped, count printed).
    registers.load       load.readback per A/B/C (patterns; per-bit
                         walks through A) + /LOAD-with-CLK-HIGH must
                         NOT land (U57 stamp gating).
    registers.isolation  A=0xAA B=0x55 C=0xC3 all read back intact,
                         A re-read after everything.
    registers.transfer   the MOV seam: A drives MDR, B loads it, rig
                         drives nothing — CE/DIR steering under real
                         bus traffic. A must survive unchanged.
    registers.outreg     OB patterns + walk; holds after MDR changes
                         (OE-grounded exposure register).
    registers.tristate   no /OUT -> all 8 MDR lines float.
    registers.stability  gate flicker + load/read slam (electrical —
                         bench ledger smell).

Approve the stage: check the box in README.md. INT-B (registers + alu,
rig emulating the bridge) follows once alu passes stage 6; INT-B2
reruns it through the real U25 bridge (mdr already bench-proven).

---

## Stage 8 — mar (LO/HI address latches + MAR->M port + decodes)

Rig is the clock (CLK only gates the LE stamps). `selftest mar` first,
then wire per `pins mar` — the printout IS the complete hookup, probes
included: ONE unbroken descent D53 -> D22 (the M8-15 bank fills
D49-D42 between the two control clusters), 33 wires with GND.

Netlist facts the tests lean on (mar.kicad_sch, verified 2026-07-22):

    U55/U58 '373  LO/HI latches: D = W0-7 (both halves from the SAME
              W byte, separate LEs), Q = private MAR0-15, OE grounded.
              No fight class exists on this board.
    U54/U59 '245  MAR -> M: DIR strapped, CE = PC_MAR_MUX plain —
              enabled at 0 (bit map: PC=1, MAR=0).
    U60 '02   all four gates, zero spares:
              LE_MAR_LO = NOR(~MAR_LO_LOAD, CLK)   (house stamp)
              LE_MAR_HI = NOR(~MAR_HI_LOAD, CLK)
              ~RAM_EN   = INV(M15) — decodes the BUS, correct under
                          either mux source
              ~PC_MAR_MUX = INV(PC_MAR_MUX)

Bus discipline: NEVER drive M while PC_MAR_MUX=0 (U54/U59 own it);
the rig emulates the PC side on M only at mux=1.

Gate expectations from src/mar_expect.h (host-tested,
hosttest/test_mar_expect.c). Two probes only — both on U60.

    Mega pin   dir  DINO net           where on the board
    GND        —    GND rail           first wire, always
    -- D53-D50: U60 '02, pins 1..4 --
    D53        I    LE_MAR_LO          U60 pin 1   (probe)
    D52        O    ~{MAR_LO_LOAD}     U60 pin 2
    D51        O    CLK                U60 pin 3 (either CLK leg)
    D50        I    LE_MAR_HI          U60 pin 4   (probe)
    -- D49-D42: M high byte (PORTL) --
    D49-D42    I/B  M8-M15=ROM_EN      U59 B side (M15 = D42, bidir)
    -- D41-D38: U60 pins 5,10,11,13 --
    D41        O    ~{MAR_HI_LOAD}     U60 pin 5
    D40        I    ~{RAM_EN}          U60 pin 10
    D39        O    CW14=PC_MAR_MUX    U60 pin 11
    D38        I    ~{PC_MAR_MUX}      U60 pin 13
    -- D37-D30: M low byte (PORTC) --
    D37-D30    I    M0-M7              U54 B side
    -- D29-D22: W bus (PORTA) --
    D29-D22    O    W7-W0              U55/U58 D sides (series R)

Run: `run mar`. Expect 7 PASS, no button work.

    mar.warmup     readiness probe, non-palindrome vectors (0xC53A /
                   0x3AC5 — mirror-witness rule).
    mar.presence   mux=0: all 16 M lines + 4 gate outputs driven —
                   FAIL names the wire.
    mar.logic      stamp + decode truth, exhaustive: 16 control states
                   x both M15 levels, M15 set via the LATCH at mux=0
                   and via the RIG at mux=1 (proves the decode follows
                   the bus).
    mar.hold       load16 + LO walks with HI held + HI walks with LO
                   held (every check reads the full 16 bits) + /LOAD
                   with CLK HIGH must not land.
    mar.mux        mux=1 -> all 16 M lines float individually +
                   ~PC_MAR_MUX asserts; latched address survives the
                   excursion.
    mar.decode     the 0x8000 boundary exactly, from BOTH sides: MAR
                   latched (0x7FFF/0x8000/0x0000) and rig-driven at
                   mux=1 with a CONTRADICTING latch (latch says RAM,
                   bus says ROM — decode must follow the bus).
    mar.stability  gate flicker + load/read slam (electrical — bench
                   ledger).

Approve the stage: check the box in README.md. INT-C (pc + mar: the
shared M bus and the mux seam) follows per the spec's build program.

---

## Stage 9 — memory (32K program ROM + 32K RAM + buffers + gates)

The v0.0.2 board updated to v0.0.3: the '121 one-shot is GONE. The RAM
write pulse is now a GATE off the clock phase — nothing to tune, and
`memory.window` is the test that proves it.

Rig is the clock (~CLK only opens the write window) and owns the whole
address bus. `selftest memory` first, then wire per `pins memory`.

PIN LAYOUT IS RIBBON-FIRST (bench call, 2026-07-23): both byte buses sit
in ONE unbroken 24-pin run, D53 -> D30, each bus ascending and
uninterrupted — MDR0-7 on D53-D46, then M0-M15 on D45-D30. One ribbon
per bus, no control wires interleaved. Signals follow on D29 -> D22 in
U51 pin order, and ~{RAM_EN} spills to D19 (D21/D20 stay banned). 34
wires with GND.

Consequence, noted in firmware: neither bus lands byte-aligned on an AVR
port any more, so this module drives and samples both PER PIN instead of
using the fixed-port helpers. The address is static per access, so the
only cost is ~10us per read — the 32768-byte romcrc sweep still finishes
well under a second.

### Burn first (TL866, AT28C256)

    python3 ../../docs/notes/progrom_gen.py

Emits to `dino/roms/`, 32768 bytes each:

    PROG_diag.bin   content-addressed, SELF-NAMING: addr 0 -> 0xA5,
                    addr 2^k -> 0x40|k. Burn this FIRST — 15 address
                    lines is the biggest one-hole surface on the machine,
                    and a mis-decoded line reports where it landed.
    PROG.bin        the MILESTONE program: LDAI 0xFF; OUT; LDAI 0x2F;
                    LDBI 0x1E; ADD; OUT;
                    HALT — safe-filled with HALT (0xFF) so an erased or
                    overrun ROM halts instead of raving.

    make burn-prog-diag     then later:  make burn-prog
    make verify-prog-diag                make verify-prog

CRCs are printed by the generator and compiled into the rig, so they
cannot disagree. The assembler validates every operand count against
microcode_gen's instruction table — a program can never encode something
the microcode cannot execute.

Netlist facts the tests lean on (memory.kicad_sch, verified 2026-07-23):

    U24 AT28C256  ROM: A0-14 = M0-14, ~CE = ROM_EN (= M15, so the ROM
              answers 0x0000-0x7FFF), ~OE = ~ROM_OUT, ~WE strapped +5V.
    U26 MCM60256AP RAM: same address lines, ~CE = ~RAM_EN (= INV(M15)
              from the MAR board), ~OE = ~RAM_OUT, ~WE = ~RAM_WRITE_EN.
    U19 '245  ROM -> MDR, DIR strapped, CE = ~ROM_OUT.
    U21 '245  RAM <-> MDR, DIR = ~WRITE_DIR, CE = ~RAM_MDR_EN.
    U51 '00   all four gates:
              ~WRITE_DIR    = INV(WRITE_DIR)
              ~RAM_WRITE_EN = NAND(WRITE_DIR, ~CLK)   <- the write window
              RAM_MDR_DIS   = NAND(~RAM_OUT, ~WRITE_DIR)
              ~RAM_MDR_EN   = INV(RAM_MDR_DIS)
              => U21 CE = AND(~RAM_OUT, ~WRITE_DIR) — SCHEMATIC BUG 2's
              fix in copper. `memory.idle` retires that class.

NEVER hand-drive: two MDR drivers at once (ROM and RAM strobes together),
or WRITE_DIR high while the selected RAM drives its own DQ. The suite
skips those states and says how many.

    Mega pin   dir  DINO net           where on the board
    GND        —    GND rail           first wire, always
    -- D53-D46: MDR ribbon (bidir — series R, the rig drives these
       during RAM writes). U19 and U21 B sides, both chips same net. --
    D53        B    MDR0               U19 pin 18 / U21 pin 18
    D52        B    MDR1               U19 pin 17 / U21 pin 17
    D51        B    MDR2               U19 pin 16 / U21 pin 16
    D50        B    MDR3               U19 pin 15 / U21 pin 15
    D49        B    MDR4               U19 pin 14 / U21 pin 14
    D48        B    MDR5               U19 pin 13 / U21 pin 13
    D47        B    MDR6               U19 pin 12 / U21 pin 12
    D46        B    MDR7               U19 pin 11 / U21 pin 11
    -- D45-D30: M ribbon. A0-A14 fan to BOTH memory chips (U24 + U26
       share every address line); M15 is the ROM's chip select. --
    D45        O    M0                 U24 pin 10 / U26 pin 10
    D44        O    M1                 U24 pin  9 / U26 pin  9
    D43        O    M2                 U24 pin  8 / U26 pin  8
    D42        O    M3                 U24 pin  7 / U26 pin  7
    D41        O    M4                 U24 pin  6 / U26 pin  6
    D40        O    M5                 U24 pin  5 / U26 pin  5
    D39        O    M6                 U24 pin  4 / U26 pin  4
    D38        O    M7                 U24 pin  3 / U26 pin  3
    D37        O    M8                 U24 pin 25 / U26 pin 25
    D36        O    M9                 U24 pin 24 / U26 pin 24
    D35        O    M10                U24 pin 21 / U26 pin 21
    D34        O    M11                U24 pin 23 / U26 pin 23
    D33        O    M12                U24 pin  2 / U26 pin  2
    D32        O    M13                U24 pin 26 / U26 pin 26
    D31        O    M14                U24 pin  1 / U26 pin  1
    D30        O    M15=ROM_EN         U24 pin 20 (ROM ~CE)
    -- D29-D22: U51 '00 in chip pin order --
    D29        O    WRITE_DIR          U51 pin 1 (daisies to 2 and 5)
    D28        I    ~{WRITE_DIR}       U51 pin 3   (probe)
    D27        O    ~{CLK}             U51 pin 4
    D26        I    ~{RAM_WRITE_EN}    U51 pin 6   (probe)
    D25        I    RAM_MDR_DIS        U51 pin 8   (probe)
    D24        O    ~{RAM_OUT}         U51 pin 9 (also U26 pin 22)
    D23        I    ~{RAM_MDR_EN}      U51 pin 11  (probe)
    D22        O    ~{ROM_OUT}         U24 pin 22 + U19 pin 19
    -- the spill (D21/D20 banned) --
    D19        O    ~{RAM_EN}          U26 pin 20 (RAM ~CE)

NOTE the address pins ASCEND on the chips in a zigzag (A0=10, A7=3,
A8=25, A9=24, A10=21, A11=23, A12=2, A13=26, A14=1) — the same
non-monotonic corner that bit the microcode EEPROMs. Count chip pins,
not header order, and beep each line to BOTH chips.

Run: `run memory` with the DIAG burn seated, fix/approve, then burn REAL
and run again. Tests auto-detect the image from byte 0 and print it.
Expect 11 PASS.

    memory.power      PHANTOM-POWER CHECK, runs first. A deliberate
                      power-off run scored 7/10 on this board: the
                      rig's driven lines push current through the DUT's
                      input clamp diodes into its VCC rail, and CMOS
                      memory reads happily on stolen current (only the
                      bipolar '00 and the write cycles failed). This
                      test holds every rig output low but one, so there
                      is nothing to steal — an unpowered '00 cannot
                      hold its HIGH outputs. FAIL here means CHECK THE
                      BENCH SUPPLY before reading any other FAIL in the
                      run. (Phantom powering is also a real hazard:
                      sustained clamp-diode current can exceed the
                      per-pin rating — the series resistors are what
                      save the board.)
    memory.warmup     readiness probe: ROM signature + a RAM round trip
                      until stable 4x; prints settle ms and the image.
    memory.presence   U51's four outputs driven; every MDR line driven
                      during a ROM read. FAIL names the wire.
    memory.logic      U51 truth, exhaustive: 64 control states x 4 gate
                      signals vs the model, fight states skipped and
                      counted. Mismatches print state + signal.
    memory.romorder   DIAG burn: walking-1 through all 15 ROM address
                      lines; a mis-decoded line prints the address the
                      chip ACTUALLY saw. REAL burn: program-row spot
                      check (says so).
    memory.romcrc     all 32768 bytes, CRC16 vs the generator constant.
                      Prints the computed CRC — copy it into the log.
    memory.ramrw      data walk at the RAM base, then a 15-line RAM
                      address walk with a distinct byte per line (a
                      collision prints whose cell answered), then far
                      corners + no-aliasing checks.
    memory.select     the 0x8000 boundary exactly: ROM answers below,
                      RAM at and above, and neither chip leaks into the
                      other's half under the wrong strobe.
    memory.window     ~RAM_WRITE_EN = NAND(WRITE_DIR, ~CLK): no write
                      with ~CLK low, no write without WRITE_DIR, write
                      lands only with both. THE '121 REPLACEMENT TEST.
    memory.idle       BUG-2 RETIREMENT: MAR parked on a RAM address with
                      no RAM op in flight -> U21 stays off, MDR floats
                      on all 8 bits. Fails on the pre-review schematic.
    memory.stability  ROM repeat / 0x2AAA-0x5555 alternation / 0x0000-
                      0x7FFF slam + a RAM write-read slam. Any flicker
                      is electrical (bench ledger smell).

Approve the stage: check the box in README.md. After alu and io, the
integration ladder (INT-A/B/B2/C/D/E) and free-run remain — the REAL
burn's program is the milestone itself.

---

## Stage 6 — alu ('382 pair + shadows + output latch + flags)

The board with the most internal state, so it gets the most probes: ten
of the twenty control wires. Rig is the clock. `selftest alu` first,
then wire per `pins alu` — ONE unbroken descent D53 -> D34, one block
per chip, then the W ribbon on D29-D22 (same home as mdr and mar). 29
wires with GND.

Netlist facts the tests lean on (alu.kicad_sch, verified 2026-07-24):

    U45/U46 '373  TMP_A / TMP_B shadows: D = W0-7 (both from the SAME
              W byte), Q = TA/TB, OE grounded.
              LE_TMP_x = NOR(~REG_x_LOAD, CLK)  [U50 g1/g2] — the house
              stamp, so an ALU operand latches at the same instant the
              register file takes the same byte.
    U38/U40 '382  the 8-bit ALU. S2:S1:S0 = SA2:SA1:SA0:
              000 CLEAR  001 B-A  010 A-B  011 A+B
              100 A^B    101 A|B  110 A&B  111 PRESET
              U38 (low) CN = ALU_CIN, CN+4 = CRY -> U40 (high) CN;
              U40 CN+4 = ALU_C, OVR = ALU_V.
    ALU_CIN = NAND(SA1, SA0)  [U53 g4 -> U50 g4] — ADD and SET carry 0,
              every other code carries 1. That is precisely what makes
              both subtract codes true two's complement: 5-3 = 2, not 1.
    U47 '373  output latch: D = F, Q = W, LE = CLK (transparent while
              CLK is HIGH), OE = ~ALU_OUT.
    U52/U53   zero tree: Z = AND(NOR(F0,F1)..NOR(F6,F7)).
    U48 '157  flag mux, S = ~ALU_OUT: ALU enabled -> new values; idle ->
              flags feed back to themselves and HOLD.
    U49 '273  flag register: Cp = ~CLK, so flags commit on the FALLING
              edge of CLK. ~Mr = ~RESET (async clear).
              Q0-3 = FLAG_C, FLAG_Z, FLAG_V, FLAG_N.

THE OP CYCLE (the real machine's ALU T-state, and what every test does):
load the shadows -> set SA -> CLK high (U47 transparent) -> ~ALU_OUT low
(U47 drives W) -> read result + combinational probes -> CLK low (U47
latches, U49 commits flags) -> read flags -> release.

Bus rule: drive W only while ~ALU_OUT is HIGH. The moment it drops, U47
owns the bus.

C and V are only defined by the '382 for the three arithmetic codes, so
`ops` asserts them exactly there and leaves the logic codes' carry alone
(the model says which, via cv_defined).

    Mega pin   dir  DINO net           where on the board
    GND        —    GND rail           first wire, always
    -- D53-D48: U50 '02 (shadow stamps + the carry rule) --
    D53        I    LE_TMP_A           U50 pin 1   (probe) -> U45 pin 11
    D52        O    ~{REG_A_LOAD}      U50 pin 2
    D51        O    CLK                U50 pin 3 (daisies to pin 6)
    D50        I    LE_TMP_B           U50 pin 4   (probe) -> U46 pin 11
    D49        O    ~{REG_B_LOAD}      U50 pin 5
    D48        I    ALU_CIN            U50 pin 13  (probe) -> U38 pin 15
    -- D47-D42: U49 '273 (the flag register) --
    D47        O    ~{RESET}           U49 pin 1  (~Mr)
    D46        I    FLAG_C             U49 pin 2   (probe)
    D45        I    FLAG_Z             U49 pin 5   (the one contract OUT)
    D44        I    FLAG_V             U49 pin 6   (probe)
    D43        I    FLAG_N             U49 pin 9   (probe)
    D42        O    ~{CLK}             U49 pin 11 (Cp)
    -- D41-D38: U38 '382 low nibble --
    D41        O    CW11=SA0           U38 pin 5  (also U40 pin 5)
    D40        O    CW10=SA1           U38 pin 6  (also U40 pin 6)
    D39        O    CW9=SA2            U38 pin 7  (also U40 pin 7)
    D38        I    CRY                U38 pin 14  (probe) -> U40 pin 15
    -- D37-D36: U40 '382 high nibble --
    D37        I    ALU_V              U40 pin 13  (probe, OVR)
    D36        I    ALU_C              U40 pin 14  (probe, CN+4)
    -- D35: U53 zero tree / D34: U47 output latch --
    D35        I    Z                  U53 pin 8   (probe)
    D34        O    ~{ALU_OUT}         U47 pin 1 + U48 pin 1
    -- D29-D22: W bus (PORTA) --
    D29-D22    B    W7-W0              U45/U46 D sides + U47 Q side
                                       (series R — the rig drives these
                                        during shadow loads)

Run: `run alu`. Expect 10 PASS, no button work.

    alu.power       phantom-power check, runs first (house rule since
                    the memory board scored 7/10 unpowered). All-low
                    opens both stamps, asserts the carry rule and clears
                    the '382s, so LE_TMP_A/B, ALU_CIN and Z must all
                    read HIGH with the rig sourcing nothing. FAIL here
                    = check the supply before reading anything else.
    alu.warmup      readiness: the milestone sum 0x2F+0x1E, plus a
                    non-palindrome logic result (0xC0|0x05 = 0xC5) so a
                    mirrored W ribbon cannot slip through.
    alu.presence    all eleven sampled lines driven; W driven while
                    ~ALU_OUT is low and floating the instant it rises.
    alu.gates       LE_TMP_A/B 4-row stamp truth, then cin.rule across
                    all 8 select codes.
    alu.shadow      TMP_A/TMP_B capture (observed through OR with 0),
                    per-bit walk on both latches, independence, and a
                    strobe-with-CLK-HIGH row that must NOT land.
    alu.ops         every function code x a 10-vector operand table
                    hitting carry, borrow, zero, overflow and sign
                    edges. F, N, Z asserted always; C and V on the
                    arithmetic codes. Mismatches print op, operands and
                    which flag disagreed.
    alu.flags       flags.commit: idle clock edges must not disturb the
                    flags (the '157 recirculates); an enabled cycle
                    updates them only on the CLK fall.
    alu.reset       flags.reset: ~RESET clears all four asynchronously,
                    with the clock parked — no edge involved.
    alu.carry       the CRY wire between nibbles: 0x07+0x07 (no ripple),
                    0x0F+0x01 (ripple), 0xF0+0x10 (high nibble only),
                    0xFF+0x01 (full width), and a SUB that borrows
                    across the boundary. A broken CRY reads as "low
                    nibble right, high nibble off by one".
    alu.stability   repeat/alternate/flag-commit slam. Flicker is
                    electrical (bench ledger smell).

Approve the stage: check the box in README.md. INT-B (registers + alu,
rig emulating the bridge) unlocks here; INT-B2 reruns it through the
real U25 bridge, already bench-proven on the mdr board.

---
## Integration — CONTROL FIRST (block model, supersedes INT-A..INT-E)

All ten modules are bench-proven, so they are fixtures. Integration is no
longer "test the seam between two boards." It is:

    MAKE THE CONTROL UNIT REAL FIRST. THEN EVERY LATER BLOCK GETS ITS
    STROBES FOR FREE, IN COPPER, AND THE RIG ONLY EVER SHEDS WIRES.

### The gate: driven-wire count. It may never go up.

Rico's requirement, and it is the right one, because two things that look
like separate goals are the same goal:

    FEWER RIG WIRES == FEWER RIG-INTRODUCED ERROR MODES

Every rig wire is a wire that can be one hole off, swapped in a ribbon, or
landed on the wrong leg. All three have already cost bench time on this
project. And the risk is NOT symmetric:

    sampled wire wrong ...... false FAIL. Costs an evening, hurts nothing.
    driven wire wrong ....... can fight a real driver. Contention, maybe
                              damage.
    driven STROBE wrong ..... worst case, because strobes are ENABLES. A
                              wrong enable is precisely how two boards end
                              up driving one bus.

So the quantity to minimize hardest is RIG-DRIVEN STROBES.

### Why that inverts the obvious plan

The control unit has the highest fan-out in the machine — it reaches every
board. A rig standing in for it must drive ~20 strobes across every
datapath board at once: the largest and most dangerous harness the project
could possibly build.

Make it REAL first and that harness never exists. The rig's whole job
becomes eight forced instruction bits, and from Block 3 it drives nothing
at all.

This is also what the original spec said — "control/microcode first
because INT-A is the highest-risk seam and needs no datapath." The
datapath-core plan drifted off that. Control-first restores it.

### THE BLOCK LAW — what a block may touch (2026-07-28)

Blocks are BLACK-BOX tests. All ten modules are bench-proven and module
coverage is extensive; a block that re-samples a signal a module test
already retired is just a module test with more wires and more ways to be
wrong.

    SAMPLE A SIGNAL AT BLOCK LEVEL ONLY IF ITS VALUE DEPENDS ON MORE THAN
    ONE MEMBER OF THE BLOCK.

If one module alone determines it, the module test owns it. If an earlier
block already sampled it, that block owns it. What is left is exactly the
behaviour that has never existed before — the seam.

Four categories, all DERIVED from the netlist, none hand-written:

    COPPER  OUT of one member AND IN of another member.
            Dropped entirely. Wired board-to-board; the rig never touches
            it. This is where the wire savings come from.
    DRIVE   IN of a member, OUT of no member, and genuinely needed as
            stimulus. Rig drives it, 220-470R series.
    STRAP   IN of a member, OUT of no member, but NOT needed as stimulus.
            Tied ON THE BOARD to a safe level. NOT a rig wire.
    SAMPLE  OUT of a member, not copper, not retired by a module test or
            an earlier block.

Every retirement must NAME the test that earned it. That is the reviewable
part, and it is why the retire list is a dict and not a list.

ACCEPTED EXCEPTION: END and HALT are copper (microcode -> root) but are
sampled anyway in every block. Nothing else can segment the instruction
stream or observe the freeze from outside. Two wires, stated as an
exception rather than smuggled in.

### NOTHING IS EVER PULLED — but rig jumpers come off freely

    CHIPS AND BOARD-TO-BOARD COPPER: never touched. Y1 stays in its socket
    from Block 1 through Block 5. No socket is ever disturbed. Once a strip
    is populated it is copper (AS-BUILT FREEZE).

    RIG JUMPERS: removed freely as they retire. That IS the ladder.

    TEMPORARY BOARD STRAPS: removed when real copper takes over the net.
    A strap left in place meets a real driver — see the Block 3 and Block 4
    prerequisites below.

Consequence, and it kills an older plan in this file: CLK is U27.5 and
RESET is U27.9, both '74 totem-pole outputs. The rig cannot drive either
without fighting a real driver, and the only non-contending injection
point (U20.2) needs Y1 out of its socket. So:

    THE RIG NEVER OWNS THE CLOCK. EVERY BLOCK FREE-RUNS AT 1.024MHz.
    THERE IS NO SINGLE-STEPPING ANYWHERE ON THIS LADDER.

Every block test is burst-capture-and-decode, not step-and-sample. Reset
is the physical button plus an `ARM ...` prompt, exactly as the root tests
already do.

### The wire budget

    BLOCK  WIRE IN                     DRIVEN  SAMPLED  JUMPERS
    -----  --------------------------  ------  -------  -------
    1      root+microcode+control_word    8       27     35+GND
    2      + pc + mar + memory            8       11     19+GND
    3      + mdr                          0       11     11+GND
    4      + registers + alu              0       11     11+GND
    5      + io                           0       11     11+GND

CLK IS SAMPLED IN BLOCKS 1-5 AS A CAPTURE QUALIFIER, not as an assertion —
root.clock still owns it. After T changes on the CLK rising edge the microcode
ROM outputs are invalid for one access time (tACC 150-250ns) and the decoded
strobes glitch through it. The MACHINE does not care (everything commits on
CLK low), but a blind sampler emits TWO frames for one T-state and loses
`t = position within the run`, which is the whole basis of the decode test.
Gating on CLK low samples after the ROM has settled. It is SAMPLED, so the
driven count is unchanged and the gate holds. Block 1's first bench run failed
exactly this way — the same opcode read 0x60/0x10/0x60 for one T across three
passes (2026-07-30).

Block 2 is the payoff: THREE BOARDS JOIN AT ZERO NEW DRIVEN WIRES, and the
sample count falls from 26 to 10, because M0-15 comes from PC/MAR and
every strobe comes from the real decoder.

Block 3 takes DRIVEN TO ZERO — the real IR fetches the machine's own
instruction bytes, so IRB0-7 stops being forced. From there the rig drives
nothing at all, ever again, and cannot fight anything by construction.

RULE: a proposed block that raises the driven count is the wrong block.
Re-cut it.

### END and HALT never move

Both are sampled in ALL SIX BLOCKS, on the same two Mega pins, tapped at
the same two DUT pins:

    D45 / PL4    CW12=END     U61.3
    D42 / PL7    CW15=HALT    U61.5

Land them at Block 1 and do not touch them again.

TAPPED AT U61, NOT AT U15. U15.16/U15.19 are the ROM's own pins; U61 is
where END actually reaches U6.~{MR} and HALT reaches U6.CET. Sampling the
source end proves the ROM pin and nothing about the two-board run that
does the work. This is the STRIKE-7 TAP RULE and it is easy to get wrong —
three independent passes over this ladder all picked the source end first.

Note this makes END and HALT both COPPER (a physical wire U15.16->U61.3
and U15.19->U61.5 that you must build) AND SAMPLED. Listing them only
under SAMPLE is exactly how a board-to-board wire goes missing.

---

## Three instruments, three different questions

The rig is not the only tool anymore, and each instrument answers a
question the others structurally cannot.

    RIG (ATmega2560)      WHAT.  Logic and topology. Exhaustive and
                          automated — it can walk all 256 opcodes x 16
                          T-states without complaint. Rig speed only:
                          settle() is 5us and every bus op is a bit-banged
                          per-pin loop. CANNOT SEE TIMING. Ever.

    LOGIC ANALYZER        WHEN.  16 channels at real speed. The right tool
    (DSLogic)             for enable overlap, T-state one-hot, END->T
                          clear, and decode glitches. Wide enough to watch
                          every SRC enable at once, which is exactly the
                          contention question.

    OSCILLOSCOPE          HOW.   Analog truth. Edge shape, ringing,
    (Siglent SDS)         overshoot, and marginal levels — a "high" that
                          is really 2.0V of floating charge. No digital
                          instrument sees any of this. You have already
                          been bitten by it once (U45.2 at 1.67V).

### Can the Mega stand in for the LA and the scope?

Partly, and it is worth doing as a FIRST look before hauling out the other
two — but know the edges:

    IT CAN
      read a whole port in one instruction — PINA is a genuine 8-channel
        simultaneous snapshot, 62.5ns wide
      burst-capture two ports back-to-back at 7 cycles/sample = 437ns
        (capture_burst() in mod_root.c, already written and proven)
      timestamp with Timer1 at 62.5ns resolution; Input Capture measures
        a pulse width directly
      hold maybe 3-4KB of samples => on the order of 1ms of capture

    MIND WHICH PORT. PINA..PING are low I/O and reachable with `in`
      (1 cycle). PINH, PINJ, PINK and PINL are EXTENDED I/O on the 2560
      and need `lds` (2 cycles), so a two-port burst touching them costs
      about 8.75 cycles = ~547ns per sample instead of 437ns. Still ample:
      the shortest thing any block asserts is a one-T END pulse at 977ns,
      and any pulse at least as long as the sample period yields at least
      one uniform sample. But do not put a fast-moving signal on PL and
      then quote root's 437ns figure.

    IT CANNOT
      see a decode glitch. An LS '138 output can glitch for 10-30ns; the
        Mega's sample period is 437-547ns. It will MISS the event outright
        or alias it. This matters because decode glitches are the exact
        fault we brought the LA in to hunt.
      see anything analog. No edge quality, no ringing, no marginal level.
        A pin sitting at 2.0V reads as a clean HIGH.
      trigger on a fault. No pulse-width or runt trigger — you cannot ask
        it to "show me the glitch," only to sample blindly and hope.
      capture two ports truly simultaneously (separate instructions, ~60ns
        of skew — usually fine, not always).

    ORDER OF USE: rig first (cheap, exhaustive, catches gross faults).
    Mega burst-capture second (free, already wired, confirms sequence).
    LA third (when sequence looks right but timing must be proven).
    Scope last (when the LA shows something strange or a level looks soft).

### Scope / LA bench rules — read before probing

    1. SHORT GROUND. Use the ground spring, not the long clip lead. On a
       breadboard a 6-inch ground lead manufactures ringing that is not
       in the circuit, and you will chase it for an hour.
    2. TRIGGER ON THE FAULT, DO NOT EYEBALL IT. A 20ns glitch is invisible
       on a slow sweep. Set a pulse-width or runt trigger and let the
       instrument find it.
    3. PROBE THE CHIP PIN, NOT THE SLOT. A slot proves the wire; the pin
       proves the chip got it.
    4. x10 probe for anything you care about the edge of. x1 loads the
       node enough to change what you are measuring.
    5. The rig and the LA can share the board. The rig drives, the LA
       watches — they do not conflict, and a rig-driven walk is a
       repeatable stimulus for LA capture. Use that.

---

## BLOCK 1 — CONTROL (root + microcode + control_word)

The finickiest boards on the machine, and the ones with no datapath
dependency at all. Nothing downstream can be trusted until the control
unit says the right thing at the right time.

### BLOCK TOOLING — DONE 2026-07-30

This section used to read "none of this exists yet, build it before
wiring". It is built, and the whole ladder was wired against it.

`kicad_contracts.py` carries a `BLOCKS` table and derives each block's
surface from the netlist under THE BLOCK LAW above: COPPER / DRIVE /
STRAP / SAMPLE, with `retire` and `strap` as dicts that must NAME the test
that earned the retirement. It hard-errors rather than guessing — unknown
member, a retirement naming a signal the block does not have,
`sample_anyway` on a non-copper net, driving copper, a pin collision, or
an unfed input it cannot classify. `pins block1`..`pins block5` print the
hookup table the bench actually wires against, straps first.

Host tests are in `docs/notes/test_kicad_blocks.py`, and they assert the
LADDER SHAPE as well as the contents: driven 8,8,0,0,0 and sampled
31,15,15,15,15, so the shape cannot drift back silently.


### Wiring — 8 driven, 31 sampled, 39 jumpers + GND

Y1 STAYS IN ITS SOCKET. The machine free-runs at 1.024MHz for this and
every later block. RESET is the physical button on an `ARM ...` prompt.

`pins block1` prints a [board] tag on every line — with three boards on the
bench the ribbon has to reach the right one, and the tag is NOT always the
producer: END/HALT land on ROOT at U61 (the consumer end, strike-7), while
SA/PC_UP/PC_MAR_MUX land on MICROCODE at U15. Breakout-strip slot numbers are
looked up against that owning board, since slot maps are per module and a
block has none of its own.

RIG DRIVES (series R in every one):

    A8-A15   IRB0-7    U16.2 .4 .6 .8 .11 .13 .15 .17

That is the whole drive list. Note the 1A/2A split on the '244 — the pins
are NOT monotonic.

RIG SAMPLES — grouped BY PORT, because capture_burst() reads whole ports
and a group split across two ports cannot be read coherently:

    PF   A4  T0           U6.14       SAMPLE LABEL — see below
         A5  T1           U6.13
         A6  T2           U6.12
         A7  T3           U6.11

    T0-3 IS SAMPLED AS A LABEL, NOT AS AN ASSERTION. root.tstates still owns
    the counter. Reading T means EVERY SAMPLE CARRIES THE T-STATE THAT
    PRODUCED IT, so the rig never has to infer t from position in a captured
    sequence. That inference cost an entire bench evening: it required the
    fetch frame to be unique, and in the SRC pass it is not (LDA's T0/T1/T2 are
    all mux_pc+pc_up+src=ROM and differ ONLY in DST), and it broke whenever a
    single T-state happened to get no sample. Four sampled wires make both
    failure modes structurally impossible. Driven is unchanged, so the gate
    holds. Rico proposed this shape at the outset — settle, sample, check,
    move on — and the free-running clock is the only reason it was not built
    that way first.

    PL   D49 CLK          U27.5       CAPTURE QUALIFIER — samples taken
                                     while CLK is HIGH are DISCARDED (the
                                     ROM access window). Not an assertion.
         D48 SA2          U15.12      anchor port, read in EVERY pass
         D47 SA1          U15.13
         D46 SA0          U15.15
         D45 END          U61.3       <- consumer end, not U15.16
         D44 PC_UP        U15.17
         D43 PC_MAR_MUX   U15.18
         D42 HALT         U61.5       <- consumer end, not U15.19

    PA   D22 ~{REG_A_LOAD}    U30.14  dst group, 7 bits
         D23 ~{REG_B_LOAD}    U30.13
         D24 ~{REG_C_LOAD}    U30.12
         D25 ~{MAR_LO_LOAD}   U30.11
         D26 ~{MAR_HI_LOAD}   U30.10
         D27 ~{IR_LOAD}       U30.9
         D28 ~{RAM_LOAD}      U30.7

    PC   D30 SRC_ACTIVE       U28.15  src group, all 8 bits in ONE port
         D31 ~{ROM_OUT}       U28.14  so control.onehot is coherent in a
         D32 ~{RAM_OUT}       U28.13  single read
         D33 ~{REG_A_OUT}     U28.12
         D34 ~{REG_B_OUT}     U28.11
         D35 ~{REG_C_OUT}     U28.10
         D36 ~{ALU_OUT}       U28.9
         D37 ~{SW_OUT}        U28.7

    PF   A0  ~{PC_CLEAR}      U29.14  jmp group
         A1  ~{MDR_OUT}       U29.11
         A2  ~{REG_OUT_LOAD}  U29.9
         A3  ~{PC_LOAD}       U62.10

    THREE BURST PASSES: (PL,PA) dst, (PL,PC) src, (PL,PF) jmp.
    IRB is held across all three and the machine repeats, so the passes
    are comparable. PL is extended I/O — ~547ns/sample, not 437ns.

BOARD STRAP (not a rig wire):

    FLAG_Z   HIGH, 1k to +5V, at U62.3.
             COND_TAKEN = NOR(~{COND}, FLAG_Z), so FLAG_Z high pins
             COND_TAKEN low and ~{PC_LOAD} = NOR(COND_TAKEN, PC_LOAD_JMP)
             can then only be pulled by a real JMP decode. The milestone
             program has no JMP or JNZ, so ~{PC_LOAD} must stay HIGH for
             the whole run. STRAPPING LOW IS THE DANGEROUS CHOICE: a
             spurious ~{COND} would take a branch into a garbage MAR.
             1k rather than a hard tie so a strap forgotten at Block 4
             meets U49.5 as a 5mA pull, not a short.

COPPER YOU MUST PHYSICALLY WIRE (rig never touches these):

    T0-3     U6.14 .13 .12 .11  ->  U17.2 .4 .6 .8
    CW0-8    U9.11 .12 .13 .15 .16 .17 .18 .19 + U15.11
                                ->  U30.1 .2 .3, U28.1 .2 .3, U29.1 .2 .3
    END      U15.16 -> U61.3
    HALT     U15.19 -> U61.5

WHY NO CW0-8 PROBES. Beyond the block law: the 19 sampled control_word
outputs are an INVERTIBLE encoding of CW0-8 for every word microcode_gen
actually emits. U28.O0 is wired (SRC_ACTIVE) so all 8 SRC codes read
back; U30 code 0 reads all-high and is unambiguous; U29's only aliased
codes are 5 and 7 and MISC never emits either. CW9-15 are separately
sampled. So CW0-15 is fully reconstructible with zero CW0-8 wires.

### Tests (control.*)

The stimulus is the same for all of them: force IRB, let the machine
free-run, burst-capture, decode offline.

    decode     Cut the captured stream at each END. The frame after a cut
               is t=0 and POSITION WITHIN THE RUN IS t. Compare the run
               against MC_REAL_WORDS[(op<<4)|t] for t=0..END.
               This asserts ORDER AND RUN LENGTH, not just contents — a
               wrong END row or a skipped state fails here, and a per-T
               lookup would miss both. T0-3 is NOT sampled; it is copper.
               The model is a CHECKER, not a driver — see below.
    onehot     Never two SRC enables low at once, never two DST loads at
               once. All 8 SRC bits are on PC so one read decides it.
               The rig catches SUSTAINED overlap only; the transient is
               the scope's job.
    seq        Force HALT's opcode: the run freezes and never resumes.
               RESET (button) recovers. The old INT-D.
    stability  Repeat the walk N times, assert identical results.

    control.cond IS DELETED. control_word.truth already swept FLAG_Z both
    ways against the real U62 at module level. Re-driving it here would be
    a passed module test with more wires — precisely what the block law
    exists to stop. Branch coverage stays retired to control_word.truth.

### Scope / LA check — ONE, two probes

Everything else Block 1 asks is a logic-value question the Mega answers.
This is the one it structurally cannot:

    2ch    ~{ROM_OUT} (U28.14) and ~{RAM_OUT} (U28.13), trigger BOTH LOW.
           Characterise the decode glitch: after T changes on the CLK
           rising edge the microcode ROM outputs are invalid for one
           access time and U28 decodes that garbage into transient
           enables. Measure WHETHER, HOW WIDE, and on which transitions.
           The Mega samples at 437-547ns and has no pulse-width trigger,
           so it cannot see a 10-30ns event at all.

           THIS IS A SUPPLY MEASUREMENT, NOT A CORRECTNESS ONE. See
           "Machine invariant: EVERYTHING COMMITS ON CLK LOW" — no
           state-changing path is reachable during CLK high, so the worst
           case is two drivers fighting: current spike and supply noise,
           never wrong data.
           In BLOCK 1 it is harmless in the strongest sense — no datapath
           boards are wired, so the '138 outputs go to rig sample pins and
           there is literally nothing to fight. Best possible place to
           measure it.
           ACT ON IT only if the supply misbehaves. Do NOT gate the '138s
           pre-emptively.

    1ch    REACTIVE ONLY. Any strobe whose HIGH looks soft. Breadboard
           runs plus fan-out can leave an enable at a level that reads as
           valid to the Mega and is marginal to a real gate.

CLK vs T0, T(last) vs END, and the ~{IR_LOAD} window are NOT here. The
first two the Mega gets at 1.024MHz; the third is meaningless until the
full Block 5 load exists.

### BENCH RESULT 2026-07-30 — 6/6 PASS

    block1.frames      diagnostic, textbook: (60,5F) (70,7E) alternating
    block1.opmap       17/17 — the complete implemented opcode map
    block1.decode      29043 samples, 0 mismatches, 0 TRANSIENTS
    block1.onehot      no sustained SRC or DST overlap
    block1.seq         T freezes on the HALT row; RESET clears T to 0
    block1.stability   per-T table identical across 8 repeats

THE DECODE GLITCH DID NOT PRODUCE A SINGLE BAD SAMPLE in 29043 reads. That is
a measurement, not a prediction: gating the capture on CLK LOW rejects the ROM
access window completely. It does NOT retire the scope check below — the rig
samples at 437ns and cannot see a 10-30ns event at all, so "zero transients"
means the glitch never reaches a sampling instant, not that it does not exist.

ONE HARDWARE FAULT, RIG-SIDE: the IRB ribbon was reversed end-for-end, bit N
landing on bit 7-N. 0x00 and 0xFF are the only bit-reversal-invariant bytes,
so HALT=0xFF masked it entirely and block1.seq passed for hours while nothing
decoded. block1.opmap is the asymmetric probe that named it, which is why it
now runs BEFORE decode.

### What Block 1 retires

    microcode ROM content EXECUTED for the first time (only the SA field
      was previously proven, via alu.ops at the real '382s)
    the tap runs from ROM to decoder
    decode correctness in copper, at speed
    END / HALT / T-state contract with the real ring counter
    enable overlap — never tested at any level before now

---

## BLOCKS 2-6 — the accretion

Each row is one wiring session. The rig only ever sheds. END and HALT
stay on D45/D42 at U61.3/U61.5 throughout and are never re-landed.

### BLOCK 2 — + pc + mar + memory      (driven 8, sampled 15, 23 jumpers)

    modules: root, microcode, control_word, pc, mar, memory

    KEEP   PL0/D49 CLK, PF4-7/A4-A7 T0-3      the STANDING TIMING SET
           PL4/D45 END  U61.3, PL7/D42 HALT   U61.5
           A8-A15  IRB0-7 driven -> U16.2 .4 .6 .8 .11 .13 .15 .17
    OFF    PL1-3 SA, PL5 PC_UP, PL6 PC_MAR_MUX
           PC0-7  the 8 SRC strobes
           PF0-3  the jmp group
    ON     PA0-7 / D22-D29  MDR0-7  <- U19.18 .17 .16 .15 .14 .13 .12 .11

    NOTE PA0-6 held the DST strobes in block 1 and now hold MDR on the MEMORY
    board — same Mega holes, different board, different signals. Re-land all
    eight, do not assume the ribbon can stay put.

    WHY MDR IS ON PA AND NOT ITS USUAL PF: so that PF4-7 remains T's home in
    EVERY block. CLK and T0-3 are worth more as five wires that never move
    than MDR is as a bus-rule default.

Three boards for free. M0-15 becomes copper between PC/MAR and memory,
and every strobe already comes from the real decoder — so 26 sample wires
come off and 8 go on.

    OFF    the 26 control/microcode sample wires
    ON     A0-A7  MDR0-7   U19.18 .17 .16 .15 .14 .13 .12 .11
    KEEP   A8-A15 IRB0-7 driven; D45/D42 END/HALT

    STRAPS, both removed at Block 3:
      WRITE_DIR -> GND at U51.1. Forces ~{RAM_WRITE_EN} = NAND(0,~CLK) = 1
        so no write ever fires, while ~{RAM_MDR_EN} = ~{RAM_OUT} keeps RAM
        reads working. FLOATING IT IS A LIVE HAZARD: it also sets the U21
        '245 direction, and a floating HIGH gives a real RAM write every
        clock low into whatever W is floating at.
      W0-7 -> 10k PULLDOWNS at U55.3 .4 .7 .8 .13 .14 .17 .18. NEVER a
        hard tie — U25 drives this bus from Block 3 and a hard tie meets a
        real driver.

    TEST   The bytes appearing on MDR0-7 are the ROM image IN ADDRESS
           ORDER, because a real PC drove a real MAR drove a real ROM.
           Checked against progrom_expect.h.

    RUN PROG_diag.bin FIRST. diag_byte = ((addr*0x9D)^(addr>>5))&0xFF is
    injective over the first 32 addresses, so every fetched byte NAMES ITS
    OWN ADDRESS. MDR0-7 is the only address witness in this block (M0-15
    is copper), and the real image's 0xFF safe-fill tail names nothing.
    Then re-run on PROG.bin.

    HONEST SCOPE. This block does NOT prove "PC -> MAR -> ROM". With no W
    driver present, ~{MAR_LO_LOAD}/~{MAR_HI_LOAD} latch garbage — LDA,
    STA, JMP and JNZ reach MAR only through the absent U25 bridge. What it
    proves is the PC_MAR_MUX handoff on M and the ~{RAM_EN} = INV(M15)
    decode.

    BENCH RESULT 2026-08-01 — 2/2 PASS
      block2.dump    diagnostic: MDR by T-state, four distinct addresses
                     inside one LDA
      block2.fetch   ADDRESS ORDER proven from inside one instruction —
                     LDA's T0/T1/T2 read PC, PC+1, PC+2, consecutive BY
                     CONSTRUCTION, captured from a fixed-interval burst and
                     matched against the DIAG image at 0x0838 and 0x1943 on
                     two runs

    THE FAULT WAS END AND HALT NOT YET WIRED. Without them T never cleared,
    the PC never advanced between instructions, and the fetch byte was
    constant. They are copper in this block (U15.16->U61.3, U15.19->U61.5)
    and they are easy to forget because block 1 SAMPLED them at U61 without
    needing the ROM-side run to exist.

    ADJACENCY MUST COME FROM A BURST. Three rig attempts failed here: assuming
    successive fetch samples were one instruction apart (at ~21% yield they
    are 2-3 apart), then requiring two consecutive POLLED successes (the poll
    loop is ~15-19 cycles against a 977ns clock, so the phase drifts and a
    success is almost never followed by another). A burst samples at a FIXED
    interval, so consecutive buffer entries are consecutive in time by
    construction.

    SCOPE/LA   PC_MAR_MUX vs M0 — the tri-state handoff, strike-6
               territory. BAD TRACE: any overlap where PC and MAR both
               drive M.

    NAMED GAP — MAR IS NEVER PROVEN AS A LATCH ON THIS LADDER.
    LDA, STA, JMP and JNZ are the ONLY instructions that load MAR
    (MAR_LO at T1, MAR_HI at T2). The milestone program is
    LDAI 0x2F; LDBI 0x1E; ADD; OUT; HALT and contains NONE of them. So MAR
    spends every block in PC_MAR_MUX passthrough, forwarding the PC to M.
    It is proven as a MUX and never as a LATCH, at block 2, 3, 4, 5 or 6.

    This is NOT resolved by a later block. Block 3 makes the path
    electrically live (W becomes copper through the U25 bridge) but no
    instruction in the image ever walks it.

    MAR's latch stays retired to mar.logic / mar.hold, which are real
    module tests but RIG-DRIVEN ones — the ladder never upgrades them to
    copper.

    CLOSING IT COSTS A TL866 MINUTE AND ZERO WIRES: a second image
    containing a JMP self-witnesses through the opcode stream, because
    JMP is (T1 MAR_LO<-ROM, T2 MAR_HI<-ROM, T3 PC_LOAD). MAR latches the
    target through the real bridge, PC loads from MAR, and the next
    opcode fetched is at the target — visible on IRB0-7, which block 3
    ALREADY SAMPLES. A wrong MAR diverges the instruction stream
    immediately. A STA/LDA round-trip through RAM is the other witness
    and lands on OB.
    Earliest block is 3, not 2: MAR is loaded src=ROM, so the byte's path
    is ROM -> MDR -> U25 -> W -> MAR, and the bridge is on the mdr board.
    No program can make MAR latch a real byte at block 2.

    See docs/notes/dino_isa_for_basic.md for the instruction detail.

### BLOCK 3 — + mdr                    (driven 0, sampled 10, 10 jumpers)

DRIVEN GOES TO ZERO. The IR is real, the machine fetches its own
instruction bytes, and IRB0-7 stops being forced.

    OFF    A0-A7 MDR0-7
    FLIP   A8-A15 IRB0-7 stay in the SAME HOLES at U16 and change from
           rig output to rig input. Leave the series resistors in: they
           are harmless on a sampled line and they are the only thing
           between a stale bundle and U34 driving into a rig output.
    KEEP   D45/D42 END/HALT
    REMOVE the WRITE_DIR and W0-7 straps BEFORE landing the mdr board.
           U37.4 is a '04 output; a hard GND strap on it is a dead short.

    SAMPLE IRB AT T1, NOT T0. U34 is a 74LS373 — a TRANSPARENT LATCH, not a
    register — and LE_IR = NOR(CLK, ~{IR_LOAD}) at U22 gate 1, so it is open
    only while CLK is LOW during T0, the one T-state asserting IR_LOAD:
        T0, CLK high   latch closed   IRB = the PREVIOUS opcode
        T0, CLK low    latch OPEN     IRB follows W, the new opcode
        T1..Tn         latch closed   IRB = the current opcode
    So IRB changes MID-T0. An unqualified read there returns the previous
    instruction's opcode about half the time and looks like random corruption.
    At T1 the latch is shut and holds the current opcode unambiguously, needing
    no CLK qualification — and every instruction has a T1, the shortest being
    fetch plus an END row.

    WHY SAMPLE IRB AT U16 (the consumer end): it is the MIRROR-WITNESS for
    the U25 bridge. Block 2 read that same byte at MDR, BEFORE it crossed
    U25 and U34. A bridge or IR permutation that a MDR-side read cancels
    out shows up here and nowhere else.

    TEST   The IRB opcode stream is 0x11 0x12 0x41 0x51 0xFF, with PC
           stride 2,2,1,1,1 derived from PC_UP counts in the burned
           microcode — no new table. Block 2 forced IRB constant, so the
           stride was constant and an instruction-length error was
           invisible; here a wrong length desyncs the very next fetch.

    SCOPE/LA   BUS_DIR (U39.8) vs ~{MDR_EN} (U22.4) on the U25 bug-4 chip.
               Direction must settle BEFORE the bridge enables. BAD TRACE:
               ~{MDR_EN} falling while BUS_DIR is still moving = a
               momentary fight across the W/MDR boundary.

    EXPECTED, NOT A FAULT: during ADD's T1, src=ALU asserts ~{ALU_OUT},
    BUS_DIR flips to W->MDR, and U25 drives MDR from a floating W (no ALU
    board yet). Nothing else drives MDR in that window, so it is
    indeterminate data, not a fight. Same during OUT's T1.

### BLOCK 4 — + registers + alu        (driven 0, sampled 10, 10 jumpers)

The full datapath. FIRST BLOCK THAT COMPUTES THE SUM.

    OFF    A8-A15 IRB0-7
    ON     A8-A15 OB0-7   U35.2 .5 .6 .9 .12 .15 .16 .19
                          (the '373 zigzag — count chip pins, not header
                           order)
    KEEP   D45/D42 END/HALT
    REMOVE the FLAG_Z strap. U49.5 (flag register Q1) drives U62.3 now,
           and leaving the strap is a '273 output into a board tie.

    TEST   Exactly 6 END pulses (LDAI, OUT, LDAI, LDBI, ADD, OUT), then
           HALT high forever and END never again — HALT's row is 0x8000
           and carries no END bit. OB reads PR_EXPECT_SUM = 0x4D onward.

    MIRROR-WITNESS: bit-reverse(0x4D) = 0xB2 and nibble-swap(0x4D) = 0xD4,
    so a flipped OR transposed OB ribbon self-names. Every coverage answer
    is chosen this way; most bytes are not self-witnessing.

    U35 HAS NO RESET, and a POWER CYCLE DOES NOT HELP — the machine
    free-runs at power-up and parks on its own answer, so OB always
    already holds it. This is solved in the PROGRAM, not the test: the
    leading LDAI 0xFF; OUT poisons OB, so any run that STARTS destroys the
    previous answer and OB can only read 0x4D if this run reached the
    second OUT. block4.stepped watches that 0x4D -> 0xFF -> 0x4D
    transition and asserts it. The old INCONCLUSIVE note is gone; it fired
    on every single run and told the operator nothing.

    SCOPE   CLK (U27.5) vs LE_TMP_A (U50.1). LE_TMP_A = NOR(~{REG_A_LOAD},
            CLK) must open for the full CLK-low half. BAD TRACE: a window
            narrower than the '373 needs, a runt, or one that never opens
            on ADD's T1.

### BLOCK 5 — + io                     (driven 0, sampled 15, 15 jumpers)

All ten boards. NOT single-stepped — see NOTHING IS EVER PULLED above.

    MOVE   OB0-7 from U35 to the io end: R9-R16 pin 1. Same Mega pins.
           Far-end tap, because that harness is what this block adds.
    KEEP   D45/D42 END/HALT

    STRAP  IS0-7 = SW1 at 0xF7 (switch 3 closed, rest open). Switches are
           10k pulled up and short to GND, so there is no driver to fight.
           0xF7 is chosen as a WITNESS: ~{SW_OUT} never asserts in the
           MILESTONE program so the '244 must stay off, and its only 0-bit
           is W3 — a bit the answer 0x4D also sets. A leaking '244 turns
           OB into 0x45 and names itself. Re-run at 0xFF as the control;
           the answer MOVING between the two settings is the leak.

           NOTE: with PROG_in seated the '244 is supposed to drive, and
           SW1 becomes an operand rather than a leak witness. See below.

    TEST   The milestone end to end across all ten boards: 6 ENDs, HALT,
           OB = 0x4D, stable for a full second of re-polling.

    NO SCOPE WORK HERE. Every question is a logic value at 437-547ns
    granularity. Save the probe budget for the IN work.

### BLOCK 6 — DROPPED 2026-08-02

The ladder ENDS AT BLOCK 5. Block 6 was to be the same ten boards with
the END jumper pulled — 9 wires — reset ten times for ten sums. It was
dropped because it adds no board and no coverage, only repetition:
blocks 4 and 5 already free-run at 1.024MHz with Y1 seated and produce
0x4D, so timing is retired. Driving the machine INTERACTIVELY from SW1
through the IN instruction is a stronger acceptance than running one
fixed program ten more times.

The instrument work it carried still stands and is not blocked by
anything: 2ch CLK (U27.5) vs ~{REG_A_LOAD} (U30.14) is the longest
control path — CLK rise through the '163, the '244, EEPROM tACC
150-250ns and the '138 decode, all inside the 488ns CLK-high half or
the ADD never commits. And 1ch OB3 (U35.9) VOH, an LS373 rated -2.6mA
sourcing 4-5mA through a 330R LED.

### Old names, for cross-reference

    INT-A  -> Block 1 (control.decode)
    INT-D  -> Block 1 (control.seq — A and D share a wiring, so merged)
    INT-C  -> Block 2
    INT-B  -> DELETED. It emulated the U25 bridge; Block 3 keeps it real.
    INT-B2 -> Block 3
    INT-E  -> Block 5

### Program image

The burned REAL image is the milestone: LDAI 5; LDBI 3; ADD; OUT; HALT.
Test against what you will actually free-run, so Block 5 is a true dress
rehearsal.

BRANCH COVERAGE IS RETIRED TO control_word.truth, which swept FLAG_Z both
ways against the real U62 at module level and proved both arms. An earlier
draft of this file assigned that job to a Block 1 test called control.cond;
THAT TEST IS DELETED — re-driving FLAG_Z at block level would be a passed
module test with more wires, which is exactly what the block law forbids.

The countdown/JNZ image stays available, a TL866 minute away, whenever a
full-program branch test is wanted. Note what that would buy that
control_word.truth does not: the branch arms exercised by a REAL microcode
row with a REAL flag from the ALU, rather than by a rig-forced bit. That
is a Block 4-or-later question, and it is not owed by the milestone.
