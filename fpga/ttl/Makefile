# cocotb runner for the plain-gate TTL models. Copied from the pattern
# proven in fpga/spike/Makefile (Task 1) -- see that file's header comment
# for the full explanation of the two non-obvious blocks below (PATH
# bootstrap re-exec, GHDL_PREFIX). Short version: cocotb runs out of a
# python3.13 venv at ~/.venvs/dino-fpga (host python3 is 3.14, unsupported
# by cocotb 2.0.1), installed PINNED:
#     ~/.venvs/dino-fpga/bin/python -m pip install 'cocotb<3.0'
# cocotb-config and python come from that venv; ghdl/yosys/nextpnr/ecppack
# come from oss-cad-suite only, per project rule.
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

SIM ?= ghdl
TOPLEVEL_LANG := vhdl

# MODEL selects which entity/test pair to run: `make` defaults to
# ttl_74ls00; `make MODEL=ttl_74ls02` runs the '02 NOR's test, etc. Each
# model lives in its own file (unlike spike_bus.vhd's two entities), so
# VHDL_SOURCES follows MODEL too.
MODEL ?= ttl_74ls00
VHDL_SOURCES := $(PWD)/$(MODEL).vhd
TOPLEVEL := $(MODEL)
MODULE := test_gates
EXTRA_ARGS += --std=08

# Task 3's four MSI models (138/157/244/245) live in test_msi.py instead of
# test_gates.py -- their MODEL branches below override MODULE accordingly.

# test_gates.py holds one truth-table test per gate function, all in one
# file (brief step 5); only the test matching MODEL's gate function is
# valid against that entity's ports, so select it here. Uses
# COCOTB_TEST_FILTER, not the older TESTCASE/COCOTB_TESTCASE var --
# COCOTB_TESTCASE is deprecated in cocotb 2.x and its DeprecationWarning
# would make `make`'s output non-pristine. The regression manager matches
# this pattern against `test.fullname` ("test_gates.<test-name>"), via
# re.search (not fullmatch) -- anchoring on "\.<name>$" (not "^<name>$")
# both matches that module-qualified form AND avoids "and_truth_table$"
# wrongly matching "nand_truth_table" as a bare string suffix. The
# backslash has to be DOUBLED here: Makefile.ghdl's recipe interpolates
# this var unquoted into a shell command line, and an unquoted shell word
# strips a single backslash before an ordinary character (bash -c 'echo
# \.x' -> ".x", turning the escaped dot into an unescaped wildcard that
# WOULD wrongly match "nand_truth_table" too) -- "\\." survives that strip
# as the single "\." the regex engine needs to receive.
ifeq ($(MODEL),ttl_74ls00)
COCOTB_TEST_FILTER := \\.nand_truth_table$$
else ifeq ($(MODEL),ttl_74ls02)
COCOTB_TEST_FILTER := \\.nor_truth_table$$
else ifeq ($(MODEL),ttl_74ls08)
COCOTB_TEST_FILTER := \\.and_truth_table$$
else ifeq ($(MODEL),ttl_74ls04)
COCOTB_TEST_FILTER := \\.inverter_truth_table$$
else ifeq ($(MODEL),ttl_74hc14)
COCOTB_TEST_FILTER := \\.inverter_truth_table$$
else ifeq ($(MODEL),ttl_74ls138)
MODULE := test_msi
COCOTB_TEST_FILTER := \\.decoder_truth_table$$
else ifeq ($(MODEL),ttl_74ls157)
MODULE := test_msi
COCOTB_TEST_FILTER := \\.mux_truth_table$$
else ifeq ($(MODEL),ttl_74ls244)
MODULE := test_msi
COCOTB_TEST_FILTER := \\.buffer_tri_state$$
else ifeq ($(MODEL),ttl_74ls245)
MODULE := test_msi
# BOTH xcvr_* tests: the mirror-witness direction test and the tri-state
# RELEASE test (the property fpga/synth/dead_tbuf.v's dead-driver deletion
# rests on). A prefix match, not an alternation -- cocotb's own
# Makefile.ghdl interpolates COCOTB_TEST_FILTER into the command line
# UNQUOTED, so `(a|b)` reaches bash as a syntax error.
COCOTB_TEST_FILTER := \\.xcvr_
else ifeq ($(MODEL),ttl_74f382)
MODULE := test_74f382
COCOTB_TEST_FILTER := \\.alu_exhaustive$$
else ifeq ($(MODEL),ttl_74ls74)
MODULE := test_stateful
COCOTB_TEST_FILTER := \\.ff74_edge_and_async$$
else ifeq ($(MODEL),ttl_74ls163)
MODULE := test_stateful
COCOTB_TEST_FILTER := \\.counter163_sync$$
else ifeq ($(MODEL),ttl_74ls169)
MODULE := test_stateful
# Matches BOTH '169 tests (the up/down/hold + load-priority truth check and
# the direction-dependent ~TC check) via their shared "counter169_" prefix
# -- same idiom as the '273/'373 branches, and for the same reason: an
# unescaped alternation reaches bash unquoted and is a syntax error.
COCOTB_TEST_FILTER := \\.counter169_
else ifeq ($(MODEL),ttl_74ls193)
MODULE := test_stateful
COCOTB_TEST_FILTER := \\.counter193_async$$
else ifeq ($(MODEL),ttl_74ls273)
MODULE := test_stateful
# Matches BOTH '273 tests (async-clear + the pre-edge-D capture
# regression) via their shared "register273_" prefix -- same idiom as
# the '373 branch just below (see its own comment for why a prefix, not
# a parenthesised alternation).
COCOTB_TEST_FILTER := \\.register273_
else ifeq ($(MODEL),ttl_74ls373)
MODULE := test_stateful
# Matches BOTH '373 tests (transparent + the stale-glitch regression) via
# their shared "latch373_" prefix, not a parenthesised alternation --
# Makefile.ghdl's recipe interpolates COCOTB_TEST_FILTER unquoted into a
# shell command line (this file's own header comment), and unescaped
# "(...)"/"|" there is a shell syntax error, not a regex one.
COCOTB_TEST_FILTER := \\.latch373_
else ifeq ($(MODEL),ttl_at28c64b)
MODULE := test_memory
COCOTB_TEST_FILTER := \\.rom64_exact_readback_and_deselect$$
SIM_ARGS += -ginit_file=$(PWD)/test_memory_16.hex -gaddr_bits=4
else ifeq ($(MODEL),ttl_at28c256)
MODULE := test_memory
COCOTB_TEST_FILTER := \\.rom256_exact_readback_and_deselect$$
SIM_ARGS += -ginit_file=$(PWD)/test_memory_16.hex -gaddr_bits=4
else ifeq ($(MODEL),ttl_mcm60256)
MODULE := test_memory
# BOTH ram_* tests via their shared prefix (same unquoted-interpolation
# reason as the '373 branch above): the mirror-witness write/read test and
# the dq_o tri-state RELEASE test that fpga/synth/bus_resolve.ys's
# shared-bus arbitration depends on.
COCOTB_TEST_FILTER := \\.ram_
SIM_ARGS += -ginit_file=$(PWD)/test_memory_16.hex -gaddr_bits=4
endif
export COCOTB_TEST_FILTER

include $(shell cocotb-config --makefiles)/Makefile.sim

# No `synth:` target here -- these plain-gate models don't need one for
# this task (unlike fpga/spike/Makefile's tri-state proof), so GHDL_PREFIX
# (needed only by `yosys -m ghdl`) is intentionally omitted. Add it back
# per the spike Makefile's comment if a later task adds synthesis here.

endif
