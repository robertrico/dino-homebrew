#!/usr/bin/env python3
"""FPGA port: PIN_MAP for every ttl_*.vhd model, `load_design()` (the
structured netlist Tasks 7+ consume), and `emit()` -- the schematic ->
structural VHDL emitter that generates `fpga/gen/*.vhd` (the nine sheet
entities + dino_core.vhd), `fpga/gen/gated_clocks.txt`, and (via `main()`)
`fpga/sim/hex/*.hex`.

This module is also the pin-map derivation tool: `normalize_type()` folds
the family/package spelling variants KiCad's netlist export produces for
the SAME physical part, and `dump_pinmap()` prints, per normalized part
type, every pin number with the pin-function name KiCad reports straight
off the real netlist -- how every PIN_MAP entry here was originally
derived (never from a datasheet -- CLAUDE.md rule 5: netlist-verify, don't
reason from memory -- applied to the FPGA port's own tooling).

CLI (`python3 fpga_gen.py [root] | --dump-pinmap [root]`):
    python3 fpga_gen.py
        Regenerates fpga/gen/*.vhd + fpga/gen/gated_clocks.txt (emit())
        AND fpga/sim/hex/{U9,U15,PROG,RAM}.hex (bin2hex() from roms/*.bin
        -- RAM.hex is always written empty, matching the real board's RAM
        starting blank) -- the ONE command that regenerates every
        artifact-of-record this module owns, the same role
        microcode_gen.py/progrom_gen.py's own `main()` plays for roms/*.bin.
    python3 fpga_gen.py --dump-pinmap [root]
        The original pinmap-dump CLI (dump_pinmap()), unchanged.
An optional `root` positional overrides the default
dino_v0_0_2/dino_v0_0_2.kicad_sch path for either mode.
"""
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_contracts as kc
import kicad_xsheet_audit as kxa

# --- pin maps for the five plain-gate models --------------------------------
# The only hand-written maps in this module -- standard quad/hex DIP-14
# packages, pinout is JEDEC-fixed and identical across '00/'02/'04/'08/'14
# regardless of logic family (LS/HC/F/...). Netlist-derived maps for the
# complex parts (registers, counters, the '382 ALU, bus transceivers) are
# Tasks 3-6's job, built off dump_pinmap()'s output below.
GATE_2IN = lambda: {1:"a1",2:"b1",3:"y1",4:"a2",5:"b2",6:"y2",7:"gnd",
                    8:"y3",9:"a3",10:"b3",11:"y4",12:"a4",13:"b4",14:"vcc"}
PIN_MAP = {
    "74LS00": GATE_2IN(), "74LS08": GATE_2IN(),
    # '02 NOR: outputs on 1,4,10,13
    "74LS02": {1:"y1",2:"a1",3:"b1",4:"y2",5:"a2",6:"b2",7:"gnd",
               8:"a3",9:"b3",10:"y3",11:"a4",12:"b4",13:"y4",14:"vcc"},
    # hex inverters
    "74LS04": {1:"a1",2:"y1",3:"a2",4:"y2",5:"a3",6:"y3",7:"gnd",
               8:"y4",9:"a4",10:"y5",11:"a5",12:"y6",13:"a6",14:"vcc"},
}
PIN_MAP["74HC14"] = dict(PIN_MAP["74LS04"])

# --- pin maps for the four combinational MSI types (Task 3) -----------------
# Built straight from
#   dump_pinmap('dino_v0_0_2/dino_v0_0_2.kicad_sch')
# output -- never a datasheet (rule 5). Two mechanical transforms sit on top
# of the brief's own "lower-case, ~->_n":
#
#  1. Every named pinfunction KiCad exports for these parts comes back as
#     literally "<Name>_<pinnumber>" -- confirmed straight off the raw
#     netlist S-expr, e.g. `(pinfunction "E3_6")` for '138 pin 6,
#     `(pinfunction "DIR_1")` for '245 pin 1. The trailing "_<pinnumber>" is
#     redundant with the dict key, so it's stripped before transcribing.
#  2. Some pins are drawn with an active-low bubble in the KiCad symbol
#     (pin *graphic style* input_low / output_low / inverted) without the
#     pin's name TEXT itself carrying a literal "~{...}" bar. That graphic
#     style is still netlist/schematic-derived fact, not memory -- read
#     straight off the raw pin definitions in each part's lib_symbols block
#     (file:line cited per pin group below) -- so it gets the same "_n"
#     suffix a literal ~{...} pin would get.
#
# '74LS244's pin functions ("1A1", "2Y4", "1~{G}", ...) lead with a
# section-number digit (TI's own 1G/1A1-4/1Y1-4, 2G/2A1-4/2Y1-4 grouping).
# VHDL identifiers can't start with a digit, so those get a mechanical "s"
# prefix ("1a1" -> "s1a1") -- a legality fix, not a renaming choice.
PIN_MAP["74LS138"] = {
    1: "a0", 2: "a1", 3: "a2",
    # E1/E2 drawn "input_low" (bubble), E3 plain "line" (no bubble) --
    # dino_v0_0_2/control_word.kicad_sch lines 1153,1171,1189 (74LS138_1_0
    # pin defs: "(pin input input_low ...(name "E1"", "E2", then
    # "(pin input line ...(name "E3"").
    4: "e1_n", 5: "e2_n", 6: "e3",
    # O0-O7 all drawn "output_low" -- same block, lines 1207-1354.
    7: "o7_n", 8: "gnd", 9: "o6_n", 10: "o5_n", 11: "o4_n", 12: "o3_n",
    13: "o2_n", 14: "o1_n", 15: "o0_n", 16: "vcc",
}
PIN_MAP["74LS157"] = {
    1: "s", 2: "i0a", 3: "i1a", 4: "za", 5: "i0b", 6: "i1b", 7: "zb",
    8: "gnd", 9: "zc", 10: "i1c", 11: "i0c", 12: "zd", 13: "i1d",
    14: "i0d",
    # E (strobe) drawn "inverted" -- dino_v0_0_2/alu.kicad_sch line 3286:
    # "(pin input inverted ...(name "E"".
    15: "e_n", 16: "vcc",
}
PIN_MAP["74LS244"] = {
    # 1~{G}_1 -> 1g_n -> s1g_n; the "1"/"2" prefix is TI's own section
    # (bank) number, present verbatim in dump_pinmap's raw pinfunction text.
    1: "s1g_n", 2: "s1a1", 3: "s2y4", 4: "s1a2", 5: "s2y3", 6: "s1a3",
    7: "s2y2", 8: "s1a4", 9: "s2y1", 10: "gnd", 11: "s2a1", 12: "s1y4",
    13: "s2a2", 14: "s1y3", 15: "s2a3", 16: "s1y2", 17: "s2a4",
    18: "s1y1", 19: "s2g_n", 20: "vcc",
}
PIN_MAP["74LS245"] = {
    1: "dir", 2: "a0", 3: "a1", 4: "a2", 5: "a3", 6: "a4", 7: "a5",
    8: "a6", 9: "a7", 10: "gnd", 11: "b7", 12: "b6", 13: "b5", 14: "b4",
    15: "b3", 16: "b2", 17: "b1", 18: "b0",
    # CE drawn "inverted" -- dino_v0_0_2/mdr.kicad_sch line 2879 (74LS245_1_0
    # pin 19 def: "(pin input inverted ...(name "CE"" at line 2882). KiCad
    # names it CE, not the generic "OE" a datasheet reader might reach for
    # from memory.
    19: "ce_n", 20: "vcc",
}

# --- pin map for the '382 4-bit ALU (Task 4) --------------------------------
# Built straight from
#   dump_pinmap('dino_v0_0_2/dino_v0_0_2.kicad_sch')
# output on dino_v0_0_2/alu.kicad_sch (both symbol Value variants present on
# that sheet, "74F382PC" and "74F382N" -- normalize_type() folds both to
# "74F382", see test_normalize_type_folds_families). Raw dump:
#   1: A1_1   2: B1_2   3: A0_3   4: B0_4   5: S0_5   6: S1_6   7: S2_7
#   8: F0_8   9: F1_9   10: GND_10   11: F2_11   12: F3_12   13: OVR_13
#   14: CN+4_14   15: CN_15   16: B3_16   17: A3_17   18: B2_18   19: A2_19
#   20: VCC_20
# Same trailing "_<pinnumber>" strip as the Task 3 parts. Pin 14's function
# text is "CN+4" -- VHDL identifiers can't contain "+", so it gets the
# mechanical "cn4" spelling (a legality fix, not a renaming choice, same
# class of transform as '244's digit-prefix fix above).
#
# Polarity: every pin in alu.kicad_sch's first 74F382PC_1_0 lib_symbols
# block (lines 126-471) is drawn plain "line" -- no bubble, no
# "inverted"/"input_low"/"output_low" graphic style anywhere on this part,
# e.g. line 126 "(pin input line" for A1 (name at 129), line 342 "(pin
# output line" for OVR (name at 345), line 378 "(pin input line" for CN
# (name at 381). So, unlike '138/'157/'245, NONE of '382's pins get an
# "_n" suffix: S0-S2, CN, and every output are active-high exactly as the
# pin name text reads. Confirmed by grep, not memory (rule 5):
#   grep -n "(pin input line\|(pin output line\|(pin power" \
#       dino_v0_0_2/alu.kicad_sch | sed -n '1,19p'
# all 17 signal pins (+2 power pins) in the first instance read "line",
# zero "_low"/"inverted".
PIN_MAP["74F382"] = {
    1: "a1", 2: "b1", 3: "a0", 4: "b0", 5: "s0", 6: "s1", 7: "s2",
    8: "f0", 9: "f1", 10: "gnd", 11: "f2", 12: "f3", 13: "ovr",
    14: "cn4", 15: "cn", 16: "b3", 17: "a3", 18: "b2", 19: "a2", 20: "vcc",
}

# --- pin maps for the five stateful parts (Task 5) ---------------------------
# Same rule as Tasks 3-4: transcribed straight off
#   dump_pinmap('dino_v0_0_2/dino_v0_0_2.kicad_sch')
# with citations into the schematic files' own lib_symbols blocks (never a
# datasheet -- CLAUDE.md rule 5). Every one of these five types samples its
# datasheet clock/latch pin(s) through the clk_sys edge-detect pattern
# (fpga/ttl/ttl_74ls*.vhd) -- see STATEFUL_TYPES below, which is what tells
# Task 8's emitter to thread clk_sys to these instances.
#
# '74 (dual D flip-flop, dino_v0_0_2.kicad_sch, 74LS74_{1,2,3}_0 lib_symbols
# blocks, lines 2499-2795): KiCad's own pin-function text is the GENERIC
# flip-flop symbol's "R"/"S"/"C"/"D"/"Q" -- literally the SAME five letters
# reused for both sections (distinguished only by pin NUMBER, unlike '244/
# '245 where the section digit is baked into the name text itself, e.g.
# "1A1"). Verified per pin: FF1 R(clear) name "~{R}" at line 2503, number
# "1" at 2510; D at line ~2521 (plain "D", no bubble), number "2"; C drawn
# as KiCad's special "input clock" pin TYPE (not just a pin-name string) at
# line 2536, number "3" -- confirming this is a real clock input, positive-
# edge (no bar/bubble on C); S(preset) name "~{S}" at 2557, number "4" at
# 2564; Q/~{Q} outputs at pins 5/6, no bubble needed transcription beyond
# the literal ~{Q} bar. FF2 mirrors this at pins 8-13: ~{Q}/Q at 8/9, S at
# line 2662/number 2669 (pin "10"), C at pin 11, D at pin 12, R at line
# 2716/number 2723 (pin "13"). R=Reset=the datasheet's active-low CLEAR
# (forces Q=0), S=Set=the datasheet's active-low PRESET (forces Q=1) --
# standard SR nomenclature, not a private renaming. Because the raw KiCad
# text can't disambiguate section 1 vs 2 (both say "R"/"S"/"C"/"D"/"Q"),
# this entry uses the FUNCTIONAL names the brief's own canonical code
# already commits to (pre1_n/clr1_n/clk1/d1/q1/q1_n, mirrored as
# pre2_n/clr2_n/clk2/d2/q2/q2_n for FF2) as the per-section index --
# task-5-brief.md's Step 3 code block IS the interface contract here, not
# a style choice layered on top of it.
PIN_MAP["74LS74"] = {
    1: "clr1_n", 2: "d1", 3: "clk1", 4: "pre1_n", 5: "q1", 6: "q1_n",
    7: "gnd",
    8: "q2_n", 9: "q2", 10: "pre2_n", 11: "clk2", 12: "d2", 13: "clr2_n",
    14: "vcc",
}

# '163 (dino_v0_0_2.kicad_sch, 74LS163_1_0, lines 2100-2390): ~{MR} (line
# 2104 name/2111 number, literal bar -> mr_n) is the SYNCHRONOUS master
# reset -- confirmed against the primary source, not memory: datasheets/
# sn74s163.pdf page 5's own logic diagram is titled "SN54161, SN54163,
# SN74161, SN74163 SYNCHRONOUS 4-BIT COUNTERS" and its own caption reads
# "SN54161, SN74161 ... however, the clear is asynchronous as shown for
# the SN54160, SN74160 decade counters at left" -- i.e. this datasheet
# itself distinguishes the '163/'161 (SYNCHRONOUS clear) from the '160/
# '162 (asynchronous clear) sitting right next to it in the same PDF,
# which is exactly the machine fact CLAUDE.md/the brief hands down for
# this part. CP (clock, line 2122/2129) drawn plain "input line" (no
# clock-type marker here, unlike '74/'273's C pins, but still the
# datasheet's clock per its own name and the SYNCHRONOUS title). ~{PE}
# (line 2248/2255, "parallel enable" -> pe_n, synchronous load) and CEP/
# CET (count-enable-parallel/count-enable-trickle, both plain, active
# high) gate synchronous counting. TC (line 2356/2363, "terminal count")
# is the RCO pin -- same page 5 logic diagram shows its AND gate fed by
# ENT (=CET) and all four Q outputs only (NOT CEP), i.e.
# TC = CET . Q3 . Q2 . Q1 . Q0, a combinational function of the CURRENT
# count and CET, independent of CP -- confirmed by inspecting the
# rendered page image directly (bottom-right AND gate, 5 inputs: ENT plus
# the four QA-QD traces; ENP/CEP is not one of them).
PIN_MAP["74LS163"] = {
    1: "mr_n", 2: "cp", 3: "d0", 4: "d1", 5: "d2", 6: "d3", 7: "cep",
    8: "gnd",
    9: "pe_n", 10: "cet", 11: "q3", 12: "q2", 13: "q1", 14: "q0",
    15: "tc", 16: "vcc",
}

# '169 (dino_v0_0_2/stack_pointer.kicad_sch -- U63-U66, the stack pointer,
# added 2026-08-10). Pin functions read straight off the netlist via
# `python3 fpga_gen.py --dump-pinmap`, never a datasheet (rule 5):
#
#   1: U/~{D}_1   2: CP_2   3-6: P0_3..P3_6   7: ~{CEP}_7   8: GND_8
#   9: ~{PE}_9   10: ~{CET}_10   11-14: Q3_11..Q0_14   15: ~{TC}_15
#   16: VCC_16
#
# Same family pinout as the '163 above, with four differences the model has
# to honour (see fpga/ttl/ttl_74ls169.vhd's header for the full statement):
# pin 1 is the direction LEVEL U/~D and NOT a clear -- this part has no clear
# of any kind; the count enables and TC are ACTIVE LOW where the '163's CEP/
# CET/TC are active high; and terminal count depends on direction (1111 up,
# 0000 down).
#
# The parallel inputs are named P0-P3, not D0-D3. That is the symbol's own
# Philips/NXP naming, matching ~PE ("parallel enable"), and it is what the
# netlist reports -- dino_hardware_growth_plan.md said "D0-D3 on 3-6" and was
# corrected against the symbol on 2026-08-10.
#
# "u_d_n" transcribes `U/~{D}`: the "/" is dropped as a separator and the
# trailing "_n" carries the bar, which sits over the D half only. Consistent
# with cep_n/cet_n/pe_n/tc_n on this same part, where the bar covers the whole
# name.
PIN_MAP["74LS169"] = {
    1: "u_d_n", 2: "cp", 3: "p0", 4: "p1", 5: "p2", 6: "p3", 7: "cep_n",
    8: "gnd",
    9: "pe_n", 10: "cet_n", 11: "q3", 12: "q2", 13: "q1", 14: "q0",
    15: "tc_n", 16: "vcc",
}

# '193 (dino_v0_0_2/program_counter.kicad_sch, 74LS193_1_0, lines
# 2073-2363): DOWN (line 2131/2138) and UP (line 2149/2156) are drawn as
# KiCad's special "input clock" pin TYPE, each its own real clock input --
# confirms the brief's "separate UP/DOWN clock pins" fact off the
# schematic, not memory. ~{LOAD} (2257/2264 -> load_n) and ~{CO}/~{BO}
# (2275/2282, 2293/2300 -> co_n/bo_n, carry/borrow) carry literal bars;
# CLR (2311/2318) has NO bar -- active-HIGH clear, confirmed straight off
# the pin-name text, matching the brief's "asynchronous CLR (active
# high)". A/B/C/D (2077, 2221, 2239, 2329) are the parallel data inputs,
# QA-QD (2113, 2095, 2167, 2185) the outputs. The CO_n/BO_n combinational
# formula (not stated by the brief) was verified against the primary
# source, not assumed: datasheets/sn74ls193.pdf page 2's own logic
# diagram (rendered at 200dpi and inspected directly) shows the ~CO NAND
# gate fed by QA/QB/QC/QD plus the raw UP line, and the ~BO NAND fed by
# ~QA/~QB/~QC/~QD plus the raw DOWN line -- i.e.
# CO_n = NOT(QA and QB and QC and QD and NOT UP)   (low iff count=15, UP low)
# BO_n = NOT(NOT QA and NOT QB and NOT QC and NOT QD and NOT DOWN)  (low iff count=0, DOWN low)
# both purely combinational functions of the CURRENT registered count and
# the live UP/DOWN pin level -- no clk_sys involvement, matching the real
# chip's asynchronous cascading behavior for chaining multiple '193s.
PIN_MAP["74LS193"] = {
    1: "b", 2: "qb", 3: "qa", 4: "down", 5: "up", 6: "qc", 7: "qd",
    8: "gnd",
    9: "d", 10: "c", 11: "load_n", 12: "co_n", 13: "bo_n", 14: "clr",
    15: "a", 16: "vcc",
}

# '273 (dino_v0_0_2/alu.kicad_sch, 74LS273_1_0, lines 3419-3781): ~{Mr}
# (line 3423/3430, literal bar -> mr_n) is ASYNCHRONOUS master reset (no
# clock-type marker on it, and datasheets/sn74ls273.pdf's own part title
# is "OCTAL D-TYPE FLIP-FLOPS WITH CLEAR" -- '273, unlike '163, has no
# synchronous-clear sibling in the same family to draw the distinction
# against, and its MR pin carries none of '163's CP-gating structure).
# Cp (line 3603/3610) drawn as KiCad's "input clock" pin type -- real
# clock, positive edge (no bar). D0-D7/Q0-Q7 are the eight data/output
# pins, plain "line" throughout.
PIN_MAP["74LS273"] = {
    1: "mr_n", 2: "q0", 3: "d0", 4: "d1", 5: "q1", 6: "q2", 7: "d2",
    8: "d3", 9: "q3", 10: "gnd", 11: "cp", 12: "q4", 13: "d4", 14: "d5",
    15: "q5", 16: "q6", 17: "d6", 18: "d7", 19: "q7", 20: "vcc",
}

# '373 (dino_v0_0_2/alu.kicad_sch, 74LS373_1_0, lines 3877-4239): OE (line
# 3878 pin TYPE "input inverted", name "OE" at 3881, number "1" at 3888)
# carries NO literal bar in its name text -- same class of bubble-only
# polarity as '138's E1/E2 and '245's CE (Task 3's precedent) -- so it
# gets the "_n" suffix from the graphic style, not the text: oe_n. O0-O7
# (e.g. line 3899/3906) are drawn "tri_state line" -- KiCad's own
# confirmation these are the tristate outputs, not plain outputs. LE
# (line 4061/4068) is plain "input line", no bar/bubble and no
# clock-type marker -- a LEVEL input (transparent latch enable), not an
# edge-triggered clock, matching the brief's "transparent while LE high"
# fact directly off the symbol's own pin type (KiCad would have drawn it
# "input clock" like '74/'163/'193/'273's CP/C/CLK pins if it were an
# edge input).
PIN_MAP["74LS373"] = {
    1: "oe_n", 2: "o0", 3: "d0", 4: "d1", 5: "o1", 6: "o2", 7: "d2",
    8: "d3", 9: "o3", 10: "gnd", 11: "le", 12: "o4", 13: "d4", 14: "d5",
    15: "o5", 16: "o6", 17: "d6", 18: "d7", 19: "o7", 20: "vcc",
}

# --- pin maps for the three memory parts (Task 6) ---------------------------
# Same rule as Tasks 3-5: transcribed straight off dump_pinmap()'s output
# (never a datasheet for the raw pin function -- CLAUDE.md rule 5).
#   AT28C64B:   dump_pinmap('dino_v0_0_2/microcode.kicad_sch') -- the
#               microcode EEPROM pair (U9/U15, roms/U9.bin U15.bin, 8K).
#   AT28C256:   dump_pinmap('dino_v0_0_2/memory.kicad_sch') -- the program
#               ROM (roms/PROG*.bin, 32K).
#   MCM60256AP: dump_pinmap('dino_v0_0_2/memory.kicad_sch') -- the bench
#               SRAM (32K), already anticipated in STATEFUL_TYPES since
#               Task 5.
# All three are DIP-28, same JEDEC 28-pin JEDEC EEPROM/SRAM pinout family
# (A0-A14 split across pins 1-10/21-26, data bus 11-13/15-19, ~CE/~OE/~WE
# at 20/22/27, GND@14 VCC@28) -- confirmed identical pin-for-pin across all
# three parts by dump_pinmap, not assumed from "they're pin-compatible"
# folklore.
#
# Two mechanical legality transforms, same class as Tasks 3-4's digit-
# prefix/"+"-strip fixes:
#  1. AT28C64B/AT28C256's data-bus pinfunction text is "I/O0".."I/O7" --
#     VHDL identifiers can't contain "/", so it becomes "io0".."io7".
#  2. MCM60256AP's data-bus pinfunction text is already legal ("DQ0".."DQ7"
#     -> "dq0".."dq7", same lowercase-only transform as every other entry).
#
# Bar-name pins (~{CE}/~{OE}/~{WE}) get the usual "_n" suffix. Address pins
# A0-A14 have no bubble in any of the three symbols -- active-high exactly
# as named.
#
# AT28C64B-specific: pins 1 and 26 (A14/A13 on the pin-compatible 32K
# parts) are literally NC on this 8K part -- confirmed straight off the
# netlist (dump_pinmap on microcode.kicad_sch reports "NC_1"/"NC_26" for
# this symbol, not assumed from "8K only needs 13 address bits" reasoning
# alone). They get PIN_MAP name "nc" and, like vcc/gnd, are excluded from
# the VHDL entity's port list (test_vhdl_entities_match_pinmap) -- a
# physically unconnected pin gets no port to wire, the same way a power
# pin does.
#
# AT28C64B (dino_v0_0_2/microcode.kicad_sch, AT28C64B_1_1 lib_symbols
# block starting line 730): NC name/number at lines 734/741 (pin 1), A12
# at 752/759 (pin 2) ... ~{CE} at 1076/1083 (pin 20), ~{OE} at 1112/1119
# (pin 22), NC at 1184/1191 (pin 26), ~{WE} at 1202/1209 (pin 27). All
# pins (except the two power pins) drawn KiCad pin TYPE "input" -- true
# even for the I/O0-7 data pins, which is a schematic-symbol looseness
# (the real chip's I/O pins are tri-state bidirectional; KiCad's AT28C64B
# symbol just doesn't model that), not evidence the model should read
# these as write-capable -- CLAUDE.md rule 4 ("Rico burns the ROMs, the
# rig verifies, it never programs") and the brief's own "async read"
# contract settle that this model drives io0-7 out-only.
PIN_MAP["AT28C64B"] = {
    1: "nc", 2: "a12", 3: "a7", 4: "a6", 5: "a5", 6: "a4", 7: "a3",
    8: "a2", 9: "a1", 10: "a0", 11: "io0", 12: "io1", 13: "io2",
    14: "gnd",
    15: "io3", 16: "io4", 17: "io5", 18: "io6", 19: "io7", 20: "ce_n",
    21: "a10", 22: "oe_n", 23: "a11", 24: "a9", 25: "a8", 26: "nc",
    27: "we_n", 28: "vcc",
}

# AT28C256 (dino_v0_0_2/memory.kicad_sch, AT28C256_1_1 lib_symbols block
# starting line 1728): A14 name at 1732 (pin 1, NC on the '64B above --
# this is the 32K part, so it's a real address line here), A13 at 2182
# (pin 26, likewise). ~{CE} at 2074 (pin 20), ~{OE} at 2110 (pin 22),
# ~{WE} at 2200 (pin 27). Same "input"-type looseness on I/O0-7 as the
# '64B, same "async read only" modeling decision.
PIN_MAP["AT28C256"] = {
    1: "a14", 2: "a12", 3: "a7", 4: "a6", 5: "a5", 6: "a4", 7: "a3",
    8: "a2", 9: "a1", 10: "a0", 11: "io0", 12: "io1", 13: "io2",
    14: "gnd",
    15: "io3", 16: "io4", 17: "io5", 18: "io6", 19: "io7", 20: "ce_n",
    21: "a10", 22: "oe_n", 23: "a11", 24: "a9", 25: "a8", 26: "a13",
    27: "we_n", 28: "vcc",
}

# MCM60256AP (dino_v0_0_2/memory.kicad_sch, MCM60256AP_1_1 lib_symbols
# block starting line 2310): DQ0 drawn KiCad pin TYPE "bidirectional" at
# line 2491/name at 2494 (pin 11) -- genuinely different from the two
# EEPROMs' "input"-typed I/O pins above, confirming this part's data bus
# really is modeled bidirectional in the schematic itself, which is why
# ttl_mcm60256.vhd's dq0-7 ports are `inout` while the ROMs' io0-7 are
# `out`. ~{CE} at 2656 (pin 20), ~{OE} at 2692 (pin 22), A13 at 2764 (pin
# 26), ~{WE} at 2782 (pin 27). Same DIP-28/A0-A14 layout as AT28C256.
PIN_MAP["MCM60256AP"] = {
    1: "a14", 2: "a12", 3: "a7", 4: "a6", 5: "a5", 6: "a4", 7: "a3",
    8: "a2", 9: "a1", 10: "a0", 11: "dq0", 12: "dq1", 13: "dq2",
    14: "gnd",
    15: "dq3", 16: "dq4", 17: "dq5", 18: "dq6", 19: "dq7", 20: "ce_n",
    21: "a10", 22: "oe_n", 23: "a11", 24: "a9", 25: "a8", 26: "a13",
    27: "we_n", 28: "vcc",
}

# The set of part types whose model samples a datasheet clock/latch pin
# against the hidden clk_sys (fpga/ttl/ttl_74ls{74,163,193,273,373}.vhd,
# Task 5; MCM60256AP -- the bench SRAM, this task -- samples WE_n's level
# through clk_sys to commit RAM writes, matching the bench's NAND(WRITE_DIR,
# ~CLK) discipline). Every member's model declares a `clk_sys` port; no
# other PIN_MAP entry in this file does. The two ROMs (AT28C64B/AT28C256)
# are deliberately NOT members -- their read path is purely asynchronous
# (CLAUDE.md rule 4/the brief's own contract: "Rico burns the ROMs, the
# rig verifies, it never programs" -- there is no write path to gate on a
# clock here at all).
STATEFUL_TYPES = {
    "74LS74", "74LS163", "74LS169", "74LS193", "74LS273", "74LS373",
    "MCM60256AP",
}

# Task-13 rework item 2 (synth-rework-brief.md): AT28C64B/AT28C256 gained a
# clk_sys-REGISTERED read (same hidden-sampling-clock contract, so
# memory_libmap can map them to DP16KD blocks instead of falling back to
# flip-flops) -- but neither has a real schematic clock/latch pin to
# sample (their read was always purely async, task-5-brief.md's own
# contract), so they stay OUT of STATEFUL_TYPES itself (whose membership
# test, test_stateful_types_membership, pins the original six-part
# semantic set unchanged). This is the separate, purely-mechanical "does
# this ttl_*.vhd model declare a clk_sys port that needs threading at
# instantiation" set _instance_block actually wires from.
CLK_SYS_TYPES = STATEFUL_TYPES | {"AT28C64B", "AT28C256"}


def bin2hex(src_bin, dst_hex):
    """Convert a raw ROM/RAM image (bytes exactly as burned -- roms/*.bin,
    generated by docs/notes/microcode_gen.py / progrom_gen.py, NEVER
    retyped by hand) into the one-byte-per-line lowercase "%02x" hex text
    format the VHDL-2008 textio loader in ttl_at28c64b.vhd/
    ttl_at28c256.vhd/ttl_mcm60256.vhd reads at elaboration (see each
    file's `load_mem` function -- it reads exactly this format: one
    two-hex-digit line per byte, in address order).

    This is a pure reformatting step -- it does not interpret or validate
    the bytes, mirroring the CLAUDE.md rule that roms/*.bin is the single
    source of truth and nothing downstream re-derives its contents.
    Returns the byte count written (== number of hex lines), so callers
    (sim Makefiles, Task 13's whole-core harness) can sanity-check against
    the expected ROM/RAM size.
    """
    with open(src_bin, "rb") as f:
        data = f.read()
    with open(dst_hex, "w") as f:
        for byte in data:
            f.write(f"{byte:02x}\n")
    return len(data)

# A part number is 74 + an optional family letter code (LS/HC/F/ALS/...) +
# a numeric base part -- package/spin suffixes (N, D, PC, the odd trailing
# digit KiCad sometimes appends) always come AFTER the numeric run, so
# stopping the match at the first non-digit after that run strips them:
#   74LS00     -> 74LS00   (nothing to strip)
#   74LS244N   -> 74LS244  (strip trailing N)
#   74F382PC   -> 74F382   (strip trailing PC)
#   74F382N    -> 74F382   (strip trailing N -- same base part, other spelling)
_PART_RE = re.compile(r"^(74[A-Z]*\d+)")

# Task 7's report flagged two real instances (U36 on program_counter, U51 on
# memory) whose Value field is the bare "7400" (plain-TTL spelling, no "LS"
# letter) -- _PART_RE folds that to normalized type "7400", which has no
# PIN_MAP entry (only "74LS00" does). Netlist-verified (rule 5) this is the
# SAME DIP-14 quad-2-input-NAND pinout as 74LS00 -- dump_pinmap() on both
# U36 and U51 reports the identical pin-function layout as every other
# 74LS00 instance in the design (gnd@7/vcc@14, y1..y4/a1..a4/b1..b4 in the
# same JEDEC positions) -- so it's aliased to "74LS00" post-_PART_RE, not
# given a second hand-written PIN_MAP entry.
TYPE_ALIASES = {"7400": "74LS00"}


def normalize_type(lib_id, value):
    """Fold KiCad's family/package spelling variants down to one canonical
    part type name, e.g. "74LS244N" and "74LS244" both -> "74LS244".

    `value` (the symbol's Value field, what Rico actually put on the
    schematic -- often the precise bench part, e.g. "74LS00") is preferred.
    `lib_id` ("<lib>:<part>", from the netlist's `(libsource (lib ..)(part
    ..))`) is the fallback for the rare case of value being blank, e.g. a
    library part with no Value override.
    """
    v = (value or "").strip()
    if not v:
        v = lib_id.split(":", 1)[-1] if lib_id else ""
    v = v.upper()
    m = _PART_RE.match(v)
    t = m.group(1) if m else v
    return TYPE_ALIASES.get(t, t)


def dump_pinmap(root):
    """Print, per normalized part type, every pin number seen in the
    netlist with the pin-function name(s) KiCad reports for it. Derived
    straight off `kicad_xsheet_audit.export_netlist()` +
    `kicad_contracts.parse_with_pinfunction()` -- no hand-typed datasheet
    pinouts beyond the five plain-gate maps above. This is how Tasks 3-6
    build the complex-part maps: run this, read the printed pin functions,
    transcribe them into a PIN_MAP entry (never from memory -- rule 5).

    Returns the {type: {pin: {pinfunction, ...}}} structure it prints, for
    callers that want it programmatically.
    """
    netfile = kxa.export_netlist(root)
    try:
        values, nets = kc.parse_with_pinfunction(netfile)
    finally:
        os.unlink(netfile)

    by_type = defaultdict(lambda: defaultdict(set))
    for _net_name, nodes in nets:
        for ref, pin, pinfunction, _pintype in nodes:
            value = values.get(ref)
            if value is None:
                continue
            t = normalize_type("", value)
            by_type[t][pin].add(pinfunction or "")

    def pin_key(p):
        return (0, int(p)) if p.isdigit() else (1, p)

    for t in sorted(by_type):
        print(t)
        for pin in sorted(by_type[t], key=pin_key):
            fns = ", ".join(sorted(by_type[t][pin])) or "?"
            print(f"  {pin}: {fns}")
    return by_type


# --- structured netlist: instance grouping + sheet assignment (Task 7) ------
# `load_design()` is the single data structure Tasks 8+ consume: every
# component in the netlist, grouped by reference (multi-unit gate symbols
# collapse to one Instance with every unit's pins merged -- see the "nets
# already flatten units" note below), with its normalized part type, the
# sheet it lives on, and each pin's netname; plus, per sheet, the boundary
# signals `kicad_contracts.build_contracts()` already derives, reshaped from
# display strings into (name, direction, width) triples a VHDL port clause
# can use directly.

# The ten sheets of dino_v0_0_2's hierarchy: the root schematic plus the
# nine sub-sheets it owns. Confirmed against kicad-cli's own netlist export
# `(design (sheet (name ..)(source ..)))` list, which enumerates exactly
# 1 root + 9 sub-sheets (rule 5 -- run the tool):
#   python3 -c "import sys;sys.path.insert(0,'docs/notes');\
#   import kicad_xsheet_audit as kxa; f=kxa.export_netlist(\
#   'dino_v0_0_2/dino_v0_0_2.kicad_sch'); print(open(f).read()[:3000])"
# Tokens are each sheet's own `(property (name "Sheetfile")(value "..."))`
# text (as read per-component off the SAME netlist export -- see
# `_ref_sheetfiles()`) with the ".kicad_sch" extension stripped, e.g.
# "program_counter.kicad_sch" -> "program_counter". The root sheet's own
# Sheetfile is "dino_v0_0_2.kicad_sch" (KiCad stamps every root-level
# component with the top file's own basename, verified directly off U61's
# comp block); it is spelled "root" here instead, so this module's sheet
# tokens agree with kicad_contracts.py's own `short()` convention -- both
# modules must land on the SAME token space, since `sheet_ports` below is
# keyed through this exact mapping and Task 8 joins it against `instances`.
# "stack_pointer" added 2026-08-10 (U63-U66 '169 + U67/U68 '245 + U69 '08 --
# the 16-bit stack pointer). Two OTHER lists must gain it too and neither is
# derived from this one: run_cocotb_ladder.sh's SIM_MODULES and
# fpga/synth/check_images.py's GEN_SHEETS, both hand-mirrored by this repo's
# own "no Python in a shell script's critical path" convention.
SHEETS = (
    "root", "program_counter", "microcode", "control_word", "mdr",
    "registers_a_b", "mar", "memory", "alu", "input_output", "stack_pointer",
)


@dataclass
class Instance:
    ref: str
    type: str
    sheet: str
    pins: dict = field(default_factory=dict)   # pin number (int) -> netname


@dataclass
class PortSig:
    name: str
    direction: str   # "in" | "out" | "inout"
    width: int


class Design:
    def __init__(self):
        self.instances = {}      # ref -> Instance
        self.sheet_ports = {}    # sheet token -> [PortSig, ...]


def _sheet_token(sheetfile_basename, root_basename):
    """"program_counter.kicad_sch" -> "program_counter"; the root sheet's
    own Sheetfile ("dino_v0_0_2.kicad_sch", matching whatever `root` was
    passed to `load_design`) -> "root" (see SHEETS comment above)."""
    if sheetfile_basename == root_basename:
        return "root"
    return os.path.splitext(sheetfile_basename)[0]


# Per-component sheet assignment: each `(comp (ref "X") ...)` block in the
# netlist export carries its own `(property (name "Sheetfile")(value
# "Y.kicad_sch"))` -- confirmed straight off the raw export (rule 5): U1's
# block reads `(ref "U1")` ... `(property (name "Sheetfile")(value
# "program_counter.kicad_sch"))`, and root-level U61's block reads the same
# property with value "dino_v0_0_2.kicad_sch". `kicad_contracts
# .parse_with_pinfunction()` doesn't expose this field (it only keeps
# ref->value and the per-net node lists), so it's pulled directly off the
# raw export text here, non-greedy up to the NEXT `(comp` so a chip with no
# Sheetfile property (shouldn't happen -- every comp in this design has one,
# confirmed by the count check in `load_design`) doesn't accidentally match
# a later component's property instead.
_COMP_SHEETFILE_RE = re.compile(
    r'\(comp\s*\(ref "([^"]+)"\)(?:(?!\(comp\s).)*?'
    r'\(name "Sheetfile"\)\s*\(value "([^"]+)"\)', re.S)


def _ref_sheetfiles(netfile_text):
    """ref -> Sheetfile basename, one entry per `(comp ...)` block."""
    return dict(_COMP_SHEETFILE_RE.findall(netfile_text))


# A bus bit's netlist label is a plain trailing-digit suffix on a base name
# ("W0".."W7", "CW0".."CW15", "MDR0".."MDR7", ...) -- the same convention
# kicad_contracts.compress() collapses into a display range ("W0-7"). This
# mirrors that grouping but returns the WIDTH as data (a VHDL port needs a
# number, not range text), and groups by shared base name regardless of
# whether the numbered bits are contiguous -- a sparse or non-contiguous
# group still needs exactly one port declaration sized to how many distinct
# wires it actually has.
#
# Composite alias labels (kicad_contracts.build_contracts's cross-sheet
# label merge, e.g. "CW9=SA2", "M15=ROM_EN") must NOT go through this
# regex: they carry a real second identity downstream (a specific SA bit,
# the ROM-enable alias) that the trailing-digit strip would silently
# destroy -- "CW9=SA2"/"CW10=SA1"/"CW11=SA0" would all collapse to base
# "CW*=SA" with the bit number gone, and a colliding pair of composites
# would silently fuse into a fake multi-bit bus with no way for Task 8 to
# recover which SA bit a port maps to. Any label containing "=" is a
# composite (build_contracts.alias_note always builds it as
# "=".join(sorted(group))) and is excluded from bus-grouping on that basis,
# not on its trailing character.
_BUS_SUFFIX_RE = re.compile(r"^(.*?)(\d+)$")


def _bus_ports(pairs, direction):
    """[(label, others), ...] (one IN/OUT/BIDIR list from build_contracts)
    -> [PortSig(name, direction, width), ...], one PortSig per bus (or per
    lone signal, width 1)."""
    groups = defaultdict(set)
    singles = []
    for label, _others in pairs:
        m = None if "=" in label else _BUS_SUFFIX_RE.match(label)
        if m:
            groups[m.group(1)].add(int(m.group(2)))
        else:
            singles.append(label)
    ports = [PortSig(base, direction, len(bits)) for base, bits in groups.items()]
    ports += [PortSig(label, direction, 1) for label in singles]
    return ports


def load_design(root):
    """Build the structured `Design` Task 8's emitter consumes: every
    netlist component as one merged `Instance` (multi-unit gate symbols
    collapse to a single reference automatically -- the netlist's `(nets
    ...)` section already lists every pin by its real number regardless of
    which schematic UNIT it belongs to, so accumulating pins per ref across
    every net merges units for free, no unit-table bookkeeping needed), plus
    each sheet's boundary signals from `kicad_contracts.build_contracts()`.
    """
    netfile = kxa.export_netlist(root)
    try:
        netfile_text = open(netfile).read()
        values, nets = kc.parse_with_pinfunction(netfile)
        ref_sheetfiles = _ref_sheetfiles(netfile_text)
    finally:
        os.unlink(netfile)

    root_basename = os.path.basename(root)
    design = Design()

    for ref, value in values.items():
        sheetfile = ref_sheetfiles.get(ref)
        if sheetfile is None:
            raise ValueError(
                f"{ref}: no Sheetfile property found in the netlist export "
                f"-- can't assign it to a sheet")
        design.instances[ref] = Instance(
            ref=ref, type=normalize_type("", value),
            sheet=_sheet_token(sheetfile, root_basename))

    for name, nodes in nets:
        netname = kxa.leaf(name)
        for ref, pin, _pinfunction, _pintype in nodes:
            inst = design.instances.get(ref)
            if inst is None:
                continue
            try:
                pin_num = int(pin)
            except ValueError:
                pin_num = pin
            inst.pins[pin_num] = netname

    contracts = kc.build_contracts(root)
    sheet_files = kc.sheet_name_map(root)
    for sheetpath, c in contracts.items():
        sch_file = sheet_files.get(sheetpath)
        if sch_file is None:
            continue
        token = _sheet_token(os.path.basename(sch_file), root_basename)
        design.sheet_ports[token] = (
            _bus_ports(c["IN"], "in") + _bus_ports(c["OUT"], "out")
            + _bus_ports(c["BIDIR"], "inout"))

    return design


# --- Task 8: boundary/exclusion table + VHDL emission -----------------------
# Everything below is netlist-VERIFIED (rule 5), not reasoned from the
# schematic drawings: every fact cited in a comment here was checked by
# running the same query pattern as the module docstring's canonical
# command against dino_v0_0_2/dino_v0_0_2.kicad_sch via load_design(),
# during this task's own investigation (see task-8-report.md for the exact
# queries and their output).

# Part types with no PIN_MAP entry that are dropped whole -- no VHDL entity
# is ever instantiated for one of these refs. Confirmed exhaustive against
# every non-PIN_MAP type in the 154-component histogram (Task 7's report):
# these 8 types and nothing else. Each type's disposition:
#   0.1ΜF, 10ΜF   bypass/debounce caps -- verified every 0.1ΜF instance's
#                 both pins are in {"GND", "+5V"} only (no other net rides
#                 on a decoupling cap), so dropping one strands nothing.
#   10KΩ          pull-ups (R1: reset debounce; R17-24: DIP-switch pull-ups)
#                 -- the far (non-power) end of every one is a net some
#                 REAL chip already reads directly (Net-(C1-Pad1) is read by
#                 U56.1; IS0-7 are read by SWITCH-GATE1) so dropping the
#                 resistor stays safe without any net-merge step.
#   330Ω          LED series limiters (R9-16) -- far end is OB0-7, already
#                 a live cross-sheet bus (registers_a_b -> input_output);
#                 dropping the resistor+LED strands nothing since ob_led
#                 taps OB directly, never touching the now-gone LED net.
#   4MHZ          Y1, the CXO oscillator -- see BOUNDARY_INPUTS/clk4m_y1.
#   LED           D1-D8 -- anode net is OB{n} (see 330Ω above); cathode is
#                 GND. No VHDL model exists for an LED; it is a pure sink.
#   RESET_BTN     SW2 -- see BOUNDARY_INPUTS/btn_reset_n.
#   SW_DIP_X08    SW1 -- see BOUNDARY_INPUTS/dip_sw (via INPUT_OUTPUT_EXTRA_PORT).
EXCLUDED_TYPES = frozenset({
    "0.1ΜF", "10ΜF", "10KΩ", "330Ω", "4MHZ", "LED", "RESET_BTN", "SW_DIP_X08",
})

# Instance INPUT pins netlisted "unconnected-..." (KiCad's own marker for a
# floating pin) that are allowed to stay floating, each tied to an explicit
# safe value instead of erroring. Found by intersecting every non-excluded
# instance's pins against the "unconnected-" prefix, then filtering to only
# the pins whose PIN_MAP name is an INPUT on the real ttl_*.vhd model (an
# unconnected OUTPUT is fine as-is -- it emits `open`, no entry needed
# here). Every one of these is an unused whole gate/bank within an
# otherwise-used multi-gate package (confirmed per ref below by checking
# that pin's OWN output is unconnected too, i.e. genuinely dead, not just
# an input the design forgot to wire):
#   U17 (74LS244, microcode)  bank-2 A inputs 1~{G}/1A1-4 unused (2Y1-4
#                              outputs also unconnected -- whole bank dead)
#   U20 (74LS163, root)       D0-D3 unused -- PE_n is tied permanently
#                              inactive (this counter never parallel-loads)
#   U22 (74LS02, mdr)         gates 3+4 of the quad-NOR unused (Y3/Y4
#                              outputs also unconnected)
#   U37 (74LS04, mdr)         inverters 4-6 of the hex-inverter unused
#   U39 (74LS00, mdr)         gate 4 of the quad-NAND unused
# Tie value '0' is arbitrary (the corresponding output is always open/
# unused too, so the tie can never be observed) -- chosen for uniformity,
# not because '0' has any electrical significance here.
NC_ALLOWED = {
    ("U17", 11): "0", ("U17", 13): "0", ("U17", 15): "0", ("U17", 17): "0",
    ("U20", 3): "0", ("U20", 4): "0", ("U20", 5): "0", ("U20", 6): "0",
    ("U22", 8): "0", ("U22", 9): "0", ("U22", 11): "0", ("U22", 12): "0",
    ("U37", 9): "0", ("U37", 11): "0", ("U37", 13): "0",
    ("U39", 12): "0", ("U39", 13): "0",
}

# normalized PIN_MAP type -> (VHDL entity name, fpga/ttl/<file>.vhd basename
# minus extension -- identical string for every part here). Hand-listed
# rather than derived from "ttl_" + type.lower() because MCM60256AP's file
# is ttl_mcm60256.vhd (no trailing "AP") -- the one exception; everything
# else IS mechanically "ttl_" + lower(type). Kept as an explicit table
# (matching test_vhdl_entities_match_pinmap's own file list) so a future
# renamed .vhd file breaks loudly here instead of silently mis-resolving.
TTL_ENTITY = {
    "74LS00": "ttl_74ls00", "74LS02": "ttl_74ls02", "74LS04": "ttl_74ls04",
    "74HC14": "ttl_74hc14", "74LS08": "ttl_74ls08", "74LS138": "ttl_74ls138",
    "74LS157": "ttl_74ls157", "74LS244": "ttl_74ls244", "74LS245": "ttl_74ls245",
    "74F382": "ttl_74f382", "74LS74": "ttl_74ls74", "74LS163": "ttl_74ls163",
    "74LS169": "ttl_74ls169",
    "74LS193": "ttl_74ls193", "74LS273": "ttl_74ls273", "74LS373": "ttl_74ls373",
    "AT28C64B": "ttl_at28c64b", "AT28C256": "ttl_at28c256",
    "MCM60256AP": "ttl_mcm60256",
}

# Per-type PIN_MAP pin names that are this part's datasheet clock/latch
# pin(s) -- the ones the model samples through the clk_sys edge-detect (or,
# for MCM60256AP, level-sample) pattern. Used only to build
# fpga/gen/gated_clocks.txt (every net driving one of these pins on a real
# instance, except the literal net "CLK" itself and power ties).
CLOCK_LATCH_PINS = {
    "74LS74": {"clk1", "clk2"}, "74LS163": {"cp"}, "74LS169": {"cp"},
    "74LS193": {"up", "down"},
    "74LS273": {"cp"}, "74LS373": {"le"}, "MCM60256AP": {"we_n"},
}

# The three memory-model sheets' per-instance generics. addr_bits is the
# task's own contract (8K AT28C64B -> 13, 32K AT28C256/MCM60256AP -> 15);
# init_file defaults point at sim/hex/<ref>.hex, generated from the real
# burned images via bin2hex() (U9.bin/U15.bin/PROG.bin -- roms/*.bin, never
# hand-retyped) plus one all-zero RAM.hex for the RAM (blank on the real
# board too). These paths are relative to `fpga/` -- the ONE documented run
# directory for anything that elaborates/simulates dino_core or any of its
# generated sub-entities (`cd fpga && ghdl -a ... gen/*.vhd`, the
# elaboration gate; `fpga/gen/Makefile`'s cocotb runs, same convention as
# `fpga/ttl/Makefile`/`fpga/spike/Makefile`) -- NOT repo-root-relative, so
# a bare "fpga/sim/hex/U9.hex" default would resolve to the WRONG file
# (fpga/fpga/sim/hex/U9.hex) from that directory. GHDL's own textio
# `file_open` has no implicit search path -- it reads exactly the string
# handed to it, relative to whatever the simulation's OWN CWD is at run
# time, not at analysis/elaboration time (`ghdl -e` never opens the file
# at all; only actually RUNNING the elaborated design does), which is
# exactly why a wrong-but-syntactically-valid path is invisible to the
# elaboration gate and needs its own covering test instead
# (test_dino_core_regen_hex_loads_from_documented_rundir in
# fpga/gen/test_regen.py, run from `fpga/` via cocotb).
# These are DEFAULTS only -- every consumer (Task 9+ testbenches, Task 13
# synthesis) is expected to override per-instance via a `-g`/generic-map
# value, exactly like fpga/ttl/Makefile's existing SIM_ARGS pattern for the
# standalone model tests -- but the DEFAULT must still be a real, correct,
# loadable path, not just a placeholder string, since an override-less run
# (or a test that forgets to override) silently gets a zero-filled ROM
# instead of a loud failure otherwise (see the missing-file behavior note
# on ttl_at28c64b.vhd's `load_mem`, a fpga/ttl-owned file outside this
# task's scope to change).
MEMORY_INSTANCES = {
    "microcode": [
        ("U9", 13, "sim/hex/U9.hex"),
        ("U15", 13, "sim/hex/U15.hex"),
        # U23, the third microcode EEPROM (CW16-23), schematic 2026-08-10.
        # Same shared {IR[7:0],T[3:0]} address as U9/U15, same 8K part, so
        # addr_bits is 13 like theirs. The image is all-0xFF today and that
        # is CORRECT, not a placeholder: every field in the third word is
        # polarised so a blank third ROM reproduces the 16-bit machine
        # exactly (microcode_gen.THIRD_INERT).
        ("U23", 13, "sim/hex/U23.hex"),
    ],
    "memory": [
        ("U24", 15, "sim/hex/PROG.hex"),
        ("U26", 15, "sim/hex/RAM.hex"),
    ],
}

# dino_core-level top-port <- root-local net (post-exclusion, the ONE
# surviving real-chip pin the dropped boundary component used to drive).
# Netlist-verified: Y1 pin 8 (its OUT pin) and U20 pin 2 (cp, the CLKIN
# pin CLAUDE.md names) are the SAME net "Net-(U20-CP)"; SW2/R1/C1's shared
# net "Net-(C1-Pad1)" is independently read by U56 pin 1 (the debounce
# Schmitt-trigger input) with no other non-excluded consumer.
BOUNDARY_INPUTS = [
    ("clk4m_y1", 1, ["Net-(U20-CP)"]),
    ("btn_reset_n", 1, ["Net-(C1-Pad1)"]),
]

# input_output's SW1 (SW_DIP_X08) is EXCLUDED but its 8 data nets (IS0-7)
# are read directly by SWITCH-GATE1 (74LS244) with no other non-excluded
# consumer on that sheet -- and this signal never crosses a sheet boundary
# in the original board-based design (build_contracts's Design.sheet_ports
# has no IS-anything entry), so it needs an EXTRA port on input_output's
# own entity (beyond what sheet_ports declares) plus a matching dino_core
# top-level port threaded straight through.
INPUT_OUTPUT_EXTRA_PORT = ("dip_sw", "in", 8, [f"IS{i}" for i in range(8)])

# dino_core-level output <- an existing internal signal, tapped without
# disturbing anything upstream of it (no component is excluded to make
# these ports exist -- OB and the HALT composite are both already real,
# driven nets; ob_led/halt just read them too).
#   ob_led: OB0-7 (registers_a_b -> input_output, already a live 8-bit
#           cross-sheet bus -- the LED anode nets Net-(D1-A).. were only
#           ever downstream of OB{n} through the now-dropped 330R+LED
#           pair, so OB itself is the FPGA-native "LED anode net").
#   halt:   the CW15=HALT composite (microcode's CW15 -> root's HALT net,
#           read at U61 pin 5/6, the consumer end CLAUDE.md's "END and
#           HALT never move" section names) -- END (CW12, U61 pin 3) is
#           the T-state-clear tap, not exposed as its own top port since
#           the interface only names `halt`.
BOUNDARY_OUTPUTS = [
    ("ob_led", 8, "OB"),
    ("halt", 1, "CW15=HALT"),
]

_GENERATED_MARKER = "-- GENERATED by fpga_gen.py - DO NOT EDIT"


def _sanitize_name(raw):
    """Deterministic, stateless net-name -> VHDL-identifier text transform.
    The brief's own rules (`~`->`_n_`, `/`->`_`, `=`->`_eq_`, leading digit
    -> `n_` prefix) plus the extra characters real KiCad-generated net text
    actually contains in this design (netlist-verified, not assumed):
    anonymous "Net-(U15-A0)"/"unconnected-(...)"-style names carry `-`, `(`,
    `)`; bar-notation nets carry `{`/`}` around the bar text (e.g.
    "~{RESET}"). `{`/`}` are stripped outright (pure KiCad bar-delimiter
    syntax, no signal beyond what `~` already encodes); `-`/`(`/`)` fold to
    `_` alongside `/` since they play the identical role (an anonymous
    KiCad-assigned separator). Doubled/leading/trailing underscores are
    collapsed/stripped afterward -- this is also what turns "~{RESET}"'s
    literal "_n_RESET" (leading underscore, illegal as a VHDL basic
    identifier's first character) into legal "n_RESET" for free, the same
    fix leading-digit prefixing exists for.
    """
    s = raw
    for ch in "{}":
        s = s.replace(ch, "")
    s = s.replace("~", "_n_")
    for ch in "/-()":
        s = s.replace(ch, "_")
    s = s.replace("=", "_eq_")
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "net"
    if s[0].isdigit():
        s = "n_" + s
    return s.lower()


class _Scope:
    """Per-generated-file sanitized-identifier namespace: sanitizes on
    first use, memoizes so the SAME raw name always returns the SAME
    identifier, and hard-fails (naming both offending raw names) if two
    DIFFERENT raw names ever sanitize to the same identifier within this
    one file's scope -- the brief's "collision check that FAILS loudly on
    duplicates." `clk_sys` (and any other fixed identifier every generated
    file uses, e.g. dino_core's own boundary port names) is pre-registered
    so an accidental net-name collision against it is caught the same way.
    """
    def __init__(self, reserved=()):
        self._by_raw = {}
        self._by_sanitized = {}
        for name in reserved:
            self._by_raw[name] = name
            self._by_sanitized[name] = name

    def name(self, raw):
        if raw in self._by_raw:
            return self._by_raw[raw]
        s = _sanitize_name(raw)
        prev = self._by_sanitized.get(s)
        if prev is not None and prev != raw:
            raise ValueError(
                f"net-name collision: {raw!r} and {prev!r} both sanitize "
                f"to {s!r}")
        self._by_sanitized[s] = raw
        self._by_raw[raw] = s
        return s


def _vhdl_type(width):
    return "std_logic" if width == 1 else f"std_logic_vector({width - 1} downto 0)"


def _composite_locals(design):
    """{(sheet, composite_port_name): local_raw_net} for every '='-composite
    port in Design.sheet_ports, e.g. ("alu", "CW9=SA2") -> "SA2". Resolved
    by searching that sheet's OWN non-excluded instance pins for a net
    matching one of the composite's '='-split parts -- netlist-verified
    (rule 5) this resolves cleanly (exactly one match) for all 7 real
    composites in this design (task-8-report.md has the full table); a
    sheet where NO local instance carries either part is a hard error
    (would silently produce an unwired composite port otherwise).
    """
    out = {}
    for sheet in SHEETS:
        for p in design.sheet_ports.get(sheet, ()):
            if "=" not in p.name:
                continue
            parts = set(p.name.split("="))
            local = None
            for ref, inst in design.instances.items():
                if inst.sheet != sheet or inst.type in EXCLUDED_TYPES:
                    continue
                hit = next((n for n in inst.pins.values() if n in parts), None)
                if hit:
                    local = hit
                    break
            if local is None:
                raise ValueError(
                    f"{sheet}: composite port {p.name!r} has no local net "
                    f"matching either half on this sheet")
            out[(sheet, p.name)] = local
    return out


_TTL_DIR_CACHE = {}


def _ttl_port_dirs(type_):
    """{pin_name: "in"|"out"|"inout"} straight off fpga/ttl/ttl_<x>.vhd's own
    entity port clause -- the model's REAL declared direction, which is not
    always mechanically derivable from KiCad's own pintype (e.g. the two
    EEPROM models' io0-7 are "out" in VHDL despite KiCad drawing them
    "input" -- see PIN_MAP["AT28C64B"]'s comment). Cached per type; same
    regex scoping as test_vhdl_entities_match_pinmap (docs/notes/
    test_fpga_gen.py) so a local-procedure parameter list inside a model's
    architecture body can never false-positive as an entity port.
    """
    if type_ in _TTL_DIR_CACHE:
        return _TTL_DIR_CACHE[type_]
    fname = TTL_ENTITY[type_] + ".vhd"
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "..", "fpga", "ttl", fname)
    src = open(path).read()
    m = re.search(r"\bport\s*\((.*?)\)\s*;\s*end\s+entity", src, re.S)
    dirs = {}
    for pm in re.finditer(r"^\s*(\w+)\s*:\s*(in|out|inout)\b", m.group(1), re.M):
        dirs[pm.group(1)] = pm.group(2)
    _TTL_DIR_CACHE[type_] = dirs
    return dirs


def _port_locals(sheet, name, width, composite_locals):
    """Canonical port name -> the list of THIS sheet's own local raw net
    names it corresponds to, one per bit (or a single-element list for a
    width-1 port). Composite ('='-named) ports resolve through
    `composite_locals`; every other port's local net names are either the
    plain name itself (width 1) or `f"{name}{i}"` for i in 0..width-1 --
    netlist-verified (rule 5) contiguous 0-based for every real bus in this
    design (task-8-report.md's bit-index table), the same convention
    `_bus_ports` used to group them coming in.
    """
    if "=" in name:
        return [composite_locals[(sheet, name)]]
    if width == 1:
        return [name]
    return [f"{name}{i}" for i in range(width)]


def _sheet_bindings(design, sheet, composite_locals, extra=()):
    """(ports, net_to_sig) for one sheet (any of SHEETS, including "root",
    which is never its own entity but still needs this to resolve its own
    instances' pins against the shared dino_core-level signals).
    ports: [(name, direction, width), ...] -- design.sheet_ports[sheet]
    plus any `extra` (name, direction, width, locals) entries (only
    input_output's INPUT_OUTPUT_EXTRA_PORT today -- a port this sheet needs
    that never crossed a sheet boundary in the original board-based design,
    so build_contracts never put it in sheet_ports).
    net_to_sig: {local_raw_net: (canonical_port_name, bit_index_or_None)} --
    how an instance pin's raw net resolves to a port/signal reference.
    """
    ports = []
    net_to_sig = {}
    for p in design.sheet_ports.get(sheet, ()):
        locs = _port_locals(sheet, p.name, p.width, composite_locals)
        direction = _effective_direction(design, sheet, locs, p.direction)
        ports.append((p.name, direction, p.width))
        for i, loc in enumerate(locs):
            net_to_sig[loc] = (p.name, None if p.width == 1 else i)
    for name, direction, width, locs in extra:
        ports.append((name, direction, width))
        for i, loc in enumerate(locs):
            net_to_sig[loc] = (name, None if width == 1 else i)
    return ports, net_to_sig


def _effective_direction(design, sheet, locals_for_port, declared_direction):
    """The REAL VHDL port mode this sheet needs for a port, derived from
    every local (non-excluded) instance pin actually touching one of
    `locals_for_port` -- NOT simply trusted from build_contracts's own
    IN/OUT/BIDIR classification (`Design.sheet_ports`'s `.direction`).

    Why this is necessary (found on review, netlist-verified): KiCad draws
    EVERY pin of a '245 transceiver "tri_state" regardless of which way
    its own DIR pin actually points at runtime -- build_contracts's
    `has_in` check only counts literal pintype "input", so it is blind to
    a sheet that reads a bus back through one of its OWN '245s in the
    opposite direction from where ANOTHER of its own '245s drives it.
    program_counter is exactly this case: U13/U14 drive `M` from the PC's
    own count (PC_MAR_MUX enabled, dir B->A) while U11/U12 read `M` INTO
    PCD for a JMP/JNZ load (PC_LOAD enabled, dir A->B) -- both pairs'
    KiCad pintype is "tri_state", so build_contracts reported plain OUT,
    but the real ttl_74ls245.vhd model declares a0-7/b0-7 `inout`
    unconditionally (electrically correct: the same physical pin IS
    bidirectional, DIR/CE only select which way it's driving RIGHT NOW).

    The trigger is specifically a LOCAL PIN DECLARED `inout` in its own
    ttl_*.vhd model (a '245 a/b pin, or MCM60256AP's dq) -- NOT merely
    "some local pin reads this net while another drives it". That weaker
    condition is NOT sufficient reason to force `inout`: VHDL-2008 (this
    project's `--std=08` throughout) lifted VHDL-93's restriction on
    reading a mode-`out` port from within its own architecture, so a
    single real driver (e.g. alu's FLAG_Z, driven once by U49's plain
    `out` q1 pin and also read locally by U48's plain `in` mux-select
    pin) is completely correctly `out` -- forcing `inout` there would be
    over-broad and wrong (confirmed by first implementing the broader
    rule, seeing FLAG_Z incorrectly flip, and narrowing to this precise
    condition). `inout` is specifically an ELECTRICAL fact (multiple
    possible drivers whose resolved value must cross the entity boundary
    in both directions), not a mere internal-readability one -- exactly
    what a genuinely bidirectional MODEL PIN signals and a plain `out`+
    `in` pair does not.
    """
    locs = set(locals_for_port)
    for inst in _real_instances(design, sheet):
        if not (set(inst.pins.values()) & locs):
            continue
        pin_map = PIN_MAP[inst.type]
        dirs = _ttl_port_dirs(inst.type)
        for pin_num, raw_net in inst.pins.items():
            if raw_net not in locs:
                continue
            pname = pin_map.get(pin_num)
            # Task-13 rework item 1: no ttl_*.vhd model declares a literal
            # `inout` port any more (ghdl-yosys-plugin severs internal nets
            # touching a sub-instance inout port at synthesis import) --
            # ttl_74ls245.vhd's a/b pins and ttl_mcm60256.vhd's dq pins are
            # now split into `<pin>_i : in` + `<pin>_o : out` pairs. The
            # SAME genuinely-bidirectional-model-pin trigger this function
            # has always used still applies; it's just detected as "both
            # halves of the split pair exist" instead of a single `inout`
            # port mode.
            if pname and f"{pname}_i" in dirs and f"{pname}_o" in dirs:
                return "inout"
    return declared_direction


def _instance_block(scope, inst, net_to_sig, generic_map_lines, gated,
                     ports_by_name=None):
    """One `<ref> : entity work.ttl_<type> [generic map (...)] port map
    (...);` block (as a single text block) for `inst`, plus side-effect:
    appends every gated-clock net this instance's clock/latch pin(s)
    resolve to onto `gated` (module-level accumulation across every sheet;
    the caller dedupes/sorts once at the very end).

    `ports_by_name`: {canonical_port_name: direction} for the CURRENT
    entity's OWN declared boundary ports (a sub-sheet's ports list) --
    omitted/{} for dino_core-level calls (root's own instances, and
    dino_core's internal cross-sheet wiring), which never re-exports a
    bidirectional net as a split port of its own: dino_core is the top,
    so a shared net collapses to one plain, resolved signal instead (see
    the sub-sheet-instantiation loop in emit() below). A canon name whose
    `ports_by_name` direction is "inout" means BOTH `<name>_i` and
    `<name>_o` are real identifiers at THIS scope (a genuinely
    bidirectional net crossing this entity's own boundary); anything else
    -- a plain in/out port, or a raw net with no net_to_sig entry at all
    (purely local to this scope) -- uses a single plain identifier for
    both the sensed and driven side, exactly matching what a real
    resolved std_logic wire (or the pre-Task-13-rework `inout` port) gave
    for free.
    """
    entity = TTL_ENTITY[inst.type]
    dirs = _ttl_port_dirs(inst.type)
    pin_map = PIN_MAP[inst.type]
    clock_pins = CLOCK_LATCH_PINS.get(inst.type, ())
    ports_by_name = ports_by_name or {}
    lines = []
    if inst.type in CLK_SYS_TYPES:
        lines.append("clk_sys => clk_sys")
    for pin_num in sorted(inst.pins, key=lambda p: (isinstance(p, str), p)):
        if pin_num not in pin_map:
            raise ValueError(
                f"{inst.ref} ({inst.type}): no PIN_MAP entry for pin "
                f"{pin_num!r} -- a missing mapping is a hard failure, not "
                f"a warning (a silently dropped pin is a silently dropped "
                f"net)")
        pin_name = pin_map[pin_num]
        if pin_name in ("vcc", "gnd", "nc"):
            continue
        raw_net = inst.pins[pin_num]
        direction = dirs.get(pin_name)
        # A pin whose base name isn't itself a declared port, but whose
        # "<name>_i"/"<name>_o" pair both are, is one of this CHILD
        # entity's genuinely bidirectional model pins (ttl_74ls245's a/b,
        # ttl_mcm60256's dq) -- needs TWO port-map associations, not one.
        split_child = (direction is None
                       and f"{pin_name}_i" in dirs and f"{pin_name}_o" in dirs)

        if raw_net == "GND":
            expr_i = expr_o = "'0'"
        elif raw_net == "+5V":
            expr_i = expr_o = "'1'"
        elif raw_net.startswith("unconnected-"):
            if split_child:
                tie = NC_ALLOWED.get((inst.ref, pin_num))
                if tie is None:
                    raise ValueError(
                        f"{inst.ref}.{pin_num} ({pin_name}, net {raw_net!r}): "
                        f"unconnected model INPUT with no NC_ALLOWED tie")
                expr_i, expr_o = f"'{tie}'", "open"
            elif direction == "out":
                expr_i = expr_o = "open"
            else:
                tie = NC_ALLOWED.get((inst.ref, pin_num))
                if tie is None:
                    raise ValueError(
                        f"{inst.ref}.{pin_num} ({pin_name}, net {raw_net!r}): "
                        f"unconnected model INPUT with no NC_ALLOWED tie")
                expr_i = expr_o = f"'{tie}'"
        elif raw_net in net_to_sig:
            canon, idx = net_to_sig[raw_net]
            base = scope.name(canon)
            suf = f"({idx})" if idx is not None else ""
            if ports_by_name.get(canon) == "inout":
                expr_i, expr_o = f"{base}_i{suf}", f"{base}_o{suf}"
            else:
                expr_i = expr_o = f"{base}{suf}"
        else:
            expr_i = expr_o = scope.name(raw_net)

        if split_child:
            lines.append(f"{pin_name}_i => {expr_i}")
            lines.append(f"{pin_name}_o => {expr_o}")
        else:
            expr = expr_o if direction == "out" else expr_i
            lines.append(f"{pin_name} => {expr}")
        if pin_name in clock_pins and raw_net not in ("CLK", "GND", "+5V") \
                and not raw_net.startswith("unconnected-"):
            gated.append(expr_i)
    body = ",\n      ".join(lines)
    gm = ""
    if generic_map_lines:
        gm = "\n    generic map (" + ", ".join(generic_map_lines) + ")"
    # Refs are almost always UxxNN, already legal VHDL labels -- except
    # SWITCH-GATE1 (input_output), whose literal '-' is not, so it goes
    # through the same net-name sanitizer (rule 5: netlist-verified this is
    # the one and only offending ref in the whole 154-component design).
    label = _sanitize_name(inst.ref) if not re.match(r"^[A-Za-z]\w*$", inst.ref) else inst.ref
    return (
        f"  {label} : entity work.{entity}{gm}\n"
        f"    port map (\n      {body});\n"
    )


def _real_instances(design, sheet):
    return [design.instances[ref] for ref in sorted(design.instances)
            if design.instances[ref].sheet == sheet
            and design.instances[ref].type not in EXCLUDED_TYPES]


def _render_ports(scope, ports):
    rendered = []
    rendered.append("clk_sys : in std_logic")
    for name, direction, width in ports:
        base = scope.name(name)
        if direction == "inout":
            # Task-13 rework item 1: no entity ever declares a literal
            # `inout` port any more -- split into a `_i`/`_o` pair at this
            # entity's own boundary too (sheet entities lose their inout
            # ports, per synth-rework-brief.md).
            rendered.append(f"{base}_i : in {_vhdl_type(width)}")
            rendered.append(f"{base}_o : out {_vhdl_type(width)}")
        else:
            rendered.append(f"{base} : {direction} {_vhdl_type(width)}")
    return rendered


def _render_entity_file(entity_name, generics, ports_rendered, signal_decls, instance_blocks):
    parts = [_GENERATED_MARKER, "", "library ieee;", "use ieee.std_logic_1164.all;", ""]
    parts.append(f"entity {entity_name} is")
    if generics:
        parts.append("  generic (")
        parts.append(";\n".join(f"    {g}" for g in generics))
        parts.append("  );")
    parts.append("  port (")
    parts.append(";\n".join(f"    {p}" for p in ports_rendered))
    parts.append("  );")
    parts.append("end entity;")
    parts.append("")
    parts.append(f"architecture rtl of {entity_name} is")
    for s in signal_decls:
        parts.append(f"  signal {s};")
    parts.append("begin")
    parts.append("")
    parts.extend(instance_blocks)
    parts.append("end architecture;")
    return "\n".join(parts) + "\n"


def _local_signals(scope, design, sheet, net_to_sig):
    """`signal <name> : std_logic;` declarations for this sheet's own
    purely-local nets: every distinct raw net touched by >=1 non-excluded
    instance on this sheet that is NOT a cross-sheet port (net_to_sig),
    NOT a power net, and NOT an "unconnected-" marker (those never become
    signals -- handled per-pin as literals/`open`/NC ties instead)."""
    seen = set()
    decls = []
    for inst in _real_instances(design, sheet):
        for raw_net in inst.pins.values():
            if raw_net in ("GND", "+5V") or raw_net.startswith("unconnected-"):
                continue
            if raw_net in net_to_sig:
                continue
            if raw_net in seen:
                continue
            seen.add(raw_net)
            decls.append(f"{scope.name(raw_net)} : std_logic")
    return decls


def _memory_generics(sheet):
    """(entity generic declarations, {ref: (init_param, addr_param)}) for a
    sheet's own MEMORY_INSTANCES, e.g. microcode -> u9_init_file/u9_addr_bits
    /u15_init_file/u15_addr_bits, each defaulted so the entity is
    independently elaborable/testable without an override."""
    decls = []
    per_ref = {}
    for ref, addr_bits, default_path in MEMORY_INSTANCES.get(sheet, ()):
        init_p = f"{ref.lower()}_init_file"
        addr_p = f"{ref.lower()}_addr_bits"
        decls.append(f'{init_p} : string := "{default_path}"')
        decls.append(f"{addr_p} : positive := {addr_bits}")
        per_ref[ref] = (init_p, addr_p)
    return decls, per_ref


def emit(root, outdir):
    """Generate the nine sheet entities + dino_core.vhd + gated_clocks.txt
    into `outdir` (fpga/gen/ for the checked-in artifacts-of-record copy).
    See docs/notes/test_fpga_gen.py for the host-tested contract and
    task-8-report.md for the full boundary-table derivation.
    """
    design = load_design(root)
    os.makedirs(outdir, exist_ok=True)
    composite_locals = _composite_locals(design)
    gated = []

    sub_sheets = [s for s in SHEETS if s != "root"]
    for sheet in sub_sheets:
        extra = [INPUT_OUTPUT_EXTRA_PORT] if sheet == "input_output" else []
        ports, net_to_sig = _sheet_bindings(design, sheet, composite_locals, extra)
        generics, mem_params = _memory_generics(sheet)
        reserved = ["clk_sys"]
        for init_p, addr_p in mem_params.values():
            reserved += [init_p, addr_p]
        scope = _Scope(reserved=reserved)
        ports_rendered = _render_ports(scope, ports)
        local_signals = _local_signals(scope, design, sheet, net_to_sig)
        ports_by_name = {name: direction for name, direction, _width in ports}
        blocks = []
        for inst in _real_instances(design, sheet):
            gmap = []
            if inst.ref in mem_params:
                init_p, addr_p = mem_params[inst.ref]
                gmap = [f"init_file => {init_p}", f"addr_bits => {addr_p}"]
            blocks.append(_instance_block(scope, inst, net_to_sig, gmap, gated,
                                           ports_by_name))
        text = _render_entity_file(sheet, generics, ports_rendered, local_signals, blocks)
        with open(os.path.join(outdir, f"{sheet}.vhd"), "w") as f:
            f.write(text)

    # dino_core: every sub-sheet's OWN sheet_ports name is, by
    # build_contracts's construction, cross-sheet (len(sheets) >= 2) --
    # union them (root's own sheet_ports counts too, since root's chips
    # are inlined here rather than behind their own entity) to get every
    # signal dino_core must declare and wire between child instances.
    cross = {}
    for sheet in SHEETS:
        for p in design.sheet_ports.get(sheet, ()):
            if p.name in cross:
                assert cross[p.name] == p.width, (
                    f"{p.name}: width {p.width} on {sheet} != "
                    f"{cross[p.name]} elsewhere")
            else:
                cross[p.name] = p.width

    top_ports = [("clk4m_y1", "in", 1), ("dip_sw", "in", 8),
                 ("btn_reset_n", "in", 1), ("ob_led", "out", 8), ("halt", "out", 1)]
    core_generics, core_mem_params = [], {}
    for sheet in ("microcode", "memory"):
        decls, per_ref = _memory_generics(sheet)
        core_generics += decls
        core_mem_params.update(per_ref)

    reserved = (["clk_sys"] + [n for n, _, _ in top_ports]
                + [n for pair in core_mem_params.values() for n in pair])
    scope = _Scope(reserved=reserved)
    ports_rendered = _render_ports(scope, top_ports)

    # root: same binding mechanism as every sub-sheet, but its "ports" are
    # never rendered as an entity clause -- root's own instances are
    # inlined directly into dino_core's architecture, so only net_to_sig
    # (which raw net on root maps to which shared/boundary signal) is used.
    boundary_in_extra = [(name, "in", width, locs) for name, width, locs in BOUNDARY_INPUTS]
    _, root_net_to_sig = _sheet_bindings(design, "root", composite_locals, boundary_in_extra)
    root_local_signals = _local_signals(scope, design, "root", root_net_to_sig)

    cross_signal_decls = [f"{scope.name(name)} : {_vhdl_type(width)}"
                           for name, width in cross.items()]

    blocks = []
    for inst in _real_instances(design, "root"):
        blocks.append(_instance_block(scope, inst, root_net_to_sig, [], gated))

    for sheet in sub_sheets:
        extra = [INPUT_OUTPUT_EXTRA_PORT] if sheet == "input_output" else []
        ports, _ = _sheet_bindings(design, sheet, composite_locals, extra)
        gmap = []
        if sheet in ("microcode", "memory"):
            for ref, _addr, _path in MEMORY_INSTANCES[sheet]:
                init_p, addr_p = core_mem_params[ref]
                gmap.append(f"{init_p} => {init_p}")
                gmap.append(f"{addr_p} => {addr_p}")
        gm = ""
        if gmap:
            gm = "\n    generic map (" + ", ".join(gmap) + ")"
        conns = ["clk_sys => clk_sys"]
        for name, direction, _width in ports:
            base = scope.name(name)
            if direction == "inout":
                # dino_core is the top -- a bidirectional cross-sheet net
                # never needs to be re-exported as a split port of its
                # own here, it just collapses to the ONE plain, resolved
                # signal `cross_signal_decls` already declares for it
                # (every local driver's `_o` and every local reader's
                # `_i` bind to the SAME identifier, exactly the electrical
                # behavior the old single `inout` association gave for
                # free).
                conns.append(f"{base}_i => {base}")
                conns.append(f"{base}_o => {base}")
            else:
                conns.append(f"{base} => {base}")
        body = ",\n      ".join(conns)
        blocks.append(
            f"  {sheet}_i : entity work.{sheet}{gm}\n"
            f"    port map (\n      {body});\n")

    tap_lines = []
    for top_name, tap_width, tap_net in BOUNDARY_OUTPUTS:
        tap_lines.append(f"  {scope.name(top_name)} <= {scope.name(tap_net)};")
    blocks.append("\n".join(tap_lines) + "\n")

    signal_decls = cross_signal_decls + root_local_signals
    core_text = _render_entity_file("dino_core", core_generics, ports_rendered,
                                     signal_decls, blocks)
    with open(os.path.join(outdir, "dino_core.vhd"), "w") as f:
        f.write(core_text)

    gated_unique = sorted(set(gated))
    with open(os.path.join(outdir, "gated_clocks.txt"), "w") as f:
        f.write("\n".join(gated_unique) + "\n")

    return design


def _regenerate(root, gen_dir, hex_dir, roms_dir):
    """The one command that regenerates every artifact-of-record this
    module owns: fpga/gen/*.vhd + gated_clocks.txt (emit()) and
    fpga/sim/hex/*.hex (bin2hex() from roms/*.bin, plus an always-empty
    RAM.hex). Returns 0 (a shell-friendly exit code) after printing a
    summary, matching microcode_gen.py/progrom_gen.py's own main()s.
    """
    emit(root, gen_dir)
    print(f"wrote {len(SHEETS) - 1} sheet entities + dino_core.vhd + "
          f"gated_clocks.txt -> {gen_dir}")
    os.makedirs(hex_dir, exist_ok=True)
    for label, bin_name in (("U9", "U9.bin"), ("U15", "U15.bin"),
                            ("U23", "U23.bin"), ("PROG", "PROG.bin")):
        n = bin2hex(os.path.join(roms_dir, bin_name), os.path.join(hex_dir, f"{label}.hex"))
        print(f"  {label}.hex: {n} bytes <- roms/{bin_name}")
    with open(os.path.join(hex_dir, "RAM.hex"), "w"):
        pass
    print("  RAM.hex: 0 bytes (blank -- the real board's RAM starts empty too)")
    return 0


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    default_root = os.path.join(here, "..", "..", "dino_v0_0_2", "dino_v0_0_2.kicad_sch")
    if argv and argv[0] == "--dump-pinmap":
        dump_pinmap(argv[1] if len(argv) > 1 else default_root)
        return 0
    root = argv[0] if argv else default_root
    gen_dir = os.path.join(here, "..", "..", "fpga", "gen")
    hex_dir = os.path.join(here, "..", "..", "fpga", "sim", "hex")
    roms_dir = os.path.join(here, "..", "..", "roms")
    return _regenerate(root, gen_dir, hex_dir, roms_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
