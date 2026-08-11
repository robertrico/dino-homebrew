# Stack + third EEPROM — bring-up handoff

**Written 2026-08-11.** Entry point for a fresh session picking this up at the
bench. Read `tests/dino_bringup/BRINGUP.md`'s "STACK + THIRD EEPROM BRING-UP"
section alongside it — this document is the context, that one is the
procedure.

## Where things stand

Commit `22aa72e0`. Working tree clean.

**Built in schematic and simulation. Zero seconds on real silicon.**

    U23         AT28C64B   third microcode EEPROM, CW16-23     microcode
    U70 / U71   '138       SRC / DST bank-1 decoders           control_word
    U63-U66     '169       16-bit stack pointer                stack_pointer
    U67 / U68   '245       SP hi/lo readback -> MDR            stack_pointer
    U69         '08        ~{SP_CE} = AND(~SP_UP, ~SP_DOWN)    stack_pointer
    U72 / U73   '245       PC0-7 / PC8-15 -> MDR               mdr

    LXISP 0x14   CALL 0x33   RET 0x34
    PUSHA 0x61   POPA 0x62   PUSHB 0x63   POPB 0x64

`make -C fpga verify` green in ~148s: host 147/147, fuzz 20/20, cocotb 40/40.
Every image synthesizes and closes timing (DP16KD 40/108, 17.22MHz vs a 12MHz
constraint).

**The committed microcode is not known-broken.** `PROG_stack` lands `OB=0x27`
on the whole-core gate model. Two earlier RET drafts were wrong; both were
caught in simulation and are now policing rules.

## Instruments available

    LA (DSLogic)   16ch at speed -- the primary instrument
    LEDs           OB, 8 bits, the acceptance signal
    Scope (SDS)    analog. Edge quality, ringing, real levels
    DMM            continuity with the board OFF; static levels

**The rig (ATmega2560) is detached.** No rig tests. STEP-CLOCK has no driver
either — it was the rig injecting at `CLKIN` (`U20.2`) with Y1 disabled. A
debounced button ('14 + RC) restores it if wanted.

## The plan, in order

    1  COPPER      land and beep every new wire, board OFF
    2  BURN        three ROMs
    3  LA          watch the stack instructions execute
    4  SHOWCASE    an LED program that makes it visible   <- to design

Test after each wiring step rather than at the end.

### 1. Copper

    python3 docs/notes/kicad_contracts.py --continuity \
        U23 U63 U64 U65 U66 U67 U68 U69 U70 U71 U72 U73

39 nets. Each line names the NEW pins to land and the existing pins to beep
against. Generated from the netlist so it cannot be incomplete — that is the
MAR-lo lesson (two runs, nine wires, never landed, because the hand-written
list could not contain a wire nobody knew about).

Beep each new pin against its NEIGHBOURS too. Board OFF: in-circuit
leg-to-leg on a live board reads clamp diodes.

**Two part-specific traps, both invisible to a round-trip test:**

- **'169 pin 1 is `U/~D`, not `~MR`.** Both '163s here (`U6`, `U20`) wire pin
  1 as a clear and `U20`'s is strapped to `+5V`. Doing that on a '169
  hardwires SP to count up only — `~{SP_DOWN}` asserts and nothing happens.
  A single PUSH/POP pair still works perfectly; nested calls corrupt.
- **`P` and `Q` number in opposite directions.** `P0-P3` = 3,4,5,6 ascending;
  `Q0-Q3` = 14,13,12,11 descending. On a DIP16 those pins sit directly
  opposite each other, so wiring by POSITION is safe and wiring by pin-number
  sequence gives a whole-nibble reversal.

### 2. Burn

    python3 docs/notes/microcode_gen.py   # U9, U15, U23 + diag pair, all CRCs
    python3 docs/notes/progrom_gen.py     # PROG_stack.bin among others

**Three ROMs, not one.** Adding instructions writes rows in every byte of the
24-bit word. CRCs are pinned as literals in `test_microcode_gen.py`, so a
different printed value means a deliberate change or a bug, never drift.

Verify each with the TL866's read-back. `U23_diag.bin` exists but nothing can
walk 4096 rows in-circuit right now (that was the rig) — burn the real image.

### 3. LA

T-state traces are generated from the microcode, never transcribed. Regenerate:

    python3 -c "import sys;sys.path.insert(0,'docs/notes');import microcode_gen as g;\
    print(g.INSTRUCTIONS['RET'])"

The full table is in BRINGUP.md. Two rows earn a channel — not because they
are suspect, but because they are where a COPPER fault is most legible:

- **`RET` T8/T9**, the tightest sequential dependency in the ISA. T8 parks the
  return HI byte in MDR, T9 replays it into `MAR_HI`. MDR holds for exactly
  ONE state. MDR-side wiring trouble surfaces here first.
- **`CALL` T3/T7**, the only consumer of the sixteen new `PC0-15` wires.

**OPEN — channel assignment.** Not decided, and shouldn't be until the board
is in front of you. Frame is likely `T0-3` + `CLK` (5 channels), leaving 11
from: `~{SP_LO_OUT}`, `~{SP_HI_OUT}`, `~{SP_LO_LOAD}`, `~{SP_HI_LOAD}`,
`~{SP_UP}`, `~{SP_DOWN}`, `~{PC_LO_OUT}`, `~{PC_HI_OUT}`, `~{RAM_LOAD}`,
`~{MDR_OUT}`, `HALT`.

### 4. Showcase — OPEN, to design

`PROG_stack` is the correctness witness, not a demonstration: two different
bytes pushed, popped into swapped registers, subtracted inside a subroutine,
one `OUT` after the `RET`.

    OB = 0x27   everything worked
    OB = 0xD9   the pops came back in the wrong order
    no OUT      CALL/RET never returned

One number at the end. A demonstration image — nested calls at visible depth,
or a pattern only correct LIFO could produce — is still to design.
`PROG_cylon` is the precedent for an image whose job is to be watched.

## Facts worth having in hand

**Bus architecture.** `MDR0-7` is the internal bus, `W` is the ALU/destination
side, `U25` bridges them. Selecting SRC bank 1 disables `U28`, so `SRC_ACTIVE`
floats high and the bridge turns on pointed MDR→W — which is why every bank-1
source lands on MDR and why a W-side one would fight it.

**SP clocks on CLK, not ~CLK.** `LE = NOR(~LOAD, CLK)` makes MAR/registers
transparent while CLK is low, so a ~CLK-clocked SP would land a post-count
value in MAR on a row that both reads SP and counts it.

**SP has no clear.** Real '169 silicon powers up random. Every program must
run `LXISP` first. The VHDL model and the Python oracle both power up
non-zero on purpose so a missing `LXISP` fails loudly instead of passing in
sim and failing on the bench.

**Timing.** CALL is 12 T-states, RET 14, at ~977ns each — 25.4us round trip.
That is within one clock of an 8080's CALL+RET (27). Half of each instruction
is SP→MAR address plumbing, because SP is not an address source. Route C (SP
drives `MAR0-15`) would make it 8 and 6, and `~{ADDR_SEL1}` is already burned
into all 4096 rows waiting for it. Documented in
`dino_hardware_growth_plan.md` step 4b, rejected for now on reversibility
grounds, not performance.

## Things NOT to treat as settled

**Bus levels have never been characterised on a healthy machine.** Every
recorded reading was taken during a debugging session, and the main set was
taken while `W[0..7] -> U55/U58` was *unwired* — eight floating inputs on the
bus that read 2.26V. Those numbers were being carried in CLAUDE.md as
standing fact and were removed 2026-08-11. See
`dino_mar_lo_investigation.md`. Characterising a healthy bus is its own
initiative.

**HALT does not hold.** Pre-existing, unexplained. The machine halts then
escapes after a few seconds. The "it's a level problem, not logic" reading is
an inference from CET being sampled every clock — not a measurement.

**Six word bits are burned and wired to nothing:** `~{CIN_SEL}`,
`~{MISC_BANK}`, `~{ADDR_SEL1}`, `FLAG_SEL0/1`, `FLAG_POL`. Reserve, not
coverage. Nothing can fail on them because nothing consumes them.

## What the FPGA cannot tell you

Analog levels, real propagation on breadboard wire, fan-out, and whether a
wire was landed. Those are bench questions and always will be. A green
`make -C fpga verify` says the logic is right, not that the machine is.

## Next after this

ADC/SBB is one `74LS157` — `S = ~{CIN_SEL}`, `I1` = the existing opcode
carry, `I0` = `FLAG_C`, zero inverters, one of four sections used. Plus two
opcodes; the `word()` kwarg and its policing already exist. Cheapest
remaining item in the machine.

Flag branches (`JC`/`JN`/`JV`, both senses) want a `'153` — or two `'157`s
chained, which is what's on hand, since a `'157`'s four sections share one
select line and a 4:1 needs two.
