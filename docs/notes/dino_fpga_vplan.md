# DINO FPGA Verification Plan (VPLAN)

**Date:** 2026-08-10.
**Method:** identical discipline to the intel-8008-vhdl precedent
(`~/Development/intel-8008-vhdl/docs/VPLAN.md`). Every row below maps a
specification-derived claim (`CLAUDE.md`'s "machine invariant" table, the
FPGA-port paragraph, and the 2026-08-04 full-ISA state section;
`tests/dino_bringup/BRINGUP.md`'s "Machine invariant: EVERYTHING COMMITS
ON CLK LOW"; `docs/notes/microcode_gen.py`'s `check_word`/`check_table`
rules) onto the real artifact inventory (`fpga/ttl/`, `fpga/sim/`,
`fpga/postsynth/`, `fpga/synth/`, `fpga/Makefile`, `docs/notes/test_*.py`,
`fpga/BRINGUP_FPGA.md`) — a row is COVERED only if some existing artifact
would **FAIL** were the behavior wrong. Where a citation names a specific
function (`path::name`), `test_vplan.py` mechanically verifies that
function exists in that file — a citation is no longer just a
plausible-looking path.

**GAP count: 5** (of 92 rows). Named in full in "Gap list" below; every
one is a genuinely un-policed rule (printed WARNING, never enforced) or a
ledgered deferral. None are silent.

## The 2026-08-10 stack phase — covered, but not yet ROWED

Twelve chips and seven instructions landed after this table was written.
They are **exercised** — the artifacts below all exist and all pass — but
they do not yet have their own rows, because the table is mechanically
coupled to `test_vplan.py`'s `KNOWN_GAPS` literal and rowing them properly
is its own pass. Named here so none of it reads as silently covered:

    U23           third microcode EEPROM, CW16-23
    U70 / U71     SRC / DST bank-1 '138s
    U63-U66       '169 stack pointer
    U67 / U68     SP readback '245s -> MDR
    U69           '08, ~{SP_CE}
    U72 / U73     PC0-15 -> MDR '245s

    LXISP  PUSHA  PUSHB  POPA  POPB  CALL  RET

Artifacts that would fail if the behaviour were wrong:

- `fpga/ttl/test_stateful.py::counter169_updown_hold_and_load_priority` and
  `::counter169_tc_is_active_low_and_direction_dependent` — the four ways a
  '169 differs from the '163 it was copied from.
- `fpga/sim/test_module_stack_pointer.py` — five cases, including a
  mirror-witness load/readback and a byte-boundary carry that would have
  caught the crossed `~TC` cascade the schematic was first drawn with.
- `fpga/sim/test_module_control_word.py::test_src_bank1_darkens_bank0_and_decodes_one_hot`
  and its DST twin and independence case.
- `fpga/sim/test_core_coverage.py::stack_round_trips_through_lifo_and_returns`
  — the whole machine, and the ONLY execution of the stack anywhere: the rig
  is detached and this hardware has never existed outside a netlist.
- `docs/notes/test_microcode_gen.py` — the 24-bit word, the `0xFF`-is-inert
  property row by row, the three new `check_word` rules, and a CRC tripwire
  on all three ROM images.

**Two rules in `check_word` exist because the gate model refused what
reasoning had accepted**, and both are worth rows of their own eventually:

- `src=RAM` cannot write `MAR` in the same word. The RAM address IS MAR and
  the '373s are transparent while CLK is low, so it closes a live loop:
  `MAR -> M -> RAM -> MDR -> U25 -> W -> MAR`.
- `misc=MDR_OUT` must be the state IMMEDIATELY after the read that parked the
  byte. `LE_MDR` falls at the T-state boundary and can latch whatever the
  NEXT source is turning on. RET's second draft parked a byte, moved another
  one, then replayed — and loaded the PC with `0x0C0C` instead of `0x000C`.

Still genuinely uncovered, and stated as such: **`~{CIN_SEL}`,
`~{MISC_BANK}`, `~{ADDR_SEL1}`, `FLAG_SEL0/1` and `FLAG_POL` are burned into
all 4096 rows and wired to nothing.** No artifact can fail on them, because
no consumer exists. They are reserve, not coverage.

**Status legend:**
- `COVERED-EXHAUSTIVE` — full-space differential sweep against an
  independent model (cite sweep).
- `COVERED-DIRECTED` — directed self-checking test (cite).
- `COVERED-INCIDENTAL` — a real, passing artifact exists, but it does not
  specifically target the claimed behavior — it would not necessarily
  fail if only THAT behavior broke. Distinct from GAP (something does
  exercise the code path) and distinct from COVERED-DIRECTED (a
  COVERED-DIRECTED artifact is aimed at the claim; a COVERED-INCIDENTAL
  one just happens to touch it).
- `GAP` — no failing check exists.

One deliberate rider: the port-phase follow-up "`prepare_roms` CRC guard"
did not exist (`fpga/sim/conftest_helpers.py`'s `prepare_roms()` only
compared source/output *mtimes*, never content) — implemented as
`_assert_crc()` in `fpga/sim/conftest_helpers.py`, host-tested
(`docs/notes/test_vplan.py::test_assert_crc_guard_catches_content_mismatch`
and `::test_prepare_roms_integration_does_not_raise_against_real_roms`).
See RES-06.

---

## Row table

### A. Machine invariant — commit on CLK low

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| INV-01 | CLAUDE.md "machine invariant" table | Register-file/IR shadow-load latches (`le_ir`, `NOR(clk, n_ir_load)`) commit only while CLK is LOW | all reachable `cw`/`clk` combos | directed | fpga/sim/conftest_helpers.py::invariant_monitor (standing, every whole-core test); fpga/sim/test_module_mdr.py::test_mdr_ir_capture_gated_by_clk_low | COVERED-DIRECTED |
| INV-02 | CLAUDE.md "machine invariant" table | MAR LO/HI shadow-load latches (`le_mar_lo`/`le_mar_hi`) commit only while CLK is LOW | all reachable combos | directed | fpga/sim/test_module_mar.py::test_mar_load_gated_by_clk_low | COVERED-DIRECTED |
| INV-03 | CLAUDE.md "machine invariant" table | ALU TMP_A/TMP_B shadow-load latches (`le_tmp_a`/`le_tmp_b`) commit only while CLK is LOW | all reachable combos | directed | fpga/sim/test_module_alu.py::test_alu_shadow_gated_by_clk_low_and_independent | COVERED-DIRECTED |
| INV-04 | CLAUDE.md "machine invariant" table | Register A/B/C/OUT LE stamps (`n_reg_a_le`..`n_reg_out_le`, `NOR(n_reg_x_load, clk)`) commit only while CLK is LOW | all reachable combos | directed | fpga/sim/test_module_registers_a_b.py::test_registers_load_commits_on_clk_low | COVERED-DIRECTED |
| INV-05 | CLAUDE.md "machine invariant" table | RAM write pulse (`n_ram_write_en = NAND(write_dir, ~clk)`) fires only while CLK is LOW | all reachable combos | directed | fpga/sim/test_module_memory.py::test_memory_ram_write_gated_by_clk_low | COVERED-DIRECTED |
| INV-07 | CLAUDE.md "machine invariant" table | PC LOAD (`n_pc_load_stable = NAND(n_pc_load, ~clk)`) lands only while CLK is LOW | all reachable combos | directed | fpga/sim/test_module_program_counter.py::test_pc_load_gated_by_clk_low | COVERED-DIRECTED |
| INV-08 | CLAUDE.md "machine invariant" table | PC CLEAR (`NOR(~pc_clear, clk)`) lands only while CLK is LOW; RESET is the un-gated leg | both | directed | fpga/sim/test_module_program_counter.py::test_pc_clear_gated_by_clk_low_reset_ungated | COVERED-DIRECTED |
| INV-10 | CLAUDE.md "machine invariant" table | RESET is asynchronous/un-gated for the PC counters (and, via the same NOR leg, for T-state clear) | both phases of CLK | directed | fpga/sim/test_module_program_counter.py::test_pc_clear_gated_by_clk_low_reset_ungated | COVERED-DIRECTED |
| INV-11 | CLAUDE.md "machine invariant" table | Bus output enables (`~ROM_OUT`/`~RAM_OUT`/`~REG_x_OUT`/`~ALU_OUT`/`~SW_OUT`/`~MDR_OUT`) are pure functions of `cw`/`flag_z`, never CLK-qualified | exhaustive `cw` sweep | directed (incidental) | fpga/sim/test_module_control_word.py::test_control_word_all_groups_active_no_interaction (never varies clk, so a future clk-dependent regression would not be caught BY THIS TEST specifically); fpga/gen/control_word.vhd (entity has no machine-CLK port at all — the real guarantee is structural, not test-driven) | COVERED-INCIDENTAL |
| INV-12 | CLAUDE.md "consequence" paragraph; BRINGUP.md "why the ungated ones do not matter" | A microcode decode glitch (transient double-enable during the ROM access window) cannot corrupt state, because every state-changing path is CLK-qualified per INV-01..INV-10 | — | derived | (composite of the surviving machine-invariant rows in this section: INV-01..INV-05, INV-07, INV-08, INV-10; no independent artifact beyond their union — the sole row in this table with no path citation of its own, by design) | COVERED-DIRECTED (derived) |

### B. Bus one-hot / shared-bus discipline

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| BUS-03 | verification-design spec, Track 3.1 (structural precondition) | Each `'138` decoder (SRC/MISC) is one-hot within its own group for every select code, independent of ROM content | exhaustive select x enable | exhaustive | fpga/ttl/test_msi.py::decoder_truth_table | COVERED-EXHAUSTIVE |

### D. Microcode ROM policing rules (`microcode_gen.check_word`/`check_table`)

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| ROM-01 | docs/notes/microcode_gen.py check_word() | `src=RAM` and `dst=RAM` in the same microword is illegal (RAM corrupts) | crafted bad word | directed | docs/notes/test_microcode_gen.py (must_raise: src=RAM dst=RAM — module-level assert, no enclosing function to cite by name) | COVERED-DIRECTED |
| ROM-02 | docs/notes/microcode_gen.py check_word() | `/MDR_OUT` replay concurrent with any other active `src` is a W-bus fight and illegal | crafted bad word | directed | docs/notes/test_microcode_gen.py (must_raise: MDR_OUT plus src=ROM) | COVERED-DIRECTED |
| ROM-03 | docs/notes/microcode_gen.py check_word() | `PC_UP` concurrent with `/PC_LOAD` in the same microword is illegal (fragile on `'193` internals) | crafted bad word | directed | docs/notes/test_microcode_gen.py (must_raise: PC_UP with PC_LOAD) | COVERED-DIRECTED |
| ROM-04 | docs/notes/microcode_gen.py check_word() | `IR_LOAD` may only occur at T0 (the instruction register changes only at fetch) | crafted bad word | directed | docs/notes/test_microcode_gen.py (must_raise: IR_LOAD outside T0) | COVERED-DIRECTED |
| ROM-05 | docs/notes/microcode_gen.py check_word() | T0 of every one of the 256 opcodes must be the universal FETCH word | all 256 opcodes + crafted bad word | directed | docs/notes/test_microcode_gen.py (256-opcode sweep + must_raise: non-fetch T0 row) | COVERED-DIRECTED |
| ROM-06 | docs/notes/microcode_gen.py check_table() | Every opcode's defined microcode block terminates (END or HALT bit) before running into safe-fill | crafted END-less block | directed | docs/notes/test_microcode_gen.py (check_table END-less-block rejection) | COVERED-DIRECTED |
| ROM-07 | docs/notes/microcode_gen.py check_word() | `src==dst` for the same register (A/B/C, "probable MOV typo") is flagged | any such word | — | check_word() only `print()`s a WARNING; never raises, never asserted by any test | GAP |
| ROM-08 | docs/notes/microcode_gen.py _check_lengths() | Per-instruction `PC_UP` count matches the instruction's byte length | every INSTRUCTIONS entry | — | _check_lengths() only `print()`s a WARNING; never raises, never asserted by any test | GAP |
| ROM-09 | CLAUDE.md "what is proven" section | `progrom_gen.OPCODES` is imported from `microcode_gen`, so the microcode and program ROMs cannot disagree on an opcode's meaning | — | directed (incidental) | docs/notes/test_progrom_coverage.py::test_simulator_against_microcode (targets simulator-vs-microcode agreement, not opcode-table identity specifically — a future accidental OPCODES fork would very likely, but not necessarily, be caught here as a side effect) | COVERED-INCIDENTAL |
| ROM-10 | CLAUDE.md "what is proven" section | The SA (ALU-select) field reaches the `'382` in the wiring's actual (bit-reversed at the microcode-bit level) order — the historical ADD-executes-as-AND bug | full netlist walk | directed | docs/notes/test_microcode_gen.py::test_sa_field_reaches_the_382_uninverted | COVERED-DIRECTED |

### E. Port fidelity (exact virtual copy)

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| FID-01 | port-design spec, "Emitter" | Every physical chip on every one of the 10 schematic sheets is instantiated exactly once in the generated VHDL | all 10 sheets | directed | docs/notes/test_fpga_gen.py::test_emit_every_chip_once_every_net_somewhere | COVERED-DIRECTED |
| FID-02 | port-design spec, "Emitter" | Every pin of every used part type is mapped to a net or explicitly marked NC; a missing mapping is a hard failure, not a warning | every part type | directed | docs/notes/test_fpga_gen.py::test_missing_pin_map_entry_is_a_hard_failure; docs/notes/test_fpga_gen.py::test_nc_allowed_covers_every_unconnected_model_input | COVERED-DIRECTED |
| FID-03 | port-design spec, "never hand-edited" | The committed `fpga/gen/*.vhd` exactly matches a fresh emitter run (no hand-edit drift) | every generated file | directed | docs/notes/test_fpga_gen.py::test_committed_gen_matches_emit_output_no_drift | COVERED-DIRECTED |
| FID-04 | port-design spec, "Chip model contract" | `clk_sys` is threaded to every stateful chip instance | every stateful instance | directed | docs/notes/test_fpga_gen.py::test_clk_sys_threaded_to_every_stateful_instance | COVERED-DIRECTED |
| FID-05 | port-design spec, Goal ("byte-identical, CRC-matched") | ROM/RAM models are initialized from the SAME bytes, CRC-matched, as the bench-burned chips | every ROM | directed | fpga/sim/conftest_helpers.py::_assert_crc (this task's rider, RES-06) | COVERED-DIRECTED |
| FID-07 | port-design spec, Goal ("byte-identical, CRC-matched") | The GENERATED `microcode` module entity's own ROM content, read back through its gate-level ports, exactly matches `microcode_gen.build_real()` — not just the `.bin`/`.hex` file on disk | all 4096 rows | exhaustive | fpga/sim/test_module_microcode.py::test_microcode_full_image_matches_build_real; fpga/sim/test_module_microcode.py::test_microcode_known_rows_match_build_real | COVERED-EXHAUSTIVE |
| FID-08 | port-design spec, Goal ("byte-identical, CRC-matched") | The GENERATED `memory` module entity's own ROM content, read back through its gate-level ports, exactly matches `progrom_gen.build_real()` | spot rows | directed | fpga/sim/test_module_memory.py::test_memory_rom_content_matches_build_real | COVERED-DIRECTED |

### F. Whole-core simulation / ISA execution

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| SIM-01 | CLAUDE.md 2026-08-04 state; port-design spec, Testing step 4 | The milestone program (`LDAI 0xFF; OUT; LDAI 0x2F; LDBI 0x1E; ADD; OUT; HALT`) free-runs in the gate-level model to `OB=0x4D` | free-run | directed | fpga/sim/test_core_milestone.py::milestone_free_runs_to_4d | COVERED-DIRECTED |
| SIM-02 | CLAUDE.md 2026-08-04 state ("PROG_in ... SW1=0x01 gives 0x30, SW1=0x1E gives 0x4D") | `IN` reads its operand from the DIP switches | SW1=0x01 and SW1=0x1E | directed | fpga/sim/test_core_milestone.py::in_tracks_switches | COVERED-DIRECTED |
| SIM-03 | port-design spec, "Standing sim assertion" | No gated-clock edge (of `gated_clocks.txt`'s checked set) ever fires while sampled machine CLK is high, across every whole-core run | every whole-core test | directed | fpga/sim/conftest_helpers.py::invariant_monitor; fpga/sim/test_core_milestone.py; fpga/sim/test_core_coverage.py; fpga/sim/test_core_fuzz.py | COVERED-DIRECTED |
| SIM-04 | CLAUDE.md 2026-08-04 state ("alu 0x39 all eight SA codes, chained non-maskingly") | The `alu` coverage image exercises all eight SA codes, chained non-maskingly; gate-level `OB` matches the oracle | full coverage run | directed | fpga/sim/test_core_coverage.py::alu_covers_every_sa_code | COVERED-DIRECTED |
| SIM-05 | CLAUDE.md 2026-08-04 state ("mem 0xC5 MAR as a latch, RAM round trip") | The `mem` coverage image witnesses MAR-as-a-latch and a RAM round trip; gate-level `OB` matches the oracle | full coverage run | directed | fpga/sim/test_core_coverage.py::mem_witnesses_mar_as_a_latch | COVERED-DIRECTED |
| SIM-06 | CLAUDE.md 2026-08-04 state ("flow 0x39 JMP lands; SUB sets FLAG_Z; JNZ correctly declines") | The `flow` coverage image's JMP lands, SUB sets FLAG_Z, and JNZ correctly declines; gate-level `OB` matches the oracle | full coverage run | directed | fpga/sim/test_core_coverage.py::flow_takes_the_jump_and_falls_through | COVERED-DIRECTED |
| SIM-07 | CLAUDE.md 2026-08-04 state ("loop 0x15 JNZ TAKEN arm x3 ... exact iteration count 3x7=21") | The `loop` coverage image's JNZ-taken arm fires 3x, flags survive an intervening STA, exact iteration count holds; gate-level `OB` matches the oracle | full coverage run | directed | fpga/sim/test_core_coverage.py::loop_takes_the_jnz_branch | COVERED-DIRECTED |
| SIM-08 | CLAUDE.md "What it cost" section (mardisc/pads, port-design spec's coverage ladder) | The `mardisc`/`pads` coverage images (MAR discriminates two different addresses; PC_LOAD lands exactly on target) match the oracle at gate level | full coverage run | directed | fpga/sim/test_core_coverage.py::mardisc_discriminates_mar_lo; fpga/sim/test_core_coverage.py::pads_lands_the_jmp_at_the_named_pad | COVERED-DIRECTED |
| SIM-09 | BRINGUP_FPGA.md "gate 5" | The POST-SYNTHESIS netlist (not the source VHDL) still reaches `OB=0x4D` on the milestone program | post-synth run | directed | fpga/postsynth/test_postsynth_milestone.py::postsynth_milestone_free_runs_to_4d | COVERED-DIRECTED |

### G. Synthesis gates

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| SYN-01 | BRINGUP_FPGA.md "gate 1" (netlist-integrity) | GHDL import severs no declared signal | every generated entity | directed | docs/notes/test_netlist_integrity.py::test_ghdl_import_severs_no_declared_signal | COVERED-DIRECTED |
| SYN-02 | BRINGUP_FPGA.md "gate 1" | The tri-state bus-resolution pre-pass (`bus_resolve.ys`) leaves no multiply-driven net | full synth | directed | docs/notes/test_netlist_integrity.py::test_bus_resolve_leaves_no_multiply_driven_net | COVERED-DIRECTED |
| SYN-03 | BRINGUP_FPGA.md "gate 5" motivation (opt_clean regression) | Coarse synthesis preserves all four memories (ROM x2 half-bytes, program ROM, RAM) — none get eaten by `opt_clean` | full synth | directed | docs/notes/test_netlist_integrity.py::test_synth_coarse_preserves_all_four_memories | COVERED-DIRECTED |
| SYN-04 | port-design spec, "Written to be BRAM-inferable" | Full synthesis maps all four memories to real block RAM (DP16KD), not distributed logic | full synth | directed | docs/notes/test_netlist_integrity.py::test_full_synth_maps_all_five_memories_to_block_ram | COVERED-DIRECTED |
| SYN-05 | BRINGUP_FPGA.md "hex-vs-roms staleness check" | Every committed `.hex` matches its committed `roms/*.bin`, byte-for-byte | every image tag | directed | fpga/synth/check_images.py::check_hex (run on every `make bit`) | COVERED-DIRECTED |
| SYN-06 | BRINGUP_FPGA.md "check-images ... --meminit gate" | The synthesized `$mem_v2` INIT content matches `roms/*.bin` byte-for-byte, for every image tag — the bytes Rico actually burns | every image tag, full synth | directed | fpga/synth/check_images.py::check_meminit (`make -C fpga check-images`) | COVERED-DIRECTED |
| SYN-07 | BRINGUP_FPGA.md "the timing gate" | Post-route timing closes at the `clk_sys` constraint (Fmax PASS) for every image tag | every image tag | directed | fpga/Makefile ($(BUILD_DIR)/dino_%.bit "timing gate" recipe step) | COVERED-DIRECTED |
| SYN-08 | port-design spec, Testing rung 6 ("zero inferred latches") | Synthesis infers zero latches | full synth, every image | — | `proc -latches warn` (fpga/Makefile, fpga/postsynth/Makefile, fpga/synth/check_images.py) only WARNS to a log; nothing parses that log and fails if the warning count is nonzero | GAP |

### I. Differential fuzzing

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| FUZZ-01 | verification-design spec, Track 1 | Random legal DINO programs produce a gate-level final `OB` matching `progrom_gen.simulate()`'s oracle | seeded soak (500 seeds) | directed | fpga/sim/test_core_fuzz.py::fuzz_one_seed | COVERED-DIRECTED |
| FUZZ-02 | verification-design spec, Track 1 ("compare those too, not just OB") | Gate-level RAM-writes summary and branches-taken count match the oracle, not just `OB` (mirror-witness discipline extended to fuzzing) | seeded soak | directed | fpga/sim/test_core_fuzz.py::fuzz_one_seed | COVERED-DIRECTED |
| FUZZ-03 | verification-design spec, Track 1 ("also fuzz the switches") | Fuzzing exercises `IN` with random, seed-derived (not hardcoded) DIP-switch values | programs containing IN | directed | fpga/sim/test_core_fuzz.py::fuzz_one_seed (drives `meta["switches"]`, a `fuzz_gen.gen()`-derived per-seed value, not a constant); docs/notes/test_fuzz_gen.py::test_uses_in_matches_program; docs/notes/test_fuzz_gen.py::test_switches_are_seed_derived_reproducible_and_vary | COVERED-DIRECTED |
| FUZZ-04 | verification-design spec, "Open items" (metavalue budget) | The metavalue-warning count across a fuzz soak stays within a documented, only-shrinking budget | full soak | directed | fpga/sim/test_core_fuzz.py::run_fuzz_seeds (budget check, raises if exceeded) | COVERED-DIRECTED |
| FUZZ-05 | verification-design spec, Track 1 (generator contract: "legal DINO programs...always terminated by HALT...jump targets constrained to program bounds") | `fuzz_gen.py`'s generator produces only sim-supported opcodes, is deterministic per seed, always HALT-terminates, jumps are forward-only (guaranteeing termination), memory ops stay inside the pinned RAM window with distinct low bytes when there are >=2, and its `uses_in` metadata matches the actual program | seeded (50 seeds per property) | directed | docs/notes/test_fuzz_gen.py::test_deterministic_and_legal; docs/notes/test_fuzz_gen.py::test_every_seed_terminates_in_oracle; docs/notes/test_fuzz_gen.py::test_jumps_are_forward_only; docs/notes/test_fuzz_gen.py::test_jnz_always_preceded_by_alu_op; docs/notes/test_fuzz_gen.py::test_memory_ops_use_distinct_low_bytes; docs/notes/test_fuzz_gen.py::test_memory_addresses_stay_in_ram; docs/notes/test_fuzz_gen.py::test_uses_in_matches_program; docs/notes/test_fuzz_gen.py::test_limit_truncates_reproducibly | COVERED-DIRECTED |

### K. Residue / ledger follow-ups

**RES-03 and RES-05 are intentionally absent** — not a gap in this
document, a gap in the ID sequence itself. `test_vplan.py::test_row_ids_
are_unique` only requires IDs to be unique, never contiguous, so nothing
mechanical depends on filling them. Recorded here, explicitly, rather
than left silently missing: these two numbers were never used.

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| RES-01 | progress.md, Task 1 note | The verification-design spec's premise ("17 sim-proven opcodes, NOP/LDCI excluded: no sim support") is stale: `sim_supports()` reports every implemented instruction (`microcode_gen.INSTRUCTIONS`, all 19, NOP/LDCI included) as executable by the oracle interpreter | every implemented instruction | directed | docs/notes/test_progrom_coverage.py::test_simulator_against_microcode (iterates `INSTRUCTIONS`, asserts `sim_supports(name)` for each — fails if NOP, LDCI, or any other opcode stopped being oracle-executable) | COVERED-DIRECTED |
| RES-02 | CLAUDE.md 2026-08-04 state ("Only LDCI and NOP remain unrun ... both unreachable by design") | LDCI's (and NOP's) FPGA-model behavior has bench silicon ground truth to validate against | — | — | none — LDCI/NOP have never executed on real DINO hardware; the fuzz harness's oracle-vs-gate-model agreement (FUZZ-01) is INTERNALLY self-consistent but has nothing on real silicon to anchor against for these two opcodes specifically | GAP |
| RES-04 | progress.md, Task 7 note | The 6 gated-clock identifiers `n_bo1`/`n_bo2`/`n_bo3`/`n_co1`/`n_co2`/`n_co3` (the `program_counter.vhd` `'193` ripple-carry chain) never rise while sampled machine CLK already reads high, on any whole-core run | multi-cycle, accumulated counter state | directed | fpga/sim/conftest_helpers.py::invariant_monitor (all six ARE in `gated_clocks.txt` and NONE are in `MONITOR_EXCLUDE` — the monitor resolves and RISE-checks them on every whole-core run; `_report_monitor`'s `assert not gaps` would fail loudly if any of the six ever became unresolvable, and a genuine CLK-high rise on any of them fails the run's own invariant assertion) | COVERED-DIRECTED |
| RES-06 | verification-design spec, Track 4 ("prepare_roms CRC guard") — port-phase follow-up, now CLOSED | `roms/*.bin` on disk is content-verified against a fresh in-memory rebuild every `prepare_roms()` call, not just when the mtime heuristic decides to regenerate | every prepare_roms() call | directed | fpga/sim/conftest_helpers.py::_assert_crc (this task's rider); docs/notes/test_vplan.py::test_assert_crc_guard_catches_content_mismatch; docs/notes/test_vplan.py::test_prepare_roms_integration_does_not_raise_against_real_roms | COVERED-DIRECTED |
| RES-07 | verification-design spec, Track 1 ("17 sim-proven opcodes... instruction stream from the 17 sim-proven opcodes") — split off from RES-01 | `fuzz_gen.py`'s `_MENU` continues to include NOP and LDCI as legal generation choices, and generated programs actually contain them from time to time (not merely menu-eligible in theory) | — | — | none — `fuzz_gen.py`'s own module-level assert (`assert all(sim_supports(n) for n in _MENU)`) only checks menu members ARE supported, never that any SPECIFIC name (NOP, LDCI, or any other) remains a member; none of `test_fuzz_gen.py`'s 8 tests check `_MENU` membership or per-opcode selection frequency either — a silent removal of NOP/LDCI from `_MENU` would narrow fuzz coverage with nothing noticing | GAP |

### L. Per-model TTL testbenches (`fpga/ttl/`)

These 18 model TBs anchor every FID/SIM claim about the generated design:
each ultimately rests on these per-part-type models being individually
correct against their own datasheet truth tables.

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| MDL-01 | port-design spec, "Chip model contract" (combinational parts) | The combinational gate primitives (`'00` NAND, `'02` NOR, `'08` AND, `'04` inverter) match their datasheet truth tables | exhaustive input sweep | exhaustive | fpga/ttl/test_gates.py::nand_truth_table; fpga/ttl/test_gates.py::nor_truth_table; fpga/ttl/test_gates.py::and_truth_table; fpga/ttl/test_gates.py::inverter_truth_table | COVERED-EXHAUSTIVE |
| MDL-02 | port-design spec, "Chip model contract" | The `'138` decoder and `'157` mux match their datasheet truth tables | exhaustive select x enable | exhaustive | fpga/ttl/test_msi.py::decoder_truth_table; fpga/ttl/test_msi.py::mux_truth_table | COVERED-EXHAUSTIVE |
| MDL-03 | port-design spec, "Tri-state parts" | The `'244` buffer drives its outputs when enabled and floats real `'Z'` when disabled | both states | directed | fpga/ttl/test_msi.py::buffer_tri_state | COVERED-DIRECTED |
| MDL-04 | port-design spec, "Tri-state parts" | The `'245` transceiver drives both directions correctly and releases (floats `'Z'`) the side it is not currently driving | both directions, both sides | directed | fpga/ttl/test_msi.py::xcvr_both_directions; fpga/ttl/test_msi.py::xcvr_releases_the_side_it_is_not_driving | COVERED-DIRECTED |
| MDL-05 | port-design spec, "Open items" ("Confirm the '382 model...during its testbench work") | The `'382` ALU matches its datasheet truth table across every op x operand pair x carry-in | exhaustive | exhaustive | fpga/ttl/test_74f382.py::alu_exhaustive | COVERED-EXHAUSTIVE |
| MDL-06 | port-design spec, "ROMs...and RAM" | The ROM models (AT28C64B/AT28C256) read back exactly what was loaded and deselect (float) correctly | both chips, both states | directed | fpga/ttl/test_memory.py::rom64_exact_readback_and_deselect; fpga/ttl/test_memory.py::rom256_exact_readback_and_deselect | COVERED-DIRECTED |
| MDL-07 | port-design spec, "ROMs...and RAM" | The RAM model (MCM60256) writes then reads back correctly under permuted addressing, and releases DQ when deselected | permuted addresses, both states | directed | fpga/ttl/test_memory.py::ram_write_then_read_permuted; fpga/ttl/test_memory.py::ram_releases_dq_when_deselected | COVERED-DIRECTED |
| MDL-08 | port-design spec, "Stateful parts" | The stateful models (`'74`, `'163`, `'193`, `'273`, `'373`) match their datasheet edge-detect/async-clear/transparent-latch behavior | per part | directed | fpga/ttl/test_stateful.py::ff74_edge_and_async; fpga/ttl/test_stateful.py::counter163_sync; fpga/ttl/test_stateful.py::counter193_async; fpga/ttl/test_stateful.py::register273_async_clear; fpga/ttl/test_stateful.py::register273_captures_pre_edge_d; fpga/ttl/test_stateful.py::latch373_transparent; fpga/ttl/test_stateful.py::latch373_no_stale_glitch_on_le_fall | COVERED-DIRECTED |

### M. Module functional correctness (bridge/steering)

CLAUDE.md names the mdr U25 bridge and memory decode as the parts worth
"keeping real" precisely because a rig/model stand-in is dangerous when
it is BETTER than the hardware (schematic bug 4 was a bridge defect a
naive model would pass clean). The `input_output` io `'244` switch gate
is the other CLAUDE.md-named "expensive to keep real" part these rows
cover.

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| MOD-01 | CLAUDE.md "Established rules" (mirror-witness) / mdr sheet netlist facts (BRINGUP.md Stage 10) | The mdr sheet's W<->MDR bridge (U25) asserts asymmetrically in both directions, not merely as a blind round trip | both directions | directed | fpga/sim/test_module_mdr.py::test_mdr_bridge_both_directions_asymmetric | COVERED-DIRECTED |
| MOD-02 | mdr sheet netlist facts (BRINGUP.md Stage 10: `CE = ~{MDR_EN}`) | With the bridge disabled (`SRC_ACTIVE` low and no MDR replay), both W and MDR float | bridge off | directed | fpga/sim/test_module_mdr.py::test_mdr_bridge_off_both_float | COVERED-DIRECTED |
| MOD-03 | mdr sheet netlist facts (BRINGUP.md Stage 10: `WRITE_DIR = INV(~{RAM_LOAD})`) | `WRITE_DIR` tracks `~RAM_LOAD` exactly | all reachable combos | directed | fpga/sim/test_module_mdr.py::test_mdr_write_dir_follows_ram_load | COVERED-DIRECTED |
| MOD-04 | port-design spec, "Chip model contract" + CLAUDE.md "expensive to keep real" (schematic bug 4 reasoning applied to the io switch gate) | The `input_output` sheet's switch gate (io `'244`) passes the DIP-switch byte through when selected and floats `'Z'` when not | both states | directed | fpga/sim/test_module_input_output.py::test_input_output_switch_passthrough_and_tristate | COVERED-DIRECTED |

### N. Stack pointer + third microcode EEPROM (2026-08-10)

Twelve chips and seven instructions. **None of this has run on real
hardware** -- the rig is detached, so every artifact below is the FPGA or a
host test. That is a change of kind, not degree: for the rest of this table
the fabric confirms a machine the bench had already proven, and here it is
the only witness there is.

| ID | Spec cite | Assertion | Conditions | Check type | Check artifact | Status |
|----|-----------|-----------|------------|------------|-----------------|--------|
| STK-01 | fpga/ttl/ttl_74ls169.vhd header; growth plan 4b | '169 synchronous load (`~PE`) has PRIORITY over the count enables, so `LXI SP` needs no stabiliser | load asserted with counting armed | directed | fpga/ttl/test_stateful.py::counter169_updown_hold_and_load_priority | COVERED-DIRECTED |
| STK-02 | fpga/ttl/ttl_74ls169.vhd header | Count enables are ACTIVE LOW and BOTH must assert; direction is a LEVEL on `U/~D`; neither asserted = HOLD | each enable alone, both, both directions | directed | fpga/ttl/test_stateful.py::counter169_updown_hold_and_load_priority | COVERED-DIRECTED |
| STK-03 | fpga/ttl/ttl_74ls169.vhd header | `~TC` is ACTIVE LOW, gated by `~CET`, and its terminal count depends on DIRECTION (1111 up, 0000 down) | both directions at both terminal values, `~CET` released | directed | fpga/ttl/test_stateful.py::counter169_tc_is_active_low_and_direction_dependent | COVERED-DIRECTED |
| STK-04 | stack_pointer.kicad_sch; CLAUDE.md mirror-witness rule | SP's 16-bit load/readback is ORDER-correct -- lo/hi not swapped, `Q0-Q3` not reversed against `P0-P3` | two DIFFERENT bytes, read back per byte | directed | fpga/sim/test_module_stack_pointer.py::sp_load_and_readback_is_a_mirror_witness | COVERED-DIRECTED |
| STK-05 | stack_pointer.kicad_sch (`~{SP_CE}` = AND of the two MISC codes) | SP HOLDS on every T-state that asserts neither `~{SP_UP}` nor `~{SP_DOWN}` -- i.e. almost all of them | four clocked T-states, both enables idle | directed | fpga/sim/test_module_stack_pointer.py::sp_holds_when_neither_up_nor_down_is_asserted | COVERED-DIRECTED |
| STK-06 | stack_pointer.kicad_sch (`~TC` chain U63->U64->U65->U66) | The carry chain runs in WEIGHT order, so a carry crosses the byte boundary: 0x00FF+1 = 0x0100 and 0x0100-1 = 0x00FF | increment and decrement across the boundary | directed | fpga/sim/test_module_stack_pointer.py::sp_crosses_the_byte_boundary | COVERED-DIRECTED |
| STK-07 | stack_pointer.kicad_sch (`U67`/`U68` CE) | Both readback '245s RELEASE `MDR0-7` when neither `_OUT` code is asserted -- SP shares that bus with ROM, RAM and three registers | neither enable | directed | fpga/sim/test_module_stack_pointer.py::sp_releases_the_bus_when_neither_readback_is_enabled | COVERED-DIRECTED |
| STK-08 | growth plan 4b (empty-descending stack) | SP counts UP and DOWN by the same amount -- a stuck `U/~D` (the '163 pin-1 trap) changes the result | 3 up then 5 down | directed | fpga/sim/test_module_stack_pointer.py::sp_counts_both_directions | COVERED-DIRECTED |
| BNK-01 | control_word.kicad_sch (`U28.E3` / `U70.E1` complementary) | Asserting `~{SRC_BANK}` darkens EVERY bank-0 source enable AND decodes bank 1 one-hot; `SRC_ACTIVE` floats high, which is what keeps the U25 bridge on | all four bank-1 SRC codes | directed | fpga/sim/test_module_control_word.py::test_src_bank1_darkens_bank0_and_decodes_one_hot | COVERED-DIRECTED |
| BNK-02 | control_word.kicad_sch (`U30.E3` / `U71.E1`) | Same for `~{DST_BANK}` -- a DST bank switch that left bank 0 live would fire a register load alongside an SP load | both bank-1 DST codes | directed | fpga/sim/test_module_control_word.py::test_dst_bank1_darkens_bank0_and_decodes_one_hot | COVERED-DIRECTED |
| BNK-03 | microcode_gen.py word() (bank bit derived from the code) | The two bank bits are INDEPENDENT: a bank-1 SRC composes with a bank-0 DST (PUSH's address setup) and vice versa (`LXI SP`) | both mixed combinations | directed | fpga/sim/test_module_control_word.py::test_the_two_banks_are_independent | COVERED-DIRECTED |
| MCC-01 | microcode_gen.py `INERT_THIRD`; CLAUDE.md erased-EEPROM rule | `0xFF` in `CW16-23` IS today's machine: no row outside the seven stack opcodes touches a third-ROM field | all 4096 rows | exhaustive | docs/notes/test_microcode_gen.py | COVERED-EXHAUSTIVE |
| MCC-02 | microcode_gen.py word() | The bank bit is DERIVED from the SRC/DST code, never passed by hand, so a caller cannot select `SP_LO` and forget to switch banks | both banks, both fields | directed | docs/notes/test_microcode_gen.py | COVERED-DIRECTED |
| MCC-03 | microcode_gen.py emit_header() | `U23.bin`/`U23_diag.bin`, their CRCs, and the 24-bit `MC_REAL_WORDS` table agree with `build_real()` and with each other | per-byte over the image | directed | docs/notes/test_microcode_gen.py; tests/dino_bringup/hosttest/test_crc16.c | COVERED-DIRECTED |
| MCC-04 | CLAUDE.md "adding an instruction costs a three-ROM burn" | A reburn is always DELIBERATE: all three image CRCs are pinned as literals, so any content change fails loudly | every generator run | directed | docs/notes/test_microcode_gen.py | COVERED-DIRECTED |
| MCC-05 | fpga/gen/microcode.vhd (U23 instance) | The third ROM reads back through the real sheet for the two WIRED bits, row by row, against `build_real()` | all 4096 rows | exhaustive | fpga/sim/test_module_microcode.py::test_microcode_full_image_matches_build_real | COVERED-EXHAUSTIVE |
| POL-01 | microcode_gen.check_word (RAM-writes-MAR rule) | `src=RAM` with `dst=MAR_LO/MAR_HI` is REJECTED -- the RAM address IS MAR and the '373s are transparent while CLK is low, closing a live loop | crafted word | directed | docs/notes/test_microcode_gen.py | COVERED-DIRECTED |
| POL-02 | microcode_gen._check_mdr_replay_is_immediate | `misc=MDR_OUT` must be the state IMMEDIATELY after the read that parked the byte -- MDR holds for exactly one state | every opcode block | directed | docs/notes/test_microcode_gen.py | COVERED-DIRECTED |
| POL-03 | microcode_gen.check_word (MDR-bus fight, bank-aware) | `misc=MDR_OUT` with ANY source in EITHER bank is rejected; the field decode folds in the bank bits, so bank-1 `PC_LO` is not mistaken for bank-0 `RAM` | crafted words, both banks | directed | docs/notes/test_microcode_gen.py | COVERED-DIRECTED |
| POL-04 | microcode_gen._check_mar_before_ram | No instruction touches RAM before BOTH MAR halves are loaded within that same instruction | every opcode block | directed | docs/notes/test_microcode_gen.py | COVERED-DIRECTED |
| POL-05 | microcode_gen.check_word (SP count-and-read) | SP cannot be counted and read in the same word -- the '169s commit on the edge that ENDS the T-state, so the byte read during it is the PRE-count value | crafted word | directed | docs/notes/test_microcode_gen.py | COVERED-DIRECTED |
| STACK-1 | progrom_gen.STACK_PROGRAM | The whole machine round-trips two DIFFERENT bytes through LIFO and returns from a subroutine: `LXISP`, `PUSHA/B`, `POPA/B`, `CALL`, `RET`. The single OUT sits AFTER the return and reports a value computed inside it | whole core, one image | directed | fpga/sim/test_core_coverage.py::stack_round_trips_through_lifo_and_returns | COVERED-DIRECTED |
| STACK-2 | progrom_gen.simulate() (bank-aware decode) | The Python oracle and the gate model agree on every stack instruction -- the oracle folds the bank bits into its field decode and models `LE_MDR` as a transparent latch, not a sampler | the stack image | directed | fpga/sim/test_core_coverage.py::stack_round_trips_through_lifo_and_returns | COVERED-DIRECTED |
| STACK-3 | progrom_gen.COVERAGE ladder | Every instruction in `INSTRUCTIONS` is exercised by some coverage image except `LDCI` (C is RET's scratch) and `NOP` | the whole ladder | directed | docs/notes/test_progrom_coverage.py::test_coverage_is_progressive | COVERED-DIRECTED |
| SYN-09 | CLAUDE.md FPGA paragraph ("every image tag synthesizes... and closes timing") | The design still infers and block-RAM-maps FIVE memories with the third microcode ROM present, with no flip-flop fallback | full synth_ecp5 | directed | docs/notes/test_netlist_integrity.py::test_full_synth_maps_all_five_memories_to_block_ram | COVERED-DIRECTED |

**Deliberately NOT rows: the six unwired word bits.** `~{CIN_SEL}`,
`~{MISC_BANK}`, `~{ADDR_SEL1}`, `FLAG_SEL0/1` and `FLAG_POL` are burned into
all 4096 rows and connected to nothing. There is no behaviour to assert, so
there is no row to write and no gap to declare -- MCC-01 covers the only
claim that exists about them today (that they read inert everywhere). They
become rows when they get consumers.

---

## Gap list

Ranking: rules that are entirely un-policed first, then ledgered
deferrals.

1. **ROM-07** — `src==dst` register self-transfer ("probable MOV typo") is a
   printed WARNING only; nothing fails if a shipped microword trips it.
2. **ROM-08** — per-instruction `PC_UP`-count-vs-byte-length mismatch
   (`_check_lengths()`) is a printed WARNING only; nothing fails if it's
   wrong.
3. **SYN-08** — "zero inferred latches" is a printed `proc -latches warn`
   only; nothing parses the synth log and fails the build if the count is
   nonzero.
4. **RES-02** — LDCI (and NOP) have no bench silicon ground truth; the FPGA
   model's behavior for them is only self-consistent (oracle vs gate
   model), never cross-checked against a real chip.
5. **RES-07** — nothing enforces that `fuzz_gen.py`'s `_MENU` keeps NOP and
   LDCI as generation choices, or that they are ever actually chosen; a
   silent removal would narrow fuzz coverage with nothing noticing.

### COVERED-INCIDENTAL rows (real artifact, not specifically targeted)

- INV-11 — bus output enables are un-gated by construction (the
  `control_word` entity has no machine-CLK port at all); the cited test
  never varies `clk` to specifically prove that independence.
- ROM-09 — `test_simulator_against_microcode` targets simulator-vs-
  microcode agreement, not opcode-table identity specifically; a future
  accidental `OPCODES` fork would very likely, but not necessarily, be
  caught here as a side effect.

---

## Row-count summary

| Status | Count (of 92 rows) |
|--------|------|
| COVERED-EXHAUSTIVE | 7 |
| COVERED-DIRECTED | 77 |
| COVERED-INCIDENTAL | 2 |
| GAP | 5 |

**5 GAP rows**, all named above, none silent. Every COVERED row cites an
artifact that genuinely fails when the behavior is wrong. The two
`COVERED-INCIDENTAL` rows are stated as such rather than folded into
`COVERED-DIRECTED`: a passing test that merely touches a claim, without
targeting it, is a different and weaker fact than one that would fail
specifically because the claim broke.
