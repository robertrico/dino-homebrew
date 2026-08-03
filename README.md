# DINO

**D**iscrete **I**ntegrated **N**ISC **O**perator — an 8-bit CPU built from
74-series logic on breadboards. No microcontroller, no FPGA, no simulation.
Every register, every bus, every gate is a chip you can put a probe on.

Schematics in KiCad, microcode in EEPROM, and a bare-metal ATmega2560 test
rig that brings the machine up one board at a time.

**Status:** all ten modules are bench-proven. Integration is next, and the
milestone is a program that adds two numbers:

```asm
LDAI 0xFF   ; poison OB — destroy the previous answer
OUT
LDAI 0x2F   ; A = 0x2F
LDBI 3      ; B = 3
ADD         ; A = A + B
OUT         ; LEDs show 0x4D
HALT
```

It is burned and seated in the program ROM, waiting for the boards to be
wired together.

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

**8-bit data, 16-bit address.** Microcoded control: a 16-bit control word
per T-state, stored in a pair of EEPROMs addressed by `opcode << 4 | T`.

```
CW15  HALT           CW11:9   ALU op select (SA2:SA0)
CW14  PC_MAR_MUX     CW8:6    MISC   -> '138 (PC_CLEAR, PC_LOAD, COND,
CW13  PC_UP                            MDR_OUT, REG_OUT_LOAD)
CW12  END            CW5:3    SRC    -> '138 (ROM, RAM, REG_A/B/C, ALU, SW)
                     CW2:0    DST    -> '138 (REG_A/B/C, MAR_LO/HI, IR, RAM)
```

Instruction set: immediate loads, memory load/store, unconditional and
zero-conditional jumps, eight ALU operations on a '382 pair, an output
port, and `HALT` at `0xFF` so an erased EEPROM halts instead of raving.

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
tests/dino_bringup/   the ATmega2560 bring-up rig (bare-metal C)
datasheets/           74-series and memory parts
```

Everything in `docs/notes` that ends in `.py` emits something, and has a
`test_*.py` beside it:

| Script | Emits |
|---|---|
| `kicad_contracts.py` | per-sheet contracts and the rig's pin map |
| `microcode_gen.py` | microcode ROM images, CRCs, and the rig's expect header |
| `progrom_gen.py` | program ROM (diagnostic + milestone images) |
| `layout_gen.py` | breadboard placement, slot maps, colour-coded wiring guides |
| `kicad_netlist.py` | `build_report()` — the netlist oracle everything else asks |
| `coverage_lint.py` | asserts every contract signal is covered by a test |

---

## The bring-up rig

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
make -C tests/dino_bringup/hosttest    # C model tests, no hardware needed
cd docs/notes && for t in test_*.py; do python3 "$t"; done
python3 docs/notes/coverage_lint.py
```

The C expect models (`*_expect.h`) contain no AVR headers on purpose — the
same logic the rig asserts against is exhaustively tested on the host
first, red before green, long before a board is wired.

---

## What is left

The integration ladder, control unit first, with the rig shedding wires at
every step until it is only watching:

```
BLOCK             ADDS                          DRIVEN  SAMPLED  JUMPERS
BLOCK 1   root + microcode + control_word          8       27     35+GND
BLOCK 2   + pc + mar + memory                      8       11     19+GND
BLOCK 3   + mdr        (real IR — it fetches)      0       11     11+GND
BLOCK 4   + registers + alu    (the sum happens)   0       11     11+GND
BLOCK 5   + io                                     0       11     11+GND
```

The ordering is not arbitrary. Every rig wire is a wire that can be one
hole off, so fewer rig wires means fewer rig-introduced faults — and the
control unit has the highest fan-out in the machine, which makes a rig
standing in for it the most dangerous harness the project could build.
Make it real first and that harness never exists. Driven hits zero at
Block 3, when the real instruction register takes over the fetch.

Blocks are **black-box** tests: a signal is sampled only if its value
depends on more than one board in the block. Anything one module already
determines is retired to that module's test, and anything produced inside
the block and consumed inside it is copper the rig never touches. Module
coverage is already extensive; re-sampling it at block level would just be
a module test with more wires and more ways to be wrong.

Nothing is ever pulled — no chip leaves its socket and the crystal stays
seated throughout — so the rig never owns the clock and every block runs
free at 1.024MHz, captured in bursts rather than single-stepped.

Bench procedure, per-stage wiring, failure meanings, and the full
integration plan are in
[`tests/dino_bringup/BRINGUP.md`](tests/dino_bringup/BRINGUP.md).

---

*Schematic PDF: [`dino_v0_0_2/dino_v0_0_2.pdf`](dino_v0_0_2/dino_v0_0_2.pdf)*
