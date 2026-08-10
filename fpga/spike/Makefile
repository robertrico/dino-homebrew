# cocotb does not support Python 3.14 (host python3, this Mac's default;
# cocotb 2.0.1's setup.py hard-errors past 3.13), so the sim harness runs
# out of a python3.13 venv at ~/.venvs/dino-fpga (created with
# `/opt/homebrew/bin/python3.13 -m venv ~/.venvs/dino-fpga` --
# python3.12 was unavailable on this machine; 3.13 is inside cocotb's
# supported range). cocotb-config and python come from that venv;
# ghdl/yosys/nextpnr/ecppack come from oss-cad-suite only, per project rule.
#
# Install PINNED, not bare `pip install cocotb`:
#     ~/.venvs/dino-fpga/bin/python -m pip install 'cocotb<3.0'
# This landed on cocotb 2.0.1, whose classic `cocotb-config --makefiles`
# flow (used below) still works. The brief's named hazard is real for
# cocotb 3.x, which is expected to drop --makefiles for the runner API --
# an unpinned install would silently pull that in on a fresh venv and
# break this Makefile and every descendant that copies this pattern with
# no warning. If a later task needs cocotb 3.x, that's a deliberate,
# separate migration of this whole pattern to the runner API, not a
# version creeping in via an unpinned `pip install`.
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
VHDL_SOURCES := $(PWD)/spike_bus.vhd

# MODEL selects which entity/test pair to run: `make` defaults to
# spike_bus; `make MODEL=spike_xcvr` runs the inout entity's test.
MODEL ?= spike_bus
TOPLEVEL := $(MODEL)
MODULE := test_$(MODEL)
EXTRA_ARGS += --std=08

include $(shell cocotb-config --makefiles)/Makefile.sim

# The yosys ghdl plugin (unlike the standalone `ghdl` binary) doesn't
# derive its IEEE library search path from its own install location --
# it needs GHDL_PREFIX pointed at oss-cad-suite's ghdl lib dir or it
# fails with "cannot find std library".
export GHDL_PREFIX := $(TOOLS)/../lib/ghdl

.PHONY: synth
synth:
	$(TOOLS)/yosys -m ghdl -p "ghdl --std=08 spike_bus.vhd -e spike_bus; tribuf -logic; synth_ecp5 -json spike.json"
	$(TOOLS)/nextpnr-ecp5 --um5g-45k --package CABGA381 --json spike.json --textcfg spike.cfg
	$(TOOLS)/ecppack spike.cfg spike.bit
	$(TOOLS)/yosys -m ghdl -p "ghdl --std=08 spike_bus.vhd -e spike_xcvr; tribuf -logic; synth_ecp5 -json spike_xcvr.json"
	$(TOOLS)/nextpnr-ecp5 --um5g-45k --package CABGA381 --json spike_xcvr.json --textcfg spike_xcvr.cfg
	$(TOOLS)/ecppack spike_xcvr.cfg spike_xcvr.bit

endif
