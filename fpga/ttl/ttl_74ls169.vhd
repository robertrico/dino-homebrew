library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- Synchronous 4-bit UP/DOWN binary counter. Four of these are DINO's stack
-- pointer (U63-U66, dino_v0_0_2/stack_pointer.kicad_sch, added 2026-08-10).
--
-- Shares the '160/'163 family pinout -- 16-pin, CP on 2, parallel inputs on
-- 3-6, ~PE on 9, enables on 7/10, terminal count on 15 -- and differs from
-- ttl_74ls163.vhd in exactly four ways, every one of which this model has to
-- get right (docs/notes/dino_hardware_growth_plan.md step 4b):
--
--   1. NO CLEAR AT ALL. Pin 1 is U/~D, the direction LEVEL, where the '163
--      has ~MR. See the power-up note below -- this is the single most
--      consequential difference and it is not about logic.
--   2. The count enables are ACTIVE LOW (~CEP/~CET) where the '163's are
--      active high.
--   3. ~TC is ACTIVE LOW, and its terminal count depends on DIRECTION:
--      1111 when counting up, 0000 when counting down. The '163's is
--      active-high and up-only.
--   4. The count is +1 or -1 per U/~D, not always +1.
--
-- The parallel inputs are P0-P3, not D0-D3 -- Philips/NXP naming matching
-- ~PE, read straight off the KiCad symbol via fpga_gen.py --dump-pinmap
-- (rule 5: never a datasheet).
--
-- LOAD HAS PRIORITY over the count enables: ~PE=0 loads regardless of
-- ~CEP/~CET, which is why the elsif chain below tests pe_n first and why
-- `LXI SP` needs no stabiliser.
--
-- POWER-UP IS DELIBERATELY NON-ZERO. A '169 has no clear of any kind, so
-- real silicon comes up at a random value and stays there until software
-- runs `LXI SP`. A model initialised to zero would be KINDER THAN THE
-- HARDWARE -- exactly the trap CLAUDE.md names ("a rig stand-in is dangerous
-- exactly when it is BETTER than the hardware"): a program that forgot to
-- initialise SP would run clean in cocotb and fail on the bench, which is
-- the "machine works, then randomly doesn't" afternoon the growth plan warns
-- about. `por_value` defaults to 1010 so anything depending on a zero SP
-- fails loudly in simulation; a testbench that wants a specific start state
-- sets the generic, and dino_core never overrides it.
--
-- CP edge detect: the same cp_m(1)/cp_m(2) stage ttl_74ls163.vhd uses. The
-- '163's own header defers a question here -- it is "safe TODAY" only because
-- U20's parallel inputs are tied to constant '0', and SP's are live (fed by
-- ROM, RAM or a register through the U25 bridge). Re-answered rather than
-- inherited: the register '373s that reach MDR only re-commit when they are
-- the DESTINATION, and DST is one-hot, so a register can never co-commit with
-- an SP load. U18 (the MDR '373) has a decode-derived LE, not a clocked one.
-- No co-committing '373 can feed these P inputs, so the (1,2) pair stands.
-- test_stateful.py::counter169_loads_from_each_source_class is the covering
-- check -- if that alignment is ever wrong, it reads the wrong byte and says so.
entity ttl_74ls169 is
  generic (
    por_value : natural := 10);          -- 1010; see POWER-UP note above
  port (
    clk_sys : in  std_logic;
    u_d_n   : in  std_logic;             -- pin 1, U/~D: '1' up, '0' down
    cp      : in  std_logic;
    p0      : in  std_logic;
    p1      : in  std_logic;
    p2      : in  std_logic;
    p3      : in  std_logic;
    cep_n   : in  std_logic;
    pe_n    : in  std_logic;
    cet_n   : in  std_logic;
    q3      : out std_logic;
    q2      : out std_logic;
    q1      : out std_logic;
    q0      : out std_logic;
    tc_n    : out std_logic);
end entity;

architecture rtl of ttl_74ls169 is
  signal cp_m : std_logic_vector(2 downto 0) := (others => '0');
  signal q_i  : unsigned(3 downto 0) := to_unsigned(por_value mod 16, 4);
begin
  process (clk_sys)
  begin
    if rising_edge(clk_sys) then
      cp_m <= cp_m(1 downto 0) & cp;
      if cp_m(1) = '1' and cp_m(2) = '0' then  -- detected CP rising edge
        if pe_n = '0' then                     -- load wins over count
          q_i <= unsigned(std_logic_vector'(p3 & p2 & p1 & p0));
        elsif cep_n = '0' and cet_n = '0' then
          if u_d_n = '1' then
            q_i <= q_i + 1;
          else
            q_i <= q_i - 1;
          end if;
        end if;
        -- else: hold. No clear branch exists -- this part has no clear.
      end if;
    end if;
  end process;

  q0 <= q_i(0);
  q1 <= q_i(1);
  q2 <= q_i(2);
  q3 <= q_i(3);

  -- ~TC is combinational on the CURRENT count, the direction, and ~CET --
  -- no CP involvement, same shape as the '163's TC but active-low and
  -- direction-dependent. Cascading works by feeding ~TC into the next
  -- chip's ~CET, which is why ~CET (not ~CEP) is the gating term here.
  tc_n <= '0' when (cet_n = '0'
                    and ((u_d_n = '1' and q_i = "1111")
                         or (u_d_n = '0' and q_i = "0000")))
          else '1';
end architecture;
