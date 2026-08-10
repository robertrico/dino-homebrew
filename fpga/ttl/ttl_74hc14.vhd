library ieee;
use ieee.std_logic_1164.all;

-- hex Schmitt-trigger inverter. The bench part is a Schmitt trigger for its
-- analog hysteresis on slow/noisy edges; digitally it's an inverter like the
-- '04, and the analog difference is out of scope for this structural model
-- by design (brief step 4).
entity ttl_74hc14 is
  port (
    a1 : in  std_logic;
    a2 : in  std_logic;
    a3 : in  std_logic;
    a4 : in  std_logic;
    a5 : in  std_logic;
    a6 : in  std_logic;
    y1 : out std_logic;
    y2 : out std_logic;
    y3 : out std_logic;
    y4 : out std_logic;
    y5 : out std_logic;
    y6 : out std_logic);
end entity;

architecture rtl of ttl_74hc14 is
begin
  y1 <= not a1;  y2 <= not a2;  y3 <= not a3;
  y4 <= not a4;  y5 <= not a5;  y6 <= not a6;
end architecture;
