library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Synchronous 4-bit up/down counter with SEPARATE UP/DOWN clock pins and
-- ASYNCHRONOUS parallel load (LOAD_n) / clear (CLR, active HIGH) --
-- confirmed against datasheets/sn74ls193.pdf p2's own logic diagram (see
-- docs/notes/fpga_gen.py's PIN_MAP["74LS193"] comment for the full
-- derivation, including the CO_n/BO_n combinational formula). UP and
-- DOWN each get their OWN 2-flop sync + rising-edge-detect history
-- (up_m/down_m) -- this part genuinely has two independent clock
-- domains on the real chip, both sampled against the same clk_sys.
-- CLR/LOAD_n are re-read every clk_sys tick (like '74/'273's async
-- pins, NOT gated behind a detected edge like '163's synchronous MR_n/
-- PE_n) so they act with no clock edge required, at clk_sys's 10ns
-- granularity -- asynchronous at the machine's ~500ns+ timescale.
--
-- CO_n/BO_n are combinational functions of the CURRENT count and the
-- LIVE (un-synced) up/down pin level -- faithful to the real chip, which
-- computes them with plain combinational gates straight off those pins
-- for cascading multiple '193s, not through any internal clock.
--
-- Edge-detect stage NOTE (no code change -- informational only, Task 12
-- adjudication): this model's UP/DOWN rising-edge detectors (up_m(1)/
-- up_m(2), down_m(1)/down_m(2)) fire 3 clk_sys ticks after the real
-- transition -- the SAME later stage ttl_74ls273.vhd's own D-capture
-- detector used to use, before being found to sample one tick too late
-- whenever its D-input is fed by a co-committing ttl_74ls373.vhd (which
-- commits its own held value 2 ticks after ITS triggering edge, one
-- stage earlier -- see that file's own header). This part has no
-- clocked D-input at all (UP/DOWN only count; LOAD_n's b0-b3 are read
-- asynchronously, not through this detector), so the specific hazard
-- ttl_74ls273.vhd hit cannot occur here regardless of what feeds it. If
-- a future model change ever adds a clocked, '373-fed data path to a
-- part like this one, that path's own detect stage would need the
-- identical (0,1)-pair realignment ttl_74ls273.vhd got, for the same
-- reason.
entity ttl_74ls193 is
  port (
    clk_sys : in  std_logic;
    b       : in  std_logic;
    qb      : out std_logic;
    qa      : out std_logic;
    down    : in  std_logic;
    up      : in  std_logic;
    qc      : out std_logic;
    qd      : out std_logic;
    d       : in  std_logic;
    c       : in  std_logic;
    load_n  : in  std_logic;
    co_n    : out std_logic;
    bo_n    : out std_logic;
    clr     : in  std_logic;
    a       : in  std_logic);
end entity;

architecture rtl of ttl_74ls193 is
  signal up_m, down_m : std_logic_vector(2 downto 0) := (others => '0');
  signal q_i           : unsigned(3 downto 0) := (others => '0');
begin
  process (clk_sys)
  begin
    if rising_edge(clk_sys) then
      up_m   <= up_m(1 downto 0) & up;
      down_m <= down_m(1 downto 0) & down;
      if clr = '1' then
        q_i <= (others => '0');
      elsif load_n = '0' then
        q_i <= unsigned(std_logic_vector'(d & c & b & a));
      elsif up_m(1) = '1' and up_m(2) = '0' then      -- detected UP rising edge
        q_i <= q_i + 1;
      elsif down_m(1) = '1' and down_m(2) = '0' then  -- detected DOWN rising edge
        q_i <= q_i - 1;
      end if;
    end if;
  end process;

  qa <= q_i(0);
  qb <= q_i(1);
  qc <= q_i(2);
  qd <= q_i(3);
  co_n <= '0' when (q_i = "1111" and up = '0') else '1';
  bo_n <= '0' when (q_i = "0000" and down = '0') else '1';
end architecture;
