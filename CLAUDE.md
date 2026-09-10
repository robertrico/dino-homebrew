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
5. **Schematics first.** Draw it, then wire it, then prove it on the bench.
   The FPGA step is gone — the twin is retired, see below.
6. **Work in the main checkout, not a worktree.** Rico, 2026-09-07. The
   bench runs `make load-hello` / `make monitor` from
   `/Users/hambook/Development/dino-homebrew`; a fix that lands in
   `.claude/worktrees/<x>` is invisible there until someone merges it,
   and a worktree branched from `origin/main` is missing everything on
   local `main` that has not been pushed. `.claude/settings.json` sets
   `worktree.bgIsolation = none` so background sessions edit `main`
   directly. Do not create worktrees for this project; if one exists,
   fast-forward `main` to it and remove it.

## Status

**FACT — the machine is COMPLETE and EXECUTES FROM RAM, 2026-08-24.**
Phases B (stack), C (`CALL`/`RET`) and D (execute-from-RAM) are all on
silicon and in copper. Every instruction in the ISA runs on hardware except
`LDCI` and `NOP`, and those are microcode-soft.

Everything below is in the schematic *and* on the breadboard. Nothing in
this file describes work that exists only on one side.

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

And phase D:

    ramexec 0x6E

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

**FACT — 147 INSTRUCTIONS PASS ON HARDWARE AT 1.024MHz, 2026-09-01.**
`PROG_isa` reads `0xB4`. The ISA is bench-proven at full speed. What
unblocked it was replacing `U56` — a damaged `74HC14`, now an `SN7414` —
and rewiring its reset chain through a second inverter section. Before
that the machine reset itself roughly every 200ms and no program of any
kind could run longer.

**OPEN — a ~0.3% residual, 2026-09-01.** `PROG_isasoak` (64 passes, 9408
subtest executions) reports 27-34 failures, plus about one non-completion
in eight runs. A single 147-subtest pass is clean most of the time, which
is why `PROG_isa` reads `0xB4` while the soak does not. `PROG_isasoak` at
500kHz is the free discriminator between timing margin and marginal
connections.

**FACT — THE RANDOM HALT WAS THE GROUND RETURN, 2026-09-01, later the same
day.** `PROG_isalive` died at pass 3..52 (`0C 24 21 34 03`) on a bare board
and completed 20/20 as `PROG_isawhere`; a DMM on the ground pins, DC,
black lead on the supply terminal, machine running, read `U27.7 142mV`,
`U6.8 342mV`, `U15.14 460mV`. Two chips on one board 200mV apart, and the
microcode ROM's LOW arriving at `U61` with 80mV of DC margin. Rico starred
GND and VCC to each board; isalive now reads `0xB4` every run, and
**`PROG_isasoak` reads `0x00` on 50 consecutive runs** — 470,400 subtest
executions, zero miscompares. **The ~0.3% residual above is CLOSED; the
ISA is clear on the record.** Post-fix rails: worst board 180mV, best 5mV,
table in `.git/sdd/HANDOFF_HALT.md`. Seven boards still sit at 124-180mV
and are the first suspects if anything analog returns. The 22pF that was
tried on `U61.5` must be confirmed OUT.

**FACT — timing WAS believed to be a concern at 1.024MHz for the EXTENDED
ISA, 2026-08-27, AND THAT READING IS SUSPECT.**
The old sentence here read "timing is not a concern at 1.024MHz", and it was
true of the 25-instruction machine it was written for. It is not true of the
174-instruction one.

**AT 500kHz `PROG_isa` READS `0xB4`: ALL 147 SUBTESTS PASS.** Every
instruction is functionally correct and no microcode row is wrong. At
1.024MHz the same image returns varying subtest numbers from identical
resets, which is a timing margin, not a logic fault.

**23 instructions load an ALU operand and consume it in the VERY NEXT
T-state**, with no settling state between the latch closing and the '382
pair being read:

    src=ROM   -> REG_B, then ALU   19   the whole 0xCx immediate family
                                        ADI/SUI/BSUI/ANI/ORI/XRI x {A,B,C}
                                        plus CPI
    src=ALU   -> REG_B, then ALU    3   INR, DCR, NOT
    src=REG_A -> REG_B, then ALU    1   SHL

Every other instruction loads its ALU operand in a PREVIOUS instruction, so
the operand latch has a whole fetch state to settle. That is why the
25-instruction machine never saw this and why the sentence above was true
when it was written.

**Inference, not yet measured: the critical path is the microcode ROM access
plus the '382 pair's RIPPLE CARRY** (U38's `CN+4` into U40's `CN`) plus the
U47/U25 return to `REG_A`, all inside one T-state. A scope on `U40`'s
outputs against `CLK` would settle it; nobody has done that.

**THE SETTLING STATES WENT IN, AND WHETHER THEY WERE NEEDED IS OPEN.** The
`SUI` failure that motivated them was deterministic across boot-vs-reset —
but that is exactly the axis a randomly-resetting machine corrupts, and
`U56` was dying at the time. The pads cost one T-state on 23 instructions
and are harmless. **Removing them and re-running `PROG_isa` is the honest
test, and it has not been done.**

Blocks 4 and 5 free-run with Y1 seated. "Works single-stepped, fails
free-run" was watched for and never appeared on the old ISA.

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

**FACT — PHASE D IS ON SILICON as of 2026-08-24. THE MACHINE EXECUTES
FROM RAM.** `PROG_ramexec` returns `0x6E`. Six gate sections that had never
been driven in this machine's life are now bench-proven:

    U22 g3   FETCH_RAM     = NOR(~ROM_OUT, ~RAM_EN)        BENCH-PROVEN
    U22 g4   ROM_BUF_ON    = NOR(~ROM_OUT, FETCH_RAM)      BENCH-PROVEN
    U37 inv4 ~{FETCH_RAM}                                  BENCH-PROVEN
    U37 inv6 ~{ROM_BUF_EN} = OR(~ROM_OUT, FETCH_RAM)  -> U19.19
    U37 inv5 ~{RAM_OE_G}   = AND(~RAM_OUT, ~FETCH_RAM) -> U26.22 + U51.9
    U39 g4   RAM_OE_ON     = NAND(~RAM_OUT, ~FETCH_RAM)    BENCH-PROVEN

**It cost no new IC.** All six were free sections on `U22`/`U37`/`U39`,
already in sockets on the MDR board, and `~ROM_OUT`/`~RAM_OUT` were
already there feeding `READS_IDLE`. Only `~{RAM_EN}` had to be brought in.
Two pin lifts on the memory board, eleven wires. **`U24.22` stays on
`~{ROM_OUT}`** — `U24`'s own `~CE = M15` deselects the ROM chip already.

**The MDR board has ONE free gate section, `U37` i5**, freed by phase E.
`U22`, `U39` and the rest of `U37` are in use; `U39` g2 now computes
`LE_MDR` from `READS_IDLE` alone with its other input strapped +5V
(2026-09-05). The next change needing a gate there needs a package.

**The table above is the phase D drawing; phase E re-sourced two of those
pins and the netlist now reads** `ROM_BUF_ON = NOR(~ROM_OUT, ~ROM_SEL)` on
`U22 g4` (`U22.12 <- ~{ROM_SEL}`) and `~{RAM_OE_G} = NAND(RAM_OE_ON, M15)`
on `U74 g3`, with `U37 inv5` freed. Netlist-extracted 2026-09-04;
`.git/sdd/PHASE_G_0.md` SECTION 2 has the whole path.

**FACT — ROM IS READABLE AS DATA, 2026-09-05. `PROG_test3` reads `0x4D`,
`PROG_romsoak` reads `0x00` (65536 reads, three shapes, zero misses) and
the monitor runs its session: `D 0000 -> 0x11`, `W FF00,99 -> 0x99`,
`O FF00`. Three re-sourced pins as specified, minus one: the RAM-side
wire (`U74.9 <- READ`) was logically identical to `RAM_OE_ON` and three
gates faster, which turned a marginal `MVI` into a broken one; it is
BACK on `RAM_OE_ON`. As built: `ROM_BUF_ON = NOR(READS_IDLE, ~ROM_SEL)`,
`~ROM_BUF_EN -> U19.19 AND U24.22`, `LE_MDR = NAND(+5V, READS_IDLE)`.
`.git/sdd/PHASE_G_0.md` RESULTS has the four faults the first image on
it exposed: a pulsing `U15` (chip, replaced -- RETRACTED the same evening: a fresh `U9` pulses too, driven to 4V with a static address; the EEPROMs are being handed a bad address for ns, found late 09-05 to be `T0` off `U6.14` glitching on the ROOT board's ground bounce -- a probe or 22pF at that pin damps it, 22pF at the far end does not; 22pF was IN as a marked partial -- RETRACTED 2026-09-06: the runt was the `RESET` wire's ROUTE, see the Open questions entry below; cap is OUT, never needed), `MVI`'s park (microcode,
settle row, `U9 0xC52B / U15 0xDCD1`), `LE_MDR` opening during the replay
(copper, `U39.4` strapped +5V), and that wire. The paragraph below is the
2026-09-04 reading that started it, kept for the shape of the mistake.**

**FACT — ROM WAS NOT READABLE AS DATA, 2026-09-04. `PROG_test3` read
`0xFE`.** Two bytes planted in ROM, `LDA`/`LDB` by absolute address, `ADD`:
both reads saw the bus park. The ROM's `~OE` (`U24.22`) and `U19`'s enable
both key on `~{ROM_OUT}`, which only the PC-driven fetch asserts; a
`src=RAM` row below 0x4000 leaves the ROM chip selected with its outputs
off and `U21` driving MDR from nothing. **No bench-green image had ever
read ROM as data** -- every table and pointer in every coverage image is in
RAM -- so nothing caught it until the monitor kept a string in ROM and
streamed bus residue to the terminal. RAM above 0x80FF is NOT the issue:
`PROG_test2` reads `0x4D` at 0xFFE0/0xFFF0. **Decision (Rico): fixed in
copper, not in software.** The ROM side keys on `READ` the way the RAM
side already keys on `M15`: three re-sourced pins, zero packages, in
`.git/sdd/PHASE_G_0.md` SECTION 3. The oracle already reads ROM as data
and is the design; the copper is what moves. Rule: **before a new image
burns, list everything it does that no green image ever did. All of it.**

**FACT — ALL OF RAM, 0x8000-0xFFFF, IS PROVEN. Rico, 2026-09-07.** The
standing caution that RAM above 0x80FF was OPEN -- kept because every
bench-green image confined its cells and stack to 0x8000-0x80FF -- is
CLOSED. Data lands and reads back, and instructions fetch, across the
whole 32K. RAM is flat and whole. The only reserved cells are the
monitor's own 0x80E0-0x80FF (its variables and the stack a `RET` needs);
a loaded program still stays off those, for the monitor's sake, not
RAM's.

**RETRACTED 2026-09-08 — THE MICROCODE SETTLE DID NOT FIX IT.** U15 was
burned with the OUT-settle (`0x45F9`) and `make go-step2` STILL halts,
OB `0x22`. The settle was the wrong fix and the model behind it was
incomplete. **What the burn PROVED:** idle T-states between OUT and the RET
fetch do NOT cure it -- only an intervening real FETCH does (a `NOP`, a
`LDAI`). So it is not OUT's bus/strobe overlapping the next fetch (a settle
would have separated them); it is the FIRST RAM fetch after an OUT being
marginal, and a throwaway fetch (NOP) absorbs it so the RET fetch is the
SECOND and is clean. RAM read path timing: OUT's own T0 fetches from RAM,
then OUT drives REG_A (RAM path off), then the RET fetch must re-assert the
RAM read -- and the first re-assert after that gap is where HALT latches.
**SETUP-MARGIN FAULT, CONFIRMED BY CLOCK, 2026-09-08.** `step2` HALTS at
1.024MHz and above, RETURNS at 500kHz. Slower clock CURES it, so it is a
setup-margin fault -- the RET fetch does not deliver a valid opcode to IR
before the latching edge. (An earlier note here predicted slower=worse from
a transparent-IR-dwell model; the bench said slower=better, so that model
is RETRACTED.) Bracket: fails at the 488ns half-window (1.024MHz), passes
at 1000ns (500kHz), so the real first-fetch-after-OUT settle is 488..1000ns.
Datasheet budget to IR is 382ns worst-case and CLOSES at 488ns, so the
missing 100..600ns is NOT in the datasheet path: it is breadboard bus
capacitance (100+pF vs the 45pF a 74LS245 tPD is specced into) plus the
`U41`(REG_A)->`U21`(RAM) CROSS-DRIVER handoff that only the OUT->fetch sees.
A fetch after a fetch is `U21`->`U21`, same buffer, no contention.
**WHY MORE SETTLE STATES DO NOT HELP:** the bottleneck is the RET fetch's
own single T-state, whose setup deadline is the clock edge; idle states
BEFORE it do not lengthen it. The burned settle proved this. **WHY A
DRIVING settle does not help either:** keeping RAM on the bus into the fetch
(U21->U21) would fix RAM but OUT cannot know the next fetch is ROM or RAM --
a RAM-driving last row makes OUT->ROM-fetch a `U21`->`U19` fight and breaks
the 147-instruction ROM path. **The fix is not in OUT's microcode.**
Options, all consistent: NOP between OUT and RET (zero burn, proven);
500kHz (zero burn, proven); PCB (the real fix -- cut the bus C). The burned
OUT settle (`0x45F9`) should be REVERTED on the next burn: it costs a
T-state and fixes nothing. **WORKAROUND, zero burn:** never put OUT
immediately before RET in RAM code; one instruction between them is enough
(`step2a`, `step2g`). Original freeze note below.

**Original claim, RETRACTED above — the freeze was
`OUT` immediately before the next fetch FROM RAM, 2026-09-08.**
`asm/ram/step2` (`LDAI 0x22; OUT; RET`) OUTs `0x22` and froze. The staircase
`asm/ram/step1..8` plus `step2pop/ram/jmp/a/b/c/e/f/g` (all oracle-green in
`test_ramsteps.py`) pinned it: fetch/`OUT`/`HALT`/`RET`/`CALL` from RAM all
work; only `OUT` IMMEDIATELY before another instruction fetched from RAM
halts, data-independent (four `OUT` values all froze; `0x34` with `REG_A`
also `0x34`, no bus transition, still froze). One instruction between them
cures it (`step2a`), and one `NOP` cures it (`step2g`, OB `0x22`, prompt
back -- `NOP`'s first execution on silicon). **Root cause:** `OUT` was one
row driving MDR from `REG_A` and strobing `REG_OUT_LOAD` in the SAME
T-state it carried END, so the next fetch began before the bus released;
on the fast `FETCH_RAM` path the transparent IR (`NOR(~LOAD, CLK)`) latched
the overlap and `U61`'s HALT latch caught it and STUCK (its pins 5/6
feed back). From ROM the fetch had margin, which is why 147 instructions
and every coverage image were clean. **Fix:** `OUT` and the register/ALU
`OUT_` family end in a `SETTLE` row (`0xff0000`, drives nothing) before
the safe-fill END; `OUTI` is left as-is (it reads a ROM immediate and
cannot cleanly carry the settle -- H2 retirement candidate anyway).
`check_table` now blesses a trailing `SETTLE` terminator. **U15 reburn,
`0xDCD1 -> 0x45F9`; U9 `0xC52B` and U23 `0xCB8E` UNCHANGED -- one chip.**
Host-green, bins regenerated; Rico burns U15 and reruns `make go-step2`
(pass = OB `0x22`, prompt back). This rides with the H1 settle-row
cleanup, which reburns the same chip.

Old note kept for the record: fetch from RAM, `OUT` and
`HALT` from RAM work (`step1` OB `0x11`); `CALL` from RAM into ROM and
`RET` from ROM back into RAM work (`bigxfer` printed 261 bytes). Every
earlier RAM program did five firsts at once; `asm/ram/step1..8` is the
staircase that does one per step, `test_ramsteps.py` its oracle answer
key, and `step2pop` / `step2ram` / `step2jmp` split `RET` into its pops,
a RAM-to-RAM return, and a bare RAM-to-ROM jump.

**FACT — gating `~{RAM_OUT}` upstream carries `U21`'s enable for free.**
`U51` is a `7400` computing `~RAM_MDR_EN = AND(~RAM_OUT, ~WRITE_DIR)`, so
one gate on `~RAM_OUT` moves both the RAM chip's `~OE` and its buffer.
That is why phase D is six gates and not eight.

**FACT — all 15 `src=ROM` microcode rows carry `mux_pc=True`,** no
exceptions, `FETCH` included, `FILL` is `src=NONE`. This had to be
re-proven before phase D: a ROM-side read can now hit RAM, so the standing
"ROM reads are exempt from the `src=RAM`->MAR loop" rule was no longer
free. It holds — MAR never drives `M` during a ROM-side read.

**FACT — `U19`'s enable is now two gate delays behind `~ROM_OUT`**, and
measured at <=50ns on the bench. `U21`'s has been two gate delays behind
`~RAM_OUT` through `U51` since the machine was built, on a plain `7400`.
The mod makes the two buffers symmetric; before it, `U19` was the odd one.

**DECISION 2026-08-24 (Rico): THE ATmega2560 RIG IS RETIRED.** Scope, DMM
and LA. As a complete CPU the machine does not need it. Full record in
`.git/sdd/RIG_RETIREMENT.md`, including what must NOT be deleted — **the
ROM burn targets live in `tests/dino_bringup/Makefile`** and have nothing
to do with the ATmega. Consequence: `--pinmap` throws `IndexError` (the
MDR sheet needs 21 rig pins, `POOL` has 19). Deferred, not repaired. Do
not extend `POOL`; that would commit a hookup table for retired hardware.
`test_kicad_contracts_pinmap.py` and
`test_kicad_blocks.py::test_pinmap_has_block_bundles` are permanently red.

**COST — `block2` can no longer read RAM under microcode control.** Its
RAM enable used to come from control_word, in-block; it now comes from the
MDR board, which does not join the ladder until block3. `block2` straps
`~{ROM_BUF_EN}` LOW and `~{RAM_OE_G}` HIGH. Both values are forced:
`~{RAM_OE_G}` LOW would leave `U19` and `U21` both driving `MDR0-7`.

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
phase-C risk** — this was checked rather than assumed. **Phase D added
none at all**: its six gates sit between the decoders and the existing
buffers' enable pins, and touch no bus pin.

**FACT — a 100Ω series resistor sits in the SP board's CLK branch**, fitted
2026-08-24, source end, that branch only. It is `R2`, drawn in
`dino_v0_0_2/stack_pointer.kicad_sch`, and the segment below it is `CLK_R`.
Schematic and copper agree. Without it the '169s double-clock: `PROG_sp3` returns `0x22` instead of
`0x2C`, deterministically. Full measurement and the PCB consequences are in
`.git/sdd/CLOCK_DISTRIBUTION.md`. **Inference:** the SP is the first thing in
this machine to put raw `CLK` on a clock pin at the end of a stub on another
board — every other state element takes CLK through a NOR or NAND first, and
a gate is a de-facto regenerator. Nothing before the stack could have exposed
this.

> ## !!! THE FPGA TWIN IS RETIRED — DO NOT TRUST IT, DO NOT REPAIR IT !!!
>
> **DECISION 2026-08-24 (Rico): retired.** `make -C fpga verify` does not
> pass and will not be fixed. Do not read a green badge into this file, do
> not gate bench work on it, and do not spend a session repairing it.
>
> It was already red before the session that retired it. Same box, same
> venv, `pytest docs/notes -q`:
>
>     HEAD, clean, before any of this   4 failed, 173 passed
>
> **11 more from one root cause: `KeyError: '100Ω'`.** `fpga_gen.py` has no
> model for a resistor. `R2` is the first passive IN A SIGNAL PATH, and
> `EXCLUDED_TYPES` cannot simply swallow it — dropping it whole strands
> `CLK_R` with no driver. Fixing it would need a net merge, `CLK_R ≡ CLK`,
> which is an admission that the twin cannot model the damping `R2` exists
> to provide.
>
> **It caught none of the three faults in the session that killed it, and
> could not have.** Six unlanded `CW` address wires, a ringing `CLK` edge,
> and `U72`/`U73` landed on the wrong chips. In all three the SCHEMATIC WAS
> CORRECT, and the twin generates FROM the schematic. It catches DESIGN
> errors; every fault that day was a build error or an analog one, and the
> bench caught all three.
>
> Dead with it: `fpga/`, `docs/notes/fpga_gen.py`,
> `docs/notes/coverage_lint.py`, `docs/notes/dino_fpga_vplan.md`, and
> `docs/notes/test_fpga_gen.py`.

**The rig (ATmega2560) is RETIRED — Rico, 2026-08-24.** Not merely
detached; retired. Bench verification is continuity against the generated
crossing list, TL866 read-back, and the coverage ROMs' `OB` values.
Instruments: DSLogic LA, Siglent scope, DMM. See
`.git/sdd/RIG_RETIREMENT.md` — and note the ROM burn targets live in
`tests/dino_bringup/Makefile` and must survive any cleanup.

**FACT — PHASE E IS ON SILICON, COMPLETE, 2026-08-26.** The machine has a
memory map, a published bus and its first card. The remaining work splits
three ways, a decision (Rico, 2026-08-25) and not a suggestion: **E** was the
memory map plus the DIP peripheral; **F** is the ISA extension; **G** is the
serial card. F and G are independent of E and of each other, in both
directions. **Phase E cost no microcode burn** — `U9`/`U15`/`U23` were never
touched; every burn was a program ROM.

    STEP A   the 16K I/O window at 0x4000-0x7FFF, carved out of ROM space.
             U74 '00 + U75 '32 on the memory board. PROG_window 0xA5 -> 0x5A
    STEP B   card zero: U76 '138 decodes M11-M13, E1 on ~{IO_RD_Q}, O0 gates
             SWITCH-GATE1. The DIP switch IS memory at 0x4000-0x47FF
    IN       RETIRED. U28.7 unlanded; ~{SW_OUT} is gone. LDA replaces it

**FACT — the machine reads the outside world at run time.** `PROG_dip`
returns `0x4D` at `SW1 = 0x1E`, and a walking `1` through all eight switches
returned all eight expected sums with **no reburn and no power cycle** —
toggle, RESET, read. `PROG_swdemo` goes further and reads the switch INSIDE
its loop, so the display changes without even a RESET. Before card zero every
image was a fixed film strip.

**FACT — the twelve-image regression now costs ONE burn.** `PROG_suite`
(`crc 0x8A1C`) holds the dispatch at `0x0000` and each test at its own 1K
slot; `SW1 = 1-12` selects, `RESET` runs it, `OB` is the answer, and a
setting outside the range OUTs `SW1` raw so a stuck switch names itself. All
twelve ran green on 2026-08-26. **The twelve standalone images stay** — the
suite depends on card zero, and they are the fallback.

**OBSERVATION, NOT A DEFECT — `ramexec`'s answer has been seen to change
after the fact, sporadically, never watched moving.** It reads `0x6E`
correctly every run. Rico, 2026-08-26: not a memory-mapping fault, and not
being chased. It is the only coverage image whose final `HALT` sits in RAM,
where an escape executes power-up garbage instead of landing on another
`HALT` — and the 81-minute hold that closed the HALT question was a
ROM-fetched `HALT`. Shape recorded in `PHASE_E.md`; it does not earn a fix
until it has a witness that cannot miss.

**A card cannot touch RAM, and that is by construction.** `M0-M15` is
published TO cards as an input; nothing on the edge lets a card assert an
address or a write enable, and DMA is removed entirely, not deferred. Card
code that runs on the CPU is software like any other and has the same reach —
conflicts there are a convention problem, the Apple/IBM slot-scratch problem,
and no hardware guards it. **`~{IO_WR}` (`U75.6`) is LANDED as of 2026-09-04**,
feeding the serial card's `~WR` (`U103.18`); `PROG_serid` reads `0x55`. Its
first landing was one hole off, on `U75.5`, and read `0xFF` -- see
`.git/sdd/PHASE_G.md` RESULT 4b.

Read `.git/sdd/PHASE_E.md` for the spec and the RESULT sections.

**FACT — PHASE G IS ON SILICON AND COMPLETE, 2026-09-04.** The serial
card (`U101` '138, `U102` '245, `U103` PC16550D, `dino_serial/`) runs at
9600 8N1. Every step-4..8 witness passed on the bench in one evening:

    serid 0x55   serid_aa 0xAA   serlsr 0x60   seriir 0xC1
    serbaud 153.6 kHz on U103.15   serloop 0x53
    sertx  "DINO" on the host terminal      <- the data bus is PROVEN
    serrx  typed char on OB AND echoed      <- phase G's exit condition

One wiring fault on the way: the card's `~WR` landed on `U75.5` (an input)
instead of `U75.6`; `PROG_serid` read `0xFF` until it moved. `~{IO_WR}`
is now landed and proven. Tooling: `asm.py --run` reports `Unoracled`
instead of dying on images the oracle refuses by design.

**FACT — THE MACHINE HAD NO POWER-ON RESET UNTIL 2026-09-04. `C1` WAS 1uF
IN COPPER, 10uF IN THE DRAWING.** With `10k x 1uF = 10ms`, reset released
~1ms into a ~10ms rail ramp (scope `U103.35`: one 0.8ms pulse at ~2.5V,
then 0V for 140ms). The core survived because HC/LS logic runs at 2.5V
and the PC/T-counter clears landed inside that runt. The PC16550D did not:
it has no internal POR, needs `MR` >= 5us on a valid rail, and started in
a random state -- LCR bits 1:0 and FCR did not hold, so it framed 5-BIT
characters both ways (bit 5 always set, trailing `0xFF` frame, RBR `0x1D`
for `[`). The RESET button was the first real MR of its life, which is why
warm was always clean. **Rico fitted 10uF; cold boot is clean.** Copper now
matches the drawing. Two theories were written and retracted on the way
(phantom power via SIN; a parked RC node) -- `.git/sdd/PHASE_G.md` RESULT 8
has the whole chase. Diagnostics from it: `PROG_serrx0`, `serlcr`,
`serlive`, `serrxlcr`, `serrxlive`; host probe `docs/notes/serprobe_host.py`.

**FACT — PHASE F IS ON SILICON AND CLOSED, 2026-09-01 (Rico).** `U77`
(`74LS157`) is in copper since 2026-08-27; the 174-instruction microcode is
BURNED and in the sockets:

    U9  0xC52B    U15 0x45F9    U23 0xCB8E     pinned in test_microcode_gen.py
    (2026-09-05: MVI settle row. Was 0xE991/0x33EA/0xCB8E from 2026-09-01.)
    (2026-09-08: OUT settle row, BURNED U15 0xDCD1 -> 0x45F9, did NOT
     fix the OUT->RET-from-RAM halt; the fetch, not idle time, is the cure.)

The witness is the self-test, not the eight standalone images: `PROG_isa`
reads `0xB4` (147 subtests, including `JNC`, `MOV A,C`, `LDAX`, `LDAM` —
none of which the pre-F ROMs decode), `PROG_isalive` `0xB4` every run, and
`PROG_isasoak` `0x00` on 50 consecutive runs, all at 1.024 MHz after the
GND/VCC starring of the same day. `LDCI` has now executed on silicon via
`MOV A,C`; `NOP` remains the one never-executed opcode by design.

Deferred to PHASE H (cleanup), listed in `.git/sdd/PHASE_F.md` RESULT 7:
the 23 `SETTLE` rows (added for a fault that was ground), the 15-opcode
`OUT_` family (write-only, so the self-test cannot witness it), 22
instructions never executed on silicon, and two scope OPENs (`CN+4` after
a logic op; the branch path timing).

**Phase F+ was 108 instructions for zero packages, zero decoder outputs,
zero wires.** An exhaustive enumeration over the landed SRC/DST/MISC codes
found 227 legal row sequences; 108 of the 172 not already in the ISA
survived curation. 82 opcodes free.

**The binding constraint is now the 256-entry opcode map, not the hardware.**
Family 9 (`SHR`/`MOV A,FLAGS`/`ADC`/`SBB`) plus the `CW22`/`CW23` branch
families already claim 10 of the free slots. `0x9x` is RESERVED for
hardware-gated opcodes and high-nibble-is-family still holds, because that
is what makes a byte hand-disassemblable at the bench.

**FACT — OB LATCHES MDR, NOT THE ACCUMULATOR**, netlist-extracted from
`registers_a_b.kicad_sch` 2026-08-27: `U44` is a `'245` with `DIR` tied
`+5V`, its A side on `MDR0-7` and `~CE = ~{REG_OUT_LOAD}`, feeding `U35.D0-7`;
`U35.LE` is `~{REG_OUT_LE}`. **`src=REG_A` on `OUT` was a microcode
convention and never a wire**, so `OUT` from B, C, either pointer half, an
immediate, memory in three addressing modes or an ALU result costs nothing
and always could have. The oracle modelled `out = A` and was silently wrong
the moment the source varied.

**FACT — the machine has MEMORY-INDIRECT addressing.** `LDAM`/`LDBM`/`STAM`/
`JMPM`/`JZM`/`JCM`, five bytes, `RET`'s MDR park generalised. `src=RAM`
cannot write MAR, so the pointer's LO byte parks in C, MAR is re-pointed at
the HI byte, and that byte is parked in MDR and **replayed immediately**.
**The assembler emits the address twice** (`addr`, `addr+1`) because MAR
loads only from W and has no increment. Clobbers C; **B survives**, which is
what makes it beat `LDC addr; LDB addr+1; LDAX`.

**DECISION 2026-08-27 (Rico), taken at the burn exactly as `PHASE_F.md`
SECTION 8 scheduled: `0x00` STAYS `NOP`.** The OPEN is closed. The
diagnostic argument for moving it — since phase D a PC landing in unwritten
RAM NOP-slides through 28KB and wraps, so a failed STORE presents as a failed
FETCH — was heard and rejected: a NOP slide is a legitimate idiom and `HALT`
at `0x00` would make a mistyped immediate stop the machine instead of
stepping over it.

**DECISION 2026-08-27 (Rico): `IN` IS RETIRED FROM THE ISA, not merely from
copper, and `0x52` is free.** Phase E retired it in copper (`U28.7`
unlanded, `~{SW_OUT}` deleted, SW1 is memory at card zero) but kept the
microcode row because phase E burned no microcode ROM. This burn writes all
three anyway. Keeping it would have left a decodable opcode that reads
GARBAGE: `src=SW` asserts `SRC_ACTIVE` so `U25` is enabled, but SW asserts
neither `~{ROM_OUT}` nor `~{RAM_OUT}`, so `U25` drives `W` from a floating
MDR.

**FACT — the oracle now models `FLAG_C`, and it REFUSES to invent one.**
`ALU_CIN = NAND(SA1,SA0)`, so `SUB`/`BSUB` get `CIN=1` and the '382's `CN+4`
is a NOT-borrow: `FLAG_C = 1` means `A >= B` unsigned. **OPEN — `CN+4` after
a LOGIC function code has never been measured**, and the '382 does not define
it, so `simulate()` raises on a `JNC` that reads a carry no arithmetic op
produced rather than answering 0. One scope reading on `U40.14` after an
`AND` closes it. A stand-in better than the hardware hides defects.

**FACT — all four flags are latched TODAY**, netlist-extracted from
`dino_v0_0_2/alu.kicad_sch` on 2026-08-25. `U49` is a `'273` clocked on
`~{CLK}` holding `FLAG_C`/`FLAG_Z`/`FLAG_V`/`FLAG_N`, and `U48` is a `'157`
whose select is `~{ALU_OUT}` — so the flags UPDATE when the ALU is the source
and HOLD otherwise. That hold is why a `Z` set by `AND` survives to a `JNZ`
two instructions later, which every poll loop leans on. **The only thing
missing was the branch SELECT**, and it is drawn: `U62` g1 computes
`COND_TAKEN = NOR(~{COND}, COND_FLAG)`, `COND_FLAG` comes off `U77.4`, and
`CW21` is a real crossing. `CW22`/`CW23` on `U23` are still no-connects, and
`word()` now REFUSES to encode a flag or a polarity they would be needed for
— `V` and `N` both have `FLAG_SEL` bit 0 clear, so either would drive `CW21`
low and silently branch on the carry. See `.git/sdd/PHASE_F.md`.

**FACT — `ALU_CIN = NAND(SA1, SA0)`.** `U53` is a `74LS08` (pins 12,13 -> 11
= `AND(SA1, SA0)`) and `U50` g4 is a `74LS02` section wired as an inverter,
so `ADD` (SA=3) gets `CIN=0` and `SUB`/`BSUB` get `CIN=1`. Recorded at
project level because a wrong version — `OR`, and later `NOR` — was in
circulation: `NOR` would give `CIN=0` for `SUB` as well, making it compute
`A-B-1` on a machine whose `SUB` is bench-proven.

## Open questions

Named because they are not settled. None is blocking.

**CLOSED FOR GOOD 2026-09-06 — IT WAS THE `RESET` WIRE'S ROUTE.** The
post-HALT flood, the "HALT escapes", the "bad" EEPROMs, the `T0` 22pF and
the serial garble that made the monitor unusable were ONE wire. `RESET`
(`U27.9`) ran root -> PC board -> memory board in the bundle with fast
edges and picked up ~1.5V for ~10ns once per few thousand cycles. `U75`
g3 regenerated it into a 3.3V pulse on `RESET_B` into the 16550's `MR`
(LCR/FCR cleared, 5-bit framing: `PROG_txlive` OB `0x00`); the same runt
into `U61.2` clears `T` when it lands on a CLK edge. Found with
`asm/txlive.asm` and a scope triggered on `U103.35`: a probe cured it at
`U75.9` and at `U10.6` -- anywhere on the net -- but not at `MR` alone.
**Pulling the wire out of the bundle fixed it with NO caps.** `T0` cap
is OUT. `U9`/`U15` were fine. Route rule for the PCB: `RESET` away from
CLK and the buses. **CORRECTION, same evening: the post-HALT `~WR` strobe
is a SECOND fault and survived the RESET fix.** Walked to `U30.7` (hard
low, `CW0-2 = 111`), `U9` alone in an access (`U15` on the same address
bus still), every `U9` leg flat, no ROM row near HALT is `1111`, and
pressing `U9` down makes it rarer: a marginal SOCKET CONTACT on `U9`,
flexed by the 09-05 chip swaps. Socket replacement pending. Design item:
a control-word pipeline register would make this whole class invisible.
Record in `.git/sdd/PHASE_G_0.md`, last two sections.

**CLOSED AGAIN 2026-09-05 — HALT HELD ALL ALONG; `U15` WAS CLEARING THE
T-COUNTER UNDER IT.** Every "OB moves after HALT" reading up to and
including this morning's was `END` (`CW12`, `U15.16`) lifting for ~25ns
into `U61` g1, `~MR` on `U6` dipping across a CLK edge, T clearing to 0,
and the byte behind the HALT executing. The chip was putting the pulse
out with a static address, clean rails and `~OE`/`~CE` low, at times
locked to no clock in the machine. A fresh AT28C64B with the same image
does not. LA, 100MHz, three clips: `U6.1`, `U6.14`, `U6.2`. Record in
`.git/sdd/PHASE_G_0.md` RESULTS, FAULT 1. **A fault independent of the
CLOCK is not in the logic.** Wander slot 1 holds `0x11` indefinitely.

**CLOSED 2026-08-25 — HALT HOLDS. The "escape" was never tested.**
`PROG_flow` reached `OB = 0x39` and held it for **at least 81 minutes**
free-running with Y1 seated — ~5.0x10^9 clocks, with `CET` on the '163
sampled on every one of them. Rico's ruling: *"it holds. it was a false
error we probably saw once, but did not test."*

This entry previously read **"OPEN — HALT does not hold. The machine halts,
then escapes after a few seconds, varying."** It had no recorded date, no
conditions and no session log — the same defect this document was rewritten
to stop repeating, and it survived long enough to justify a three-wire
`U61` latch in `PHASE_F.md` SECTION 0.

**The measurement is sound because the witness cannot miss.** `PROG_flow` is
the only image where an escape is visible: `bad` (`LDAI 0xE7; OUT; HALT`)
sits immediately behind the final HALT, so an escape flips OB `0x39 -> 0xE7`
and **sticks** — everything past `bad` is `SAFE_FILL = 0xFF = HALT` and
nothing there executes an `OUT`. An unwatched transition is therefore not
missed data. OB never left `0x39`.

**Consequence: the `U61` HALT latch is NOT built.** `PHASE_E_PLAN.md` Task 0
steps 0b-0e are retired unexecuted; `U61` g2/g3 stay free for phase F, which
counts them. Full record in `PHASE_E_PLAN.md` RESULT 0a.

**The lesson is the rule, not the reading:** a fault seen once and never
reproduced is an observation, not a defect. Give it a witness that cannot
miss and a recorded duration before it earns a fix.

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

**THE LADDER IS HISTORY, NOT PROCEDURE.** All five blocks were bench-proven
2026-08-02, and the rig that drove them is retired — nothing drives `IRB0-7`
now, so block 1 and block 2 cannot be run as acceptance blocks at all. What
survives is the classification: COPPER, STRAP and SAMPLE are netlist-derived
and still describe the machine. DRIVE is the rig-only part.

**Phase D moved `block2`.** Its RAM enable used to come from control_word,
in-block; it now comes from the MDR board, which does not join until block3.
`block2` therefore straps `~{ROM_BUF_EN}` LOW and `~{RAM_OE_G}` HIGH — both
forced, since `~{RAM_OE_G}` LOW would leave `U19` and `U21` both driving
`MDR0-7`. Cost: block2 can no longer read RAM under microcode control.

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

    docs/notes/kicad_contracts.py   contracts + crossing lists
                                    --continuity <refs>  what to land
                                    --since <rev>        what changed, classified
                                    --stamp              MODULE CONTRACT blocks
                                    --pinmap             DEAD, throws. Rig retired.
    docs/notes/microcode_gen.py     microcode ROM images + CRCs + header
    docs/notes/progrom_gen.py       program ROMs, and the Python oracle
    docs/notes/layout_gen.py        breadboard placement, slot maps,
                                    wiring guides, layout pages
    docs/notes/kicad_netlist.py     build_report() — the netlist oracle
    docs/notes/fpga_gen.py          DEAD with the twin
    docs/notes/coverage_lint.py     DEAD with the twin

**The oracle is NOT the twin.** `simulate()` in `progrom_gen.py` interprets
the real microcode rows out of `microcode_gen.INSTRUCTIONS` and computes what
`OB` should read. It produced `alu 0x39`, `mem 0xC5`, `stack 0x27`,
`ramexec 0x6E` — the answer key you compare the machine against. Without it
a coverage ROM is a program with no expected value. It stays.

    python3 docs/notes/progrom_gen.py --expected

Host tests sit next to each (`test_*.py`), plus C model tests in
`tests/dino_bringup/hosttest/` — those compile against the retired rig's
expectation headers, so they die with it unless the headers are kept.

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
- **A FAULT THAT IS INDEPENDENT OF WHAT THE MACHINE IS EXECUTING IS NOT IN
  THE DATAPATH.** 2026-09-01, and it cost fifteen diagnostic ROM images.
  Nine different loops -- no RAM, one read, one write, conditional branch,
  unconditional branch, only-original-instructions, and each new
  instruction on its own -- ALL died at the same ~200ms wall clock. That
  uniformity WAS the answer and it was visible after the third
  measurement: when changing the program changes nothing, the program is
  not the variable. The cause was the reset circuit asserting itself
  ~90ms after power-up. **Before writing an instruction-level test, check
  that instruction-level differences move the result at all.**
- **START WITH THE RAILS. 2026-09-01, ROOT CAUSE OF THE RANDOM HALT.** A
  fault that is program-dependent, random, probe-sensitive and answers to
  a 22pF on a logic input is not a logic fault. DMM, DC, black lead on the
  SUPPLY terminal, red on one GND pin and one VCC pin per board, machine
  running. Thirty seconds. The day this was finally done it read `U27.7
  142mV, U6.8 342mV, U15.14 460mV`: LS LOWs from the microcode board were
  arriving at the clock board's NOR with 80mV of DC margin, and every CLK
  edge's ground bounce ate it. `HALT` and `END` both glitched into `U6`.
  Bulk caps do nothing for DC drop — the fix is copper: supply entry at
  the centre boards, GND and VCC starred to every board. **Rico's rule:
  computers are analog; when a fault is not in the program, measure the
  rails before building a single logic model.** For the PCB: ground
  plane, star or per-board power entry, and this is why. Sister rule
  below found the same class of fault on a single node; this one is the
  whole machine.
- **A VOLTAGE INSIDE A SCHMITT'S HYSTERESIS BAND IS A RANDOM-EVENT
  GENERATOR. 2026-09-01, ROOT CAUSE OF A THREE-DAY HUNT.** The reset RC
  node sat at **2.45V** -- ~255uA being sunk against `R1`'s 10k. A
  `74HC14` at 5V has `VT+ ~2.9V` and `VT- ~2.0V`, so the node sat squarely
  BETWEEN the thresholds: the Schmitt held its last state and any noise
  flipped it. The machine reset itself at random, roughly every 200ms.
  **The sink was `U56` ITSELF -- the '14's input was damaged**, not `C1`.
  C1 was suspected first because a leaky electrolytic is the usual answer
  to that measurement; lifting it settled the question in one step, which
  is why lifting is worth doing before replacing.
  **`U56` IS NOT ONLY THE RESET SCHMITT.** Its section 1 inverts `T3` for
  the T-state decoders -- `U8.6` takes `T3`, `U7.6` takes its complement --
  so a damaged part there corrupts T-STATE DECODING, which is program-
  independent random misexecution. Suspect the whole package, not the one
  section whose symptom you noticed.
  **The signature: the fault was independent of the program, worse with
  handling, and vanished entirely while the reset button was HELD** --
  because holding it pulls the node to a clean 0V. Measured with a DMM in
  thirty seconds once anyone looked at the node instead of the datapath.
- **THE RESET CIRCUIT IS ALSO INVERTED AS DRAWN, 2026-09-01.** `U56` is a
  `74HC14` -- an INVERTING Schmitt -- with `R1` 10k pulling the node UP and
  `C1` 10uF to ground, so `RST_SIG` starts HIGH (reset released, machine
  runs) and falls LOW after `10k x 10uF ~= 90ms` (reset asserted, and it
  stays asserted because C1 stays charged). Holding the button discharges
  C1 and the machine runs; releasing it kills the machine ~90ms later.
  The symptom is a machine that runs for a fifth of a second and stops,
  regardless of program. **Fix: route `RST_SIG` through a second `'14`
  section -- `U56` has four spare -- which also gives the machine the
  power-on reset it has never had.** The reset circuit was changed after
  the 81-minute `PROG_flow` soak, which is why that result and this one do
  not contradict each other.
- **A LOOSELY SEATED DECOUPLING CAP IS WORSE THAN NO CAP.** Rico,
  2026-08-27, after a full day lost to it. A cap on a marginal contact is
  an inductive stub across the rail, not a bypass. The signature is
  behaviour that depends on POWER-UP HISTORY rather than on inputs: the
  same ROM returning a correct answer on power-up and a wrong one after
  RESET, the same program drifting between sessions, and a fault that
  worsens monotonically as the boards are handled. **Combinational logic
  cannot depend on what ran before it.** When a reading does, stop
  building logic models and go press on the passives -- five successive
  models were fitted to that noise before the caps were reseated, and
  every one of them was wrong. Reseating restored it. Corollary: after
  ANY session of repeated chip swaps, re-seat the decoupling before
  trusting a single reading, because every pull flexes the board.
- **A CHANGE THAT IS LOGICALLY IDENTICAL AND ONLY FASTER IS A TIMING
  CHANGE, AND THE ORACLE IS BLIND TO IT. 2026-09-05, twice.** `NAND(READ,
  M15)` and `NAND(RAM_OE_ON, M15)` are the same function; the first is
  three gates quicker on `M15` and turned the RAM on while `U18` was still
  parking a ROM byte. The `MVI` settle row's first cut moved `pc_up` one
  row and made the ROM change address under an open latch. Both passed
  every host test. **Before re-sourcing a pin, list every transparent
  latch that is open across the boundary it speeds up.**
- **A WITNESS THAT REWRITES THE SAME VALUE IS MIRROR-BLIND TO A WRITE
  FAULT. 2026-09-05.** `PROG_isa` planted `0x2E` into `CELL` with `MVI`
  147 times per pass and read `0xB4` while `MVI` was writing a MIX of the
  immediate and the cell's old byte -- old and new were equal. The monitor
  found it by writing two different pointers into one cell. Every plant
  in a self-test must differ from what the cell held.
- **A RUNT CURED BY CAPACITANCE ANYWHERE ON A NET IS PICKUP ALONG THE
  RUN, NOT A FAULT AT A PIN. 2026-09-06, THE `RESET` WIRE.** Two days of
  chip swaps, a `T0` cap and a ground plan went into a runt that a probe
  cured at `U75.9`, at `U10.6`, at either end -- and pulling the wire out
  of its bundle cured with nothing fitted. Before blaming either end of a
  wire, look at what runs beside it. Sister rule: **the UART is the only
  device in the machine that counts strobes or has an asynchronous reset;
  a serial-only fault with `isa` clean is a strobe or a reset, never the
  datapath** -- RAM shrugs off a spurious rewrite, a FIFO does not.
- **A COMPONENT VALUE IS COPPER TOO. 2026-09-04, the cold-boot UART fault.**
  Rule 4 verifies WIRING; a beep cannot tell 1uF from 10uF. `C1` was 1uF
  in the socket against 10uF in the drawing, the power-on reset was a
  0.8ms runt at half rail, and an evening went to two wrong theories about
  the parts AROUND the RC while the RC itself was never measured. The
  0.8ms release against a 40ms expectation WAS the measurement -- a 10k RC
  that lets go that fast is 1uF. When a timing is 10x off, suspect the
  passive's value before the silicon's threshold. Scope the node on a
  button release: the tail is tau, in one capture.
- **A single-shot test on a marginal board reports noise with a straight
  face.** Repeat the operation N times inside one image and pass only on
  unanimity. `PROG_sui16` was the pattern (image deleted 2026-09-01 with
  the rest of that day's diagnostics; the shape is what matters) -- sixteen
  identical subtests,
  one verdict.
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
- **A test nothing calls is not a test.** `test_microcode_gen.py` held the
  only check that compares the microcode's SA ENCODING against the '382's
  WIRING — written after three bench images agreed on a wrong answer because
  `ADD` executed as `AND`. **It had never run.** Three things stacked: the
  module's self-check was module-level asserts plus a closing `print("OK")`
  and never called its own `test_` functions; `unittest` collects nothing
  from bare functions; and `pytest`, the only runner that would have
  collected them, is not installed on this machine. It printed OK and
  exited 0 while asserting nothing. It ALSO would have failed if reached —
  it matched the bare alias `SA0` where the net reports as `CW11/SA0`, the
  alphabetical-first rule biting a TOOL instead of a schematic. Guarded now
  by `test_suite_reachability.py`, and the fix everywhere was to ENUMERATE
  `test_` functions rather than list them by hand: a tuple of names is a
  step someone has to remember.
- **An instruction's T-state cost is `1 + len(rows)`.** `T0` is the implicit
  universal `FETCH` and is not in `INSTRUCTIONS[name][1]`. Summing rows and
  calling them T-states put a 2x error into the UART polling headroom — 133x
  claimed where the real figure is 67x — and it survived review because the
  conclusion it supported (polling is adequate) was true either way. **A
  margin that is right for the wrong reason is still unmeasured.**
- **A 3-bit field decode is bank-blind.** Bank-1 `PC_LO` (code 10) shares its
  low three bits with bank-0 `RAM` (code 2). Both `check_word` and the Python
  oracle read a PC push as a RAM read until the decode folded in the bank
  bits.
- **`src=RAM` cannot write MAR in the same word.** The RAM address is MAR and
  the '373s are transparent while CLK is low, closing a live loop
  `MAR -> M -> RAM -> MDR -> U25 -> W -> MAR`. ROM reads are exempt: their
  address comes from the PC.
- **`misc=MDR_OUT` must follow the read that parked the byte, with at most
  one `src=NONE` settle between, and a ROM-side park NEEDS that settle,
  with `pc_up` on the settle and not on the park.** `LE_MDR` falls when
  `READS_IDLE` rises, three gates after the decode; a `mux_pc` flip in the
  same boundary turns the RAM on under the open latch, and a `pc_up`
  moves the ROM's address under it. 2026-09-05, `MVI`. `LE_MDR` no longer
  opens on `~RAM_LOAD` (`U39.4` strapped +5V), so the replay row itself
  cannot re-open the park.

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

**`.git/sdd/` IS NOT VERSIONED, AND THAT IS A SETTLED CHOICE.** Git cannot
track its own directory, so the phase documents there have no history and no
backup. Rico knows and has ruled: **do not raise it again.** Do not propose
moving them, mirroring them, or committing them. `.git/sdd/` is where process
documents live, full stop.

**Process documents live out of tree in `.git/sdd/`** — bring-up procedures,
plans, investigations, session handoffs, progress checkboxes. Any stale
in-tree reference to one of them (BRINGUP.md, dino_mar_lo_investigation.md,
dino_hardware_growth_plan.md, …) resolves to `.git/sdd/<name>`. The repo
keeps design and reference docs plus everything generated.

LIVE — read these:

    .git/sdd/PHASE_E_PLAN.md                 the eight-task implementation plan
                                             for phase E. START HERE
    .git/sdd/PHASE_F_STEP_1_LANDING.md       U77's landing list: the four pins,
                                             the one lift, and the inert proof
    .git/sdd/PHASE_E.md                      the phase E SPEC: a 16K I/O window
                                             carved out of ROM space at
                                             0x4000-0x7FFF, eight 2K card slots
                                             decoded on M11-M13, the published
                                             bus, IN retires, the DIP switch
                                             becomes card zero. ON SILICON
                                             AND COMPLETE 2026-08-26
    .git/sdd/PHASE_F.md                      ISA extension: one '157, then
                                             everything soft. Independent of E
                                             and G in both directions. Carries
                                             the collision-free opcode map
                                             (SECTION 6). STEP 1 DRAWN, STEP 2
                                             WRITTEN AND HOST-GREEN, NOTHING
                                             BURNED. Read its RESULTS section
                                             FIRST -- the spec above it
                                             predates the rulings
    .git/sdd/PHASE_G_0.md                    the monitor (D/W/O over serial,
                                             host-green) AND the fix that
                                             lets it run: ROM readable as
                                             data, three re-sourced pins.
                                             REMOVE/ADD/BEEP tables, the
                                             witness order, the OPENs. ON
                                             SILICON 2026-09-05; RESULTS has
                                             the four faults. START HERE
    .git/sdd/PHASE_G.md                      the serial card: '138 + '245 +
                                             PC16550D. Follows E; does NOT
                                             depend on F. ON SILICON 2026-09-04
    .git/sdd/PHASE_I.md                      CompactFlash storage: '138 +
                                             '138 + '245 + '04 + CF-to-IDE
                                             in slot 2 (0x5000), 8-bit PIO,
                                             DFS filesystem, BOM. Follows E
                                             and G, assumes the monitor.
                                             SPECCED 2026-09-04, not drawn
    .git/sdd/PHASE_D.md                      execute-from-RAM: build
                                             procedure, both checkpoints,
                                             the ramexec result
    .git/sdd/RIG_RETIREMENT.md               the ATmega is retired; what is
                                             dead, and what must NOT be
                                             deleted with it
    .git/sdd/POWER.md                        PCB phase starts HERE. Supply
                                             choice (ATX / PicoPSU / brick),
                                             current budget, TASKS 1-3:
                                             measure the machine, measure the
                                             ATX, feed the machine. Written
                                             2026-09-08; draw 1.25-1.34A
                                             (bench ammeter, 2026-09-10)
    .git/sdd/GROUNDING.md                    ground is a wire. Star, external
                                             grounds at the star only, measure
                                             the table. The primer 2026-09-05
                                             should have started with. READ
                                             BEFORE WIRING ANYTHING
    .git/sdd/CLOCK_DISTRIBUTION.md           the 100R fix and the PCB
                                             consequence — read before any
                                             board gets its own clock branch
    .git/sdd/dino_hardware_growth_plan.md    what is planned and priced
    docs/notes/dino_isa_for_basic.md         the instruction set roadmap

HISTORICAL — accurate for their moment, superseded since. Do not follow
them as procedure:

    .git/sdd/PHASE_C.md                      CALL/RET landing record
    .git/sdd/dino_mar_lo_investigation.md    why the recorded bus readings
                                             are not evidence
    .git/sdd/SP_BEEP.md                      phase-B landing record
    .git/sdd/SP_DEBUG.md                     phase-B LA capture plan
    .git/sdd/dino_stack_bringup_handoff.md   stack bring-up; stack is DONE
    .git/sdd/BRINGUP.md                      per-stage bench procedure;
                                             rig-era, and the rig is retired
    .git/sdd/README.md                       progress checkboxes, rig-era
    .git/sdd/dino_test_bringup_design.md     the bring-up spec, rig-era
    .git/sdd/BRINGUP_FPGA.md                 the fabric; twin is retired
    docs/notes/dino_fpga_vplan.md            coverage map; twin is retired
