# cocotb runner for per-module sheet-entity testbenches (Task 9) --
# fpga/sim/test_module_<name>.py drives and samples exactly the sheet's
# CONTRACT ports (fpga/gen/<name>.vhd's own port list), the same signals
# the bench rig DRIVEs/SAMPLEs per tests/dino_bringup/src/mod_*.c's own
# bind() -- same doctrine, new instrument. Task 10 points MODULE_UNDER_TEST
# at the other eight sheets and writes their own test_module_<name>.py;
# nothing else here should need to change per-module.
#
# Same PATH-bootstrap/venv pattern as fpga/Makefile/fpga/ttl/Makefile/
# fpga/spike/Makefile -- see fpga/ttl/Makefile's header for the full
# explanation of the two non-obvious blocks below.
VENV  := $(HOME)/.venvs/dino-fpga/bin
TOOLS := $(HOME)/oss-cad-suite/bin

# --- PATH bootstrap --------------------------------------------------------
# GNU Make 3.81 (macOS's default /usr/bin/make) does not apply an in-file
# `export PATH := ...` update to $(shell ...) calls issued while parsing
# the rest of this makefile -- only to recipe subprocesses. cocotb's own
# Makefile.sim/Makefile.inc resolve `cocotb-config` and the simulator
# makefile via bare $(shell cocotb-config ...) calls we don't control, so
# PATH has to be correct in the real OS environment before make starts
# parsing them. Re-exec once, for real, with PATH fixed, then proceed.
ifndef DINO_FPGA_REEXEC
export DINO_FPGA_REEXEC := 1
export PATH := $(VENV):$(TOOLS):$(PATH)

.PHONY: $(MAKECMDGOALS) __reexec_default__
.DEFAULT_GOAL := __reexec_default__
$(MAKECMDGOALS) __reexec_default__:
	@$(MAKE) $(MAKECMDGOALS)

else
# --- real targets, PATH already correct in the environment ---------------

# Pinned explicitly: Makefile.sim's own "all: sim" rule (its first real
# target) is normally what GNU Make picks as the default goal with no
# other target rules ahead of it -- but the dino_core branch below adds
# its OWN standalone target (prepare_roms, CUSTOM_SIM_DEPS' recipe) ahead
# of the `include Makefile.sim` line, and an earlier target rule silently
# steals the default-goal slot from a later one. Pin it here so a bare
# `make MODULE_UNDER_TEST=dino_core` still runs the simulation, not just
# the ROM-prep step.
.DEFAULT_GOAL := all

SIM ?= ghdl
TOPLEVEL_LANG := vhdl

# MODULE_UNDER_TEST selects which fpga/gen/<name>.vhd sheet entity this
# run exercises; `make` defaults to program_counter (Task 9's first
# module). VHDL_SOURCES is every ttl/ model (no inter-file dependencies
# among them, so glob order is fine -- fpga/Makefile's own reasoning)
# plus gen/$(MODULE_UNDER_TEST).vhd LAST: GHDL analyzes in file-list
# order and every one of the 9 sheet entities depends only on ttl/
# instances, never on another gen/ file -- Task 8's report's "analysis
# order" dependency note (dino_core.vhd must come last of ALL of them)
# is about elaborating the WHOLE composed machine, not about testing one
# sheet in isolation. Should a future MODULE_UNDER_TEST ever need more
# than one gen/ file, extend VHDL_SOURCES in that dependency order --
# this default already lists the sheet file last, the position that
# matters.
MODULE_UNDER_TEST ?= program_counter

# dino_core (Task 11, whole-core sim) is not one sheet -- it instantiates
# all nine gen/ sheet entities plus a handful of raw ttl_* gates of its
# own, so VHDL_SOURCES has to carry every gen/ file, with dino_core.vhd
# analyzed LAST (GHDL analyzes in file-list order; dino_core.vhd is the
# only gen/ file that depends on the other eight -- Task 8's report's
# "analysis order" note, the same constraint fpga/Makefile's own
# TEST_regen precedent already respects). MODULE also has to switch:
# there is no test_module_dino_core.py, this task's test lives under its
# own name.
ifeq ($(MODULE_UNDER_TEST),dino_core)
GEN_SHEETS := alu control_word input_output mar mdr memory microcode program_counter registers_a_b stack_pointer
VHDL_SOURCES := $(wildcard $(PWD)/../ttl/*.vhd) $(patsubst %,$(PWD)/../gen/%.vhd,$(GEN_SHEETS)) $(PWD)/../gen/dino_core.vhd
# MODULE (cocotb's own variable, which .py file under fpga/sim/ it loads
# @cocotb.test()s from) defaults to Task 11's whole-core suite but is a
# plain default, not a hard pin -- overridable on the command line, e.g.
# `make MODULE_UNDER_TEST=dino_core MODULE=test_core_coverage
#      TESTCASE=alu_covers_every_sa_code`, Task 12's own seam onto the
# same dino_core elaboration (all nine gen/ sheets + dino_core.vhd) this
# branch already builds -- no change needed to VHDL_SOURCES/GEN_SHEETS
# above, only which Python test module cocotb loads.
MODULE ?= test_core_milestone
else
VHDL_SOURCES := $(wildcard $(PWD)/../ttl/*.vhd) $(PWD)/../gen/$(MODULE_UNDER_TEST).vhd
MODULE := test_module_$(MODULE_UNDER_TEST)
endif
TOPLEVEL := $(MODULE_UNDER_TEST)
EXTRA_ARGS += --std=08

# microcode/memory carry init_file generics (fpga/gen/microcode.vhd,
# fpga/gen/memory.vhd) whose DEFAULTS ("sim/hex/<ref>.hex") are relative
# to fpga/ (fpga/Makefile's documented run directory -- see that file's
# own header), not to THIS Makefile's run directory (fpga/sim/, per this
# Makefile's own header). Left at the default here, GHDL would look for
# fpga/sim/sim/hex/<ref>.hex and fail -- override with -g<generic>=<path>,
# the exact SIM_ARGS mechanism fpga/ttl/Makefile uses for MODEL=ttl_
# at28c64b/at28c256/mcm60256 (its own MEMORY_INSTANCES precedent), pointed
# at fpga/sim/hex/*.hex (committed, generated by docs/notes/fpga_gen.py's
# bin2hex() -- Task 8), which DOES sit directly under this Makefile's
# $(PWD).
ifeq ($(MODULE_UNDER_TEST),microcode)
SIM_ARGS += -gu9_init_file=$(PWD)/hex/U9.hex -gu15_init_file=$(PWD)/hex/U15.hex
SIM_ARGS += -gu23_init_file=$(PWD)/hex/U23.hex
else ifeq ($(MODULE_UNDER_TEST),memory)
SIM_ARGS += -gu24_init_file=$(PWD)/hex/PROG.hex -gu26_init_file=$(PWD)/hex/RAM.hex
# ttl_at28c256/ttl_mcm60256's `load_mem()` (fpga/ttl/ttl_mcm60256.vhd)
# builds its 32768-row init value in a LOCAL VARIABLE inside an impure
# function -- GHDL's interpreter counts that as a single "variable"
# allocation of 32768 * 8 std_logic elements = 256KB, over the default
# --max-stack-alloc=128KB run-option limit (only tripped here because
# this is the first task to actually RUN, not just elaborate, a memory
# model at its real addr_bits=15 depth -- fpga/ttl/test_memory.py's own
# MODEL=ttl_at28c256/ttl_mcm60256 branches use a 16-row addr_bits=4
# fixture specifically to stay under it). Raise the limit rather than
# shrink the fixture -- this sheet's whole point is exercising the REAL
# ROM/RAM content.
SIM_ARGS += --max-stack-alloc=1024
else ifeq ($(MODULE_UNDER_TEST),dino_core)
# Same relative-path reasoning as the microcode/memory branches above,
# all four memory-model generics at once (dino_core's own generics,
# fpga/gen/dino_core.vhd) plus the same --max-stack-alloc=1024 the
# memory branch needs (dino_core carries the SAME 32K AT28C256/MCM60256AP
# instances, one level down). DINO_PROG_HEX selects which coverage image
# this run's PROGRAM ROM boots from -- ROM content is a GHDL generic,
# resolved once at elaboration, so it CANNOT change between
# @cocotb.test()s in one run; test_core_milestone.py's two tests
# therefore need two separate `make` invocations (TESTCASE= selects one),
# the second overriding DINO_PROG_HEX to hex/PROG_in.hex. Defaults to the
# milestone image so a bare `make MODULE_UNDER_TEST=dino_core` runs the
# hard-gate program without any override.
DINO_PROG_HEX ?= hex/PROG.hex
SIM_ARGS += -gu9_init_file=$(PWD)/hex/U9.hex -gu15_init_file=$(PWD)/hex/U15.hex
SIM_ARGS += -gu23_init_file=$(PWD)/hex/U23.hex
SIM_ARGS += -gu24_init_file=$(PWD)/$(DINO_PROG_HEX) -gu26_init_file=$(PWD)/hex/RAM.hex
SIM_ARGS += --max-stack-alloc=1024

# ROM-image prep (conftest_helpers.prepare_roms(), this task's own
# interface): regenerate roms/*.bin if microcode_gen.py/progrom_gen.py
# are newer, then bin2hex() every image this run's generics point at
# (including PROG_in.hex, which fpga_gen.py's own _regenerate() does not
# emit -- it only converts the milestone image, not every coverage tag)
# into fpga/sim/hex/. CUSTOM_SIM_DEPS is cocotb's OWN extension point
# (Makefile.ghdl: "$(COCOTB_RESULTS_FILE): analyse $(CUSTOM_SIM_DEPS)"),
# not a bespoke hook -- this runs before every dino_core elaboration,
# never after (the hex file has to exist before `ghdl -r` reads it at
# elaboration time; a Python-side check inside the test itself would run
# too late, per this task's own report).
#
# tags=tuple(progrom_gen.COVERAGE) (Task 12): every run converts EVERY
# COVERAGE image (real/in/alu/mem/flow/loop/adda/addb/probe), not just
# the pair a given TESTCASE happens to need -- prepare_roms()'s own
# staleness check (conftest_helpers._stale()) makes this idempotent and
# cheap on repeat invocations, and it means the same CUSTOM_SIM_DEPS hook
# serves test_core_milestone.py and test_core_coverage.py without needing
# to know, from the Makefile, which .hex a given TESTCASE will read.
CUSTOM_SIM_DEPS += prepare_roms
.PHONY: prepare_roms
prepare_roms:
	python3 -c "import conftest_helpers as ch; ch.prepare_roms(tags=tuple(ch.progrom_gen.COVERAGE))"
endif

include $(shell cocotb-config --makefiles)/Makefile.sim

# The yosys ghdl plugin (unlike the standalone `ghdl` binary invoked by
# cocotb's own Makefile.sim) doesn't derive its IEEE library search path
# from its own install location -- it needs GHDL_PREFIX pointed at
# oss-cad-suite's ghdl lib dir or it fails with "cannot find std
# library". Inert for this Makefile's own cocotb+ghdl sim runs (which
# use the standalone `ghdl` binary and resolve fine without it), carried
# over from fpga/spike/Makefile for consistency across the fpga/*/
# Makefile family per this task's interface.
export GHDL_PREFIX := $(TOOLS)/../lib/ghdl

endif
