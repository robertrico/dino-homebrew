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

The stack images joined them 2026-08-24:

    sp1 0x2C   sp2 0x53   sp3 0x2C   sp 0x27   spcylon (sweeps, soak image)
    swdemo (never halts, SW1 bit 0 picks the arm)

The phase-C images joined them the same day:

    calladdr 0x5C   callraw 0x2A   call 0x4B   stack 0x27

`LDCI` and `NOP` are the only instructions that have never executed, and they
are unreachable by design — C is `RET`'s scratch register and nothing can read
it back. That is a MICROCODE-SOFT gap, not a hardware one: `MOV A,C` or
`PUSHC`/`POPC` would retire it for the cost of one three-ROM burn. Say which
kind of unrun it is.

The milestone image is `LDAI 0xFF; OUT; LDAI 0x2F; LDBI 0x1E; ADD; OUT;
HALT` → `OB = 0x4D`. The leading `LDAI 0xFF; OUT` poisons OB deliberately:
`U35` has no reset and the machine free-runs at power-up, so OB always holds
the previous answer. `PROG_in` substitutes SW1 for the second addend;
confirmed at SW1=0x01 → 0x30 and SW1=0x1E → 0x4D.

**FACT — timing is not a concern at 1.024MHz.** Blocks 4 and 5 free-run with
Y1 seated. "Works single-stepped, fails free-run" was watched for and never
appeared.

**FACT — PHASE B IS ON SILICON as of 2026-08-24.** The stack pointer, both
bank-1 decoders and the third EEPROM are bench-proven. `PROG_sp` returns
`0x27` and `PROG_spcylon` sweeps continuously, which means all three `~TC`
ripple links carry:

    U23         AT28C64B   third microcode EEPROM, CW16-23     BENCH-PROVEN
    U70 / U71   '138       SRC / DST bank-1 decoders           BENCH-PROVEN
    U63-U66     '169       16-bit stack pointer                BENCH-PROVEN
    U67 / U68   '245       SP hi/lo readback -> MDR            BENCH-PROVEN
    U69         '08        ~{SP_CE} = AND(~SP_UP, ~SP_DOWN)    BENCH-PROVEN

    LXISP 0x14   PUSHA 0x61   POPA 0x62   PUSHB 0x63   POPB 0x64

**FACT — PHASE C IS ON SILICON as of 2026-08-24.** `CALL` and `RET` execute
on hardware. The whole ISA now runs except `LDCI` and `NOP`.

    U72 / U73   '245       PC0-7 / PC8-15 -> MDR               BENCH-PROVEN

    CALL 0x33   RET 0x34

    PROG_calladdr 0x5C   CALL without RET; the pushed return address read
                         back by ABSOLUTE address. Names which byte broke:
                         0xC1 = LO (U72), 0xC2 = HI (U73).
    PROG_call     0x4B   the RETURN ADDRESS as the observable -- pads, for
                         RET. The landing site is the only thing that can
                         produce the answer.
    PROG_stack    0x27   work done INSIDE the callee, surviving the return.
                         0xD9 names a wrong LIFO order.

**It cost no ROM burn.** `CALL`/`RET` were already in the sockets — decoded
out of `roms/U9.bin`+`U15.bin`+`U23.bin`, 12 and 14 rows, zero differing from
the generator. Phase C was two '245s and wire.

**FACT — the five never-asserted decoder outputs all work.** Before
2026-08-24 none of these had ever been driven low, because nothing but
`CALL`/`RET` selects them:

    U30.12   ~REG_C_LOAD    RET T4     dst=REG_C
    U29.11   ~MDR_OUT       RET T9     the ISA's ONLY MDR replay
    U28.10   ~REG_C_OUT     RET T10    src=REG_C
    U70.13   ~PC_LO_OUT     CALL T7
    U70.12   ~PC_HI_OUT     CALL T3

Three are on pre-existing chips (`U28`, `U29`, `U30`), so
`--continuity U72 U73` never listed them — the walk filters to nets touching
the NEW designators. Same structural blind spot that hid `U28.6`/`U30.6`.
**Any future addition must hand-check the old-chip pins it wakes up.**

**FACT — `CALL` pushes PC+1, not PC+3.** The pushes at T3/T7 precede the
operand fetch at T9/T10, so PC has been incremented only once. `RET`
compensates: T11 `PC_LOAD` restores CALL+1, then T12 and T13 both carry
`PC_UP` and step over the two operand bytes. **Those trailing PC_UP states are
load-bearing, not padding** — on an LA a correct `RET` loads a PC pointing
into the middle of the `CALL`. Verified on hardware 2026-08-24. Read `RET` to
T13 before judging it; misreading this produced a false "found a bug" call the
same day.

**The fault phase C actually had was a wrong tap, not a wrong wire.**
`U72`/`U73` were first landed on `U11`/`U12` — the PC **load** path, whose B
side is `PCD0-15` feeding the counters' DATA inputs. `CALL` needs to *read*
the PC, so they belong on `PC0-15`, the counters' **Q** outputs, paralleling
`U13`/`U14`. The symptom was `PROG_callraw` reporting `0x26` — the low byte of
the previous `JMP`'s target, i.e. stale load data. **A raw-report image found
it; an assert-only image had called it `0xC1` and pointed at the wrong pin.**

**The SCHEMATIC was right and so was the tool.** `--continuity U72 U73` named
`PC0 -> U72.2, against U1.3 and U13.18` — the Q outputs, correctly. Unlike
phase B, where the checklist had real blind spots, here the generated list was
complete and the wiring diverged from it. Follow the list literally.

**FACT — MDR is 15 pins and almost all of them are tri-state.** Twelve '245
or '373 outputs contributing leakage only, and exactly THREE permanent DC
loads: `U18.3` (the MDR '373's own D input), `U63.3` and `U65.3` (the SP's
parallel-load taps). Worst-case sink ~1.5mA against the weakest driver's
2.1mA. Phase C adds two tri-state pins, about +2.7%. **Bus loading is not a
phase-C risk** — this was checked rather than assumed.

**FACT — a 100Ω series resistor sits in the SP board's CLK branch**, fitted
2026-08-24, source end, that branch only. It is NOT in `dino_v0_0_2/` yet.
Without it the '169s double-clock: `PROG_sp3` returns `0x22` instead of
`0x2C`, deterministically. Full measurement and the PCB consequences are in
`.git/sdd/CLOCK_DISTRIBUTION.md`. **Inference:** the SP is the first thing in
this machine to put raw `CLK` on a clock pin at the end of a stub on another
board — every other state element takes CLK through a NOR or NAND first, and
a gate is a de-facto regenerator. Nothing before the stack could have exposed
this.

> ## !!! THE FPGA TWIN IS BROKEN — DO NOT TRUST IT !!!
>
> **`make -C fpga verify` DOES NOT PASS, as of 2026-08-24.** The old claim
> here — "green in ~148s, host suite 147/147" — was stale and is deleted.
> Measured, same box, same venv, `pytest docs/notes -q`:
>
>     working tree     16 failed, 164 passed
>     HEAD, clean      4 failed, 173 passed     <- ALREADY RED before today
>
> **Four failures predate everything in this session:**
> `test_microcode_gen::test_sa_field_reaches_the_382_uninverted`, and three in
> `test_netlist_integrity` where the installed yosys rejects
> `proc -latches warn` — a toolchain version drift, not code.
>
> **Twelve more come from one root cause: `KeyError: '100Ω'`.** `fpga_gen.py`
> has no model for a resistor. R2 is the first passive IN A SIGNAL PATH, and
> `EXCLUDED_TYPES` cannot simply swallow it — dropping it whole strands
> `CLK_R` with no driver. It needs a net merge, `CLK_R ≡ CLK`, which is
> correct at logic level and is also an admission that the twin cannot model
> the damping R2 exists to provide.
>
> **DECISION 2026-08-24 (Rico): DEFER. Retire the twin after serial.** Not
> repaired, deliberately. Do not read a green badge into this file, and do
> not gate any bench work on the twin until it is either fixed or removed.

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
- **A round trip through ONE address is blind in the ADDRESS.** Mirror-witness
  again, pointed at the pointer rather than the data. `PROG_sp1` pushes to
  `[SP]` and pops from `[SP]`; if SP never counts, both use the same cell and
  `0x2C` round-trips perfectly through a stack pointer wired to nothing. It
  reported a green machine for most of 2026-08-24 while every bank-1 decoder
  output was dead. `PROG_sp`'s `0x00` is no better — a dead REG_B, a dead SUB
  and a dead POP all produce it, so it names nothing. `PROG_sp2` plants a
  sentinel in the cell push #2 must reach and reads it back by ABSOLUTE
  address; `PROG_sp3` puts a different sentinel in each neighbour so an
  off-by-one names its direction. **Any new pointer needs an image that reads
  a cell only a MOVED pointer reaches, and reads it by a path that cannot
  inherit the fault under test.**
- **The instrument can BE the cure.** Probing `CLK` at `U63.2` added ~10-15pF,
  damped a ringing edge, and made the fault vanish — so every attempt to
  observe it suppressed it, and at 20MS/s the runt was under one sample
  anyway. Found only by A/B-ing the probe itself: on `0x2C` every run, off
  `0x22` every run. **When probing changes the answer, that is the
  measurement, not an annoyance.** Stop reading the trace and start
  characterising the probe's own effect. Corollary: prefer an OB-only ROM
  witness over a probe on this machine, because a ROM cannot perturb the
  circuit it is testing.
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

> **!!! BROKEN AND SCHEDULED FOR RETIREMENT — see the Status section !!!**
> `make -C fpga verify` does not pass. Everything below describes what the
> twin DID, not what it currently does.

**FACT** — a generated VHDL twin (`fpga/gen/*.vhd`, emitted by `fpga_gen.py`,
never hand-edited) reproduces the schematic gate-for-gate. The whole ISA ran
green in cocotb, and every image tag synthesized, placed, routed and closed
timing on a Lattice ECP5-5G Versa: `DP16KD 40/108`, `TRELLIS_COMB 910/43848`,
17.22MHz against a 12MHz constraint.

**FACT — it caught none of 2026-08-24's three faults, and could not have.**
Six unlanded `CW` address wires, a ringing `CLK` edge, and U72/U73 landed on
the wrong chips. In all three the SCHEMATIC WAS CORRECT and the twin generates
FROM the schematic, so a wiring-diverges-from-design fault is invisible to it
by construction. The twin catches DESIGN errors. Every fault that day was a
build error or an analog one, and the bench caught all three.

**It cannot see** analog levels, real propagation on breadboard wire, fan-out,
or whether a wire was landed. Those are bench questions and always will be.

`docs/notes/dino_fpga_vplan.md` is the coverage map — 92 rows mapping each
claimed invariant to the artifact that would fail if it were wrong, with 5
GAPs named as such. Green means every wired check passed, not that everything
is checked.

`.git/sdd/BRINGUP_FPGA.md` covers the fabric. The breadboard machine is the
machine; the port is design-ahead.

## Where to read next

**Process documents live out of tree in `.git/sdd/`** — bring-up procedures,
plans, investigations, session handoffs, progress checkboxes. Any stale
in-tree reference to one of them (BRINGUP.md, dino_mar_lo_investigation.md,
dino_hardware_growth_plan.md, …) resolves to `.git/sdd/<name>`. The repo
keeps design and reference docs plus everything generated.

    .git/sdd/CLOCK_DISTRIBUTION.md           the 100R fix, and the PCB
                                             consequence — read before any
                                             board gets its own clock branch
    .git/sdd/SP_BEEP.md                      the phase-B landing record
    .git/sdd/SP_DEBUG.md                     the LA capture plan (phase B,
                                             now historical)
    .git/sdd/dino_stack_bringup_handoff.md   START HERE for stack bring-up
    .git/sdd/BRINGUP.md                      bench procedure, per stage
    .git/sdd/README.md                       progress checkboxes
    .git/sdd/dino_test_bringup_design.md     the bring-up spec
    .git/sdd/dino_hardware_growth_plan.md    what is planned and priced
    docs/notes/dino_isa_for_basic.md         the instruction set roadmap
