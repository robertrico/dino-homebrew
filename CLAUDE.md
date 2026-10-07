# CLAUDE.md — DINO (Discrete Integrated NISC Operator)

An 8-bit CPU built from discrete 74-series logic on breadboards, designed in
KiCad. Split out of the `hardware` portfolio repo on 2026-07-28 with full
history preserved.

This file states what the machine IS. What it was believed to be and turned
out not to be lives in `.git/sdd/MISTAKES_MISSTEPS.md`, dated. A retraction
goes there, not here; here the corrected fact replaces the wrong one.

## READ `.git/sdd/HANDOFF.md` FIRST

Rico, 2026-09-27: any session in this repo starts by reading
`.git/sdd/HANDOFF.md` -- the live bench state, where the probes are, and
the exact next action. It supersedes anything below that it contradicts.
Rewrite it at the end of each session.

## How this document is written

Every claim is one of three things, and says which:

- **fact** — measured, run, or extracted from the netlist, with the source
  named. Reproducible.
- **inference** — follows from a fact by reasoning.
- **open** — not known. Named so nobody treats it as settled.

A number without a source is not a measurement: delete it or go measure it.

## Working rules — these override default behaviour

1. **Never commit or push without an explicit ask.** Rico commits.
2. **TDD.** Host-testable logic gets a host test first, RED before GREEN.
3. **Rico burns the ROMs** (TL866). Tools verify; they never program.
4. **Netlist-verify before naming a pin or encoding anything.** Never
   write an assertion or a landing list from a reading of the schematic
   or from a pin list in a note — extract it first:

       python3 -c "import sys;sys.path.insert(0,'docs/notes');\
       from kicad_netlist import build_report;\
       print(*build_report('dino_v0_0_2/program_counter.kicad_sch')[0],sep='\n')"

   Two seconds, authoritative.
5. **Schematics first.** Draw it, then wire it, then prove it on the bench.
6. **Work in the main checkout, not a worktree.** Rico, 2026-09-07. The
   bench runs `make load-hello` / `make monitor` from
   `/Users/hambook/Development/dino-homebrew`; `.claude/settings.json`
   sets `worktree.bgIsolation = none`. If a worktree exists, fast-forward
   `main` to it and remove it.
7. **Announce every bench run** — what runs, the hardware state assumed
   (which ROM is seated, caps, probes, reset), what each outcome means —
   and wait for "go". One test, one read-out per turn. Rico ends sessions.
8. **Say which ROM is in `U24` with every reading.** The coverage and test
   images HALT at their own end; the monitor never halts.

## Status, as of 2026-10-06

**FACT — the machine is complete, executes from RAM, has a memory map, a
serial card and a ROM monitor.** Phases B (stack), C (CALL/RET), D
(execute-from-RAM), E (I/O window + DIP card), F (174-instruction ISA), G
(serial card) and G_0 (monitor) are on silicon and drawn. Instruments:
Siglent SDS1204X-E, DSLogic Plus LA (16 ch at 100 MHz in buffer mode,
2026-10-06 CSV headers), DMM, TL866. The ATmega rig and the FPGA twin are
retired (see "Retired").

**FACT — interrupts work (2026-10-06).** The INT core (U80-U87), the
serial card's 7406N (U104) and the ~{IRQ} jumper are wired; every rung of
PHASE_INT SECTION 4 passes at 1.024 MHz: `intmask 0x39`, `inthalt 0x5A`,
`intcount` one interrupt per loop, `intaddrsw` opcode addresses only,
`intflags 0x5A` (10/10 at 1.024 MHz and 500 kHz), `intser` echo. One soft
vector, `0x9090` in RAM: INT pushes PC and jumps there; whoever EIs plants
`JMP handler`. `PROG_imon` is the monitor's language with input on the
RDA interrupt, a 16-byte ring, Ctrl-C break (SECTION "The monitor").

**FACT — SCELBAL BASIC runs on DINO (2026-10-06).** **`PROG_basic` is in
`U24`** (crc `0xC34C`): `PROG_imon` verbatim at 0x0000, then SCELBAL
(8008, 1974) translated by `docs/notes/scelbal_xlate.py` into
`asm/basic.asm` (GENERATED). `G 0A00` cold, `G 0A03` warm. On silicon:
HELLO/GOTO loop, LIST, Ctrl-C, `PRINT 2/3` = ` 0.6666667` (the 8008's
digits), `PRINT PEEK(16384)` = 28. Host: byte-for-byte transcripts
against the original on `i8008.py` (`test_scelbal_dino.py`, 93% of the
8008 code executed). U24 is a 28C256 but only 16K is decoded (A14 = M14,
`~CE` needs M14 = 0); ~700 bytes free. Design, rulings, wishlist:
`.git/sdd/PHASE_BASIC.md`.

**FACT — the ISA is bench-proven at 1.024 MHz.** `PROG_isa` reads `0xB4`
(147 subtests), `PROG_isalive` `0xB4` every run, `PROG_isasoak` `0x00` on
50 consecutive runs (470,400 subtest executions), 2026-09-01 after the
GND/VCC starring; `0xB4` and `0x00` again on 2026-09-29 on the interrupt
microcode with the write gate in.

Microcode in the sockets: `U9 0x4102  U15 0x9BC4  U23 0x8A40`, the carry
microcode, burned 2026-10-06 (`isa 0xB4` x10, `isasoak 0x00` x10,
`carry 0xAD` x10). Pinned in `test_microcode_gen.py`; every row outside
0x96-0x99 is byte-identical to the 0x0C0A interrupt image (`test_carry.py`
pins it).

**FACT — ADC/SBB/ACI/SBI work (2026-10-06).** `U76` ('157, ALU board)
picks the '382's CN: `S <- CW16` (`U23.11`), `I0a <- FLAG_C` (`U49.2`),
`I1a <- ALU_CIN` (`U50.13`, the NAND term), `Za -> ALU_CN` (`U38.15`).
`CW16` is low only on the ALU rows of `0x96 ADC`, `0x97 SBB`, `0x98 ACI`,
`0x99 SBI`; `check_word` refuses it anywhere but `src=ALU` with
ADD/SUB/BSUB. `PROG_carry` `0xAD`: 12 subtests x 256 passes, each op with
the carry flipping across it, 10/10 at 1.024 MHz.

Coverage images and their expected `OB` (all oracle-computed, all
bench-green on the dates in `roms/README.md`):

    mardisc 0x6B  pads 0x40  mem 0xC5  flow 0x39  alu 0x39  loop 0x15
    PROG 0x4D     sp1 0x2C   sp2 0x53  sp3 0x2C   sp 0x27
    calladdr 0x5C callraw 0x2A call 0x4B stack 0x27  ramexec 0x6E
    window 0x5A   dip 0x4D   suite (SW1 = 1..12 selects)  test3 0x4D
    romsoak 0x00  serid 0x55 serid_aa 0xAA serlsr 0x60 seriir 0xC1
    serloop 0x53  sertx "DINO" on the host  serrx echo   isa 0xB4
    intmask 0x39  inthalt 0x5A  intflags 0x5A  intaddrsw 0x40/42/43/45
    intcount "MI" per loop  intser echo  (all UNORACLED, terminal-read)
    carry 0xAD

`NOP` is the only opcode that has never executed on silicon, by design.
22 further instructions and the 15-opcode `OUT_` family have never
executed (microcode-soft, PHASE_F.md RESULT 7). Say which kind of unrun
an instruction is: hardware-unproven or microcode-soft.

**FACT — RAM 0x8000-0xFFFF is proven whole** (Rico, 2026-09-07): data
lands and reads back, instructions fetch, across all 32K. The monitor
reserves 0x80E0-0x80FF (its variables and the stack a RET needs).

**FACT — ROM is readable as data** (2026-09-05): `PROG_test3` 0x4D,
`PROG_romsoak` 0x00 (65,536 reads). As built: `ROM_BUF_ON = NOR(READS_IDLE,
~ROM_SEL)` on `U22` g4, `~ROM_BUF_EN -> U19.19 and U24.22`, `LE_MDR =
NAND(+5V, READS_IDLE)` on `U39` g2, `~RAM_OE_G = NAND(RAM_OE_ON, M15)` on
`U74` g3. Path in `.git/sdd/PHASE_G_0.md` SECTION 2.

**FACT — a RET fetched from RAM was latching 0xFF; cause found and fixed in
copper 2026-09-29.** The FETCH row's transparent IR moves the microcode
address during CLK-low; the DST decoder output `U30.7` (code 111 =
`~RAM_LOAD`) runts 14-16 ns on some opcode transitions; the write gate
`NAND(WRITE_DIR, ~CLK)` is open then; the RAM gets a 14 ns `~WE` at PC's
address with its own byte on the bus; the cell survives, the chip's output
is wrong until the next address change, and IR latches 0xFF. From ROM the
same runt is harmless (`M15` = 0). The same runt reached `~IO_WR` and wrote
0x00 into `[MAR]` at every RESET. **Fix, in copper and drawn (2026-09-29,
ERC 0):** the write strobe is gated off in T-state 0, the only state with
the IR open:

    ~RAM_WRITE_EN = NAND(WRITE_DIR, WR_GATE)      WR_GATE = NOR(CLK, ~TO0)
    U62 g4:  11 <- CLK   12 <- ~{TO0} (U56.4)   13 = WR_GATE -> U51.4
    U56 3->4: TO0 (U7.15, one-hot state 0, active low) -> ~{TO0}
    sheets: control_word (U62 g4), root (U56 sec 2), memory (U51.4 label)

Witnesses: `retlda` 40/40 return (was 7/8 halting), no `~WE` pulse under
59 ns in 10 runs on a pulse trigger, `step2`/`retmvi`/`retcrlf`/`callret`/
`retinr`/`retldam`/`rethlsp` 5/5, `bigxfer` returns, a byte planted at
0x8200 survives halt + RESET. Copper beeped against the drawing, six
pins good (2026-09-29). An alternative form, `AND(WRITE_DIR, TO0)` on
`U69` g2 into `U51.5`, is recorded and not built. Record:
`.git/sdd/RAM_RET_FETCH.md`.

**OPEN:**
- `SERIAL_RX_A0.md`: received bytes lose 1->0 bits; 22 pF on `U103.28`
  (A0) is a marked partial fix and stays in; not the write runt (tested
  2026-09-29 with the gate in, 22 pF out: fails 4/4).
- One halt at PC 0x000x mid serial payload, 2026-09-29, once; RESET not
  probed at the time. ROM bytes 0x0001/0x0004 are 0xFF operands.
- `CN+4` after a LOGIC function on the '382 has never been measured; the
  oracle raises on a `JNC` that depends on it rather than guess.
- The 23 `SETTLE` rows (23 instructions load an ALU operand and consume it
  the next state): cost a T-state, necessity unproven, revert candidates
  at the next burn (PHASE H). The OUT settle was reverted 2026-09-29.
- Bus levels have never been characterised on a healthy machine.
- Seven boards sit at 124-180 mV of ground offset after the starring
  (`HANDOFF_HALT.md`); first suspects if anything analog returns.
- Why `isa` passed for months before the INT build if `U47` was this
  marginal (load/ground current on the ALU board? unmeasured), and why
  100 pF on `U47.11` helped (the race model predicts worse).
- DMA: off this board by the 2026-09-24 ruling; Rico re-decides before
  the first PCB (`.git/sdd/PROPOSAL_DMA.md`).
- The PCB: 4-layer mainboard placed, GND and +5V planes, not routed;
  power supply undecided (`.git/sdd/POWER.md`; draw 1.25-1.34 A).

## Architecture, netlist-extracted

**Control.** Horizontal microcode, no pipeline. Three AT28C64B (`U9`, `U15`,
`U23`) hold a 24-bit control word; the address is `IRB0-7` through `U16`
and the T-count bits `T0-T3` through `U17`, `A12` grounded. Nothing else
addresses the EEPROMs. `T0..T3` are the '163 `U6`'s Q0..Q3, the COUNT
bits; the one-hot states are `U7`/`U8` outputs `TO0..TO11`, active low
(`TO0` = `U7.15`). T0 (count 0) is the universal FETCH row for all 256
opcodes; the T-counter steps until `END`. SRC/DST/MISC are 3-bit '138
banks; bank 1 (`U70`/`U71`) is selected by disabling `U28`.

**The machine invariant.** Everything that changes state is clock-qualified
and commits on CLK low:

    register/IR/MAR/ALU loads   NOR(~LOAD, CLK)
    ALU output latch U47 LE     CLK_ALU = INV(~CLK), U37 inv 5 (a gate, not
                                raw CLK: see "Rules", 2026-10-06)
    RAM write                   NAND(WRITE_DIR, WR_GATE), WR_GATE = NOR(CLK, ~TO0)
    PC load                     NAND(PC_LOAD, ~CLK)
    PC clear                    NOR(~PC_CLEAR, CLK)
    PC count                    NAND(PC_UP, ~CLK)
    T-state clear/hold          the '163's synchronous clear and CET

Bus output enables are ungated. During an execute row the microcode
address only moves at CLK rise, so decode runts land in CLK-high and reach
nothing. During the FETCH row the IR is transparent in CLK-low, so decode
runts DO land in the write window; the T0 gate above closes that hole.
Flags (`U49`, '273) clock on `~CLK`. The SP ('169s) clocks on `CLK`,
because MAR/registers are transparent while CLK is low. The machine is
fully static; the clock can stop.

**Buses.** `MDR0-7` is the internal bus; `W` is the ALU/destination side;
`U25` bridges them, `DIR = NAND(~ALU_OUT, ~SW_OUT)`. Whenever any source is
active the bridge is on and both buses carry the byte: MAR and IR latch
from W, registers from MDR. Every bank-1 source lands on MDR. MDR sources:
ROM `U19`, RAM `U21`, REG A/B/C `U41-43`, SP `U67`/`U68`, PC `U72`/`U73`,
MDR replay `U18`. MDR has three permanent DC loads (`U18.3`, `U63.3`,
`U65.3`); worst-case sink ~1.5 mA against the weakest driver's 2.1 mA.

**OB latches MDR, not the accumulator** (`U44` '245 -> `U35` '373 on
`~REG_OUT_LOAD`/`~REG_OUT_LE`). `src=REG_A` on `OUT` is a microcode
convention.

**ALU.** Two '382s (`U38`, `U40`), ripple carry `U38.14 -> U40.15`.
`ALU_CIN = NAND(SA1, SA0)` (`U53` '08 + `U50` g4 as inverter): `ADD` gets
CIN=0, `SUB`/`BSUB` CIN=1, and `CN+4` is a NOT-borrow (`FLAG_C` = 1 means
A >= B unsigned). `U76` section a passes `ALU_CIN` to `U38.15` while `CW16`
is high and `FLAG_C` while it is low (ADC/SBB/ACI/SBI); CN = FLAG_C is
right for both ADC and SBB because CN is a not-borrow on SUB. All four flags latch in `U49`; `U48` ('157, select
`~ALU_OUT`) makes them update when the ALU is the source and hold
otherwise. `U62` g1 computes `COND_TAKEN = NOR(~COND, COND_FLAG)`,
`COND_FLAG` off `U77.4`; `CW21` is a real crossing, `CW22`/`CW23` are
no-connects and `word()` refuses flags or polarities that would need them.

**Memory-indirect addressing** (`LDAM`/`LDBM`/`STAM`/`JMPM`/`JZM`/`JCM`):
the pointer's LO byte parks in C, MAR is re-pointed at the HI byte, that
byte parks in MDR and is replayed immediately; the assembler emits `addr`
and `addr+1`. Clobbers C, B survives.

**CALL pushes PC+1, not PC+3** (pushes at T3/T7 precede the operand fetch
at T9/T10); `RET`'s T12/T13 `PC_UP` states step over the operand bytes and
are load-bearing. `src=RAM` cannot write MAR in the same word (live loop
through the transparent '373s). All 15 `src=ROM` rows carry `mux_pc=True`.
`misc=MDR_OUT` must follow the read that parked the byte, at most one
`src=NONE` settle between, `pc_up` on the settle. These are `check_word`/
`check_table` rules.

**Memory map.** ROM 0x0000-0x3FFF (`U24`), I/O window 0x4000-0x7FFF
(`U74` '00 + `U75` '32 on the memory board; eight 2K slots decoded on
M11-M13), RAM 0x8000-0xFFFF (`U26`). Card 0 = the DIP switch at 0x4000
(`dino_io/`'s `U76` '138 -- not the ALU board's `U76` '157). Card 1 = the serial card at 0x4800 (`U101` '138, `U102`
'245, `U103` PC16550D, `dino_serial/`), 9600 8N1, 3.6864 MHz can,
`~IO_WR` from `U75.6` to `U103.18`. Cards see `M0-M15` as an input only;
no DMA, by construction and by ruling (2026-09-24).

**Analog parts of the design.** `R2` 100R series in the SP board's CLK
branch (without it the '169s double-clock). `C1` 10 uF / `R1` 10k reset RC
through two sections of `U56` (`SN7414`), ~90 ms power-on reset; the
16550's `MR` comes off `U75` g3 (`RESET_B`). GND and VCC starred to every
board (2026-09-01). The RESET wire runs clear of CLK and the buses and is
GND-wrapped (2026-09-06/27). 22 pF on `U103.28` (see OPEN).

**Free gate sections** (netlist 2026-10-06): `U83` g3/g4 ('00, INT
board; inputs strapped GND), `U36` g4 (PC board, '00), `U69` g2/g3/g4 (SP board, '08), `U56` 5->6 and
13->12 ('14, root), `U78` five inverters (peripheral bus), `U61` g3/g4
('02, root). `U74` and `U75` are fully used. `U62` g4 and `U56` 3->4 are
taken by the T0 write gate (`WR_GATE`). `U37` inv 5 is `CLK_ALU`.
`U76` b/c/d ('157, ALU board) are grounded and hostage to `CW16`'s select,
like `U77` b/c/d to `CW21`: not a spare-gate resource.

**Clock.** 4 MHz can divided to 1.024 MHz; 500 kHz option for timing
discrimination. `CLK` = `U27.5`, `RESET` = `U27.9`, both '74 totem-pole.
Taps: `U20.14` 1.024 MHz, `.13` 512 kHz, `.12` 256 kHz, `.11` 128 kHz;
**`U20.15` is TC, NOT a tap** (also 128 kHz: hit 2026-10-06).
STEP-CLOCK (Y1 out, `CLKIN` driven at `U20.2`) has no driver since the rig
left; a debounced button would restore it.

**The monitor** (`asm/monitor.asm`, `PROG_monitor.bin`): `D addr`,
`W addr,val`, `O addr`, `L addr,len` + hex, `G addr` (a CALL, so a RET
returns to the prompt). Host side: `docs/notes/dinoload.py` (load, `--go`),
`docs/notes/serprobe_host.py`, `.git/sdd/tools/mon.py` (commands),
`listen.py`, `sinstop.py` (RX witness). RAM programs live in `asm/ram/`,
`.org 0x8100`.

**`PROG_imon`** (`asm/imon.asm`, crc `0xC12B`, banner `DINO IMON`) is the
same language with input on the 16550 RDA interrupt: every prompt plants
`JMP isr` at `0x9090`, sets IER = 0x01 and EIs; `isr` puts bytes in a ring
at `0x80A0-0x80AF` and Ctrl-C (0x03) resets SP and returns to the prompt.
`putc 0x0345`, `puthex 0x02C4`, `crlf 0x036B`, `puts 0x0376` are pinned to
the polling monitor's addresses (`test_imon.py`). Reserved: `0x80A0-0x80FF`,
stack `0x80DF` down. HALT in a G program waits for a key: Ctrl-C returns,
any other key resumes. `asm/ram/spin.asm` is the Ctrl-C witness.

## Decisions

- 2025-07-18: control words come out of an EEPROM addressed by opcode and
  T-state, not gates. 2025-07-25: 3-bit '138 banks make bus sources
  mutually exclusive by construction.
- 2026-07-28: integration is control-first and black-box (the block law:
  sample at block level only what depends on more than one member; the
  driven-wire count may not rise). The ladder is history; the
  classification survives.
- 2026-08-24: the ATmega rig and the FPGA twin are retired, not repaired.
- 2026-08-25: phases E, F and G are independent in both directions.
- 2026-08-27: `0x00` stays `NOP`; `IN` is retired from the ISA (`0x52`
  free); `0x9x` reserved for hardware-gated opcodes; high nibble = family.
- 2026-09-01: computers are analog; when a fault is not in the program,
  measure the rails before building a logic model.
- 2026-09-04: ROM-as-data fixed in copper, not worked around in software.
- 2026-09-07: RAM is proven whole; a frozen RAM program is a control-path
  question.
- 2026-09-08: the breadboard phase is over; one mainboard (now 4-layer),
  the phase E slots as its only connectors, power designed and measured
  first; S-100 style cards rejected.
- 2026-09-24: DMA stays off this board, Rev A included; interrupts go on.
- 2026-09-29: mistakes and retractions live in
  `.git/sdd/MISTAKES_MISSTEPS.md`, not here.

## Rules derived from specific failures

Each is a rule because something broke. The narrative behind each is in
`.git/sdd/MISTAKES_MISSTEPS.md` under its date.

- **No raw CLK on a latch pin at the end of a stub.** A gate output
  regenerates the edge. `U47`'s LE on raw CLK sat at 1.0-1.2 V for ~20 ns
  while TMP_A opened on the same edge; the ALU latched half its next
  answer. Same class as the SP '169s and `R2`. (2026-10-06)
- **A blip is not a failure.** Run the image that would fail before
  prescribing copper (the ~FLAGS_OUT gate: intflags passed ungated).
  (2026-10-06)
- **An interrupt source the CPU starts is not random relative to it.**
  THRE after four characters lands in a ~7-clock window; slide it (SW1)
  before trusting "all boundaries were hit". (2026-10-06, intaddr)
- **Rails first.** Random, probe-sensitive, program-independent faults:
  DMM GND and VCC of every board against the supply terminal, machine
  running, before any logic model. (2026-09-01: 460 mV of ground.)
- **A fault independent of what the machine executes is not in the
  datapath.** When changing the program changes nothing, the program is
  not the variable. (2026-09-01)
- **A voltage inside a Schmitt's hysteresis band is a random-event
  generator**; suspect the whole package, and lift before replacing.
  (2026-09-01, `U56`)
- **A component value is copper too.** A beep cannot tell 1 uF from
  10 uF; when a timing is 10x off, suspect the passive. (2026-09-04, `C1`)
- **A loosely seated decoupling cap is worse than no cap.** Behaviour that
  depends on power-up history is a passive, not logic; reseat after any
  chip swapping. (2026-08-27)
- **A runt cured by capacitance anywhere on a net is pickup along the
  run**; look at what runs beside the wire. The UART is the only device
  that counts strobes or has an asynchronous reset: a serial-only fault
  with `isa` clean is a strobe or a reset. (2026-09-06)
- **The instrument can be the cure.** When probing changes the answer,
  that is the measurement; A/B the probe; prefer an OB-only ROM witness.
  (2026-08-24, `U63.2`)
- **Rate is not data on this machine.** Halt rates moved 7/8 -> 1/22 with
  probes, a cap and warmth. Use a witness that cannot miss: a pulse
  trigger, a planted byte, a soak with a count. (2026-09-29)
- **A change that is logically identical and only faster is a timing
  change, and the oracle is blind to it.** List every transparent latch
  open across the boundary before re-sourcing a pin. (2026-09-05, twice)
- **A witness that rewrites the same value is mirror-blind.** Every plant
  must differ from what the cell held. (2026-09-05, `MVI`)
- **Mirror-witness.** A round trip through one bus bank or one address is
  blind to permutation and to a pointer that never moved; every module
  needs an asymmetric path, every pointer an image that reads a cell only
  a MOVED pointer reaches. (`PROG_sp2`/`sp3`)
- **Before a new image burns, list everything it does that no green image
  ever did.** (2026-09-04, ROM as data)
- **A single-shot test on a marginal board reports noise.** Repeat inside
  one image, pass on unanimity.
- **Before reading a cell as evidence, list every image loaded since it
  was planted.** (2026-09-29)
- **Say which ROM is seated with every reading.** (2026-09-29)
- **Any addition must hand-check the old-chip pins it wakes up**: the
  continuity walk lists only nets touching NEW designators. (`U28.6`,
  `U30.6`, `U29.11`)
- **One-hole slips on adjacent gate pins are the most common wiring
  fault**; beep against both neighbours. Never beep a live board. A pin
  that beeps to every chip is on a rail. As-built slot maps are copper.
- **No blind counters.** A failing assertion names the lying signal.
- **A stand-in better than the hardware hides defects.** (the '169 and
  the oracle both power SP up non-zero; `simulate()` refuses to invent a
  carry)
- **KiCad names a net after the alphabetically first label.** Any alias
  on a `CWnn` net must sort after it (`~{` guarantees it). Every sheet
  touching an aliased net must declare the same label set
  (`alias_splits()` guards). An alias binds only when its consumer pin
  exists. Diff ERC JSON against a baseline; only the delta is readable.
- **A tool's silence is not coverage. A test nothing calls is not a
  test.** Enumerate `test_` functions; `test_suite_reachability.py`
  guards.
- **An instruction's T-state cost is `1 + len(rows)`**; T0 is implicit.
- **A 3-bit field decode is bank-blind**; fold the bank bits in.
- **Phantom power**: rig lines fed DUT VCC through clamp diodes; any level
  measured with a rig attached is suspect.

## Everything is generated, nothing is retyped

    docs/notes/kicad_contracts.py   contracts + crossing lists
                                    --continuity <refs>  what to land
                                    --since <rev>        what changed, classified
                                    --stamp              MODULE CONTRACT blocks
                                    --pinmap             DEAD, throws. Rig retired.
    docs/notes/microcode_gen.py     microcode ROM images + CRCs + header
    docs/notes/progrom_gen.py       program ROMs, and the Python oracle
    docs/notes/isatest_gen.py       the ISA self-test family (isa, isacount,
                                    isaid, isasoak, isalive, isawhere)
    docs/notes/layout_gen.py        breadboard placement, slot maps, guides
    docs/notes/kicad_netlist.py     build_report() — the netlist oracle
    docs/notes/roms_readme_gen.py   roms/README.md

`simulate()` in `progrom_gen.py` interprets the real microcode rows and
computes what `OB` should read; it is the answer key, and it is not the
twin. `python3 docs/notes/progrom_gen.py --expected`. Host tests sit next
to each generator (`test_*.py`). Adding an instruction costs a three-ROM
burn; CRCs are pinned literals so a reburn is always deliberate. New
programs are `.asm` under `asm/`, never Python lists.

Permanently red tests, by ruling: `test_kicad_contracts_pinmap.py`,
`test_kicad_blocks.py::test_pinmap_has_block_bundles` (rig), and the
`fpga`/`vplan` tests (twin). Pre-existing red, not from bench work:
`test_bus_gen`, `test_continuity_completeness`, `test_erc_cleanup`,
`test_footprint_gen`, `test_kicad_blocks`, `test_pcb_gen`,
`test_suite_reachability` (HANDOFF section 6).

## Retired

**The ATmega2560 rig** (2026-08-24). Bench verification is continuity
against the generated crossing list, TL866 read-back, and the coverage
ROMs' `OB`. The ROM burn targets in `tests/dino_bringup/Makefile` are not
rig code and must survive any cleanup. Do not extend `POOL`.

**The FPGA twin** (2026-08-24). `make -C fpga verify` does not pass and
will not be fixed; do not gate bench work on it or spend a session on it.
It generated from the schematic and so could only catch design errors;
every fault that killed it was a build or analog fault. Dead with it:
`fpga/`, `fpga_gen.py`, `coverage_lint.py`, `dino_fpga_vplan.md`,
`test_fpga_gen.py`, `.git/sdd/BRINGUP_FPGA.md`.

## Where to read next

**`.git/sdd/` is not versioned, and that is settled.** Rico knows; do not
raise it. Process documents (bring-up, plans, investigations, handoffs)
live there; the repo keeps design and reference docs plus everything
generated. Any stale in-tree reference to a process doc resolves to
`.git/sdd/<name>`.

LIVE:

    .git/sdd/HANDOFF.md                 bench state and the next action. FIRST
    .git/sdd/PHASE_BASIC.md             SCELBAL on DINO: translator, rulings,
                                        UDF/PEEK/POKE, microcode wishlist
    .git/sdd/MISTAKES_MISSTEPS.md       every retraction and wrong model, dated
    .git/sdd/RAM_RET_FETCH.md           the RAM-fetch halt: chase, cause, gate,
                                        witnesses. CLOSED and DRAWN 2026-09-29
    .git/sdd/SERIAL_RX_A0.md            RX loses 1->0 bits; 22 pF partial; OPEN
    .git/sdd/PHASE_INT.md               interrupts: microcode, images, plan
    .git/sdd/PHASE_G_0.md               the monitor and ROM-as-data path
    .git/sdd/PHASE_G.md                 the serial card
    .git/sdd/PHASE_E.md, PHASE_E_PLAN.md   memory map, I/O window, card zero
    .git/sdd/PHASE_F.md                 the ISA extension and the opcode map
    .git/sdd/PHASE_I.md                 CompactFlash: specced, not drawn
    .git/sdd/POWER.md                   PCB power: supply choice, tasks
    .git/sdd/GROUNDING.md               ground is a wire. Read before wiring
    .git/sdd/CLOCK_DISTRIBUTION.md      the 100R and the PCB consequence
    .git/sdd/HANDOFF_HALT.md            per-board ground offsets after starring
    .git/sdd/RIG_RETIREMENT.md          what is dead and what must not be deleted
    .git/sdd/dino_hardware_growth_plan.md   planned and priced
    docs/notes/dino_isa_for_basic.md    the instruction set roadmap
    roms/README.md                      every image, CRC, expected OB, subtest map

HISTORICAL (accurate for their moment, not procedure): `PHASE_C.md`,
`PHASE_D.md`, `SP_BEEP.md`, `SP_DEBUG.md`, `dino_stack_bringup_handoff.md`,
`dino_mar_lo_investigation.md`, `BRINGUP.md`, `README.md`,
`dino_test_bringup_design.md`, `HANDOFF_ARCHIVE_2026-09-27_28.md`.
