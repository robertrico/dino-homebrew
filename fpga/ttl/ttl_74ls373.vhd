library ieee;
use ieee.std_logic_1164.all;

-- Octal D-type TRANSPARENT latch. LE is sampled through the usual 2-flop
-- sync (le_m); le_m(1) is that sync's settled/current level. The
-- transparent path is a plain CONCURRENT (combinational) signal
-- assignment outside the clocked process: q_i <= d_bus when le_m(1)='1'
-- else held -- so once le_m(1) has settled high, any further change of
-- d_bus propagates to q_i with zero clk_sys-edge delay, exactly matching
-- the real chip's "output follows D while LE is high" behaviour. Only
-- the HELD value (what to latch when LE falls) is registered, on a
-- detected LE-falling transition -- checked ONE STAGE EARLIER than the
-- transparent mux's own le_m(1) (le_m(1)='1' and le_m(0)='0', not
-- le_m(2)/le_m(1) -- the mirror image of every other model's
-- rising-edge check here, and found off by one stage the hard way: an
-- le_m(2)/le_m(1) detector fires ONE clk_sys tick AFTER le_m(1) itself
-- has already fallen and switched the mux off the transparent path, so
-- for that one tick `held` still named the PREVIOUS latch cycle's value
-- and every dependent sheet (MDR, IR, MAR hi/lo, ALU TMP A/B, registers
-- A/B/C/OUT -- eleven '373 instances) inherited a one-tick stale glitch
-- on every LE fall, first caught by whole-core simulation (Task 11) and
-- reproduced/pinned down as fpga/ttl/test_stateful.py's
-- latch373_no_stale_glitch_on_le_fall. Detecting on le_m(1)/le_m(0)
-- instead makes `held`'s update land in the SAME clk_sys edge/delta as
-- le_m(1)'s own fall (both driven by the same process, same edge), so
-- the mux never has a tick where it has switched away from d_bus but
-- `held` isn't updated yet. OE_n tristates the outputs independently of
-- the latch's internal state -- confirmed "input inverted" bubble-style
-- pin, no literal ~{OE} text, in docs/notes/fpga_gen.py's
-- PIN_MAP["74LS373"] comment.
--
-- No fabric register ever clocks on le/oe_n/d0-d7 directly: le_m and
-- held are both driven only from the clk_sys-clocked process, and the
-- transparent mux reads le_m(1) (a clk_sys-registered signal), never the
-- raw le pin.
entity ttl_74ls373 is
  port (
    clk_sys : in  std_logic;
    oe_n    : in  std_logic;
    o0      : out std_logic;
    d0      : in  std_logic;
    d1      : in  std_logic;
    o1      : out std_logic;
    o2      : out std_logic;
    d2      : in  std_logic;
    d3      : in  std_logic;
    o3      : out std_logic;
    le      : in  std_logic;
    o4      : out std_logic;
    d4      : in  std_logic;
    d5      : in  std_logic;
    o5      : out std_logic;
    o6      : out std_logic;
    d6      : in  std_logic;
    d7      : in  std_logic;
    o7      : out std_logic);
end entity;

architecture rtl of ttl_74ls373 is
  signal le_m  : std_logic_vector(2 downto 0) := (others => '0');
  signal held  : std_logic_vector(7 downto 0) := (others => '0');
  signal d_bus : std_logic_vector(7 downto 0);
  signal q_i   : std_logic_vector(7 downto 0);
begin
  d_bus <= d7 & d6 & d5 & d4 & d3 & d2 & d1 & d0;

  process (clk_sys)
  begin
    if rising_edge(clk_sys) then
      le_m <= le_m(1 downto 0) & le;
      if le_m(1) = '1' and le_m(0) = '0' then  -- detected LE falling edge,
                                                -- one stage earlier than
                                                -- before -- see header
        held <= d_bus;
      end if;
    end if;
  end process;

  q_i <= d_bus when le_m(1) = '1' else held;  -- transparent path: combinational

  o0 <= q_i(0) when oe_n = '0' else 'Z';
  o1 <= q_i(1) when oe_n = '0' else 'Z';
  o2 <= q_i(2) when oe_n = '0' else 'Z';
  o3 <= q_i(3) when oe_n = '0' else 'Z';
  o4 <= q_i(4) when oe_n = '0' else 'Z';
  o5 <= q_i(5) when oe_n = '0' else 'Z';
  o6 <= q_i(6) when oe_n = '0' else 'Z';
  o7 <= q_i(7) when oe_n = '0' else 'Z';
end architecture;
