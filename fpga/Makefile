# The FPGA twin: the mainboard and its seated cards as gates on the ECP5-5G Versa.
#
#     make gen                    regenerate fpga/gen/ for the slot table
#                                 (docs/notes/fpga_slots_gen.py SLOTS)
#     make sim                    every coverage image, simulated, vs the oracle
#     make bit IMAGE=isa          build/dino_isa.bit with roms/PROG_isa.bin in U24
#     make prog IMAGE=isa         load it into the FPGA's SRAM (volatile)
#     make prog-flash IMAGE=isa   write it to the SPI flash (survives power)
#
# IMAGE names roms/PROG_<IMAGE>.bin; IMAGE=real is roms/PROG.bin. The
# microcode in U9/U15/U23 is roms/U9.bin, U15.bin, U23.bin. Toolchain:
# oss-cad-suite only (yosys, nextpnr-ecp5, ecppack, openFPGALoader).
TOOLS := $(HOME)/oss-cad-suite/bin
PY    ?= python3
IMAGE ?= isa
ROM   := $(if $(filter real,$(IMAGE)),PROG,PROG_$(IMAGE))
BUILD := $(CURDIR)/build
GEN   := $(CURDIR)/gen
# what dino_system needs, in order: the core, the seated cards, the system
SYSTEM = $(shell cat $(GEN)/dino_system_files.txt 2>/dev/null)
SRC   = $(CURDIR)/ttl_fpga.v $(SYSTEM) $(CURDIR)/pll_48mhz.v $(CURDIR)/versa_top.v

.PHONY: gen sim bit prog prog-flash clean
gen:
	$(PY) ../docs/notes/fpga_slots_gen.py

sim:
	$(PY) ../docs/notes/fpga_twin_suite.py --seeds 3

$(GEN)/$(ROM).hex: ../roms/$(ROM).bin
	$(PY) -c "import sys; d=open(sys.argv[1],'rb').read(); \
	open(sys.argv[2],'w').write(''.join('%02x\n' % b for b in d))" $< $@

bit: $(BUILD)/dino_$(IMAGE).bit

# yosys reads the ROM images relative to fpga/gen (U9.hex etc.), so it runs there
$(GEN)/dino_system_files.txt:
	$(PY) ../docs/notes/fpga_slots_gen.py

$(BUILD)/dino_$(IMAGE).bit: $(GEN)/dino_system_files.txt $(SRC) $(GEN)/$(ROM).hex versa.lpf
	mkdir -p $(BUILD)
	cd $(GEN) && $(TOOLS)/yosys -q -l $(BUILD)/yosys_$(IMAGE).log \
	  -p "read_verilog -I$(GEN) -DU24_HEX=\"$(ROM).hex\" $(SRC); \
	      synth_ecp5 -top versa_top -json $(BUILD)/dino_$(IMAGE).json"
	$(TOOLS)/nextpnr-ecp5 --um5g-45k --package CABGA381 \
	  --json $(BUILD)/dino_$(IMAGE).json --lpf versa.lpf \
	  --textcfg $(BUILD)/dino_$(IMAGE).config \
	  --log $(BUILD)/nextpnr_$(IMAGE).log -q
	$(TOOLS)/ecppack $(BUILD)/dino_$(IMAGE).config $@

# -c ft2232: the Versa's on-board programmer (the retired twin's flow)
prog: bit
	$(TOOLS)/openFPGALoader -c ft2232 $(BUILD)/dino_$(IMAGE).bit

prog-flash: bit
	$(TOOLS)/openFPGALoader -c ft2232 -f $(BUILD)/dino_$(IMAGE).bit

clean:
	rm -rf $(BUILD)
