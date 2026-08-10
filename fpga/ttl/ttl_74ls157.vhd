library ieee;
use ieee.std_logic_1164.all;

-- Quad 2:1 line multiplexer. e_n (pin 15, strobe) is confirmed active-low
-- by the KiCad pin graphic style "inverted" in alu.kicad_sch's
-- 74LS157_1_0 lib_symbols block (line 3286), not datasheet memory --
-- strobe high forces all four outputs low, per PIN_MAP's comment.
entity ttl_74ls157 is
  port (
    s   : in  std_logic;
    e_n : in  std_logic;
    i0a : in  std_logic;
    i1a : in  std_logic;
    za  : out std_logic;
    i0b : in  std_logic;
    i1b : in  std_logic;
    zb  : out std_logic;
    i0c : in  std_logic;
    i1c : in  std_logic;
    zc  : out std_logic;
    i0d : in  std_logic;
    i1d : in  std_logic;
    zd  : out std_logic);
end entity;

architecture rtl of ttl_74ls157 is
begin
  za <= '0' when e_n = '1' else i1a when s = '1' else i0a;
  zb <= '0' when e_n = '1' else i1b when s = '1' else i0b;
  zc <= '0' when e_n = '1' else i1c when s = '1' else i0c;
  zd <= '0' when e_n = '1' else i1d when s = '1' else i0d;
end architecture;
