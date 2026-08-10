library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Synchronous 4-bit binary counter with SYNCHRONOUS master reset (unlike
-- '273's async MR_n -- confirmed against datasheets/sn74s163.pdf p5,
-- whose own caption distinguishes this part from the '160/'162 decade
-- counters' asynchronous clear; see docs/notes/fpga_gen.py's
-- PIN_MAP["74LS163"] comment). CP is sampled through the same 2-flop
-- sync + rising-edge-detect core as every stateful model here; clear,
-- load, and count are all gated INSIDE the detected-edge branch (not
-- polled every clk_sys tick like '74/'273's async pins) -- that
-- placement is exactly what makes clear/load synchronous: asserting
-- MR_n/PE_n with no CP edge changes nothing.
--
-- TC (RCO) is a combinational function of the CURRENT count and CET —
-- datasheets/sn74s163.pdf p5's own logic diagram shows its AND gate fed
-- by ENT (=CET) and all four Q outputs only, no CP involvement — so it's
-- a concurrent signal assignment outside the clocked process, updating
-- immediately when CET or the count changes.
--
-- Edge-detect stage NOTE (no code change -- informational only, Task 12
-- adjudication): this model's CP rising-edge detector (cp_m(1)/cp_m(2))
-- fires 3 clk_sys ticks after the real transition -- the SAME later
-- stage ttl_74ls273.vhd's own D-capture detector used to use, before
-- being found to sample one tick too late whenever its D-input is fed by
-- a co-committing ttl_74ls373.vhd (which commits its own held value 2
-- ticks after ITS triggering edge, one stage earlier -- see that file's
-- own header). Safe here TODAY: this chip's parallel-load inputs (d0-d3)
-- are dino_core.vhd's own U20 instance, tied to constant '0', never fed
-- by a live '373 output at all. If a future net ever loads this counter
-- from a co-committing '373's restamp, this model's own detect stage
-- would need the identical (0,1)-pair realignment ttl_74ls273.vhd got,
-- for the same reason.
entity ttl_74ls163 is
  port (
    clk_sys : in  std_logic;
    mr_n    : in  std_logic;
    cp      : in  std_logic;
    d0      : in  std_logic;
    d1      : in  std_logic;
    d2      : in  std_logic;
    d3      : in  std_logic;
    cep     : in  std_logic;
    pe_n    : in  std_logic;
    cet     : in  std_logic;
    q3      : out std_logic;
    q2      : out std_logic;
    q1      : out std_logic;
    q0      : out std_logic;
    tc      : out std_logic);
end entity;

architecture rtl of ttl_74ls163 is
  signal cp_m : std_logic_vector(2 downto 0) := (others => '0');
  signal q_i  : unsigned(3 downto 0) := (others => '0');
begin
  process (clk_sys)
  begin
    if rising_edge(clk_sys) then
      cp_m <= cp_m(1 downto 0) & cp;
      if cp_m(1) = '1' and cp_m(2) = '0' then  -- detected CP rising edge
        if mr_n = '0' then
          q_i <= (others => '0');
        elsif pe_n = '0' then
          q_i <= unsigned(std_logic_vector'(d3 & d2 & d1 & d0));
        elsif cep = '1' and cet = '1' then
          q_i <= q_i + 1;
        end if;
        -- else: no clear/load/count condition -- hold (no edge -> unchanged
        -- is covered simply by not reaching this branch at all).
      end if;
    end if;
  end process;

  q0 <= q_i(0);
  q1 <= q_i(1);
  q2 <= q_i(2);
  q3 <= q_i(3);
  tc <= '1' when (q_i = "1111" and cet = '1') else '0';
end architecture;
