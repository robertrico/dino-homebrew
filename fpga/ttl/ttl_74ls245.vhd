library ieee;
use ieee.std_logic_1164.all;

-- Octal bus transceiver. KiCad names pin 1 "DIR" ('1': A->B, '0': B->A)
-- and pin 19 "CE" (not the generic "OE" a datasheet reader might reach
-- for from memory) -- confirmed active-low by the "inverted" pin graphic
-- style in mdr.kicad_sch's 74LS245_1_0 lib_symbols block. dump_pinmap
-- names the data pins individually (A0..A7/B0..B7), not as a vector, so
-- the port list follows one std_logic per pin per PIN_MAP, per this
-- task's ambiguity resolution.
--
-- a0-7/b0-7 were `inout` through Task 13's first synthesis attempt; split
-- into `<pin>_i`/`<pin>_o` pairs for the Task-13 rework
-- (synth-rework-brief.md item 1): ghdl-yosys-plugin silently severs
-- internal nets that touch a sub-instance `inout` port at synthesis
-- import (fine in simulation, broken on the import path). `<pin>_o`
-- carries this model's own tri-state drive ('Z' when not driving);
-- `<pin>_i` is the pure sense input this model reads. PIN_MAP itself is
-- unchanged (still "a0".."b7" -- the real datasheet pin names stay the
-- stem; fpga_gen.py's emitter is what threads BOTH `_i`/`_o` associations
-- onto the same net at every instantiation site, restoring the exact same
-- resolved-bus electrical behavior an `inout` port gave for free).
entity ttl_74ls245 is
  port (
    dir  : in  std_logic;
    ce_n : in  std_logic;
    a0_i : in  std_logic;
    a0_o : out std_logic;
    a1_i : in  std_logic;
    a1_o : out std_logic;
    a2_i : in  std_logic;
    a2_o : out std_logic;
    a3_i : in  std_logic;
    a3_o : out std_logic;
    a4_i : in  std_logic;
    a4_o : out std_logic;
    a5_i : in  std_logic;
    a5_o : out std_logic;
    a6_i : in  std_logic;
    a6_o : out std_logic;
    a7_i : in  std_logic;
    a7_o : out std_logic;
    b0_i : in  std_logic;
    b0_o : out std_logic;
    b1_i : in  std_logic;
    b1_o : out std_logic;
    b2_i : in  std_logic;
    b2_o : out std_logic;
    b3_i : in  std_logic;
    b3_o : out std_logic;
    b4_i : in  std_logic;
    b4_o : out std_logic;
    b5_i : in  std_logic;
    b5_o : out std_logic;
    b6_i : in  std_logic;
    b6_o : out std_logic;
    b7_i : in  std_logic;
    b7_o : out std_logic);
end entity;

architecture rtl of ttl_74ls245 is
begin
  b0_o <= a0_i when (ce_n = '0' and dir = '1') else 'Z';
  b1_o <= a1_i when (ce_n = '0' and dir = '1') else 'Z';
  b2_o <= a2_i when (ce_n = '0' and dir = '1') else 'Z';
  b3_o <= a3_i when (ce_n = '0' and dir = '1') else 'Z';
  b4_o <= a4_i when (ce_n = '0' and dir = '1') else 'Z';
  b5_o <= a5_i when (ce_n = '0' and dir = '1') else 'Z';
  b6_o <= a6_i when (ce_n = '0' and dir = '1') else 'Z';
  b7_o <= a7_i when (ce_n = '0' and dir = '1') else 'Z';

  a0_o <= b0_i when (ce_n = '0' and dir = '0') else 'Z';
  a1_o <= b1_i when (ce_n = '0' and dir = '0') else 'Z';
  a2_o <= b2_i when (ce_n = '0' and dir = '0') else 'Z';
  a3_o <= b3_i when (ce_n = '0' and dir = '0') else 'Z';
  a4_o <= b4_i when (ce_n = '0' and dir = '0') else 'Z';
  a5_o <= b5_i when (ce_n = '0' and dir = '0') else 'Z';
  a6_o <= b6_i when (ce_n = '0' and dir = '0') else 'Z';
  a7_o <= b7_i when (ce_n = '0' and dir = '0') else 'Z';
end architecture;
