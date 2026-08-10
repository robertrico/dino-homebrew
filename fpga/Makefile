# cocotb runner for entities that live directly under fpga/ -- dino_core
# and its generated sub-entities (fpga/gen/*.vhd). This is the documented
# run directory: the elaboration gate (`cd fpga && ghdl -a ... gen/*.vhd`)
# and MEMORY_INSTANCES' default generic paths (docs/notes/fpga_gen.py,
# "sim/hex/<ref>.hex") are BOTH relative to here, not repo root and not
# fpga/gen/. Same PATH-bootstrap/venv pattern as fpga/ttl/Makefile/
# fpga/spike/Makefile -- see fpga/ttl/Makefile's header for the full
# explanation of the two non-obvious blocks below.
VENV  := $(HOME)/.venvs/dino-fpga/bin
TOOLS := $(HOME)/oss-cad-suite/bin

ifndef DINO_FPGA_REEXEC
export DINO_FPGA_REEXEC := 1
export PATH := $(VENV):$(TOOLS):$(PATH)

.PHONY: $(MAKECMDGOALS) __reexec_default__
.DEFAULT_GOAL := __reexec_default__
$(MAKECMDGOALS) __reexec_default__:
	@$(MAKE) $(MAKECMDGOALS)

else

# Pinned explicitly: cocotb's own Makefile.sim defines `all: sim` as its
# first real target, which GNU Make would otherwise pick as the default
# goal for a bare `make` -- but this file's own `bit`/`bits`/`clean-bit`
# targets (Task 13, below) are now defined EARLIER in the file, and an
# earlier target rule silently steals the default-goal slot from a later
# one (the exact fpga/sim/Makefile precedent this comment borrows). Pin
# it here so a bare `make`/`make MODEL=dino_core` still runs the
# simulation, not `bit`.
.DEFAULT_GOAL := all

SIM ?= ghdl
TOPLEVEL_LANG := vhdl

# MODEL selects which generated entity/test pair to run: `make` defaults
# to `microcode` (Task 8 review fix #1's covering test -- proves the
# DEFAULT init_file generics resolve and load real ROM content from THIS
# directory, not overridden here on purpose). VHDL_SOURCES is every ttl/
# model (no inter-file dependencies among them, so glob order is fine)
# plus gen/$(MODEL).vhd LAST (GHDL analyzes in file-list order and
# gen/$(MODEL).vhd depends on the ttl/ entities it instantiates).
MODEL ?= microcode
VHDL_SOURCES := $(wildcard $(CURDIR)/ttl/*.vhd) $(CURDIR)/gen/$(MODEL).vhd
TOPLEVEL := $(MODEL)
MODULE := test_regen
EXTRA_ARGS += --std=08

# --- FPGA bitstream synthesis (Task 13) ------------------------------------
# `make bit IMAGE=<tag>` -> build/dino_<tag>.bit for the Lattice ECP5-5G
# Versa board (top/versa_top.vhd, top/versa.lpf). Deliberately separate
# from the cocotb MODEL-sim machinery above -- guarded off from the
# `include Makefile.sim` line below (see the ifeq at the bottom of this
# block) so a synthesis-only invocation never needs cocotb-config to
# resolve, and vice versa. Toolchain is oss-cad-suite ONLY (CLAUDE.md rule
# 5's "RUN THE TOOL" instrument list, same reasoning as GHDL_PREFIX below)
# -- every binary is invoked by its full $(TOOLS)/ path rather than
# relying on PATH order, since a homebrew yosys/ghdl/ecppack also exists
# on this machine and must never shadow oss-cad-suite's.
#
# $(CURDIR), never $(PWD): PWD is an inherited ENVIRONMENT variable naming
# the directory the user's shell was in, and make does not update it for
# -C. `make -C fpga bit IMAGE=real` therefore resolved every path below
# against the REPO ROOT and died with "No rule to make target
# .../fpga-port/build/dino_real.bit". `make bits` masked it: its recipe
# spawns a shell, and a POSIX shell re-derives PWD from getcwd() at
# startup, so the recursive `$(MAKE) bit` got a corrected PWD by accident.
# $(CURDIR) is make's own always-correct cwd. Both invocation styles are
# verified: `make -C fpga bit IMAGE=real` and `cd fpga && make bit
# IMAGE=real`.
IMAGE ?= real
# mardisc/pads added post-merge (2026-08-08 doc task): the two coverage
# images that answered the MAR_LO investigation (docs/notes/
# dino_mar_lo_investigation.md) on the bench 2026-08-04, now proven to
# build for fabric too. cylon is NOT a COVERAGE tag (progrom_gen.py:
# "deliberately NOT in COVERAGE: it never halts") so it is intentionally
# absent from this list -- it still builds fine via `make bit
# IMAGE=cylon` because check_images.py's TAGS table (below this
# Makefile's own HEX_cylon entry) carries it independently.
IMAGE_TAGS := real in alu mem flow loop mardisc pads
BUILD_DIR := $(CURDIR)/build

# progrom_gen.COVERAGE tag -> fpga/-relative committed hex path
# (fpga/sim/hex/PROG*.hex, Task 12's own bin2hex() output --
# conftest_helpers._hex_name()'s same "real"->PROG.hex,
# other->PROG_<tag>.hex rule, hand-mirrored here since this Makefile has
# no Python in its critical path).
HEX_real    := sim/hex/PROG.hex
HEX_in      := sim/hex/PROG_in.hex
HEX_alu     := sim/hex/PROG_alu.hex
HEX_mem     := sim/hex/PROG_mem.hex
HEX_flow    := sim/hex/PROG_flow.hex
HEX_loop    := sim/hex/PROG_loop.hex
HEX_mardisc := sim/hex/PROG_mardisc.hex
HEX_pads    := sim/hex/PROG_pads.hex
# cylon: never halts, not in progrom_gen.COVERAGE, but roms/PROG_cylon.bin
# exists and bin2hex()s the same way every other image does -- burned as
# the victory-lap/soak image (fpga/BRINGUP_FPGA.md). `make bit
# IMAGE=cylon` works off this one extra line; no other Makefile change
# needed.
HEX_cylon   := sim/hex/PROG_cylon.hex

# GEN_SHEETS/analysis order: identical to fpga/sim/Makefile's own
# MODULE_UNDER_TEST=dino_core branch (Task 8's report: dino_core.vhd
# depends on all 9 sub-sheets, must be analyzed LAST; a bare glob sorts
# it 3rd alphabetically and fails). top/versa_top.vhd goes last of all --
# it depends on dino_core.
GEN_SHEETS := alu control_word input_output mar mdr memory microcode program_counter registers_a_b
SYNTH_VHDL_SOURCES := $(wildcard $(CURDIR)/ttl/*.vhd) $(patsubst %,$(CURDIR)/gen/%.vhd,$(GEN_SHEETS)) $(CURDIR)/gen/dino_core.vhd $(CURDIR)/top/versa_top.vhd
SYNTH_SCRIPTS := $(CURDIR)/synth/bus_resolve.ys $(CURDIR)/synth/dead_tbuf.v

.PHONY: bit bits clean-bit check-images prog prog-flash
bit: $(BUILD_DIR)/dino_$(IMAGE).bit

# Two load targets (Rico's naming, 2026-08-09):
#     make prog IMAGE=cylon         # SRAM load -- volatile, instant, no flash
#                                   # wear; the bring-up iteration default
#     make prog-flash IMAGE=cylon   # SPI FLASH write -- image survives power
#                                   # cycles; wears flash, use when an image
#                                   # is meant to stay
# `-c ft2232` is the verified cable for this board (openFPGALoader v1.1.1
# has no ecp5_versa board entry); if detect fails, try -c ft4232 before
# suspecting hardware.
prog: bit
	$(TOOLS)/openFPGALoader -c ft2232 $(BUILD_DIR)/dino_$(IMAGE).bit

prog-flash: bit
	$(TOOLS)/openFPGALoader -c ft2232 -f $(BUILD_DIR)/dino_$(IMAGE).bit

# Restated synthesis gate 2's second half, as a repeatable check rather
# than a one-off session script: synthesize each image tag through the
# PRODUCTION sequence, pull the INIT off every $mem_v2 cell in the
# resulting netlist, decode it back to bytes and compare against the
# committed roms/*.bin -- the same bytes Rico burns. Slow (nine full
# syntheses), so it is its own target, not a `bit` prerequisite; the fast
# half of the same script (--hex, .hex-vs-.bin staleness) IS a `bit`
# prerequisite and runs on every build.
check-images:
	python3 $(CURDIR)/synth/check_images.py --hex --meminit

# --- Consolidated verification meta-target ---------------------------------
# `make -C fpga verify` -- host suite -> fuzz -> cocotb TB ladder, in
# genuinely cheapest-first order so a red step is found fast: host suite
# (every docs/notes/test_*.py under pytest), fuzz (fpga/sim/test_core_fuzz.py,
# DINO_FUZZ_N seeds, defaults to 20 when unset), THEN the cocotb TB ladder
# (fpga/run_cocotb_ladder.sh -- 18 ttl + 9 sim + 2 milestone + 8 coverage
# invocations, 37 total). No ordering dependency exists between the three
# (the host suite's drift/no-drift tests write into pytest's own tmp_path,
# the cocotb ladder only READS fpga/gen/*.vhd, never touching it) --
# reordering is purely a fail-fast optimization, not a correctness
# requirement. `DINO_FUZZ_N=500 make -C fpga verify` threads through to the
# fuzz stage for a soak (it's a plain env var Make passes to the recipe's
# subprocess); see that file's own header for the calibration numbers.
#
# Deliberately NOT included: `bits`/`check-images`/postsynth -- those are
# build-and-place gates over all nine image tags, not part of this target's
# host/fuzz/cocotb stack, and are run separately per this file's own
# "Reproducibility" section in BRINGUP_FPGA.md; folding a multi-image
# synthesis ladder into every `verify` run would make the fast steps wait
# on the slowest one for no correctness gain.
#
# Fails LOUD at the first red step (`|| exit 1` after every stage, plus a
# named FAILED line so the banner alone says which stage broke) and prints
# one final banner with wall time either way. Read the failing stage's own
# artifact for the specific problem -- results.xml (host suite/fuzz),
# fpga/ttl/results.xml or fpga/sim/results.xml (cocotb ladder) -- see
# BRINGUP_FPGA.md's verification section for "how to read a failure" per
# stage.
#
# `-n`/`-t`/`-q` are NOT dry runs against this target: this file's re-exec
# block at the top trips GNU Make's documented "a recipe line referencing
# $(MAKE) always executes, even under -n/-t/-q" rule, so `make -n verify`
# still runs the real thing. There is no dry-run flag that is actually dry
# against this Makefile; don't reach for one to "just check the recipe."
.PHONY: verify
verify:
	@echo "=== verify: START $$(date) ==="
	@t0=$$(date +%s); \
	echo "--- [1/3] host suite: pytest docs/notes/ ---"; \
	python3 -m pytest $(CURDIR)/../docs/notes -q || { echo "=== VERIFY FAILED at [1/3] host suite ==="; exit 1; }; \
	echo "--- [2/3] fuzz (DINO_FUZZ_N=$${DINO_FUZZ_N:-20}) ---"; \
	python3 $(CURDIR)/sim/test_core_fuzz.py || { echo "=== VERIFY FAILED at [2/3] fuzz ==="; exit 1; }; \
	echo "--- [3/3] cocotb TB ladder (18 ttl + 9 sim + 2 milestone + 8 coverage) ---"; \
	$(CURDIR)/run_cocotb_ladder.sh || { echo "=== VERIFY FAILED at [3/3] cocotb TB ladder ==="; exit 1; }; \
	t1=$$(date +%s); \
	echo "=== VERIFY: ALL GREEN ($$((t1-t0))s wall) ==="

# Builds all eight required image tags in one invocation (this task's own
# gate: "all eight tags build"). Recurses via $(MAKE) so each tag gets its
# own IMAGE-driven pattern-rule expansion.
bits:
	@for tag in $(IMAGE_TAGS); do \
	  echo "=== building dino_$$tag.bit ==="; \
	  $(MAKE) bit IMAGE=$$tag || exit 1; \
	done

# yosys(-m ghdl) -> nextpnr-ecp5 -> ecppack, one shell recipe per stage so
# each stage's own log is captured and its real exit status (not tee's)
# gates the next stage. PROG_HEX is versa_top's own generic (defaults to
# the milestone image); $(HEX_$*) selects the per-tag hex via ghdl's
# -g<generic>=<value> passthrough THROUGH yosys's `ghdl` command -- the
# one genuinely new mechanism this task proves (verified working against
# a throwaway string-generic entity before trusting it on the real
# design; see task-13-report.md).
#
# `script synth/bus_resolve.ys` is the shared-bus tri-state resolution
# pre-pass -- READ THAT FILE, it carries the full root-cause write-up.
# Short version: synth_ecp5's own coarse stage runs `flatten; tribuf
# -logic` and that ALONE leaves 24 multiply-driven nets (8 pairing the
# program ROM's $memrd_v2 DATA against a tribuf-resolution $pmux, 16
# pairing the four '193 counters' $dff Q against one), which nextpnr-ecp5
# rejects at placement.
# bus_resolve.ys runs the same flatten/tribuf but with two exact repairs
# in between (split vector tri-states per-bit so `tribuf` groups them with
# the bit-wide ones sharing the same net; delete tri-state buffers whose
# enable folds to a hard constant 0). It is deliberately NOT the old
# pre-flatten `tribuf -logic` that synth-rework-brief.md item 4 removed --
# that one ran BEFORE flatten, where sub-instance tri-states aren't yet
# visible as one mux-resolution problem. This one flattens first.
#
# --ignore-loops (nextpnr): this design's shared tri-state bus fabric
# (every register/latch sits on a bus also read by whatever decodes its
# OWN output-enable -- registers_a_b.vhd's TMP_A/B/C latches are the
# clearest example) produces genuine topological combinational loops once
# `tribuf -logic` turns tri-state drivers into muxes. Netlist-traced, not
# assumed: n_reg_a_out gates BOTH U31's oe_n and U41's dir simultaneously
# (gen/registers_a_b.vhd), so the loop the mux structure exposes can never
# actually contend on real silicon -- the same "combinational decode chain
# settles before anything commits" architecture CLAUDE.md already
# documents for the microcode ROM access window. nextpnr's own sanctioned
# mechanism for exactly this class of bus-fabric design; see
# task-13-report.md for the full trace.
#
# --timing-allow-fail is NOT "timing is allowed to fail." It is there for
# one specific, documented class: `--ignore-loops` cuts each combinational
# bus loop and, in doing so, invents a ZERO-DELAY pseudo-launch at the cut
# point, which nextpnr then reports as a hold violation (594 of them, all
# -0.18ns). Every printed path LAUNCHES from a fake 0.00ns pseudo-source at
# the loop-break combinational cell itself -- mdr's U25 (x8), registers_a_b's
# U41 (x2) -- and CAPTURES at a REAL flip-flop's D input (U18/U31/U32/U33's
# held_TRELLIS_FF_Q_* -- see task-13-report.md "Bus resolution + gates",
# gate 4): a fake launch paired with a real capture means no genuine
# launch-to-capture pair exists in the first place, not merely that the
# path is short. Those are not launch-to-capture paths, and nextpnr has
# no switch to waive them individually, so the whole
# timing check has to be made non-fatal to get past them. That would leave
# SETUP closure -- the thing that actually depends on the clk_sys
# constraint -- as a human log read, which is how Task 13 shipped six
# bitstreams whose 100MHz constraint was never met. The `timing gate` step
# below closes that: it re-reads the FINAL (post-route) Fmax line for
# clk_sys out of nextpnr's own log and fails the build unless it says
# PASS. Take the LAST such line on purpose -- nextpnr prints one after
# placement and one after routing, and only the second is real.
$(BUILD_DIR)/dino_%.bit: $(SYNTH_VHDL_SOURCES) $(SYNTH_SCRIPTS) top/versa.lpf
	@mkdir -p $(BUILD_DIR)
	@python3 $(CURDIR)/synth/check_images.py --hex $*
	GHDL_PREFIX=$(TOOLS)/../lib/ghdl $(TOOLS)/yosys -m ghdl -p \
	  "ghdl --std=08 -gPROG_HEX=$(HEX_$*) $(SYNTH_VHDL_SOURCES) -e versa_top; synth_ecp5 -top versa_top -run begin:coarse; proc -latches warn; script synth/bus_resolve.ys; synth_ecp5 -top versa_top -run coarse: -json $(BUILD_DIR)/dino_$*.json" \
	  > $(BUILD_DIR)/dino_$*.synth.log 2>&1 || (tail -n 60 $(BUILD_DIR)/dino_$*.synth.log; exit 1)
	$(TOOLS)/nextpnr-ecp5 --um5g-45k --package CABGA381 \
	  --json $(BUILD_DIR)/dino_$*.json --lpf top/versa.lpf \
	  --textcfg $(BUILD_DIR)/dino_$*.config \
	  --ignore-loops --timing-allow-fail --report $(BUILD_DIR)/dino_$*.report.json \
	  > $(BUILD_DIR)/dino_$*.pnr.log 2>&1 || (tail -n 80 $(BUILD_DIR)/dino_$*.pnr.log; exit 1)
	@last=`grep "Max frequency for clock .*clk_sys" $(BUILD_DIR)/dino_$*.pnr.log | tail -n 1`; \
	 case "$$last" in \
	   *"(PASS at "*) echo "timing gate: $${last#*Info: }" ;; \
	   "") echo "TIMING GATE FAILED (dino_$*): nextpnr reported NO Fmax line for clk_sys."; \
	       echo "  Either the clock net was renamed or versa.lpf's FREQUENCY NET no longer matches;"; \
	       echo "  --timing-allow-fail means nextpnr will NOT have failed on its own."; \
	       grep -i "constraining clock\|Max frequency" $(BUILD_DIR)/dino_$*.pnr.log; exit 1 ;; \
	   *) echo "TIMING GATE FAILED (dino_$*): $$last"; \
	      echo "  Post-route setup closure is NOT met at the constraint in top/versa.lpf."; \
	      echo "  Lower FREQUENCY NET \"clk_sys\" (and versa_top.vhd's EHXPLLL divisors to match), or fix the path."; \
	      grep -A 30 "Critical path report for clock" $(BUILD_DIR)/dino_$*.pnr.log | head -n 40; exit 1 ;; \
	 esac
	$(TOOLS)/ecppack $(BUILD_DIR)/dino_$*.config $(BUILD_DIR)/dino_$*.bit \
	  > $(BUILD_DIR)/dino_$*.pack.log 2>&1 || (cat $(BUILD_DIR)/dino_$*.pack.log; exit 1)
	@echo "built $(BUILD_DIR)/dino_$*.bit"

clean-bit:
	rm -rf $(BUILD_DIR)

# Skip the cocotb sim include entirely for synthesis-only goals -- it
# would otherwise force cocotb-config to resolve (harmless when the venv
# is on PATH, but a needless coupling for a target that never touches
# cocotb) and, more importantly, keeps this section reusable if a future
# CI runner has one toolchain but not the other.
ifeq ($(filter bit bits clean-bit check-images prog prog-flash verify,$(MAKECMDGOALS)),)
include $(shell cocotb-config --makefiles)/Makefile.sim
endif

endif
