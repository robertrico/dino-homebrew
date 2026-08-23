# DINO

**D**iscrete **I**ntegrated **N**ISC **O**perator — an 8-bit CPU built from
74-series logic on breadboards. That's the machine itself: no
microcontroller, no FPGA. Every register, every bus, every gate is a chip
you can put a probe on. (The repo does carry a generated FPGA twin for
design-ahead — see `fpga/`.)

Schematics in KiCad, microcode in EEPROM, and a bare-metal ATmega2560 test
rig that brings the machine up one board at a time.

**Status: IT RUNS.** All ten modules and all five integration blocks are
bench-proven, and the machine executes programs at full speed off its own
1.024MHz crystal. The milestone:

```asm
LDAI 0xFF   ; poison OB — destroy the previous answer first
OUT
LDAI 0x2F   ; A = 0x2F
LDBI 0x1E   ; B = 0x1E
ADD         ; A = A + B
OUT         ; LEDs show 0x4D
HALT
```

And it is no longer limited to what is burned into the ROM. `IN` reads the
DIP switches onto the bus, so an operand comes off the bench:

```asm
LDAI 0x2F   ; one addend from ROM
IN          ; the other from SW1
ADD
OUT         ; 0x2F + 0x01 = 0x30, 0x2F + 0x1E = 0x4D
HALT
```

Timing is retired: it free-runs, and "works single-stepped, fails
free-run" never appeared.

**The whole ISA executed on hardware on 2026-08-04** — every coverage image
produced its expected byte on the LEDs. `LDA`, `STA`, `JMP`, `JNZ` and seven
of the eight ALU codes had been burned and policed since the ROMs were first
written and had never once run.

**A stack pointer and a third microcode EEPROM exist in schematic and
simulation as of 2026-08-11** — twelve chips and seven instructions
(`LXISP`, `CALL`, `RET`, `PUSHA/POPA/PUSHB/POPB`), verified in the FPGA twin
and in the Python oracle, **not yet on silicon**. That is the next bench
session. After it: a 16550 UART, then a proto-Monitor.

---

## The part worth reading about

Building a CPU from discrete logic is a known exercise. The interesting
problem is different: **on a breadboard, with 60+ chips and a thousand
jumpers, how do you know the machine you built is the machine you drew?**

The answer here is four layers, each catching what the one before it
cannot:

```
schematic  ──▶  netlist audit  ──▶  generated contracts  ──▶  bench test
 (KiCad)        (gate equations       (pinmaps, ROM images,     (ATmega2560
                 extracted, not        expect models — all       drives real
                 eyeballed)            emitted from the          silicon and
                                       netlist)                  compares)
```

The rule underneath it: **nothing is retyped.** Every table in this repo —
pin assignments, the microcode ROM, the program ROM, the breadboard slot
maps, the wiring guides — is generated from the KiCad netlist by a script
with its own host tests. A schematic change propagates automatically. A
hand-maintained table would drift the moment someone moved a wire, and
drift is invisible until it costs you an evening.

Every test assertion is **netlist-verified before it is written**. Reading
a schematic and typing what you think a gate does is how you write a test
that agrees with your misunderstanding.

### Rules that were paid for on the bench

Each of these exists because something went wrong first:

- **Mirror-witness.** A write-then-read through the same bus bank is
  permutation-blind — a flipped jumper bank cancels itself out. Every
  module needs at least one asymmetric path. This is what finally caught a
  reversed PORTF→MDR bank that every round-trip test had passed.
- **Phantom power.** The rig's driven lines feed the DUT's VCC through
  input clamp diodes, so an unpowered CMOS board reads perfectly fine.
  A deliberate power-off run once scored 7/10. Every module now has a
  `power` test that runs first and holds the rig's outputs at the level
  that sources no current.
- **As-built freeze.** Once a breadboard strip is populated, its slot map
  is copper. Read it off the board and record it verbatim; never renumber
  a strip someone is wiring to.
- **No blind counters.** A failing assertion must print enough detail to
  name the lying signal, or the test is just a rumour.

### Faults this method actually caught

Not hypotheticals — these came off the bench, most diagnosed from serial
logs alone without a scope:

| Fault | How it was found |
|---|---|
| `U18.1` (OE) on `MDR_OUT` instead of `~MDR_OUT` | enable polarity inverted; cascaded into four failing tests until bus-fight analysis fingered it |
| PORTF→MDR jumper bank reversed | invisible to every A/B/C round trip, caught only by the asymmetric OUT-register path |
| `MDR5`↔`MDR6` crossed | decoded from byte 0 arithmetic alone: `0xA5 → 0xC5` is exactly a bit-5/6 exchange |
| Bridge DIR/EN keyed on destination instead of source | schematic bug — ADD could never have committed. Found by netlist audit before the board existed |
| Missing common ground | the all-float scan; first bench rule in action |
| `A8`-`A11` address rotation on the microcode ROM | the address-order test named every rotated line |

The last one matters most: **it was found on paper.** A netlist audit
caught a bridge defect that would have made the milestone program
impossible, before a single wire was cut.

---

## The machine

**8-bit data, 16-bit address.** Microcoded control: a **24-bit control word**
per T-state, stored in **three** EEPROMs addressed by `opcode << 4 | T`.

```
CW23:16  third ROM — bank selects, and room to grow
         CW17 SRC bank   CW18 DST bank   CW19 MISC bank

CW15  HALT           CW11:9   ALU op select (SA2:SA0)
CW14  PC_MAR_MUX     CW8:6    MISC   -> '138  bank 0: PC_CLEAR, PC_LOAD,
CW13  PC_UP                           COND, MDR_OUT, REG_OUT_LOAD,
CW12  END                             SP_UP, SP_DOWN
                     CW5:3    SRC    -> '138  bank 0: ROM, RAM, REG_A/B/C,
                                       ALU, SW
                                       bank 1: SP_LO/HI, PC_LO/HI
                     CW2:0    DST    -> '138  bank 0: REG_A/B/C, MAR_LO/HI,
                                       IR, RAM    bank 1: SP_LO/HI
```

The word was 16 bits and full — `SA(3) + MISC(3) + SRC(3) + DST(3) + END +
PC_UP + MUX + HALT` with two spare MISC codes and nothing else. The third
EEPROM buys bank-select bits rather than a wider field, so **every previously
burned row keeps its meaning**: bank 0 decodes exactly as before.

Instruction set: immediate loads, memory load/store, unconditional and
zero-conditional jumps, eight ALU operations on a '382 pair, an output port,
a switch input, a 16-bit stack pointer with `CALL`/`RET` and push/pop, and
`HALT` at `0xFF` so an erased EEPROM halts instead of raving.

**Adding an instruction costs a three-ROM burn** — a new opcode writes rows
in every byte of the word. Image CRCs are pinned as literals in
`test_microcode_gen.py`, so a reburn is always deliberate.

**Memory:** 32K program ROM and 32K RAM, split at `0x8000`.

**Commit discipline:** everything that changes state is clock-qualified and
commits while the clock is low — register loads through `NOR(~LOAD, CLK)`,
the RAM write pulse through `NAND(WRITE_DIR, ~CLK)`, PC load, clear and
count each gated independently. The consequence is useful: the microcode
ROM's access-time glitch cannot reach anything that holds state, so a
decode glitch here is a power-supply question, never a correctness one.

---

## Layout

```
dino_v0_0_2/          KiCad schematics, one sheet per module
docs/notes/           generators + design notes (see below)
roms/                 the burned EEPROM images — what is in the sockets
fpga/                 the generated VHDL twin, TTL models, cocotb, synthesis
tests/dino_bringup/   the ATmega2560 bring-up rig (bare-metal C)
datasheets/           74-series and memory parts
```

Everything in `docs/notes` that ends in `.py` emits something, and has a
`test_*.py` beside it:

| Script | Emits |
|---|---|
| `kicad_netlist.py` | `build_report()` — the netlist oracle everything else asks |
| `kicad_contracts.py` | per-sheet contracts, pin map, `--continuity` landing lists, `--since` change lists |
| `microcode_gen.py` | the three microcode ROM images, CRCs, expect header |
| `progrom_gen.py` | program ROMs, coverage images, and the Python oracle |
| `roms_readme_gen.py` | `roms/README.md` — the inventory read at the burner |
| `layout_gen.py` | breadboard placement, slot maps, colour-coded wiring guides |
| `fpga_gen.py` | schematic → VHDL, plus simulation hex images |
| `fuzz_gen.py` | differential fuzz seeds, VHDL twin vs the Python oracle |
| `coverage_lint.py` | asserts every contract signal is covered by a testbench |

---

## The FPGA twin

`fpga_gen.py` emits VHDL from the same netlist — `fpga/gen/*.vhd`, never
hand-edited — reproducing the schematic gate for gate, on top of behavioural
models of the actual parts (`fpga/ttl/ttl_74ls373.vhd`, `ttl_74f382.vhd`,
`ttl_at28c256.vhd`, …).

```bash
make -C fpga verify      # ~148s: host suite, differential fuzz, cocotb ladder
```

Every image tag synthesises, places, routes and closes timing on a Lattice
ECP5-5G Versa. `docs/notes/dino_fpga_vplan.md` is the coverage map: 92 rows,
each mapping a claimed invariant to the artifact that would **fail** if it
were wrong, with five gaps named as gaps.

**It cannot see** analog levels, real propagation on breadboard wire,
fan-out, or whether a wire was landed. Those are bench questions and always
will be. The breadboard machine is the machine; the twin is design-ahead.

---

## The bring-up rig

**The rig is currently detached and unwired** — it brought the machine up
board by board and shed its wires as each block was proven, which was always
the plan. Bench verification is now continuity against the generated crossing
list, TL866 read-back, and the coverage images' answers on the LEDs. What
follows is how it works when it is connected.

One firmware image, every test compiled in, selected at runtime over a
serial shell. The rig is stimulus, clock, and analyser.

```
list                  every test, grouped by module
run all               everything wired
run alu               one module
run alu.flags         one test
pins alu              the complete jumper table for that module
```

`pins <module>` **is** the hookup list — it prints from the same generated
tables the firmware resolves at runtime, so the paper and the code cannot
disagree.

### Build

```bash
cd tests/dino_bringup
source env.sh
build && flash && monitor      # avr-gcc, avrdude, screen @115200
```

### Test

```bash
make -C fpga verify                    # everything: host suite, fuzz, cocotb
make -C tests/dino_bringup/hosttest    # C model tests, no hardware needed
```

Individual generators self-test standalone, **run from the repo root** — they
resolve `roms/` relative to themselves, so `cd docs/notes` first and they
will not find it:

```bash
for t in docs/notes/test_*.py; do python3 "$t"; done
python3 docs/notes/coverage_lint.py
```

A few (`test_fpga_gen`, `test_vplan`, `test_netlist_integrity`) need `pytest`
and `cocotb`; `make -C fpga verify` runs them in the project venv.

The C expect models (`*_expect.h`) contain no AVR headers on purpose — the
same logic the rig asserts against is exhaustively tested on the host
first, red before green, long before a board is wired.

---

## How it was brought up

The integration ladder, control unit first, with the rig shedding wires at
every step until it was only watching. **All five blocks were bench-proven by
2026-08-02**; the counts below are current and include the stack sheet:

```
BLOCK             ADDS                          DRIVEN  SAMPLED
BLOCK 1   root + microcode + control_word          8       39
BLOCK 2   + pc + mar + memory                      8       31
BLOCK 3   + mdr        (real IR — it fetches)      0       15
BLOCK 4   + registers + alu + stack                0       15
BLOCK 5   + io                                     0       15
```

The ordering is not arbitrary. Every rig wire is a wire that can be one hole
off, so fewer rig wires means fewer rig-introduced faults — and the control
unit has the highest fan-out in the machine, which makes a rig standing in
for it the most dangerous harness the project could build. Make it real first
and that harness never exists. Driven hits zero at Block 3, when the real
instruction register takes over the fetch.

Blocks are **black-box** tests: a signal is sampled only if its value depends
on more than one board in the block. Anything one module already determines
is retired to that module's test, and anything produced inside the block and
consumed inside it is copper the rig never touches.

Nothing is ever pulled — no chip leaves its socket and the crystal stays
seated throughout — so the rig never owns the clock and every block runs free
at 1.024MHz, captured in bursts rather than single-stepped.

### The blind spot that cost a day

That last sentence contains the flaw. **Copper is driven by no test and
sampled by no test.** A module test drives those nets from the rig's own
pins, so the board-to-board run is never needed and cannot fail; the block
ladder classifies them as copper and never looks. **The wire between two
proven modules was checked by nothing.**

Two runs — nine wires — turned out never to have been landed at all, and
every element around them measured perfectly correct the entire time. The
fix is generated, not remembered:

```bash
python3 docs/notes/kicad_contracts.py --continuity U63 U64 U65 U66 ...
python3 docs/notes/kicad_contracts.py --since HEAD~1
```

The first prints every pin a named chip needs landed. The second prints what
changed, classified — and it is not optional, because the continuity walk
filters to nets touching the *new* chips, so a lifted strap on an existing
pin is invisible to it. Two blind spots in that tool itself were found and
regression-tested in `test_continuity_completeness.py`; one of them had been
dropping the ROM chip-enable from every checklist ever produced.

## What is left

```
land the stack   73 nets, 154 pins, plus 6 copper changes and 2 new wires
burn three ROMs  U9, U15, U23
PROG_sp          SP alone — LXISP and the counter, no CALL/RET
PROG_stack       push/pop, LIFO order observable
then             CALL/RET on hardware, a 16550 UART, a proto-Monitor
```

Bench procedure, per-stage wiring, failure meanings, and the full
integration plan live out of tree with the rest of the process documents
(maintainer's `.git/sdd/`).

---

*Schematic PDF: [`dino_v0_0_2/dino_v0_0_2.pdf`](dino_v0_0_2/dino_v0_0_2.pdf)*
