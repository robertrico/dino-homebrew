library ieee;
use ieee.std_logic_1164.all;

entity spike_bus is
  port (
    en_a_n : in  std_logic;
    en_b_n : in  std_logic;
    a_val  : in  std_logic_vector(7 downto 0);
    b_val  : in  std_logic_vector(7 downto 0);
    y      : out std_logic_vector(7 downto 0));
end entity;

architecture rtl of spike_bus is
  signal bus_w : std_logic_vector(7 downto 0);
begin
  bus_w <= a_val when en_a_n = '0' else (others => 'Z');
  bus_w <= b_val when en_b_n = '0' else (others => 'Z');
  y     <= bus_w;
end architecture;

-- VHDL library/use clauses only bind to the single design unit that
-- follows them, so a second entity in the same file needs its own.
library ieee;
use ieee.std_logic_1164.all;

entity spike_xcvr is
  port (dir  : in    std_logic;
        oe_n : in    std_logic;
        a    : inout std_logic_vector(7 downto 0);
        b    : inout std_logic_vector(7 downto 0));
end entity;

architecture rtl of spike_xcvr is
begin
  b <= a when (oe_n = '0' and dir = '1') else (others => 'Z');
  a <= b when (oe_n = '0' and dir = '0') else (others => 'Z');
end architecture;
