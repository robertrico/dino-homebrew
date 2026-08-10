library ieee;
use ieee.std_logic_1164.all;

entity ttl_74ls00 is        -- quad 2-input NAND
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

architecture rtl of ttl_74ls00 is
begin
  y1 <= a1 nand b1;  y2 <= a2 nand b2;
  y3 <= a3 nand b3;  y4 <= a4 nand b4;
end architecture;
