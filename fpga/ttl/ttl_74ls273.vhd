library ieee;
use ieee.std_logic_1164.all;

-- Octal D-type positive-edge-triggered register with ASYNCHRONOUS master
-- reset (MR_n) -- unlike '163's synchronous clear, MR_n here is polled
-- every clk_sys tick (same as '74's PRE_n/CLR_n) rather than gated
-- behind the detected CP-edge branch, so it forces Q=0 with no clock
-- edge required. CP is sampled through the standard 2-flop sync +
-- rising-edge-detect core. See docs/notes/fpga_gen.py's
-- PIN_MAP["74LS273"] comment for the netlist pin-function derivation.
--
-- Edge-detect stage ALIGNED to ttl_74ls373.vhd's own le_m(1)/le_m(0)
-- pair (cp_m(0)='1' and cp_m(1)='0', not cp_m(1)/cp_m(2)) -- found off
-- by one stage the same way '373's own le-falling detector once was
-- (see that file's header). Before this fix, a '273 whose D-input is
-- fed (through combinational logic) by a co-committing '373's own
-- restamped output -- e.g. alu.vhd's FLAG_Z register (U49) sampling the
-- ALU's zero-detect, itself downstream of TMP_A/TMP_B's (U45/U46)
-- write-back on the SAME clk-falling edge that also closes U49's own
-- capture window -- detected its rising CP edge ONE clk_sys tick LATER
-- than the '373 detects its own commit, so by the time this register's
-- detector fired, the '373 had ALREADY restamped and its new value had
-- already propagated back through the combinational cone into this
-- register's own D-input: a real, sim-only false read (the ALU's fresh,
-- POST-restamp zero-flag captured instead of the PRE-restamp one),
-- traced end-to-end and confirmed NOT a wiring/netlist bug
-- (docs/notes/kicad_netlist.build_report('dino_v0_0_2/alu.kicad_sch')
-- matches fpga/gen/alu.vhd exactly) and NOT present on real silicon
-- (U49's own clock derives from U27's Q-bar with effectively zero extra
-- gate delay, while the corrupted D path needs ~4 real chip
-- propagation delays, tens of ns, against a ~5ns hold-time requirement
-- -- comfortable margin, sound synchronous design). Pinned down by
-- fpga/sim/test_core_coverage.py's flow/loop whole-core tests (Task 12)
-- and reproduced in isolation by
-- fpga/ttl/test_stateful.py::register273_captures_pre_edge_d. Aligning
-- this register's own detect stage to '373's removes the artificial
-- one-tick lag entirely -- both models now commit on the SAME clk_sys
-- tick relative to their shared triggering edge, so neither can ever
-- observe the other's post-edge update.
entity ttl_74ls273 is
  port (
    clk_sys : in  std_logic;
    mr_n    : in  std_logic;
    q0      : out std_logic;
    d0      : in  std_logic;
    d1      : in  std_logic;
    q1      : out std_logic;
    q2      : out std_logic;
    d2      : in  std_logic;
    d3      : in  std_logic;
    q3      : out std_logic;
    cp      : in  std_logic;
    q4      : out std_logic;
    d4      : in  std_logic;
    d5      : in  std_logic;
    q5      : out std_logic;
    q6      : out std_logic;
    d6      : in  std_logic;
    d7      : in  std_logic;
    q7      : out std_logic);
end entity;

architecture rtl of ttl_74ls273 is
  signal cp_m : std_logic_vector(2 downto 0) := (others => '0');
  signal q_i  : std_logic_vector(7 downto 0) := (others => '0');
begin
  process (clk_sys)
  begin
    if rising_edge(clk_sys) then
      cp_m <= cp_m(1 downto 0) & cp;
      if mr_n = '0' then
        q_i <= (others => '0');
      elsif cp_m(0) = '1' and cp_m(1) = '0' then  -- detected CP rising edge,
                                                   -- one stage earlier than
                                                   -- before -- see header
        q_i <= d7 & d6 & d5 & d4 & d3 & d2 & d1 & d0;
      end if;
    end if;
  end process;

  q0 <= q_i(0);
  q1 <= q_i(1);
  q2 <= q_i(2);
  q3 <= q_i(3);
  q4 <= q_i(4);
  q5 <= q_i(5);
  q6 <= q_i(6);
  q7 <= q_i(7);
end architecture;
