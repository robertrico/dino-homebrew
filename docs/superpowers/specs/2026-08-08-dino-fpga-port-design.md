# DINO FPGA Port — Design

Date: 2026-08-08
Status: draft, awaiting review

## Goal

Reproduce the breadboard DINO as an **exact virtual copy** on the ECP5 Versa
board: same microcode and program ROM images (byte-identical, CRC-matched),
same microarchitecture, every 74-series chip individually represented with its
U-number, every net taken verbatim from the KiCad netlist. Once the copy is
proven, the FPGA becomes the design-ahead bench: new hardware (stack, UART,
third microcode EEPROM) is prototyped in fabric before any copper is cut.

## Decisions made

| Question | Decision |
|---|---|
| Fidelity | Exact virtual copy — chip-level structural, same ROM images |
| Hierarchy | Mirrors the KiCad sheet hierarchy: one entity per sheet, chips inside |
| Chip internals | Fast-clock sampled state (glitch-safe), pure combinational for logic parts |
| Integration | Standalone top-level bitstream; no LiteX, no Migen |
| Language | VHDL (GHDL toolchain; matches prior intel-8008-vhdl experience) |
| Success | Full burned ISA proven — milestone + IN + alu/mem/flow/loop coverage images, in simulation AND on the Versa board |
| Toolchain | `~/oss-cad-suite/bin` exclusively: ghdl, yosys 0.68 (+ghdl plugin, verified working), nextpnr-ecp5, ecppack |

## Architecture

```
.kicad_sch (10 sheets) ──build_report()──► fpga_gen.py ──► generated VHDL
                                                             (never hand-edited)

fpga/
  ttl/            hand-written, one entity per PART TYPE ('163, '382, '244, ...)
                  ports named per datasheet; testbench per entity
  gen/            GENERATED: one entity per schematic sheet + dino_core.vhd
  top/            hand-written: versa_top.vhd, versa.lpf
  sim/            testbenches (cocotb, Python) + ROM hex images from generators

docs/notes/fpga_gen.py        the emitter (sibling of the other generators)
docs/notes/test_fpga_gen.py   host tests for the emitter
```

### Generated hierarchy

`dino_core.vhd` instantiates ten module entities — `program_counter`, `mar`,
`mdr`, `memory`, `microcode`, `control_word`, `registers_a_b`, `alu`,
`input_output`, `root` (the `dino_v0_0_2` top sheet: clock and reset) —
wired by the cross-sheet nets. Each module entity's
ports are exactly the sheet's contract signals (the boundaries
`kicad_contracts.py` and `kicad_xsheet_audit.py` already know). Inside each
module: one instance per physical chip, keeping its U-number, with every pin
connection taken from `build_report()`. Nothing about the design is
hand-transcribed; rule 5 (netlist-verify before encoding) is satisfied by
construction because the emitter consumes the netlist directly.

### Chip model contract (`fpga/ttl/`)

- **Combinational parts** ('00, '02, '04, '138, '157, '244, '382, ...):
  pure combinational VHDL, no clock. Data-path glitches are authentic and
  harmless — the same machine invariant that protects the bench (everything
  state-changing commits on CLK low) protects the model.
- **Stateful parts** ('163, '74, register files): take a hidden `clk_sys`
  port (board 100 MHz) in addition to their datasheet pins. Their "clock"
  pins are 2-flop synchronized and edge-detected against `clk_sys`. The
  board's gated clocks (`NOR(~LOAD, CLK)` etc.) work exactly as wired, but no
  fabric register ever clocks on a LUT output — glitch-safe by construction,
  and static timing analysis stays meaningful. (Standard retro-FPGA
  technique; MiSTer cores model original chips the same way.)
- **Tri-state parts** ('244 outputs onto the W bus): model with real `'Z'` on
  `std_logic`. GHDL resolves the bus like copper in simulation; yosys
  converts internal tri-states to muxes at synthesis (`tribuf`). The
  netlist stays verbatim even for the shared bus. The microcode policing
  (`check_word` bus-fight rejection) is what makes the mux conversion legal.
- **ROMs (microcode EEPROMs, program ROM) and RAM**: models initialized from
  hex files emitted by `microcode_gen.py` / `progrom_gen.py` — the same bytes,
  same CRCs as the burned chips. `OPCODES` stays single-source. Written to be
  BRAM-inferable.
- **Y1 + divider**: Y1 is a 4 MHz oscillator (`dino_v0_0_2.kicad_sch`); its
  stand-in is the 100 MHz board clock divided by 25 → 4 MHz, injected at
  Y1's output node. The modeled divider chips produce machine CLK from
  there, exactly as copper does. (The machine is fully static, so exact
  frequency is not load-bearing — but the stand-in replaces Y1, not the
  divider.)

### Emitter (`fpga_gen.py`)

- Walks all ten sheets via `build_report()`; groups by sheet; maps each
  component to a `ttl/` entity via a per-part-type pin-number → port-name
  table (same shape as `PIN_ASSIGN` in `kicad_contracts.py`).
- Boundary components (connectors, LEDs, switches, pushbutton, crystal,
  power symbols) are excluded by an explicit table and become `dino_core`
  ports.
- The emitter adds a `clk_sys` port to every generated module entity and
  threads it to every stateful chip instance — VHDL has no hidden ports,
  so this wiring is generated, owned by the emitter, and covered by its
  host tests.
- Host tests (`test_fpga_gen.py`): every chip instantiated exactly once,
  every net accounted for, every pin of every used part type mapped or
  explicitly marked NC. A missing mapping is a hard failure, not a warning.

### Board mapping (`versa_top.vhd` + `versa.lpf`)

- OB register → Versa user LEDs.
- DIP switches → SW1 byte (the `PROG_in` path through the io '244).
- Pushbutton → the RESET net, at the same point the bench button sits.
- 100 MHz board oscillator → `clk_sys`.
- Pin locations cribbed from the litex-boards
  `lattice_versa_ecp5.py` platform file (reference only; no LiteX import).

## Testing — TDD ladder, mirrors bringup

Host-testable logic gets a test FIRST, RED before GREEN, per house rule 3.

0. **Toolchain spike** — before any emitter work: two '244 models driving a
   shared `'Z'` bus, one cocotb testbench, and a full
   ghdl → yosys(+ghdl plugin, tribuf) → nextpnr-ecp5 → ecppack pass.
   Proves the two assumed-but-unproven paths in this repo: internal
   tri-state-to-mux conversion through the plugin, and cocotb driving
   oss-cad-suite's GHDL via VPI. Both risks die before they can cost a
   redesign.
1. **Per-model testbenches** (cocotb over GHDL — Python testbenches, keeping
   TDD in Python). Datasheet truth tables and timing behavior per part type.
2. **Emitter host tests** — completeness and mapping checks above.
3. **Per-module testbenches** — ports of the rig module tests: the same
   contract signals the rig DRIVEs and SAMPLEs become testbench stimulus and
   assertion points. Module coverage doctrine carries over to fabric.
4. **Whole-core simulation** — milestone program free-runs to OB = 0x4D;
   IN program with forced DIP values: 0x01 → 0x30, 0x1E → 0x4D.
5. **Full ISA in simulation** — alu/mem/flow/loop coverage images run to
   completion with expected values asserted. `mem` finally witnesses
   MAR-as-a-latch, which the milestone never exercises.
6. **Synthesis gate** — yosys(+ghdl) → nextpnr-ecp5 timing-clean at
   `clk_sys`; zero inferred latches, zero synthesis warnings accepted
   without written justification.
7. **Board** — milestone on LEDs, DIP sweep, then the coverage images.
   One bitstream per ROM image set (no program-select hardware invented).

Failure output follows NO BLIND COUNTERS: every assertion names the lying
signal and prints the decoded bus/T-state context.

Standing sim assertion (whole-core testbenches): no gated-clock edge may
fire while the sampled machine CLK is high. The bench invariant says none
can; the assertion makes an emitter or model bug that violates it loud
instead of silent.

## Design-ahead workflow (the point of all this)

After the copy is proven, new hardware is prototyped in this order:

1. Edit the **KiCad schematic** (new sheet or sheet change — stack, UART,
   third microcode EEPROM).
2. Regenerate: `fpga_gen.py` → VHDL, generators → ROM images.
3. Prove in simulation, then in fabric on the Versa.
4. Only then order parts and cut copper; the bench build follows the
   already-proven schematic.

The generated VHDL is **never hand-edited**. KiCad remains the single source
of truth; if fabric and schematic disagree, the schematic wins and the VHDL
is regenerated. This is the same "everything is generated, nothing is
retyped" doctrine extended to the FPGA.

## Non-goals

- No breadboard changes, no ISA changes in this port.
- No LiteX/Migen anywhere in this repo.
- No refactor of remote_8008; it is a pin-map reference only.
- No hand-written behavioral re-implementation of DINO modules — the only
  hand-written VHDL is the `ttl/` part-type library and the board shell.

## Open items (small, non-blocking)

- `pip install cocotb` — the one new dependency.
- Choose exact Versa LED/DIP/button pins when writing `versa.lpf`.
- Confirm the '382 model against `dino_alu_74f382_design.md` notes (carry
  chain detail) during its testbench work.
