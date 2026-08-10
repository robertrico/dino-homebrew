# DINO FPGA Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exact virtual copy of the breadboard DINO on the ECP5 Versa — every chip instanced with its U-number inside sheet-mirrored VHDL modules, generated from the KiCad netlist, running the byte-identical burned ROM images, full ISA proven in simulation and on the board.

**Architecture:** Hand-written VHDL library of 74-series part-type models (`fpga/ttl/`, combinational parts pure, stateful parts sampled against a hidden 100 MHz `clk_sys`); a Python emitter (`docs/notes/fpga_gen.py`) that walks the KiCad netlist and generates one entity per schematic sheet plus `dino_core.vhd`; a thin hand-written Versa shell. Spec: `docs/superpowers/specs/2026-08-08-dino-fpga-port-design.md`.

**Tech Stack:** VHDL-2008, GHDL, cocotb (Python testbenches), yosys+ghdl-plugin → nextpnr-ecp5 → ecppack (all from `~/oss-cad-suite/bin`), Python 3 host tests with the existing `docs/notes` generator ecosystem.

## Global Constraints

- **NEVER commit.** Every "commit" checkpoint means: STOP and ask Rico. Rico commits when Rico decides (CLAUDE.md rule 1).
- All EDA tools via `TOOLS=$HOME/oss-cad-suite/bin` — never the Homebrew yosys/ghdl (plugin mismatch).
- Target device: `LFE5UM5G-45F`, package `CABGA381` (nextpnr: `--um5g-45k --package CABGA381`).
- VHDL-2008 everywhere (`--std=08`). Entities/files lower_snake_case: `ttl_74ls02.vhd` → `entity ttl_74ls02`.
- Active-low signals suffixed `_n`.
- Generated VHDL (`fpga/gen/`) is never hand-edited. KiCad is the single source of truth.
- Pin→port maps are **derived from the netlist pin functions wherever KiCad provides them** (`parse_with_pinfunction`); hand-written only for the five plain-gate types whose KiCad pins are unnamed. Never typed from datasheet memory (house rule 5).
- TDD: every model, emitter feature, and sim gets its test FIRST, RED before GREEN.
- Test failures must name the lying signal (NO BLIND COUNTERS).
- ROM images come from `microcode_gen.py`/`progrom_gen.py` output (`roms/*.bin`) — never re-typed; expected program results come from `progrom_gen.simulate()` at test runtime — never hand-computed.

**Machine facts the implementer needs (verified against this repo):**

- Ten sheets: `dino_v0_0_2` (root: clock/reset), `program_counter`, `mar`, `mdr`, `memory`, `microcode`, `control_word`, `registers_a_b`, `alu`, `input_output`.
- Part types in the netlist: 74LS00/7400, 74LS02, 74LS04, 74HC14, 74LS08, 74LS74, 74LS138, 74LS157, 74LS163, 74LS193, 74LS244(N), 74LS245, 74LS273, 74LS373, 74F382 (custom lib `2026-07-13_03-50-17:74F382PC`), AT28C64B ×2 (microcode), AT28C256 (program ROM), MCM60256AP (32K SRAM), CXO_DIP14 (Y1, 4 MHz), SW_Push, SW_DIP_x08, plus R/C/LED/power symbols (boundary/excluded).
- Multi-unit gate symbols appear once **per gate unit** in the schematic but share one reference — the emitter must group units by reference into one chip instance.
- '163 clear is SYNCHRONOUS; '193 load/clear are ASYNCHRONOUS with separate UP/DOWN clock pins; '373 is a transparent latch (level-sensitive LE); '245 is bidirectional (VHDL `inout`).
- The machine commits all state on CLK low (see CLAUDE.md "machine invariant") — the standing sim assertion in Task 11 encodes this.
- `kicad_contracts.build_contracts(root)` → cross-sheet contract signals (module ports). `kicad_xsheet_audit.export_netlist(root)` + `kicad_contracts.parse_with_pinfunction(netfile)` → `(values, nets)` structured netlist with pin-function names (e.g. `U13.1(DIR)`).
- Versa pins (from `~/Development/remote_8008/litex-boards/litex_boards/platforms/lattice_versa_ecp5.py`): clk100 = P3 **LVDS**; rst_n button = T1 LVCMOS33; LEDs (active-low) E16 D17 D18 E18 F17 F18 E17 F16 (LVCMOS25); DIP switches H2 K3 G3 F2 (LVCMOS15) J18 K18 K19 K20 (LVCMOS25).

---

### Task 1: Toolchain spike — tri-state bus + cocotb + full synthesis pass

Kills the two unproven paths before anything depends on them: (a) internal `'Z'` bus through ghdl-yosys-plugin → tribuf → nextpnr; (b) cocotb driving oss-cad-suite's GHDL via VPI (host Python is 3.14 — if cocotb chokes on it, resolve now: try `pip install cocotb`, if incompatible use a `python3.12` venv for the sim harness and record that in the Makefile).

**Files:**
- Create: `fpga/spike/spike_bus.vhd`
- Create: `fpga/spike/test_spike_bus.py`
- Create: `fpga/spike/Makefile`

**Interfaces:**
- Produces: proven `make sim` / `make synth` patterns that every later Makefile copies; the cocotb+GHDL invocation recipe; confirmation that `'Z'` survives synthesis.

- [ ] **Step 1: Install cocotb**

```bash
python3 -m pip install cocotb
cocotb-config --version
cocotb-config --makefiles   # MUST print a path — see below
```

If pip refuses (externally-managed) use `python3 -m pip install --user cocotb`. If cocotb does not support Python 3.14, create `python3.12 -m venv ~/.venvs/dino-fpga` and use its python/cocotb-config in all Makefiles.

**Known hazard, check now:** cocotb 2.x deprecates the classic `cocotb-config --makefiles` flow this plan's Makefiles use, in favor of a Python runner API. If `--makefiles` is absent or warns of removal, either pin `pip install 'cocotb<2.0'` or convert the spike Makefile's sim target to the runner API (`cocotb.runner.get_runner("ghdl")`) — and whichever you pick here is the pattern every later Makefile copies.

- [ ] **Step 2: Write the spike DUT — two tri-state drivers sharing one bus**

`fpga/spike/spike_bus.vhd`:

```vhdl
library ieee;
use ieee.std_logic_1164.all;

entity spike_bus is
  port (
    en_a_n : in  std_logic;
    en_b_n : in  std_logic;
    a_val  : in  std_logic_vector(7 downto 0);
    b_val  : in  std_logic_vector(7 downto 0);
    y      : out std_logic_vector(7 downto 0));
end entity;

architecture rtl of spike_bus is
  signal bus_w : std_logic_vector(7 downto 0);
begin
  bus_w <= a_val when en_a_n = '0' else (others => 'Z');
  bus_w <= b_val when en_b_n = '0' else (others => 'Z');
  y     <= bus_w;
end architecture;
```

Add a second entity in the same file exercising `inout` ('245-style, the other tri-state shape Task 3 needs and synthesis must survive):

```vhdl
entity spike_xcvr is
  port (dir  : in    std_logic;
        oe_n : in    std_logic;
        a    : inout std_logic_vector(7 downto 0);
        b    : inout std_logic_vector(7 downto 0));
end entity;

architecture rtl of spike_xcvr is
begin
  b <= a when (oe_n = '0' and dir = '1') else (others => 'Z');
  a <= b when (oe_n = '0' and dir = '0') else (others => 'Z');
end architecture;
```

- [ ] **Step 3: Write the failing cocotb test**

`fpga/spike/test_spike_bus.py`:

```python
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def bus_hands_off_between_drivers(dut):
    dut.a_val.value = 0x55
    dut.b_val.value = 0xAA
    dut.en_a_n.value = 0
    dut.en_b_n.value = 1
    await Timer(10, units="ns")
    assert dut.y.value == 0x55, f"driver A enabled: y={dut.y.value} not 0x55"
    dut.en_a_n.value = 1
    dut.en_b_n.value = 0
    await Timer(10, units="ns")
    assert dut.y.value == 0xAA, f"driver B enabled: y={dut.y.value} not 0xAA"
```

Add `fpga/spike/test_spike_xcvr.py` for the inout entity (run with `make MODEL=spike_xcvr`): drive `a` with `dir='1'`, assert `b` follows; release, drive `b` with `dir='0'`, assert `a` follows — cocotb writing an `inout` both ways proves the VPI path Task 3's '245 tests depend on.

- [ ] **Step 4: Write the Makefile**

`fpga/spike/Makefile`:

```make
TOOLS := $(HOME)/oss-cad-suite/bin
SIM ?= ghdl
TOPLEVEL_LANG := vhdl
VHDL_SOURCES := $(PWD)/spike_bus.vhd
TOPLEVEL := spike_bus
MODULE := test_spike_bus
EXTRA_ARGS += --std=08
export PATH := $(TOOLS):$(PATH)
include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: synth
synth:
	$(TOOLS)/yosys -m ghdl -p "ghdl --std=08 spike_bus.vhd -e spike_bus; tribuf -logic; synth_ecp5 -json spike.json"
	$(TOOLS)/nextpnr-ecp5 --um5g-45k --package CABGA381 --json spike.json --textcfg spike.cfg
	$(TOOLS)/ecppack spike.cfg spike.bit
	$(TOOLS)/yosys -m ghdl -p "ghdl --std=08 spike_bus.vhd -e spike_xcvr; tribuf -logic; synth_ecp5 -json spike_xcvr.json"
	$(TOOLS)/nextpnr-ecp5 --um5g-45k --package CABGA381 --json spike_xcvr.json --textcfg spike_xcvr.cfg
	$(TOOLS)/ecppack spike_xcvr.cfg spike_xcvr.bit
```

- [ ] **Step 5: Run the sim, expect it to pass; run synth, expect a .bit**

```bash
cd fpga/spike && make && make synth && ls -la spike.bit
```

Sim must PASS (if it errors on VPI/python version, fix per Step 1 before continuing). `make synth` must complete with no tri-state-related errors and produce `spike.bit`. Inspect the yosys log: the `'Z'` assignments must have become mux logic (search the log for `tribuf`).

- [ ] **Step 6: Checkpoint — ask Rico to commit** (suggested: `fpga: toolchain spike — tristate bus survives ghdl+yosys+nextpnr, cocotb harness works`)

---

### Task 2: `fpga_gen.py` scaffold, PIN_MAP, and the five plain-gate models

**Files:**
- Create: `docs/notes/fpga_gen.py` (PIN_MAP + pinmap-dump helper only, emission comes in Tasks 7–8)
- Create: `docs/notes/test_fpga_gen.py`
- Create: `fpga/ttl/ttl_74ls00.vhd`, `ttl_74ls02.vhd`, `ttl_74ls04.vhd`, `ttl_74hc14.vhd`, `ttl_74ls08.vhd`
- Create: `fpga/ttl/Makefile` (cocotb runner, parameterized by model — copied from spike pattern)
- Create: `fpga/ttl/test_gates.py`

**Interfaces:**
- Produces: `fpga_gen.PIN_MAP: dict[str, dict[int, str]]` mapping normalized part type → pin number → VHDL port name; `fpga_gen.normalize_type(lib_id, value) -> str` (folds `74xx:7400`+`74xx:74LS00`→`74LS00`, `74LS244N`→`74LS244`, the custom `74F382PC` lib id →`74F382`); `fpga_gen.dump_pinmap(root)` printing netlist pin functions per part type for deriving complex-part maps in later tasks.

- [ ] **Step 1: Write failing host tests for PIN_MAP and normalize_type**

In `docs/notes/test_fpga_gen.py`:

```python
import fpga_gen

def test_normalize_type_folds_families():
    assert fpga_gen.normalize_type("74xx:7400", "74LS00") == "74LS00"
    assert fpga_gen.normalize_type("74xx:74LS244N", "74LS244") == "74LS244"
    # the alu sheet contains BOTH value variants of the '382 — fold both
    assert fpga_gen.normalize_type("2026-07-13_03-50-17:74F382PC", "74F382PC") == "74F382"
    assert fpga_gen.normalize_type("2026-07-13_03-50-17:74F382PC", "74F382N") == "74F382"

def test_gate_pinmaps_complete():
    # every gate pin 1..14 mapped exactly once; power pins named vcc/gnd
    for t in ("74LS00", "74LS02", "74LS04", "74HC14", "74LS08"):
        pm = fpga_gen.PIN_MAP[t]
        assert set(pm.keys()) == set(range(1, 15)), f"{t}: pins {sorted(pm)} not 1..14"
        assert pm[7] == "gnd" and pm[14] == "vcc", f"{t}: power pins misnamed"

def test_vhdl_entities_match_pinmap():
    # parse each ttl/*.vhd entity port list; must equal PIN_MAP names minus vcc/gnd
    import re, pathlib
    for t, fname in [("74LS00","ttl_74ls00.vhd"), ("74LS02","ttl_74ls02.vhd"),
                     ("74LS04","ttl_74ls04.vhd"), ("74HC14","ttl_74hc14.vhd"),
                     ("74LS08","ttl_74ls08.vhd")]:
        src = (pathlib.Path(__file__).parents[2] / "fpga/ttl" / fname).read_text()
        ports = set(re.findall(r"^\s*(\w+)\s*:\s*(?:in|out|inout)\b", src, re.M))
        want = {n for p, n in fpga_gen.PIN_MAP[t].items() if n not in ("vcc", "gnd")}
        assert ports == want, f"{t}: VHDL ports {ports} != PIN_MAP {want}"
```

Run `python3 -m pytest docs/notes/test_fpga_gen.py -v` → FAIL (no module).

- [ ] **Step 2: Implement PIN_MAP for the five gate types + normalize_type + dump_pinmap**

Gate pinouts (the only hand-written maps; standard quad/hex packages):

```python
# docs/notes/fpga_gen.py
GATE_2IN = lambda: {1:"a1",2:"b1",3:"y1",4:"a2",5:"b2",6:"y2",7:"gnd",
                    8:"y3",9:"a3",10:"b3",11:"y4",12:"a4",13:"b4",14:"vcc"}
PIN_MAP = {
    "74LS00": GATE_2IN(), "74LS08": GATE_2IN(),
    # '02 NOR: outputs on 1,4,10,13
    "74LS02": {1:"y1",2:"a1",3:"b1",4:"y2",5:"a2",6:"b2",7:"gnd",
               8:"a3",9:"b3",10:"y3",11:"a4",12:"b4",13:"y4",14:"vcc"},
    # hex inverters
    "74LS04": {1:"a1",2:"y1",3:"a2",4:"y2",5:"a3",6:"y3",7:"gnd",
               8:"y4",9:"a4",10:"y5",11:"a5",12:"y6",13:"a6",14:"vcc"},
}
PIN_MAP["74HC14"] = dict(PIN_MAP["74LS04"])

def normalize_type(lib_id, value): ...
def dump_pinmap(root): ...   # prints {type: {pin: netlist pinfunction}} from
                             # kicad_xsheet_audit.export_netlist + parse_with_pinfunction
```

`dump_pinmap` walks the structured netlist and prints, per normalized type, every pin number with the pin-function name KiCad reports — this is how Tasks 3–6 derive the complex-part maps without datasheet memory.

- [ ] **Step 3: Run host tests → the two PIN_MAP tests pass, the VHDL test still fails (no files)**

- [ ] **Step 4: Write the five gate models**

`fpga/ttl/ttl_74ls02.vhd` (pattern; others identical shape with their function):

```vhdl
library ieee;
use ieee.std_logic_1164.all;

entity ttl_74ls02 is        -- quad 2-input NOR
  port (a1,b1,a2,b2,a3,b3,a4,b4 : in std_logic;
        y1,y2,y3,y4             : out std_logic);
end entity;

architecture rtl of ttl_74ls02 is
begin
  y1 <= a1 nor b1;  y2 <= a2 nor b2;
  y3 <= a3 nor b3;  y4 <= a4 nor b4;
end architecture;
```

'00: `nand`. '08: `and`. '04 and 'hc14: six inverters `y1 <= not a1;` etc. ('14 is Schmitt on the bench; digitally an inverter — the analog difference is out of scope by design).

- [ ] **Step 5: Write failing cocotb truth-table tests, then run**

`fpga/ttl/test_gates.py` (one test per model, exhaustive over inputs):

```python
import cocotb, itertools
from cocotb.triggers import Timer

@cocotb.test()
async def nor_truth_table(dut):
    for a, b in itertools.product((0, 1), repeat=2):
        dut.a1.value = a; dut.b1.value = b
        await Timer(1, units="ns")
        exp = int(not (a or b))
        assert dut.y1.value == exp, f"y1: a1={a} b1={b} -> {dut.y1.value}, want {exp}"
```

(Repeat the loop for gates 2–4 of each package, and equivalent tests for '00/'04/'08/'14 in the same file — every gate of every package exercised, every assertion naming the pin.) Makefile runs each model: `make MODEL=ttl_74ls02` sets `TOPLEVEL`/`MODULE` accordingly. Run all five: PASS. Re-run host tests: `test_vhdl_entities_match_pinmap` now PASSES.

- [ ] **Step 6: Checkpoint — ask Rico to commit**

---

### Task 3: Combinational MSI models — '138, '157, '244, '245

**Files:**
- Create: `fpga/ttl/ttl_74ls138.vhd`, `ttl_74ls157.vhd`, `ttl_74ls244.vhd`, `ttl_74ls245.vhd`
- Create: `fpga/ttl/test_msi.py`
- Modify: `docs/notes/fpga_gen.py` (add the four PIN_MAP entries)
- Modify: `docs/notes/test_fpga_gen.py` (extend both completeness tests to the new types)

**Interfaces:**
- Produces: PIN_MAP entries whose names come from `dump_pinmap` output (netlist pin functions — e.g. '245 pin 1 is `DIR`, pin 19 `OE_n`-equivalent as KiCad names it); `ttl_74ls245` with `inout` A/B ports.

- [ ] **Step 1: Run `python3 -c "import sys;sys.path.insert(0,'docs/notes');import fpga_gen;fpga_gen.dump_pinmap('dino_v0_0_2/dino_v0_0_2.kicad_sch')"` and copy the printed pin→name maps for 74LS138/157/244/245 into PIN_MAP verbatim** (lower-cased, `~`→`_n`). Where KiCad reports an empty name (it does for some pins), fill from the same chip's other unit or the KiCad symbol editor — never from memory — and note the source in a comment.

- [ ] **Step 2: Extend host tests (failing): PIN_MAP completeness for the four new types ('138/'157: pins 1..16; '244/'245: 1..20), VHDL-ports-match test extended.** Run → FAIL.

- [ ] **Step 3: Write the models.** '138: 3→8 decoder, outputs active low, three enables (`y <= "11111111"; if g1='1' and g2a_n='0' and g2b_n='0' then y(to_integer(unsigned(c&b&a))) <= '0'; end if;` in a process). '157: quad 2:1 mux with active-low strobe. '244: two 4-bit tri-state buffers (`y <= a when g_n='0' else 'Z'` per bit). '245:

```vhdl
entity ttl_74ls245 is       -- octal bus transceiver
  port (dir  : in    std_logic;          -- '1': A->B, '0': B->A
        oe_n : in    std_logic;
        a    : inout std_logic_vector(8 downto 1);
        b    : inout std_logic_vector(8 downto 1));
end entity;

architecture rtl of ttl_74ls245 is
begin
  b <= a when (oe_n = '0' and dir = '1') else (others => 'Z');
  a <= b when (oe_n = '0' and dir = '0') else (others => 'Z');
end architecture;
```

(If the KiCad symbol names individual pins `A1..A8`/`B1..B8` rather than vectors, the entity uses individual `std_logic` ports to match PIN_MAP one-to-one — the emitter maps pin-by-pin either way; prefer whatever makes `test_vhdl_entities_match_pinmap` pass without special cases.)

- [ ] **Step 4: cocotb tests in `test_msi.py`** — '138: all 8 select codes × enable combinations; '157: both selects, strobe high forces zeros; '244: drive vs 'Z' per section; '245: both directions AND the released side reads back what an external driver puts on it (cocotb drives `a` while `dir='0'` — asymmetric, per the mirror-witness rule). Run → PASS.

- [ ] **Step 5: Checkpoint — ask Rico to commit**

---

### Task 4: The '382 ALU model

**Files:**
- Create: `fpga/ttl/ttl_74f382.vhd`
- Create: `fpga/ttl/test_74f382.py`
- Modify: `docs/notes/fpga_gen.py` (+PIN_MAP entry from `dump_pinmap`, cross-checked against `docs/notes/dino_alu_74f382_design.md`)
- Modify: `docs/notes/test_fpga_gen.py` (extend completeness tests)

**Interfaces:**
- Produces: `ttl_74f382` — S(2:0) op select, A/B(3:0), Cn in, F(3:0), Cn+4, OVR. Op table (from the design note, which is netlist-verified): 0=CLEAR(0000), 1=B−A, 2=A−B, 3=A+B, 4=A XOR B, 5=A OR B, 6=A AND B, 7=PRESET(1111). **Verify this table against `dino_alu_74f382_design.md` before writing the test; the note wins over this plan.**

- [ ] **Step 1: Write the failing exhaustive test** — all 8 ops × all 256 A/B pairs × both carries, expected computed in Python (arithmetic ops as 4-bit adds with carry per F382 datasheet semantics: subtraction as complement-and-add, carry out and overflow from the 4-bit result). Assertions name op/a/b/cin on failure.
- [ ] **Step 2: Run → FAIL (no entity).**
- [ ] **Step 3: Implement** — a single process computing a 5-bit unsigned result for the three arithmetic ops (`b - a`, `a - b`, `a + b`, each `+ cin` per '382 convention: subtrahend complemented, Cn active-high borrow-free), logic ops direct, OVR from bit3/bit4 carry disagreement. Run → PASS, all 4096+ vectors.
- [ ] **Step 4: Checkpoint — ask Rico to commit**

---

### Task 5: Stateful models — '74, '163, '193, '273, '373

Every stateful model takes `clk_sys` and samples its datasheet "clock"/"latch" pins through a 2-flop synchronizer + edge/level detector. No fabric register ever clocks on a modeled logic net.

**Files:**
- Create: `fpga/ttl/ttl_74ls74.vhd`, `ttl_74ls163.vhd`, `ttl_74ls193.vhd`, `ttl_74ls273.vhd`, `ttl_74ls373.vhd`
- Create: `fpga/ttl/test_stateful.py`
- Modify: `docs/notes/fpga_gen.py` (+5 PIN_MAP entries via `dump_pinmap`; also add `STATEFUL_TYPES = {"74LS74","74LS163","74LS193","74LS273","74LS373","MCM60256AP"}` — the set the emitter threads `clk_sys` to)
- Modify: `docs/notes/test_fpga_gen.py`

**Interfaces:**
- Produces: the canonical edge-detect pattern all five share; `fpga_gen.STATEFUL_TYPES` consumed by the emitter (Task 8) and its host tests.

- [ ] **Step 1: Failing cocotb tests first**, driving pin-level waveforms against a 100 MHz `clk_sys` clock started with `cocotb.start_soon(Clock(dut.clk_sys, 10, units="ns").start())`:
  - '74: D captured on CLK rise only; PRE_n/CLR_n asynchronous dominance.
  - '163: **synchronous** clear (CLR_n low + clock edge → zero; no edge → unchanged — assert both), sync load, count only when CET·CEP, RCO at 15.
  - '193: separate UP/DOWN clock pins, **asynchronous** load (LOAD_n low loads immediately, no clock), asynchronous CLR (active high), borrow/carry outs.
  - '273: 8-bit register, async MR_n.
  - '373: **transparent** while LE high (output follows D combinationally — assert mid-level change propagates), latched on LE fall; OC_n tristates Q.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.** Pattern (from '74, reused by all):

```vhdl
architecture rtl of ttl_74ls74 is
  signal clk1_m : std_logic_vector(2 downto 0) := (others => '0');
  signal q1_i   : std_logic := '0';
begin
  process (clk_sys)
  begin
    if rising_edge(clk_sys) then
      clk1_m <= clk1_m(1 downto 0) & clk1;            -- 2-flop sync + history
      if pre1_n = '0' then q1_i <= '1';
      elsif clr1_n = '0' then q1_i <= '0';
      elsif clk1_m(1) = '1' and clk1_m(2) = '0' then  -- detected rising edge
        q1_i <= d1;
      end if;
    end if;
  end process;
  q1   <= q1_i;
  q1_n <= not q1_i;
end architecture;
```

'373 differs: while sampled LE is high, `q <= d` combinationally (transparent path is combinational; only the held value is registered on detected LE fall). '193 clocks both UP and DOWN pins through their own detectors; async LOAD_n/CLR handled at the top of the process like PRE/CLR above.

- [ ] **Step 4: Run → PASS. Host tests for the new PIN_MAP entries and STATEFUL_TYPES membership → PASS.**
- [ ] **Step 5: Checkpoint — ask Rico to commit**

---

### Task 6: Memory models + ROM hex flow

**Files:**
- Create: `fpga/ttl/ttl_at28c64b.vhd`, `ttl_at28c256.vhd`, `ttl_mcm60256.vhd`
- Create: `fpga/ttl/test_memory.py`
- Modify: `docs/notes/fpga_gen.py` (add `bin2hex(src_bin, dst_hex)` — one byte per line, `%02x`; +3 PIN_MAP entries via `dump_pinmap`)
- Modify: `docs/notes/test_fpga_gen.py` (bin2hex round-trip test; PIN_MAP completeness)

**Interfaces:**
- Produces: ROM entities with `generic (init_file : string; addr_bits : positive)`, async read (`d <= mem(addr) when ce_n='0' and oe_n='0' else 'Z'`), loaded via VHDL-2008 textio at elaboration; RAM with same read path plus `clk_sys`-sampled write (WE_n low sampled level while CE_n low commits `mem(addr) <= d` — matching the bench NAND(WRITE_DIR, ~CLK) discipline upstream); `bin2hex` used by sim Makefiles and Task 13.

- [ ] **Step 1: Failing tests**: bin2hex round-trip host test; cocotb: ROM loaded from a known 16-byte hex file returns exact bytes, tri-states when deselected; RAM write-then-read PLUS the asymmetric witness — write via the data port, read back with a DIFFERENT address order than written (permutation-blind guard, mirror-witness rule).
- [ ] **Step 2: Run → FAIL. Implement. Run → PASS.**
- [ ] **Step 3: Checkpoint — ask Rico to commit**

---

### Task 7: Emitter — structured netlist, instance grouping, sheet assignment

**Files:**
- Modify: `docs/notes/fpga_gen.py`
- Modify: `docs/notes/test_fpga_gen.py`

**Interfaces:**
- Consumes: `kicad_xsheet_audit.export_netlist`, `kicad_contracts.parse_with_pinfunction`, `kicad_contracts.build_contracts`.
- Produces: `fpga_gen.load_design(root) -> Design` where `Design.instances: dict[ref, Instance]` (`Instance.type` normalized, `.sheet`, `.pins: dict[int, netname]` merged across units) and `Design.sheet_ports: dict[sheet, list[PortSig]]` from `build_contracts` (signal name, direction, width). This is the single data structure Tasks 8+ consume.

- [ ] **Step 1: Write failing host tests pinned to verified netlist facts:**

```python
def test_load_design_groups_units_and_assigns_sheets():
    d = fpga_gen.load_design(ROOT)
    u1 = d.instances["U1"]                      # PC counter, program_counter sheet
    assert u1.type == "74LS193"
    assert u1.sheet == "program_counter"
    assert u1.pins[4] == "+5V"                  # DOWN clock strapped high (verified)
    # a multi-unit gate chip appears ONCE with all 14 pins merged
    gates = [i for i in d.instances.values() if i.type == "74LS02"]
    assert all(set(g.pins) <= set(range(1, 15)) and len(g.pins) >= 12 for g in gates), \
        "a 74LS02 instance is missing unit pins - units not merged by reference"

def test_every_chip_on_exactly_one_sheet():
    d = fpga_gen.load_design(ROOT)
    for ref, inst in d.instances.items():
        assert inst.sheet in fpga_gen.SHEETS, f"{ref} landed on unknown sheet {inst.sheet!r}"
```

- [ ] **Step 2: Run → FAIL. Implement `load_design`.** The netlist export gives components with sheetpaths and per-net pin lists with functions; group by reference, normalize types, attach nets to pin numbers. If `parse_with_pinfunction`'s return shape differs from assumption, adapt the implementation — **the tests are the contract**, and they pin real facts (`U1.4 → +5V`) read from `build_report` output, not guesses.
- [ ] **Step 3: Run → PASS.**
- [ ] **Step 4: Checkpoint — ask Rico to commit**

---

### Task 8: Emitter — boundary table, power ties, VHDL emission

**Files:**
- Modify: `docs/notes/fpga_gen.py`
- Modify: `docs/notes/test_fpga_gen.py`
- Create (generated, checked in for diffability like the ROM images): `fpga/gen/*.vhd` — nine sheet entities + `dino_core.vhd`

**Interfaces:**
- Produces: `fpga_gen.emit(root, outdir)` writing one entity per sub-sheet (ports = contract signals + `clk_sys` + boundary nets) and `dino_core.vhd` (the root sheet's own chips + instances of the nine modules; ports = boundary only: `clk4m_y1 : in`, `dip_sw : in (7 downto 0)`, `btn_reset_n : in`, `ob_led : out (7 downto 0)`, `halt : out`, plus `clk_sys`). Every chip instance `U<n>: entity work.ttl_<type> port map (...)` with nets mapped per PIN_MAP.
- **Boundary/exclusion table** (explicit, host-tested): power symbols and C/R/LED dropped; net `GND`→`'0'`, `+5V`→`'1'` wherever they feed logic pins; `CXO_DIP14` (Y1) removed, its OUT-pin net becomes port `clk4m_y1`; `SW_DIP_x08` removed → `dip_sw` ports; `SW_Push` removed → `btn_reset_n` port (the button's net into the debounce '74 — NOT the RESET net, which stays U27-driven exactly as copper); LED anode nets → `ob_led` outputs; HALT/END consumer nets (U61.3/U61.5 taps) → `halt` output. Unconnected model outputs emit `open`; an unconnected model INPUT is a hard error unless listed in `NC_ALLOWED` with a tie value.
- **Also emitted: `fpga/gen/gated_clocks.txt`** — every net that drives a clock/latch pin of a `STATEFUL_TYPES` instance and is not machine CLK itself, one net name per line. Task 11's standing invariant monitor consumes this file; the host tests assert it is non-empty and lists only nets that exist in the generated VHDL.

- [ ] **Step 1: Failing host tests:**

```python
def test_emit_every_chip_once_every_net_somewhere(tmp_path):
    fpga_gen.emit(ROOT, tmp_path)
    src = "".join(p.read_text() for p in tmp_path.glob("*.vhd"))
    d = fpga_gen.load_design(ROOT)
    for ref, inst in d.instances.items():
        if inst.type in fpga_gen.EXCLUDED_TYPES: continue
        n = len(re.findall(rf"\b{ref}\s*:\s*entity work\.ttl_", src))
        assert n == 1, f"{ref} instantiated {n} times"

def test_clk_sys_threaded_to_every_stateful_instance(tmp_path): ...
    # for each instance whose type is in STATEFUL_TYPES, its port map
    # contains "clk_sys => clk_sys"; every generated entity declares clk_sys

def test_no_hand_edit_marker(tmp_path): ...
    # every generated file starts with "-- GENERATED by fpga_gen.py - DO NOT EDIT"

def test_boundary_table_covers_all_excluded_refs(tmp_path): ...
    # every excluded component's every pin is either 'drop' or mapped to a port;
    # anything unaccounted is a hard failure listing the ref.pin
```

Plus a golden-file test: `emit` output for the `mar` sheet (smallest) compared line-for-line against a committed golden written once by eye-review of the first output.

- [ ] **Step 2: Run → FAIL. Implement emission.** VHDL signal names from net names via a sanitizer (`~`→`_n_`, `/`→`_`, leading digit → `n_` prefix, collision check that FAILS loudly on duplicates). Multi-driver nets (the W bus, '245 inouts) are plain `std_logic` signals resolved by 'Z' semantics — no special casing.
- [ ] **Step 3: Run host tests → PASS. Then the elaboration gate:**

```bash
cd fpga && $HOME/oss-cad-suite/bin/ghdl -a --std=08 ttl/*.vhd gen/*.vhd && \
  $HOME/oss-cad-suite/bin/ghdl -e --std=08 dino_core
```

Zero errors. This catches type/port mismatches the regex tests can't.

- [ ] **Step 4: Checkpoint — ask Rico to commit** (generated files included — they are artifacts-of-record like `roms/*.bin`)

---

### Task 9: Per-module testbench pattern — program_counter first

**Files:**
- Create: `fpga/sim/Makefile` (cocotb, `MODULE_UNDER_TEST` parameterized, VHDL_SOURCES = ttl + gen)
- Create: `fpga/sim/test_module_program_counter.py`

**Interfaces:**
- Produces: the module-TB pattern: stimulus/assertion signals are exactly the sheet's contract ports (the same signals the rig DRIVEs and SAMPLEs — same doctrine, new instrument). Each test docstring names the rig test it ports.

- [ ] **Step 1: Failing test** — port the PC module's rig assertions: clear then count on CLK-low commits (PC_UP gating), PC_LOAD behavior, rollover carry between '193 stages. Drive the contract ports (CLK, PC_UP, PC_LOAD, W-side inputs), sample PC outputs. Expected values computed in the test, failures print T-by-T decode.
- [ ] **Step 2: Run → FAIL is expected only if the model/emitter has a bug — this TB validates generated wiring, so a PASS on first run is legitimate (the RED phase for generated code lived in Tasks 7–8 host tests). Investigate any failure down to the named signal before touching models.**
- [ ] **Step 3: Run → PASS. Checkpoint — ask Rico to commit**

---

### Task 10: Per-module testbenches — remaining eight sheets

**Files:**
- Create: `fpga/sim/test_module_{mar,mdr,memory,microcode,control_word,registers_a_b,alu,input_output}.py`

Same pattern as Task 9. Minimum assertion set per module, each naming its ported rig test: mar (latch + address drive), mdr (both bus directions — asymmetric, mirror-witness), memory (RAM write on CLK low only; ROM/RAM decode), microcode (ROM word for known (opcode,T) pairs matches `microcode_gen.build_real()` — import it, never retype), control_word (strobe decode one-hot), registers_a_b (load commits on CLK low, bus output enables), alu (SA field reaches '382 uninverted — port `test_sa_field_reaches_the_382_uninverted`'s spirit against generated wiring; ADD produces sum not AND), input_output (OB latch, PROG_in switch path through the io '244).

- [ ] **Step 1: Write all eight (failing-or-validating per Task 9 note). Step 2: Run → all PASS. Step 3: Checkpoint — ask Rico to commit**

---

### Task 11: Whole-core simulation — milestone + IN + standing invariant assertion

**Files:**
- Create: `fpga/sim/test_core_milestone.py`
- Create: `fpga/sim/conftest_helpers.py` (ROM-image prep: run `microcode_gen`/`progrom_gen` mains if `roms/` stale, `bin2hex` into `fpga/sim/hex/`)

**Interfaces:**
- Consumes: `dino_core`, ROM hex images, `progrom_gen.simulate()` as oracle.
- Produces: `run_program(dut, prog_hex, switches, max_us)` helper reused by Task 12.

- [ ] **Step 1: Failing test:**

```python
@cocotb.test()
async def milestone_free_runs_to_4d(dut):
    """LDAI 0xFF; OUT; LDAI 0x2F; LDBI 0x1E; ADD; OUT; HALT -> OB=0x4D.
    Oracle: progrom_gen.simulate(), never hand-typed."""
    exp = oracle_final_ob("real")          # progrom_gen tag: "real" = milestone image
    await power_on(dut)                    # clk_sys 100MHz, div-25 tick on clk4m_y1
    await wait_halt(dut, timeout_us=500)
    assert dut.ob_led.value == exp, f"OB={int(dut.ob_led.value):#04x} want {exp:#04x}"

@cocotb.test()
async def in_tracks_switches(dut):
    for sw, want in ((0x01, 0x30), (0x1E, 0x4D)):
        ... # "in" image, dip_sw=sw, expect OB==want (also cross-checked
            # against progrom_gen.simulate(switches=sw))
```

Plus the **standing invariant monitor**, started in every whole-core test: a coroutine sampling every net listed in `fpga/gen/gated_clocks.txt` (a Task 8 deliverable) and asserting none rises while sampled machine CLK is high. Violation prints the net name and T-state.

- [ ] **Step 2: Run → investigate any failure to the named signal (this is the SA-field moment for the whole port — the first time encoding meets generated wiring).**
- [ ] **Step 3: PASS both. Checkpoint — ask Rico to commit**

---

### Task 12: Full burned ISA in simulation — alu, mem, flow, loop images

**Files:**
- Create: `fpga/sim/test_core_coverage.py`

- [ ] **Step 1: One test per image.** Image tags are progrom_gen's own: the `COVERAGE` dict keys `alu`, `mem`, `flow`, `loop` (progrom_gen.py:473-482; .bin filenames are `PROG_<tag>.bin`) — plus `adda`/`addb` if `sim_supports()` covers them. For each tag: build hex, run `run_program`, compare final OB and halt state against `progrom_gen.simulate()` for that image. `mem` is the MAR-as-a-latch witness — its docstring says so.
- [ ] **Step 2: Run → PASS all. GHDL wall-time note: at 100 MHz clk_sys these are ≤ a few million delta cycles; if a run exceeds minutes, raise the div-25 tick ratio in sim only (generic on the TB harness, never in versa_top).**
- [ ] **Step 3: Checkpoint — ask Rico to commit**

---

### Task 13: Versa shell, LPF, synthesis gate

**Files:**
- Create: `fpga/top/versa_top.vhd`
- Create: `fpga/top/versa.lpf`
- Create: `fpga/Makefile` (synth targets, one bitstream per program image)

**Interfaces:**
- Consumes: `dino_core` ports from Task 8.
- Produces: `make -C fpga bit IMAGE=real` → `build/dino_real.bit`; same for tags `in`, `alu`, `mem`, `flow`, `loop` (progrom_gen's own tag names; IMAGE selects `roms/PROG.bin` for `real`, `roms/PROG_<tag>.bin` otherwise).

- [ ] **Step 1: versa_top** — LVDS clk100 input (P3), `clk_sys` = clk100 directly; ÷25 process → `clk4m_y1`; rst_n button (T1) → `btn_reset_n`; DIP → `dip_sw` (polarity: pass-through, flip after board check if inverted); LEDs active-low: `led <= not ob_led`. ROM image chosen at synthesis: the program-ROM init hex path is a generic set from the Makefile (`ghdl -gPROG_HEX=...` via yosys `ghdl` command generics).
- [ ] **Step 2: versa.lpf** — exact pins from the Global Constraints table:

```
LOCATE COMP "clk100" SITE "P3";     IOBUF PORT "clk100" IO_TYPE=LVDS;
LOCATE COMP "rst_n"  SITE "T1";     IOBUF PORT "rst_n"  IO_TYPE=LVCMOS33;
LOCATE COMP "led[0]" SITE "E16";    IOBUF PORT "led[0]" IO_TYPE=LVCMOS25;
... (all 8 LEDs: E16 D17 D18 E18 F17 F18 E17 F16)
LOCATE COMP "dip[0]" SITE "H2";     IOBUF PORT "dip[0]" IO_TYPE=LVCMOS15;
... (H2 K3 G3 F2 LVCMOS15; J18 K18 K19 K20 LVCMOS25)
FREQUENCY PORT "clk100" 100 MHZ;
```

- [ ] **Step 3: Synthesis gate** — `make bit IMAGE=real`: yosys `-m ghdl` analyzing ttl+gen+top, `tribuf -logic`, `synth_ecp5`; nextpnr `--um5g-45k --package CABGA381 --lpf top/versa.lpf`; ecppack. Requirements: timing met at 100 MHz (report in log), **zero inferred latches** (grep yosys log; the '373 transparent path is legal only through its clk_sys-registered form — a real latch cell in the report is a model bug), no unconstrained-pin warnings. Build all six image bitstreams.
- [ ] **Step 4: Checkpoint — ask Rico to commit**

---

### Task 14: Board bring-up procedure

**Files:**
- Create: `fpga/BRINGUP_FPGA.md`

- [ ] **Step 1: Write the bench-bible-style doc** (mirrors `tests/dino_bringup/BRINGUP.md` shape): per-bitstream flash command (`$HOME/oss-cad-suite/bin/openFPGALoader -b ecp5_versa build/dino_real.bit` — verify the board name with `openFPGALoader --list-boards`, fall back to `ecpprog`), what the LEDs must show (`PROG` → 0x4D pattern with LED polarity spelled out per-LED), the DIP sweep table for `PROG_in` (0x01→0x30, 0x1E→0x4D), reset-button behavior (FPGA power-up state ≠ bench U35 poison quirk — document the difference), and per-image expected finals **printed by a helper**: `python3 docs/notes/progrom_gen.py --expected` (add that flag if absent — it prints each image's simulate() final OB so the bench sheet is generated, not retyped).
- [ ] **Step 2: Rico flashes and checks.** Any board-vs-sim divergence is a finding to run down at the named signal — the sim, module TBs, and LA are the instruments, in that order.
- [ ] **Step 3: Checkpoint — ask Rico to commit; port complete when all six bitstreams behave per the doc.**

---

## Self-Review (performed at write time)

- **Spec coverage:** exact-copy structure (T7–8), sheet hierarchy (T8), chip guts fast-clock (T5), tri-state verbatim (T1, T3, T8), ROM byte-identity (T6, T11), full-ISA success criterion (T12, T14), toolchain spike (T1), clk_sys threading host-tested (T8), gated-clock standing assertion (T11), Y1 ÷25 at Y1's node (T8 boundary + T13), design-ahead workflow (enabled by T8's regeneration; documented in spec, no task needed), non-goals respected (no LiteX/Migen anywhere).
- **Placeholders:** none; every step has code, an exact command, or a named source of truth to copy from (`dump_pinmap`, design notes, `simulate()`).
- **Type consistency:** `load_design`/`Design`/`PIN_MAP`/`STATEFUL_TYPES`/`EXCLUDED_TYPES`/`bin2hex`/`run_program` names match across tasks 2, 5, 6, 7, 8, 11, 12.
