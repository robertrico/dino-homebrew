library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- 3-to-8 line decoder/demultiplexer. Port names come from PIN_MAP
-- (docs/notes/fpga_gen.py) transcribed off dump_pinmap('dino_v0_0_2/
-- dino_v0_0_2.kicad_sch') -- e1_n/e2_n active-low, e3 active-high, and
-- o0_n..o7_n active-low are confirmed by the KiCad pin *graphic style*
-- (input_low / line / output_low) in control_word.kicad_sch's
-- 74LS138_1_0 lib_symbols block, not datasheet memory. See the PIN_MAP
-- comment there for exact cited line numbers.
entity ttl_74ls138 is
  port (
    a0   : in  std_logic;
    a1   : in  std_logic;
    a2   : in  std_logic;
    e1_n : in  std_logic;
    e2_n : in  std_logic;
    e3   : in  std_logic;
    o0_n : out std_logic;
    o1_n : out std_logic;
    o2_n : out std_logic;
    o3_n : out std_logic;
    o4_n : out std_logic;
    o5_n : out std_logic;
    o6_n : out std_logic;
    o7_n : out std_logic);
end entity;

architecture rtl of ttl_74ls138 is
begin
  process(a0, a1, a2, e1_n, e2_n, e3)
    variable sel : integer range 0 to 7;
  begin
    o0_n <= '1'; o1_n <= '1'; o2_n <= '1'; o3_n <= '1';
    o4_n <= '1'; o5_n <= '1'; o6_n <= '1'; o7_n <= '1';
    if e3 = '1' and e1_n = '0' and e2_n = '0' then
      sel := to_integer(unsigned'(a2 & a1 & a0));
      case sel is
        when 0 => o0_n <= '0';
        when 1 => o1_n <= '0';
        when 2 => o2_n <= '0';
        when 3 => o3_n <= '0';
        when 4 => o4_n <= '0';
        when 5 => o5_n <= '0';
        when 6 => o6_n <= '0';
        when 7 => o7_n <= '0';
        when others => null;
      end case;
    end if;
  end process;
end architecture;
