# CLAUDE.md — DINO (Discrete Integrated NISC Operator)

An 8-bit CPU built from discrete 74-series logic on breadboards, designed
in KiCad, and brought up module-by-module with a bare-metal ATmega2560
test rig. Split out of the `hardware` portfolio repo on 2026-07-28 with
full history (138 commits) preserved.

## Working rules — these override default behaviour

1. **NEVER commit or push without an explicit ask.** This is a bench
   machine; Rico commits when Rico decides.
2. **Milestone gate — SATISFIED 2026-08-02.** The rule was: no ISA or
   hardware extensions until the whole machine adds two numbers. It does,
   free-running, and it now adds a number handed to it on the switches.
   The gate is open; extensions are on the table. Keep the habit that made
   it work — one capability at a time, netlist first, host test RED first.
3. **TDD.** Host-testable logic gets a host test FIRST, RED before GREEN.
   On the bench, RED/GREEN is the hardware itself.
4. **Rico burns the ROMs** (TL866). The rig verifies; it never programs.
5. **Netlist-verify before encoding.** Never write an assertion from a
   reading of the schematic — extract the gate equation first. And when a
   question about wiring comes up, RUN THE TOOL, don't reason from memory:

       python3 -c "import sys;sys.path.insert(0,'docs/notes');\
       from kicad_netlist import build_report;\
       print(*build_report('dino_v0_0_2/program_counter.kicad_sch')[0],sep='\n')"

   This is authoritative and takes two seconds. Reasoning about the design
   from memory has been wrong more than once.
6. **`avr-gcc -Werror` clean is the verification you can do.** The bench
   run is Rico's.

## State as of 2026-08-04

**THE MACHINE RUNS.** All ten modules bench-proven, all five integration
blocks bench-proven, and the ISA has its first interactive instruction.
Coverage lint: 0 gaps, 0 pending. Stage 1 (rig self-test) is CLOSED as a
diagnostic, not a gate.

The milestone program is burned and seated:

    LDAI 0xFF; OUT; LDAI 0x2F; LDBI 0x1E; ADD; OUT; HALT   -> OB = 0x4D

The leading `LDAI 0xFF; OUT` POISONS OB. U35 has no reset and the machine
free-runs at power-up, so OB always already holds the previous answer and
a power-cycle does not clear it — the program destroys the old answer
itself, and OB can only read 0x4D if THIS run reached the second OUT.

`PROG_in` replaces the second addend with SW1 through the io '244. Bench
confirmed across settings: SW1=0x01 gives 0x30, SW1=0x1E gives 0x4D.

**Timing is RETIRED.** Blocks 4 and 5 free-run at 1.024MHz with Y1 seated.
"Works single-stepped, fails free-run" was the signature to watch for; it
never appeared.

**THE WHOLE ISA HAS EXECUTED — 2026-08-04.** Every coverage ROM is green:

    mardisc  0x6B   MAR discriminates two DIFFERENT addresses
    pads     0x40   PC_LOAD lands exactly on target
    mem      0xC5   MAR as a latch, RAM round trip
    flow     0x39   JMP lands; SUB sets FLAG_Z; JNZ correctly declines
    alu      0x39   all eight SA codes, chained non-maskingly
    loop     0x15   JNZ TAKEN arm x3, two live RAM cells, flags held across
                    STA, exact iteration count (3 x 7 = 21)
    PROG     0x4D   the milestone
    cylon    ---    never halts. The victory lap, and a real soak test.

`LDA`/`STA`/`JMP`/`JNZ` and seven of the eight ALU codes had never executed
before that day. Only `LDCI` and `NOP` remain unrun, both unreachable by
design — C is write-only until `MOV` exists.

**What it cost: two board-to-board runs, nine wires, never landed.**
`~PC_LOAD` -> `U11.19`/`U12.19`, and `W[0..7]` -> `U55`/`U58` D pins. Nothing
was broken; two things were absent. Full post-mortem in
`docs/notes/dino_mar_lo_investigation.md`, and the process finding is this:

> **A COPPER wire is driven by no test and sampled by no test. The wire
> between two proven modules is checked by nothing.**

Module tests drive those nets from the RIG's own pins, so the board-to-board
run is never needed and cannot fail. The block ladder classifies them as
COPPER and never samples them. `kicad_contracts.py` already emits the exact
per-sheet crossing list — **that list IS a continuity checklist** and nothing
makes anyone walk it. Same blind spot covers bare same-chip jumpers
(`CLK` at `U60.3<->U60.6`, `HALT` at `U61.5<->U61.6`).

And `PROG_mem` passed throughout, because it stores and loads through ONE
address (`0x8000` — bit 15 alone) and is therefore blind to what that address
actually was. `PROG_mardisc` exists to ask that question and belongs BEFORE
`PROG_loop` in every future run.

**TWO OPEN ITEMS, neither blocking.**

1. **HALT does not HOLD.** The machine halts, then escapes after a few
   seconds, varying. `CET` on the '163 is sampled every clock, so one escape
   in a few million clocks is a marginal level, not logic. Only visible on
   `PROG_flow` — every other image has `0xFF` fill past its HALT, so an escape
   just re-halts.
2. **Marginal levels.** `W` 2.26V, `PC_MAR_MUX` 1.0V avg, `MAR3` 3.22V. The
   fan-out gate, arriving early. No instrument in the kit reports it as a
   failure — the LA reads 2.26V as a clean 1. Item 1 may be its only visible
   symptom, because the halt is the one state where noise margin shows.

**NEXT: an assembler** (Rico is writing it mostly by hand), then Phase 2 —
mounting/boxing and the move to cards. Re-running blocks 1-5 plus the full
coverage set after the move is the acceptance FOR the move.

**What remains after that:** the roadmap, in Rico's stated order — minimum work to
reach the 16550 UART so DINO can talk to a terminal, then a proto-Monitor,
then the wider ISA. `IN` is the front half of I/O; `OUT` to a UART data
register instead of the LEDs is the back half, and the I/O decode '138 is
what it needs. Nothing is blocking it.

**Read `tests/dino_bringup/BRINGUP.md` first.** It is the bench bible:
per-stage wiring, commands, expected output, failure meanings, and the
integration plan. `tests/dino_bringup/README.md` has the progress
checkboxes. `docs/notes/dino_test_bringup_design.md` is the spec.

## Integration is CONTROL FIRST, BLACK-BOX, and LOW-WIRE

**The block law (2026-07-28).** Blocks are black-box tests. Module
coverage is already extensive, so a block that re-samples what a module
test retired is just a module test with more wires and more ways to be
wrong.

> **Sample a signal at block level only if its value depends on more than
> one member of the block.**

Four categories, all derived from the netlist, none hand-written:

    COPPER  out of one member AND in of another -> DROPPED, wired
            board-to-board, rig never touches it
    DRIVE   in of a member, out of none, needed as stimulus -> rig drives
    STRAP   in of a member, out of none, NOT needed -> tied on the board
    SAMPLE  out of a member, not copper, not already retired

Every retirement must NAME the test that earned it.
Accepted exception: END/HALT are copper but sampled in every block —
nothing else segments the instruction stream or sees the freeze.

**Driven-wire count is the gate and may never go up.** Risk is asymmetric:
a wrong SAMPLED wire is a false FAIL, a wrong DRIVEN wire can fight a real
driver, and a wrong driven STROBE is worst because strobes are ENABLES.

**Keep real what is expensive** (alu, registers, bus sharing, the U25
bridge, memory decode). A rig stand-in is dangerous exactly when it is
BETTER than the hardware — schematic bug 4 was a bridge defect a
rig-emulated bridge passes clean.

    BLOCK  ADDS                          DRIVEN  SAMPLED  JUMPERS
    1      root+microcode+control_word      8       27     35+GND
    2      + pc + mar + memory              8       11     19+GND
    3      + mdr                            0       11     11+GND
    4      + registers + alu                0       11     11+GND
    5      + io                             0       11     11+GND

CLK is sampled in blocks 1-5 as a CAPTURE QUALIFIER (root.clock still owns it
as an assertion): the microcode ROM outputs are invalid for one access time
after T changes, and a blind sampler splits one T-state into several frames.
Sampled, so driven is unchanged.

Driven hits ZERO at Block 3 when the real IR fetches the machine's own
instruction bytes. From there the rig cannot fight anything by
construction. END/HALT are the same two wires (D45/D42, tapped at
**U61.3/U61.5**, the consumer end) in every block.

An earlier datapath-first plan was inverted on 2026-07-28 for the
wire-count reason. Don't re-propose it.

**NOTHING IS EVER PULLED — but rig jumpers come off freely.** Chips and
board-to-board copper are never touched; Y1 stays seated from Block 1 to
Block 5. Rig jumpers are removed as they retire — that IS the ladder.
Temporary board straps (`WRITE_DIR`, `W0-7`, `FLAG_Z`) must come off when
real copper takes over the net, or a real driver meets a tie.

**Two clock modes, and each test must say which it needs.** `CLK` is
U27.5 and `RESET` is U27.9, both '74 totem-pole outputs, so the rig can
never inject there. The one non-contending point is `CLKIN` at **U20.2**,
the divider input, reachable only with Y1 disabled at its EN pin. That
gives:

    FREE-RUN     Y1 in, CLKIN jumper off   block4.milestone, block5.run
    STEP-CLOCK   Y1 out, CLKIN on U20.2    block3.clocked, block4.stepped

The bench alternates between them, so arriving in the wrong one is the
NORMAL case, not an error. Both directions are guarded and each names its
own repair. The discriminator is not "does CLK move?" — a live Y1 moves it
for you, which is how a step test once reported success while the machine
free-ran past every sample. It is **"does CLK hold still when I stop
asking?"** Free-run tests check the opposite: CLK must show both levels.

The machine is fully static (the '121 one-shot is gone), so the clock can
stop indefinitely. Free-run tests are burst-capture-and-decode; reset is
the button on an `ARM` prompt, and no press has to be fast.

## The machine invariant (do not re-derive)

**Everything that changes state is clock-qualified and commits on CLK
low.** Register/IR/MAR/ALU loads via `NOR(~LOAD, CLK)`; RAM write via
`NAND(WRITE_DIR, ~CLK)`; PC load via `NAND(PC_LOAD, ~CLK)`; PC clear via
`NOR(~PC_CLEAR, CLK)`; PC count via `NAND(PC_UP, ~CLK)`; T-state clear and
hold via the '163's SYNCHRONOUS clear and CET. Bus output enables are
ungated, correctly.

**Consequence:** a microcode decode glitch is a SUPPLY question, never a
CORRECTNESS one — nothing state-changing can be reached during the ROM
access window. Do NOT gate the '138s pre-emptively. Full table in
BRINGUP.md, "Machine invariant: EVERYTHING COMMITS ON CLK LOW".

## Three instruments, three questions

- **Rig** answers WHAT — exhaustive logic and topology, but rig speed only
  (`settle()` is 5us). It CANNOT see timing. Ever.
- **DSLogic LA** answers WHEN — 16ch at real speed. Enable overlap,
  one-hot T, END→T clear, decode glitches.
- **Scope (Siglent SDS)** answers HOW — analog. Edge quality, ringing, and
  levels that read as a clean HIGH to the Mega while being marginal to a
  real gate.

The Mega can stand in as a first look (`PINA` is a true 8ch 62.5ns
snapshot, ~3 MSa/s burst, Timer1 input capture at 62.5ns) but cannot catch
a 10-30ns decode glitch at a ~300ns sample period, sees nothing analog,
and has no pulse-width trigger. Order of use: rig, Mega burst, LA, scope.

## Everything is generated, nothing is retyped

    docs/notes/kicad_contracts.py   contracts + pinmap from the netlist
                                    (PIN_ASSIGN = bench-pinned overrides,
                                     PIN_PROBES = rig-internal probes)
    docs/notes/microcode_gen.py     microcode ROM images + CRCs + header
    docs/notes/progrom_gen.py       program ROM (DIAG + milestone program)
    docs/notes/layout_gen.py        breadboard placement, slot maps,
                                    wiring guides, layout pages
    docs/notes/kicad_netlist.py     build_report() — the netlist oracle
    docs/notes/coverage_lint.py     asserts every contract signal is tested

Host tests sit next to each (`test_*.py`), plus C model tests in
`tests/dino_bringup/hosttest/`. Run them all before believing anything.

## Hard-won rules, each paid for on the bench

- **Mirror-witness.** A write-then-read through the same bus bank is
  permutation-blind. Every module needs at least one asymmetric path. This
  is what caught the flipped PORTF→MDR bank, invisible to every
  round-trip test.
- **Phantom power.** Rig lines feed DUT VCC through input clamp diodes, so
  an unpowered CMOS board reads fine (memory scored 7/10 with the supply
  OFF). Every module gets a `power` test that holds rig outputs at the
  level sourcing no current, and it runs FIRST.
- **Swapped rig wires are a first-class fault.** When two signals read as
  each other's values, check the RIBBON first — one accessible end,
  nothing glued down, and both ends look right at a glance.
- **One-hole slips on adjacent gate pins** ('02 out/in/in, '04 in/out)
  are the single most common wiring fault here. Beep against both
  neighbours before power.
- **Never beep a live board.** `idle` first. In-circuit leg-to-leg reads
  clamp diodes, not copper.
- **A pin that beeps to every chip is on a power rail.**
- **AS-BUILT FREEZE.** Once a strip is populated, its slot map is copper.
  Read it off the board and write it down verbatim; never renumber a strip
  someone is wiring to. The ALU slot map cost an evening learning this.
- **NO BLIND COUNTERS.** A failing assertion must print enough detail to
  name the lying signal.
- **RAM discipline.** 8KB SRAM is the rig's scarcest resource; every
  print-only string lives in flash (`uart_putsP`, `PSTR`, PROGMEM tables).

## What is proven and what is not

- Microcode is **100% burned** (CRCs exact), **well-policed**
  (`check_word`/`check_table` reject bus fights, IR loads outside T0,
  missing END, PC_UP/length mismatch) and now **EXECUTED**. What that
  bought, immediately: the SA field had been packed bit-reversed since the
  ROMs were first burned, so every ADD was executing as AND. It survived
  every earlier test because a permutation is self-consistent — block1
  checked ROM against pin and found them agreeing, `alu.ops` drove SA from
  the rig and never used the microcode's encoding at all, and
  `test_microcode_gen` hard-coded the SAME wrong packing. Nothing compared
  the ENCODING against the WIRING until a program ran.
  `test_sa_field_reaches_the_382_uninverted()` now walks the netlist and
  does exactly that.
- Executed so far: the milestone path (`LDAI`, `ADD`, `OUT`, `HALT`) and
  `IN`. `LDA`/`STA`/`JMP`/`JNZ` and the other seven ALU codes are burned
  and policed but still unrun — the coverage images `alu`, `mem`, `flow`
  and `loop` exist and are generated, and `mem` is the only witness for
  MAR-as-a-latch, which the milestone never exercises.
- The opcode table is no longer PROPOSED in any meaningful sense —
  `LDAI=0x11` was the only documented anchor, `HALT=0xFF` is the one real
  choice (an erased EEPROM halts instead of raving), and the rest are
  arbitrary but now BURNED and RUN. `progrom_gen.py` imports `OPCODES`
  from `microcode_gen`, so the two ROMs cannot disagree.
- Timing is RETIRED. Blocks 4 and 5 free-run with Y1 seated at 1.024MHz
  and produce 0x4D. "Works single-stepped, fails free-run" was the
  signature to watch for; it never appeared.
