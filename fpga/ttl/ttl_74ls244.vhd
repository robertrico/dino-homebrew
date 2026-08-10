library ieee;
use ieee.std_logic_1164.all;

-- Octal buffer/line driver, two independent 4-bit tri-state sections
-- (TI's own "1"/"2" section numbering, s-prefixed because VHDL
-- identifiers can't start with a digit -- see PIN_MAP's comment in
-- docs/notes/fpga_gen.py). s1g_n/s2g_n confirmed active-low straight off
-- dump_pinmap's "1~{G}_1"/"2~{G}_19" pinfunction text (literal ~{} bar).
entity ttl_74ls244 is
  port (
    s1g_n : in  std_logic;
    s1a1  : in  std_logic;
    s1a2  : in  std_logic;
    s1a3  : in  std_logic;
    s1a4  : in  std_logic;
    s1y1  : out std_logic;
    s1y2  : out std_logic;
    s1y3  : out std_logic;
    s1y4  : out std_logic;
    s2g_n : in  std_logic;
    s2a1  : in  std_logic;
    s2a2  : in  std_logic;
    s2a3  : in  std_logic;
    s2a4  : in  std_logic;
    s2y1  : out std_logic;
    s2y2  : out std_logic;
    s2y3  : out std_logic;
    s2y4  : out std_logic);
end entity;

architecture rtl of ttl_74ls244 is
begin
  s1y1 <= s1a1 when s1g_n = '0' else 'Z';
  s1y2 <= s1a2 when s1g_n = '0' else 'Z';
  s1y3 <= s1a3 when s1g_n = '0' else 'Z';
  s1y4 <= s1a4 when s1g_n = '0' else 'Z';
  s2y1 <= s2a1 when s2g_n = '0' else 'Z';
  s2y2 <= s2a2 when s2g_n = '0' else 'Z';
  s2y3 <= s2a3 when s2g_n = '0' else 'Z';
  s2y4 <= s2a4 when s2g_n = '0' else 'Z';
end architecture;
