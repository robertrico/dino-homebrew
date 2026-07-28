# CLAUDE.md — DINO (Discrete Integrated NISC Operator)

An 8-bit CPU built from discrete 74-series logic on breadboards, designed
in KiCad, and brought up module-by-module with a bare-metal ATmega2560
test rig. Split out of the `hardware` portfolio repo on 2026-07-28 with
full history (138 commits) preserved.

## Working rules — these override default behaviour

1. **NEVER commit or push without an explicit ask.** This is a bench
   machine; Rico commits when Rico decides.
2. **Milestone gate.** No ISA or hardware extensions until the whole
   machine adds two numbers. Bug fixes are exempt.
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

## State as of 2026-07-28

**All ten modules bench-proven.** root, pc, microcode, control_word, mdr,
registers, mar, memory, alu, io. Coverage lint: 0 gaps, 0 pending.
Stage 1 (rig self-test) is CLOSED as a diagnostic, not a gate.

**What remains:** the integration ladder, then free-run. The milestone
program is burned and seated: `LDAI 5; LDBI 3; ADD; OUT; HALT` → OUT
should read 0x08.

**Read `tests/dino_bringup/BRINGUP.md` first.** It is the bench bible:
per-stage wiring, commands, expected output, failure meanings, and the
integration plan. `tests/dino_bringup/README.md` has the progress
checkboxes. `docs/notes/dino_test_bringup_design.md` is the spec.

## Integration is CONTROL FIRST

Two rules pick the blocks:

1. **Emulate what is cheap to be right about** (T-states, addresses,
   strobes, the instruction byte). **Keep real what is expensive** (alu,
   registers, bus sharing, the U25 bridge, memory decode). A rig stand-in
   is dangerous exactly when it is BETTER than the hardware — schematic
   bug 4 was a bridge defect that a rig-emulated bridge passes clean.
2. **Driven-wire count is the gate and may never go up.** Fewer rig wires
   == fewer rig-introduced error modes; the same goal. Risk is asymmetric:
   a wrong SAMPLED wire is a false FAIL, a wrong DRIVEN wire can fight a
   real driver, and a wrong driven STROBE is worst because strobes are
   ENABLES.

The control unit has the highest fan-out in the machine, so a rig
impersonating it would build the largest and most dangerous harness of the
project. Make it real first:

    BLOCK 1  root + microcode + control_word     ~11 driven
    BLOCK 2  + pc + mar + memory                  11  (three boards free)
    BLOCK 3  + mdr                                 6  (real IR)
    BLOCK 4  + registers + alu                     2  (real flags)
    BLOCK 5  + io, single-stepped                  2
    BLOCK 6  free-run, Y1 in socket                0  (8 wires + GND + HALT)

An earlier datapath-first plan was inverted on 2026-07-28 for exactly the
wire-count reason. Don't re-propose it.

**Block 1 is blocked on tooling that does not exist yet.** The rig's pin
bundles are per-module, and root/microcode/control_word reuse the same
Mega pins — there is no `pins <block>` and so no table to wire against.
Build block support in `kicad_contracts.py` first (union of members,
drop what becomes copper between them but keep it as sampled probes,
hard-error on pin collisions), then `mod_control.c`. Full checklist in
BRINGUP.md under "UNFINISHED WORK".

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

- Microcode is **100% burned** (CRCs exact) and **well-policed**
  (`check_word`/`check_table` reject bus fights, IR loads outside T0,
  missing END, PC_UP/length mismatch) but **unexecuted** except for the SA
  field, which `alu.ops` proved at the real '382s. Block 1 executes a
  microcode row for the first time.
- The opcode table is marked PROPOSED, which sounds scarier than it is:
  `progrom_gen.py` imports `OPCODES` from `microcode_gen`, so the two ROMs
  cannot disagree. The numbers are arbitrary; `HALT=0xFF` is the one real
  choice, so an erased EEPROM halts instead of raving.
- Timing is proven by NOTHING yet. Only free-run with Y1 seated retires
  it. "Works single-stepped, fails free-run" is the clean signature.
