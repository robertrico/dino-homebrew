# CLAUDE.md — DINO (Discrete Integrated NISC Operator)

An 8-bit CPU built from discrete 74-series logic on breadboards, designed in
KiCad. Split out of the `hardware` portfolio repo on 2026-07-28 with full
history preserved.

## How this document is written

Every claim here is one of three things, and it says which:

- **fact** — measured, run, or extracted from the netlist, with the source
  named. Reproducible.
- **inference** — follows from a fact by reasoning. Usually right; has been
  wrong.
- **open** — not known. Named so nobody treats it as settled.

If a number appears without a source, it is not a measurement. Delete it or
go measure it. This document previously carried voltage readings with no
recorded conditions, date, or session log, and they were being used to
justify design decisions.

## Working rules — these override default behaviour

1. **Never commit or push without an explicit ask.** Rico commits.
2. **TDD.** Host-testable logic gets a host test first, RED before GREEN.
3. **Rico burns the ROMs** (TL866). Tools verify; they never program.
4. **Netlist-verify before encoding.** Never write an assertion from a
   reading of the schematic — extract the gate equation first:

       python3 -c "import sys;sys.path.insert(0,'docs/notes');\
       from kicad_netlist import build_report;\
       print(*build_report('dino_v0_0_2/program_counter.kicad_sch')[0],sep='\n')"

   Two seconds, authoritative. Reasoning from memory has been wrong more
   than once.
5. **Schematics first.** Draw it, verify on the FPGA, refine, then hardware.

## Status

**FACT — the machine works.** All ten original modules and all five
integration blocks were bench-proven by 2026-08-02. The whole ISA executed
on hardware 2026-08-04; every coverage ROM produced its expected `OB`:

    mardisc 0x6B   pads 0x40   mem 0xC5   flow 0x39
    alu     0x39   loop 0x15   PROG 0x4D  cylon (never halts, soak image)

`LDCI` and `NOP` have not executed and are unreachable by design — C is
`RET`'s scratch register.

The milestone image is `LDAI 0xFF; OUT; LDAI 0x2F; LDBI 0x1E; ADD; OUT;
HALT` → `OB = 0x4D`. The leading `LDAI 0xFF; OUT` poisons OB deliberately:
`U35` has no reset and the machine free-runs at power-up, so OB always holds
the previous answer. `PROG_in` substitutes SW1 for the second addend;
confirmed at SW1=0x01 → 0x30 and SW1=0x1E → 0x4D.

**FACT — timing is not a concern at 1.024MHz.** Blocks 4 and 5 free-run with
Y1 seated. "Works single-stepped, fails free-run" was watched for and never
appeared.

**FACT — the stack and third EEPROM exist in schematic and simulation only,
as of 2026-08-11.** Twelve chips, seven instructions, nothing on silicon:

    U23         AT28C64B   third microcode EEPROM, CW16-23     microcode
    U70 / U71   '138       SRC / DST bank-1 decoders           control_word
    U63-U66     '169       16-bit stack pointer                stack_pointer
    U67 / U68   '245       SP hi/lo readback -> MDR            stack_pointer
    U69         '08        ~{SP_CE} = AND(~SP_UP, ~SP_DOWN)    stack_pointer
    U72 / U73   '245       PC0-7 / PC8-15 -> MDR               mdr

    LXISP 0x14   CALL 0x33   RET 0x34
    PUSHA 0x61   POPA 0x62   PUSHB 0x63   POPB 0x64

`make -C fpga verify` is green in ~148s: host suite 147/147, 20-seed
differential fuzz, cocotb ladder 40/40 (19 TTL models + 10 sheet models + 2
milestone + 9 coverage images).

**The rig (ATmega2560) is detached and unwired.** Bench verification is
therefore continuity against the generated crossing list, TL866 read-back,
and the coverage ROMs' `OB` values. Instruments available: DSLogic LA,
Siglent scope, DMM.

## Open questions

Named because they are not settled. None is blocking.

**OPEN — HALT does not hold.** The machine halts, then escapes after a few
seconds, varying. `CET` on the '163 is sampled every clock, so an escape
once in millions of clocks is a level problem rather than a logic one — that
much is inference, not measurement. Only visible on `PROG_flow`; every other
image has `0xFF` fill past its HALT so an escape just re-halts.

**OPEN — bus levels have never been characterised on a healthy machine.**
Every level reading this project has recorded was taken during a debugging
session, on a board that was misbehaving, usually with the rig attached. The
rig's own clamp diodes feed the DUT (see phantom power below), so those
readings measure the rig as much as the board. The one reading with a
recorded source is `U45.2 at 1.67V`, which was a real fault and was fixed.

Earlier versions of this file listed `W 2.26V`, `PC_MAR_MUX 1.0V avg` and
`MAR3 3.22V` as standing facts. **They have no recorded date, conditions or
session log anywhere in the repo.** They were removed rather than kept as
unsourced law. Characterising a healthy bus is its own initiative.

**FACT — the stack lands 73 nets / 154 pins**, netlist-extracted 2026-08-11,
the largest single addition since the machine was built. Plus 6 no-connects
(`CW16`, `CW19-23`) and, on chips that already exist, 6 copper changes and 2
new wires. `kicad_contracts.py --continuity <refs>` emits the landing list;
`--since <rev>` emits the change list. The second is not optional: the
continuity walk filters to nets touching the NEW chips, so a lifted strap on
an existing pin — `U28.6`/`U30.6`, both decoder enables — is invisible to it.

**The count was 39/94 until the tooling was fixed on 2026-08-11**, and the
gap was invisible work, not new work. Two blind spots, both now
regression-tested in `docs/notes/test_continuity_completeness.py`:

- **A net's key is its full label set.** Cross-sheet connectivity here is a
  naming convention — every label is sheet-local and KiCad joins nothing
  between sheets. So a net labelled `ROM_EN` on one sheet and `M15/ROM_EN` on
  another got two keys, both looked sheet-local, and the cross-sheet filter
  dropped the wire. `M15/ROM_EN` is the ROM chip-enable and it was missing
  from every checklist this tool ever produced; it survived only because a
  dead `~CE` means nothing boots. `alias_splits()` now fails a test on any
  recurrence, and this is a *second* naming hazard distinct from the
  alphabetical-first rule below — that one is fixed by naming, this one by
  making every sheet declare the same label set.
- **Sheet-internal nets were filtered out.** Right for the default
  board-to-board report, wrong when you name chips: a new chip's own on-board
  wiring is most of the job. `~{TC1}` is the cost of getting it wrong —
  `U63.15 -> U64.10` unlanded and the SP counts correctly for 256 pushes
  before the low byte wraps, so `PROG_stack` passes clean.

## The machine invariant

**FACT, netlist-extracted.** Everything that changes state is clock-qualified
and commits on CLK low:

    register/IR/MAR/ALU loads   NOR(~LOAD, CLK)
    RAM write                   NAND(WRITE_DIR, ~CLK)
    PC load                     NAND(PC_LOAD, ~CLK)
    PC clear                    NOR(~PC_CLEAR, CLK)
    PC count                    NAND(PC_UP, ~CLK)
    T-state clear/hold          the '163's synchronous clear and CET

Bus output enables are ungated. **Inference:** a microcode decode glitch is
therefore a supply question rather than a correctness one, because nothing
state-changing is reachable during the ROM access window. Do not gate the
'138s pre-emptively. Full table in BRINGUP.md.

**FACT — the machine is fully static** (the '121 one-shot is gone), so the
clock can stop indefinitely.

**FACT — SP clocks on CLK, not ~CLK.** `LE = NOR(~LOAD, CLK)` makes
MAR/registers transparent while CLK is low, so a ~CLK-clocked SP would update
at the start of that window and a row doing `SRC=SP_LO, DST=MAR_LO,
MISC=SP_DOWN` would land the post-decrement value in MAR.

## Bus architecture

**FACT, netlist-extracted.** `MDR0-7` is the internal bus; `W` is the
ALU/destination side; `U25` is the transceiver between them.

    MDR side   ROM (U19), RAM (U21), REG A/B/C (U41-43), SP, PC_LO/PC_HI
    W side     ALU, SW           -- the two inputs to BUS_DIR's NAND
    both       U25 bridge, DIR = NAND(~ALU_OUT, ~SW_OUT)

**FACT** — whenever any source is active the bridge is on and *both* buses
carry the byte, so a destination can latch from either side. The machine is
already split that way: MAR and IR latch from W, registers latch from MDR.

**FACT** — selecting SRC bank 1 disables `U28`, so `SRC_ACTIVE` (its `O0`)
floats high, the bridge turns on pointed MDR→W, and a W-side bank-1 source
would fight it. Every bank-1 source therefore lands on `MDR0-7`. Bank 1 also
has no NONE slot, for the same reason: `SRC=8` with nothing driving would let
MDR supply W silently.

## Integration: control first, black-box, low-wire

**The block law (2026-07-28).** Blocks are black-box tests:

> Sample a signal at block level only if its value depends on more than one
> member of the block.

Four categories, all derived from the netlist:

    COPPER  out of one member AND in of another -> wired board-to-board
    DRIVE   in of a member, out of none, needed as stimulus
    STRAP   in of a member, out of none, not needed -> tied on the board
    SAMPLE  out of a member, not copper, not already retired

Every retirement names the test that earned it. END/HALT are copper but
sampled in every block — nothing else segments the instruction stream.

**Driven-wire count is the gate and may not rise.** Risk is asymmetric: a
wrong sampled wire is a false FAIL; a wrong driven wire can fight a real
driver; a wrong driven strobe is worst because strobes are enables.

    BLOCK  ADDS                          DRIVEN  SAMPLED
    1      root+microcode+control_word      8       39
    2      + pc + mar + memory              8       31
    3      + mdr                            0       15
    4      + registers + alu + stack        0       15
    5      + io                             0       15

Driven hits zero at block 3, when the real IR fetches the machine's own
instruction bytes. A datapath-first ladder was considered and rejected on
2026-07-28 for wire count; don't re-propose it.

**Two clock modes.** `CLK` is `U27.5` and `RESET` is `U27.9`, both '74
totem-pole outputs, so nothing can inject there. The one non-contending
point is `CLKIN` at `U20.2`, reachable with Y1 disabled:

    FREE-RUN     Y1 in,  CLKIN jumper off
    STEP-CLOCK   Y1 out, CLKIN driven at U20.2

The discriminator is not "does CLK move?" — a live Y1 moves it for you,
which is how a step test once reported success while the machine free-ran
past every sample. It is "does CLK hold still when I stop asking?"

STEP-CLOCK currently has no driver, since it was the rig's. A debounced
button ('14 + RC into `U20.2`) restores it.

## Instruments

    LA (DSLogic)   WHEN. 16ch at speed. Enable overlap, one-hot T,
                   END->T clear, decode glitches.
    Scope (SDS)    HOW. Analog. Edge quality, ringing, actual levels.
    DMM            static levels, continuity.

With the clock stopped, a DMM and one probe see everything, one net at a
time, with unlimited time — which is most of what a wide bus watcher would
buy.

## Everything is generated, nothing is retyped

    docs/notes/kicad_contracts.py   contracts + pinmap + crossing lists
                                    --continuity <refs>  what to land
                                    --since <rev>        what changed, classified
    docs/notes/microcode_gen.py     microcode ROM images + CRCs + header
    docs/notes/progrom_gen.py       program ROMs, and the Python oracle
    docs/notes/layout_gen.py        breadboard placement, slot maps,
                                    wiring guides, layout pages
    docs/notes/kicad_netlist.py     build_report() — the netlist oracle
    docs/notes/fpga_gen.py          schematic -> VHDL, sim hex images
    docs/notes/coverage_lint.py     contract signals vs FPGA testbenches

Host tests sit next to each (`test_*.py`), plus C model tests in
`tests/dino_bringup/hosttest/`.

**Adding an instruction costs a three-ROM burn.** A new opcode writes rows in
every byte of the 24-bit word. `U9`/`U15` stay untouched only for changes
confined to `CW16-23`. Image CRCs are pinned as literals in
`test_microcode_gen.py` so a reburn is always deliberate.

## Rules derived from specific failures

Each names the failure it came from. They are rules because something broke,
not because they are principles.

- **Mirror-witness.** A write-then-read through the same bus bank is
  permutation-blind. Every module needs one asymmetric path. Caught the
  flipped PORTF→MDR bank, which every round-trip test passed.
- **Phantom power.** Rig lines feed DUT VCC through input clamp diodes, so an
  unpowered CMOS board reads fine — memory once scored 7/10 with the supply
  off. This also means any level measured with the rig attached is suspect.
- **One-hole slips on adjacent gate pins** ('02 out/in/in, '04 in/out) are
  the most common wiring fault here. Beep against both neighbours.
- **Never beep a live board.** In-circuit leg-to-leg reads clamp diodes.
- **A pin that beeps to every chip is on a power rail.**
- **As-built freeze.** Once a strip is populated its slot map is copper. Read
  it off the board verbatim; never renumber a strip someone is wiring to.
- **No blind counters.** A failing assertion must name the lying signal.
- **A stand-in that is BETTER than the hardware hides defects.** Schematic
  bug 4 was a bridge defect a rig-emulated bridge passed clean. Same reason
  the '169 model and the Python oracle both power SP up non-zero: the real
  part has no clear.
- **KiCad names a net after the alphabetically first label on it.** `CW9`
  beats `SA2`, `CW12` beats `END`, and `COND0` beat `CW21` — taking the name
  off the `CW[0..23]` bus and producing `net_not_bus_member`. Any alias on a
  `CWnn` net must sort after it; a leading `~{` guarantees that. Diff
  `kicad-cli sch erc --format json` against a HEAD baseline: the absolute
  count is meaningless, only the delta is readable.
- **An alias binds only when its consumer pin exists.** Unwired bits emit as
  plain `cw16`/`cw19`-`cw23`. That is correct, not a failed label.
- **Every sheet touching an aliased net must declare the SAME label set.**
  A net's key is its full label set joined; sheets connect by name and nothing
  else. Label it `ROM_EN` on one sheet and `M15/ROM_EN` on another and it
  becomes two keys, both sheet-local, and the continuity checklist drops the
  wire without a word. Cost `M15/ROM_EN` — the ROM chip-enable — every
  checklist ever generated. Guarded by `alias_splits()`.
- **A tool's silence is not coverage.** The continuity list is the only check
  the netlist→copper step has, so a hole in it is a hole in that step's entire
  coverage. Both holes found on 2026-08-11 were in the report, not the
  schematic — the machine was right and the paperwork was wrong, which is the
  harder direction to notice.
- **A 3-bit field decode is bank-blind.** Bank-1 `PC_LO` (code 10) shares its
  low three bits with bank-0 `RAM` (code 2). Both `check_word` and the Python
  oracle read a PC push as a RAM read until the decode folded in the bank
  bits.
- **`src=RAM` cannot write MAR in the same word.** The RAM address is MAR and
  the '373s are transparent while CLK is low, closing a live loop
  `MAR -> M -> RAM -> MDR -> U25 -> W -> MAR`. ROM reads are exempt: their
  address comes from the PC.
- **`misc=MDR_OUT` must be the state immediately after the read that parked
  the byte.** `LE_MDR` falls at the T-state boundary and can latch whatever
  the next source turns on.

The last three were found by the gate model after reading the schematic had
accepted them. All are now `check_word`/`check_table` rules.

## What the FPGA does and does not cover

**FACT** — a generated VHDL twin (`fpga/gen/*.vhd`, emitted by `fpga_gen.py`,
never hand-edited) reproduces the schematic gate-for-gate. The whole ISA runs
green in cocotb, and every image tag synthesizes, places, routes and closes
timing on a Lattice ECP5-5G Versa: `DP16KD 40/108`, `TRELLIS_COMB 910/43848`,
17.22MHz against a 12MHz constraint.

**It cannot see** analog levels, real propagation on breadboard wire, fan-out,
or whether a wire was landed. Those are bench questions and always will be.

`docs/notes/dino_fpga_vplan.md` is the coverage map — 92 rows mapping each
claimed invariant to the artifact that would fail if it were wrong, with 5
GAPs named as such. Green means every wired check passed, not that everything
is checked.

`fpga/BRINGUP_FPGA.md` covers the fabric. The breadboard machine is the
machine; the port is design-ahead.

## Where to read next

    docs/notes/dino_stack_bringup_handoff.md   START HERE for stack bring-up
    tests/dino_bringup/BRINGUP.md          bench procedure, per stage
    tests/dino_bringup/README.md           progress checkboxes
    docs/notes/dino_test_bringup_design.md the bring-up spec
    docs/notes/dino_hardware_growth_plan.md what is planned and priced
    docs/notes/dino_isa_for_basic.md       the instruction set roadmap
