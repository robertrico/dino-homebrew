library ieee;
use ieee.std_logic_1164.all;

-- Dual D-type positive-edge-triggered flip-flop with asynchronous PRESET
-- and CLEAR. THE canonical stateful-model pattern (task-5-brief.md Step
-- 3): clk_sys is a hidden 100MHz fabric clock with no netlist pin; every
-- OTHER port is a real datasheet pin, sampled through a 2-flop
-- synchronizer + rising-edge detector (clk1_m/clk2_m) rather than ever
-- clocking a fabric register directly on clk1/clk2. PRE_n/CLR_n are
-- re-read on every clk_sys tick (not put through the sync history), so
-- at clk_sys's 10ns period they respond within a fraction of a machine
-- clock edge -- indistinguishable from true asynchronous dominance at
-- the ~500ns+ machine timescale, while never introducing an actual
-- fabric async reset. See docs/notes/fpga_gen.py's PIN_MAP["74LS74"]
-- comment for the pin-function derivation (KiCad's own R/S/C/D/Q names,
-- disambiguated per-section by the brief's own pre/clr/clk/d/q naming).
--
-- Edge-detect stage NOTE (no code change -- informational only, Task 12
-- adjudication): this model's rising-edge detector (clk1_m(1)/clk1_m(2),
-- clk2_m(1)/clk2_m(2)) fires 3 clk_sys ticks after the real transition --
-- the SAME later stage ttl_74ls273.vhd's own D-capture detector used to
-- use, before being found to sample one tick too late whenever its
-- D-input is fed by a co-committing ttl_74ls373.vhd (which commits its
-- own held value 2 ticks after ITS triggering edge, one stage earlier --
-- see that file's own header). Safe here TODAY: nothing in the current
-- design feeds this flip-flop's D-input from a '373 restamping on the
-- SAME edge that clocks this chip. If a future net ever does, this
-- model's own detect stage would need the identical (0,1)-pair
-- realignment ttl_74ls273.vhd got, for the same reason.
entity ttl_74ls74 is
  port (
    clk_sys : in  std_logic;
    -- flip-flop 1 (pins 1,2,3,4,5,6)
    clr1_n  : in  std_logic;
    d1      : in  std_logic;
    clk1    : in  std_logic;
    pre1_n  : in  std_logic;
    q1      : out std_logic;
    q1_n    : out std_logic;
    -- flip-flop 2 (pins 8,9,10,11,12,13)
    q2_n    : out std_logic;
    q2      : out std_logic;
    pre2_n  : in  std_logic;
    clk2    : in  std_logic;
    d2      : in  std_logic;
    clr2_n  : in  std_logic);
end entity;

architecture rtl of ttl_74ls74 is
  signal clk1_m : std_logic_vector(2 downto 0) := (others => '0');
  signal clk2_m : std_logic_vector(2 downto 0) := (others => '0');
  signal q1_i   : std_logic := '0';
  signal q2_i   : std_logic := '0';
begin
  process (clk_sys)
  begin
    if rising_edge(clk_sys) then
      clk1_m <= clk1_m(1 downto 0) & clk1;
      if pre1_n = '0' then
        q1_i <= '1';
      elsif clr1_n = '0' then
        q1_i <= '0';
      elsif clk1_m(1) = '1' and clk1_m(2) = '0' then  -- detected rising edge
        q1_i <= d1;
      end if;

      clk2_m <= clk2_m(1 downto 0) & clk2;
      if pre2_n = '0' then
        q2_i <= '1';
      elsif clr2_n = '0' then
        q2_i <= '0';
      elsif clk2_m(1) = '1' and clk2_m(2) = '0' then
        q2_i <= d2;
      end if;
    end if;
  end process;

  q1   <= q1_i;
  q1_n <= not q1_i;
  q2   <= q2_i;
  q2_n <= not q2_i;
end architecture;
