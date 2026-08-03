# DINO bring-up rig

**Bench procedure lives in [BRINGUP.md](BRINGUP.md)** — per-stage wiring
tables, commands, expected output, failure meanings. Start there.

Bare-metal ATmega2560 test rig for the DINO CPU. Spec:
`../../docs/notes/dino_test_bringup_design.md` (test definitions,
build-program order, power/grounding rules). Pin hookups: flash, connect
serial, `pins <module>`.

## Quick start
    source env.sh          # port autodetect (override: DINO_RIG_PORT)
    build                  # avr-gcc via Makefile
    flash                  # avrdude through the Mega bootloader
    monitor                # screen, 115200 (exit: ctrl-a k)

## Shell
    list                   # all tests grouped by module
    run all                # everything (absent modules fail presence fast)
    run root               # one module
    run root.divider       # one test
    pins root              # jumper hookup table (GND first, always)
    selftest root          # rig-only loopback for ONE module's pins —
                           # prints its own pair list (root = 6 jumpers).
                           # `run selftest` = full 27-jumper all-pin check.

## Per-module workflow
    1. build the module board, hand-check it
    2. `selftest <mod>` — jumper the printed pairs, rig-only, expect PASS
    3. pull the jumpers, wire the DUT per `pins <mod>`
    4. `run <mod>` — fix / approve

## Bench rules (from the spec — non-negotiable)
- Bench 5V powers the DUT boards; Mega on USB; grounds commoned once.
  An UNPOWERED board does NOT fail cleanly: the rig's driven lines steal
  current through the DUT's input clamp diodes and CMOS parts read fine
  on it (measured 2026-07-23: memory scored 7/10 with the supply off).
  Every module suite gets a `power` test that runs first — it holds the
  rig's outputs low so there is nothing to steal. FAIL there = check the
  supply before believing any other FAIL.
- 220-470R series resistor in every rig-DRIVEN jumper.
- SWAPPED RIG WIRES are a first-class fault (ALU bring-up 2026-07-26). When
  two signals behave as EACH OTHER'S values, there are three places the
  transposition can live: the board wires, the strip slots, or the rig
  ribbon. Check the RIBBON FIRST — it is one accessible end, nothing is
  glued down, and both ends look correct at a glance. On the ALU this cost
  two rounds of beeping the DUT (U48 outputs, then U48 inputs) before the
  ribbon turned out to be the culprit.
- root runs LIVE: Y1 seated, DUT free-runs at 1.024MHz; rig monitors and
  drives only contract signals (END/HALT driven, rest sampled). You press
  the physical reset button when a test prints `ARM ...` — 10s window.
  Note: RESET stays asserted a while after release (RC stretch, measured
  0.25-2.2s bench-dependent); tests wait on the line, not a timer.
- Later module stages: rig is the clock, Y1 OUT (per spec).
- Loopback jumpers for `run selftest` are printed by the test itself.
- `run selftest` (and therefore `run all`) drives the loopback pool pins,
  which double as root's sampled lines — run selftest ONLY in the rig-only
  loopback config, never with a DUT board wired (series resistors limit
  the damage, but don't lean on them).

## Build-program progress (update as stages pass)
- [x] 1 rig self-test — CLOSED 2026-07-28 as WON'T-RUN-AS-A-GATE. Never run on the bench, and it doesn't need to be: the module tests validate the rig more completely than a loopback jumper does. Selftest proves pin->jumper->pin; a module test proves pin->ribbon->strip->chip and back, so ten modules green already means every pin in those bundles drives, reads, and maps to the net the pinmap claims. A dead pin or a wrong pinmap entry cannot survive a module going green. The regress ("what tests the tester") terminates at independent agreement, not self-inspection: host-tested expect models (no AVR, no rig), netlist-derived assertions, a generated pinmap, and ten modules agreeing with all three after first going RED on real faults. mod_selftest.c STAYS in firmware as a DIAGNOSTIC, not a stage — when a freshly wired board comes up all-red, `selftest <mod>` rules out the rig side in one command and ~6 jumpers. Jumper tables and failure signatures live in BRINGUP.md stage 1.
- [x] 2 root — PASSING on bench 2026-07-15 (live-clock guided workflow, 5/5)
- [x] 7 pc — PASSING on bench (baseline 9/9, by 2026-07-16). Hardened beyond passing: blind fault-injection runs (pulled GND, pulled ~CO2 carry wire) — suite correctly fingerprinted each fault class (value-dependent load corruption = grounding; bits 8-11 count corruption + growing clear residue = floating '193 UP pin).
- [x] 4 microcode — PASSING on bench 2026-07-16, BOTH burns (DIAG 7/7 then REAL 7/7, CRCs exact: U9=0xAD70 U15=0x58D7). Caught during bring-up: A8-A11 wire rotation + rig-side IRB5/7 jumper cross — addr.order self-named every one. REAL pair stays seated. Opcode table is PROPOSED 2026-07-16 (only LDAI=0x11 was documented) — see microcode_gen.py OPCODES.
- [x] 3 control_word — PASSING on bench 2026-07-17 (7/7). Pin layout: one unbroken D53->D22 descent, one contiguous block per chip (kicad_contracts.py PIN_ASSIGN/PIN_PROBES); `pins control_word` prints every wire, probes included. Bring-up caught 5 rig-wiring faults over 5 runs, all on the U62/COND leg + the D19 spill wire — the U62 input/output probes fingerprinted each one from the FAIL pattern alone (~PC_LOAD=NOR(FLAG_Z,..) signature, probe-reads-Z signature, floating pin 1). One-hole slips around U62 pins 1/2/3 were 4 of the 5. INT-A (control_word + microcode) now unblocked. INT-A unblocks when this passes.
- [x] 10 mdr — PASSING on bench 2026-07-20 (8/8, landed early out of build-order). bridge.route retired schematic bug 4 on real copper. Bring-up caught 6 rig/board wiring faults over 3 runs, all serial-log-diagnosed: IRB bank dead (U34 side), WRITE_DIR wire, BUS_DIR run to U25.1, ~IR_LOAD leg, and the finale — U18.1 (OE) wired to MDR_OUT (U37 pin 6) instead of ~{MDR_OUT} (U37 pin 5): enable polarity inverted, U18 drove MDR at idle and released during replay, which cascaded into capture/tristate/bridge/stability fails until the fight analysis fingered U18. THIRD one-hole-slip fault class on this build ('04 in/out pins are adjacent — beep against both neighbors before power).
- [x] 5 registers — PASSING on bench 2026-07-21 (9/9). Longest bring-up yet (~8 runs): CLK<->C_LOAD leg swap, /OUT distribution shifted one register, gate-INPUT-vs-OUTPUT taps (U57.8-for-10, U57.14-VCC-for-13 — the beeps-to-every-chip rail fingerprint), dead 5V rail segment + lost U44 DIR strap after rework (parasitic-power signature: gates die as more strobes assert), OUT harness mirror+bridge+dangle, and the finale: PORTF->MDR jumper bank flipped — invisible to every A/B/C round-trip test (write/read through same wires cancels), caught ONLY by the asymmetric outreg path. Mirror-witness rule now codified in the spec; warmup vector hardened 0x5A->0xC5 (palindrome was mirror-blind). Meter rule earned: never beep a live board (`idle` first); in-circuit leg-to-leg reads diodes, not copper.
- [x] 8 mar — PASSING on bench 2026-07-22 (7/7). Bring-up caught: missing common ground (the all-float scan — bench rule 1 in action), a full stale-layout rewire (pre-PIN_ASSIGN hookup; rewire-alert process rule born here), '245 CEs on the inverted mux net (U60.13 for .11), the scrambled U60 right column, M9<->M10 swap (walk-decoded). One test bug found+fixed in the open: logic pass A compared RAM_EN against a latch that sweep states could recapture from floating W — W now held during the pass, and mismatches print state+signal detail. Suite: 7 tests, gate model host-tested, 2 probes (both on U60), decode hits the 0x8000 boundary from both bus drivers incl. a latch-vs-bus contradiction row. INT-C (pc+mar) unblocked. See BRINGUP.md stage 8.
- [x] 9 memory — PASSING on bench 2026-07-23, BOTH burns, 11/11 with the power test (DIAG crc 0xDFE7, REAL crc 0xF501 — both exact). The '121 is GONE: memory.window proves the RAM write pulse is now NAND(WRITE_DIR, ~CLK), a gate off the clock phase. memory.idle retired schematic bug 2. Added after a deliberate power-off run scored 7/10: memory.power, a phantom-power check that runs FIRST (rig sources nothing, so an unpowered '00 cannot hold its HIGH outputs). Bring-up: ONE fault, one run — MDR5<->MDR6 crossed (D48/D47), decoded from the byte-0 arithmetic alone (0xA5 -> 0xC5 = exactly a bit-5/6 exchange). ramrw/window/idle all passed THROUGH the swap because they round-trip the rig's own bytes — only the asymmetric ROM path could see it (mirror-witness rule earning its keep). Firmware (mod_memory.c, 10 tests; U51 gate model host-tested in hosttest/test_mem_expect.c; netlist-verified 2026-07-23), BENCH PENDING. v0.0.2 board updated to v0.0.3: the '121 one-shot is gone, the RAM write pulse is a gate (NAND(WRITE_DIR, ~CLK)) — memory.window is its test. memory.idle retires schematic bug 2 (U21 CE = AND(~RAM_OUT, ~WRITE_DIR)). NEW TOOLING: docs/notes/progrom_gen.py (host-tested, 16 tests) emits roms/PROG_diag.bin (self-naming address proof over 15 lines) + roms/PROG.bin (THE MILESTONE PROGRAM: LDAI 0xFF; OUT; LDAI 0x2F; LDBI 0x1E; ADD; OUT; HALT, safe-filled HALT) + CRCs + src/progrom_expect.h; assembler validates operand counts against microcode_gen's instruction table. Burn: make burn-prog-diag / burn-prog. Pin layout is ribbon-first per Rico's bench call: both byte buses in one unbroken 24-pin run D53->D30 (MDR0-7 = D53-D46, M0-M15 = D45-D30), signals on D29-D22 + D19 — neither bus is byte-aligned, so this module drives/samples per pin. See BRINGUP.md stage 9.
- [x] 6 alu — PASSING on bench 2026-07-26 (10/10). Board wiring was sound; the bring-up cost was process, not copper (see the ledger: slot renumbering mid-wiring, and a map reconstructed from inference instead of read off the board). Real fault: swapped rig ribbon wires on the FLAG_Z/FLAG_V pair. Test bugs found and fixed: alu.shadow's held-value assertions called compute(), which reloads the operands it was checking; alu.power claimed UNPOWERED on a partial collapse. '382 C/V on the logic codes came back operand-dependent (XOR 3/10, OR 1/10, CLR & AND 10/10, SET 0/10) with C and V always agreeing — deterministic but not constant, so not worth a baseline. Original: (mod_alu.c, 10 tests; arithmetic + gate model host-tested in hosttest/test_alu_expect.c, exhaustive over the operand grid; netlist-verified 2026-07-24), BENCH PENDING. Most probed board on the machine: 10 of 20 control wires are probes (both shadow stamps, ALU_CIN, the CRY nibble ripple, ALU_C/ALU_V/Z combinational AND FLAG_C/V/N registered — so a flag FAIL says whether the arithmetic or the commit lied). C/V asserted only on the three arithmetic codes ('382 leaves them undefined for logic). See BRINGUP.md stage 6.
- [x] 11 io — PASSING on bench 2026-07-26 (5/5, FIRST RUN — the only module to pass first time). Guided tests: io.switches prompts per-switch open/closed (pull-ups + switch-to-GND mean a CLOSED switch reads 0, so the prompt spells it out rather than naming a byte); io.leds walks a single LED twice then lights all eight, two y/n questions. Patterns 0xC5/0x3A chosen non-palindromic per the mirror-witness rule. io.tristate is the one that matters downstream — the '244 must truly release W for the ALU/MAR/MDR to share the bus.
Integration is BLOCK-BASED, CONTROL-FIRST, and BLACK-BOX (2026-07-28,
supersedes INT-A..INT-E — see BRINGUP.md "THE BLOCK LAW" and
"Integration — CONTROL FIRST"). Make the control unit real first; every
later block then gets its strobes free, in copper, and the rig only sheds.

THE BLOCK LAW: sample a signal at block level ONLY if its value depends on
more than one member of the block. Module coverage is already extensive —
a block that re-samples what a module test retired is a module test with
more wires. COPPER (out of one member, in of another) is DROPPED, not
probed. STRAP what needs a safe level but no stimulus. Every retirement
NAMES the test that earned it. END/HALT are the one accepted exception:
copper, but sampled in every block because nothing else segments the
instruction stream.

THE GATE IS DRIVEN-WIRE COUNT, AND IT MAY NEVER GO UP. Risk is not
symmetric: a wrong SAMPLED wire is a false FAIL, a wrong DRIVEN wire can
fight a real driver, and a wrong driven STROBE is worst of all because
strobes are enables.

NOTHING IS EVER PULLED — no chip leaves its socket, no board-to-board
copper is ever removed, Y1 stays seated from Block 1 to Block 5. Rig
jumpers come off freely as they retire; that IS the ladder. Temporary
board straps must come off when real copper takes over the net.
CONSEQUENCE: CLK (U27.5) and RESET (U27.9) are '74 outputs the rig cannot
drive without contention, so EVERY BLOCK FREE-RUNS AT 1.024MHz AND
NOTHING IS SINGLE-STEPPED. Every test is burst-capture-and-decode.

THREE INSTRUMENTS, THREE QUESTIONS: the rig answers WHAT (logic and
topology, exhaustive, but it CANNOT see timing); the DSLogic LA answers
WHEN; the scope answers HOW (analog — edge quality, ringing, marginal
levels). The Mega burst-captures two ports at 437ns/sample (547ns if
either is PH/PJ/PK/PL — extended I/O needs lds, not in), which is enough
for every logic-value question on this ladder and useless for a 10-30ns
decode glitch. Order: rig, then Mega burst-capture, then LA, then scope.

END and HALT are the same two wires in ALL SIX BLOCKS — D45/D42, tapped at
U61.3/U61.5 (the CONSUMER end, where END reaches U6.~MR and HALT reaches
U6.CET). Land them at Block 1 and do not touch them again.

- [x] BLOCK 1 — CONTROL: root + microcode + control_word. **PASSING on bench 2026-07-30, 6/6.** 8 driven, 31 sampled, 39 jumpers + GND. `block1.decode` compared **29043 control words** against MC_REAL_WORDS with **zero mismatches and zero transients**; `block1.opmap` read **17/17** of the implemented opcode map straight off the hardware. RETIRES: the microcode ROM EXECUTED for the first time (only the SA field was previously proven, via alu.ops), the tap runs from ROM to decoder, decode correctness in copper at 1.024MHz, the END/HALT/T-state contract with the real ring counter, RESET recovery, and ENABLE OVERLAP — never tested at any level before now.
  ONE HARDWARE FAULT, and it was rig-side: **the IRB ribbon was reversed end-for-end**, bit N landing on bit 7-N. Only 0x00 and 0xFF are bit-reversal-invariant, so HALT=0xFF masked it completely and every early run passed `seq` while decoding nothing. The mirror-witness rule again: a flipped bank is invisible to any symmetric test. `block1.opmap` — force all 256 IRB values, report which produce a non-fill row — is the asymmetric probe that named it, and it is why opmap now runs BEFORE decode.
  EVERY OTHER FAULT WAS THE RIG. In order: opcode enumeration guessed from the image (T0 is FETCH for all 256, so 238 fakes were walked); a uint8 mismatch counter that wrapped 1060 to 39; a two-confirming-sample rule that was arithmetically impossible (CLK-low is 488ns = 7.8 cycles, one sample per T-state at most) and emitted zero frames while onehot and stability reported PASS on nothing; run alignment inferred from frame POSITION, which needs the fetch frame to be unique — it is not, since LDA's T0/T1/T2 differ only in DST; a capture that read CLK before the group port so samples straddled the rising edge; a sampler too slow to fit the CLK-low window, yielding 2 samples in 68000 attempts; and a phase-locked loop that never reached half the T-states. The fix for the last three was Rico's original proposal: SAMPLE T0-3 AND LET EVERY SAMPLE LABEL ITSELF.
- [x] BLOCK 2 — + pc + mar + memory. **PASSING on bench 2026-08-01, 2/2.** 8 driven (unchanged), 15 sampled, 23 jumpers + GND. `block2.fetch` proves ADDRESS ORDER from inside one instruction: LDA reads ROM at T0/T1/T2 — PC, PC+1, PC+2, consecutive BY CONSTRUCTION — captured from a fixed-interval burst so adjacency is proven rather than assumed, then matched against the DIAG image. Two runs matched at 0x0838 and 0x1943, wherever the PC happened to be. RETIRES: the PC_MAR_MUX handoff on M, the `~{RAM_EN}=INV(M15)` decode, and the ROM read path onto MDR — three boards joining for ZERO new driven wires.
  ONE HARDWARE FAULT: **END and HALT were not yet wired**, so the T counter never cleared, the PC never advanced between instructions, and the fetch byte was constant. Once wired, the bytes varied immediately.
  RIG FAULTS, all of the same family — a test that can pass on data carrying no information: `block2.fetch` first reported PASS on all-`0xFF`, because the milestone image is 7 bytes and `0x0007-0x7FFF` is safe-fill, so a constant run matches the fill region at tens of thousands of addresses (BRINGUP.md warned of exactly this and I wrote the test vulnerable to it anyway). Then it assumed successive fetch samples were one instruction apart — at ~21% yield they sit 2-3 apart. Then it tried to build adjacency from two consecutive POLLED successes, which never fired once: the poll loop is ~15-19 cycles against a 977ns clock, so the phase drifts and a success is almost never followed by another. **Adjacency has to come from a fixed-interval burst, not from luck.**
  THRESHOLD NOW GENERATED, NOT GUESSED: three consecutive diag bytes do NOT identify a unique address — the byte truncates to 8 bits, leaving a 4-fold ambiguity almost everywhere and 8-fold in 256 places. A hand-picked `<= 4` would have false-failed on 3% of positions. `progrom_gen.diag_triple_max()` emits `PR_DIAG_TRIPLE_MAX` and the rig asserts against that. The honest claim is 1-in-4096 discrimination, not a unique address.
- [x] BLOCK 3 — + mdr. **PASSING on bench 2026-08-02, both ways.** DRIVEN GOES 8 -> 0: the IR is real, the machine fetches its own instruction bytes, and IRB0-7 stays in the same holes at U16 while flipping to sampled. 15 sampled + CLKIN = 16 jumpers. RETIRES: the IRB copper run mdr U34 -> microcode U16 proven at the consumer end, the fetch path end to end (PC -> MAR -> M -> ROM -> MDR -> U25 -> W -> U34 -> IRB), the U25 bridge in the MDR->W direction under real strobes at speed, LE_IR = NOR(CLK, ~{IR_LOAD}) latching the right byte, and INSTRUCTION LENGTH — invisible to block 2, which forced IRB constant.
  `block3.clocked` is the strongest evidence of the bring-up: stepping from a known state it read **A5 40 41 D7 from 0x0000 at ONE address**, then the next run **continued at 0x0004** with `42 11 4B 43` — the LDAI at 0x0005 advancing two bytes and skipping 0x0006. Nobody told the rig where run 2 should start; it fell out of the machine's own execution. It also verifies THE DIVIDER: exactly 2 pulses per CLK edge (U20 Q0 /2 into U27 /2), which root.clock cannot do since it measures only the resulting frequency.
  `block3.free` passes repeatedly at 4 addresses — the DIAG image's own structural ambiguity. Its earlier ~30% pass rate was NOT the board: the burst is unrolled `.rept 4` with the loop overhead outside, so intervals are 437/437/437/687ns, a T-state landing on the long gap got one sample instead of two, the count-based debounce rejected it, and an entire INSTRUCTION vanished from the stream. Acceptance now tests the SEQUENCE (T can only advance by +1) instead of counting samples.
- [ ] BLOCK 4 — + registers + alu. FIRST BLOCK THAT COMPUTES THE SUM. IRB comes off, OB0-7 goes on at U35.2/5/6/9/12/15/16/19 (the '373 zigzag — count chip pins). Remove the FLAG_Z strap: U49.5 drives U62.3 now. Test: exactly 6 END pulses then HALT forever, OB = 0x4D. bit-reverse(0x4D) = 0xB2 and nibble-swap(0x4D) = 0xD4, so a flipped or transposed ribbon self-names. U35 HAS NO RESET and a power-cycle does not clear it, so the PROGRAM poisons OB with 0xFF before computing: any run that starts destroys the old answer, and OB can only read 0x4D if this run reached the second OUT.
- [x] BLOCK 5 — + io. All ten boards, NOT single-stepped. OB0-7 moves to the io end (R9-R16 pin 1), same Mega pins. STRAP IS0-7 = SW1 at 0xF7: its only 0-bit is W3, exactly the bit of the answer, so a leaking '244 turns OB into 0x00 and names itself. No scope work here — save the probe budget.
- BLOCK 6 — DROPPED 2026-08-02. It was the same ten boards again with the END jumper off, ten resets for ten sums. It added no board and no coverage, only repetition, and blocks 4 and 5 already free-run at 1.024MHz with Y1 seated. Running the machine INTERACTIVELY off SW1 via IN is a stronger acceptance than the same fixed program ten more times. The LA/scope work it carried is not lost — 2ch CLK (U27.5) vs ~{REG_A_LOAD} (U30.14) is still the longest control path, and 1ch OB3 (U35.9) VOH is still worth a look.

ALL TEN MODULES BENCH-PROVEN as of 2026-07-26: root, pc, microcode, control_word, mdr, registers, mar, memory, alu, io. Coverage lint reports 0 gaps and 0 pending. What remains is the integration ladder and free-run — the milestone program (LDAI 0xFF; OUT; LDAI 0x2F; LDBI 0x1E; ADD; OUT; HALT) is already burned and seated in the program ROM.

## RAM discipline (8KB SRAM is the rig's scarcest resource)
Every string the firmware only PRINTS lives in flash: literal messages
via `uart_putsP()`, test labels via `PSTR()`, signal-name tables as
PROGMEM flash-pointer arrays indexed with `PN()`, the TESTS registry in
PROGMEM (copy out with `memcpy_P`). The `test_check_*_r` variants exist
only for runtime-built RAM labels (selftest pin names). Bulk capture
borrows `g_arena` (2KB, one user at a time — root's burst buffers live
there) instead of adding static buffers. As of 2026-07-20 (5 modules +
selftest + shell): 39.8% RAM. Budget ~350B/module for pin bindings —
all remaining stages fit with room to spare.

## Regenerating
    python3 ../../docs/notes/kicad_contracts.py --pinmap   # after any schematic change
    python3 ../../docs/notes/coverage_lint.py              # coverage invariant
    python3 ../../docs/notes/microcode_gen.py              # after any microcode/opcode
                                                           # change: bins + expect header
                                                           # (reflash rig, re-burn ROMs)
    python3 ../../docs/notes/progrom_gen.py                # after any program/ISA change:
                                                           # PROG bins + expect header
    python3 ../../docs/notes/layout_gen.py <mod>           # breadboard placement page,
                                                           # scored from the netlist
    python3 ../../docs/notes/layout_gen.py <mod> --auto    # derive a placement instead
