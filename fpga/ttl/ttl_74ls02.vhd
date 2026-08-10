library ieee;
use ieee.std_logic_1164.all;

entity ttl_74ls02 is        -- quad 2-input NOR
  port (
    a1 : in  std_logic;
    b1 : in  std_logic;
    a2 : in  std_logic;
    b2 : in  std_logic;
    a3 : in  std_logic;
    b3 : in  std_logic;
    a4 : in  std_logic;
    b4 : in  std_logic;
    y1 : out std_logic;
    y2 : out std_logic;
    y3 : out std_logic;
    y4 : out std_logic);
end entity;

architecture rtl of ttl_74ls02 is
begin
  y1 <= a1 nor b1;  y2 <= a2 nor b2;
  y3 <= a3 nor b3;  y4 <= a4 nor b4;
end architecture;
