# Restated synthesis gate 5: simulate the POST-SYNTHESIS netlist.
#
# `make -C fpga/postsynth` synthesizes dino_core through the real
# oss-cad-suite flow (the SAME `synth_ecp5 -run begin:coarse` + `script
# synth/bus_resolve.ys` + `synth_ecp5 -run coarse:map_ram` sequence
# fpga/Makefile's `bit` rule uses, so this gate cannot drift away from
# what the bitstreams are built from), writes it out as flat Verilog, and
# runs it under Icarus with cocotb -- no VHDL anywhere in the simulated
# design. See test_postsynth_milestone.py's own header for why the
# coarse-stage netlist is the right (and only simulatable) cut point.
#
# dino_core is the top here, NOT versa_top: versa_top instantiates the
# EHXPLLL hard PLL, which is a black box with no simulation model. The
# board shell is evidenced by place-and-route, not by simulation.
#
# Same PATH-bootstrap/venv pattern as fpga/Makefile and fpga/sim/Makefile
# -- see fpga/ttl/Makefile's header for the full explanation.
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

.DEFAULT_GOAL := all

FPGA_DIR := $(CURDIR)/..
NETLIST  := $(CURDIR)/build/dino_core_postsynth.v

GEN_SHEETS := alu control_word input_output mar mdr memory microcode program_counter registers_a_b
SYNTH_VHDL_SOURCES := $(wildcard $(FPGA_DIR)/ttl/*.vhd) $(patsubst %,$(FPGA_DIR)/gen/%.vhd,$(GEN_SHEETS)) $(FPGA_DIR)/gen/dino_core.vhd

# dino_core's four memory-init generics default to "sim/hex/<ref>.hex",
# fpga/-relative (fpga/Makefile's documented run directory) -- which is
# exactly where this recipe runs yosys from, so the defaults resolve and
# the netlist is built against the MILESTONE program image, no override
# needed. `write_verilog -selected` after `select dino_core` keeps the
# Lattice cell library (read in by synth_ecp5's `begin` label, and full
# of processes the Verilog backend would choke on) out of the output.
#
# `opt_clean -purge` is a SIMULATOR requirement, not an optimization:
# without it the backend still emits each ROM model's dead `mem` alias
# wire as one 262144-bit hex literal on a single 65KB line, and Icarus's
# lexer dies on it ("input buffer overflow, can't enlarge buffer because
# scanner uses REJECT"). It only removes wires nothing reads; the real
# memories are $mem_v2 cells and are untouched (asserted by the run
# reaching HALT with the right answer at all).
$(NETLIST): $(SYNTH_VHDL_SOURCES) $(FPGA_DIR)/synth/bus_resolve.ys $(FPGA_DIR)/synth/dead_tbuf.v
	@mkdir -p $(dir $(NETLIST))
	cd $(FPGA_DIR) && GHDL_PREFIX=$(TOOLS)/../lib/ghdl $(TOOLS)/yosys -m ghdl -p \
	  "ghdl --std=08 $(SYNTH_VHDL_SOURCES) -e dino_core; \
	   synth_ecp5 -top dino_core -run begin:coarse; \
	   proc -latches warn; \
	   script synth/bus_resolve.ys; \
	   synth_ecp5 -top dino_core -run coarse:map_ram; \
	   opt_clean -purge; \
	   select dino_core; \
	   write_verilog -noattr -selected $(NETLIST)" \
	  > $(CURDIR)/build/postsynth.log 2>&1 || (tail -n 40 $(CURDIR)/build/postsynth.log; exit 1)
	@echo "wrote $(NETLIST)"

SIM := icarus
TOPLEVEL_LANG := verilog

# oss-cad-suite's bin/vvp is a WRAPPER SCRIPT that exports
# PYTHONHOME=<suite root> before exec'ing the real binary. cocotb embeds
# CPython inside vvp, so that hijacks the interpreter out from under the
# dino-fpga venv and the run dies with "Failed to import encodings
# module" before a single test starts. Point cocotb at libexec/ (the real
# binaries the wrappers exec) so the venv's own Python stays in charge --
# still oss-cad-suite ONLY, per CLAUDE.md's toolchain rule, just one
# level below the wrapper. iverilog's wrapper only adds
# -pVVP_EXECUTABLE=..., which matters solely for `iverilog -r`-style
# direct execution that this flow never uses.
ICARUS_BIN_DIR := $(TOOLS)/../libexec
# yosys's own behavioural models for the coarse cells its Verilog backend
# emits as instances rather than expressions -- $alu (16, the '382 carry
# datapath) and $_TBUF_ (9, the tri-state drivers that land directly on
# dino_core's OWN output ports, which `tribuf -logic` deliberately leaves
# alone: at versa_top level those same nets are internal and resolve to
# zero tri-states, which is why the bitstream netlist has none). Shipped
# with the toolchain, not written here.
VERILOG_SOURCES := $(TOOLS)/../share/yosys/simlib.v $(TOOLS)/../share/yosys/simcells.v $(NETLIST)
TOPLEVEL := dino_core
MODULE := test_postsynth_milestone

# cocotb's own extension point (Makefile.icarus: the results file depends
# on $(CUSTOM_COMPILE_DEPS)) -- the netlist has to exist before iverilog
# runs, and there is no Python-side hook that runs early enough.
CUSTOM_COMPILE_DEPS += $(NETLIST)

include $(shell cocotb-config --makefiles)/Makefile.sim

endif
