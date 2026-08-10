library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

-- MCM60256AP: 32K x 8 static RAM, the bench's only writable memory
-- (PIN_MAP["MCM60256AP"] in docs/notes/fpga_gen.py; already anticipated
-- in STATEFUL_TYPES since Task 5). Same asynchronous READ contract, init
-- file loading, generic-passing mechanism (SIM_ARGS, not GHDL_RUN_ARGS)
-- and addr_bits/physical-pin-width decoupling as
-- ttl_at28c64b.vhd/ttl_at28c256.vhd (read ttl_at28c64b.vhd's header for
-- the full derivation) -- init_file here is not one of roms/*.bin (RAM
-- starts blank on the real board), just whatever fixture a test or a
-- later whole-core sim (Task 11/13) wants pre-loaded; an all-zero/short
-- file is fine, load_mem() zero-fills anything past EOF.
--
-- WRITE differs from the two ROMs -- this is the one part in this task
-- that's a STATEFUL_TYPES member and carries a clk_sys port. Matching the
-- bench's own machine invariant (CLAUDE.md: "RAM write via
-- NAND(WRITE_DIR, ~CLK)" -- everything that changes state is clock-
-- qualified and commits on CLK low) and the brief's literal contract
-- ("the model samples WE_n level via clk_sys while CE_n low, commits
-- mem(addr) <= d"): we_n is run through the same 2-flop synchronizer
-- shape as every stateful model since Task 5 (we_m), and the SETTLED
-- level (we_m(1), not an edge) gates the write -- this is genuinely
-- level-sensitive, not edge-triggered, matching real async-SRAM write
-- behaviour (a write commits for as long as CE_n/WE_n are both held low,
-- not on a single clock edge). ce_n is read live/combinationally inside
-- the clk_sys-clocked branch, same as '163's mr_n/pe_n/cep/cet precedent
-- (Task 5) -- it's a plain enable, not itself a clock/latch pin needing
-- its own synchronizer.
--
-- dq0-dq7 were `inout` (not `out`, unlike the two ROMs' io0-io7) through
-- Task 13's first synthesis attempt -- confirmed off the schematic
-- itself, not assumed: dump_pinmap on dino_v0_0_2/memory.kicad_sch
-- reports this part's data pins with KiCad pin TYPE "bidirectional" (vs.
-- "input" for the two EEPROMs' I/O0-7, PIN_MAP["MCM60256AP"] comment in
-- docs/notes/fpga_gen.py), matching the real electrical behaviour a
-- writable RAM needs. Split into `dq<n>_i`/`dq<n>_o` pairs for the
-- Task-13 rework (synth-rework-brief.md item 1): ghdl-yosys-plugin
-- silently severs internal nets that touch a sub-instance `inout` port
-- at synthesis import (fine in simulation, broken on the import path) --
-- same fix, same rationale as ttl_74ls245.vhd's a/b pins. `dq<n>_i` is
-- the sense input (an external driver's write data lands here); `dq<n>_o`
-- is this model's own read-data drive ('Z' when not driving). No change
-- to the electrical behaviour: an external driver puts write data on
-- dq<n>_i, read back off the resolved net (dq_bus, now built from the
-- `_i` side); this model never drives dq<n>_o except during a read
-- (ce_n='0' and oe_n='0') -- the same tri-state discipline validated
-- against a standalone GHDL/cocotb spike before this file was written.
entity ttl_mcm60256 is
  generic (
    init_file : string;
    addr_bits : positive
  );
  port (
    clk_sys : in  std_logic;
    a14     : in  std_logic;
    a12     : in  std_logic;
    a7      : in  std_logic;
    a6      : in  std_logic;
    a5      : in  std_logic;
    a4      : in  std_logic;
    a3      : in  std_logic;
    a2      : in  std_logic;
    a1      : in  std_logic;
    a0      : in  std_logic;
    dq0_i   : in  std_logic;
    dq0_o   : out std_logic;
    dq1_i   : in  std_logic;
    dq1_o   : out std_logic;
    dq2_i   : in  std_logic;
    dq2_o   : out std_logic;
    dq3_i   : in  std_logic;
    dq3_o   : out std_logic;
    dq4_i   : in  std_logic;
    dq4_o   : out std_logic;
    dq5_i   : in  std_logic;
    dq5_o   : out std_logic;
    dq6_i   : in  std_logic;
    dq6_o   : out std_logic;
    dq7_i   : in  std_logic;
    dq7_o   : out std_logic;
    ce_n    : in  std_logic;
    a10     : in  std_logic;
    oe_n    : in  std_logic;
    a11     : in  std_logic;
    a9      : in  std_logic;
    a8      : in  std_logic;
    a13     : in  std_logic;
    we_n    : in  std_logic
  );
end entity;

architecture rtl of ttl_mcm60256 is
  constant depth : integer := 2 ** addr_bits;
  type mem_t is array (0 to depth - 1) of std_logic_vector(7 downto 0);

  function hex_nibble(c : character) return integer is
  begin
    case c is
      when '0' to '9' => return character'pos(c) - character'pos('0');
      when 'a' to 'f' => return character'pos(c) - character'pos('a') + 10;
      when 'A' to 'F' => return character'pos(c) - character'pos('A') + 10;
      when others => return 0;
    end case;
  end function;

  impure function load_mem(fname : string) return mem_t is
    file f : text open read_mode is fname;
    variable l : line;
    variable m : mem_t := (others => (others => '0'));
    variable i : integer := 0;
    variable v : integer;
  begin
    while not endfile(f) and i < depth loop
      readline(f, l);
      if l'length >= 2 then
        v := hex_nibble(l(l'left)) * 16 + hex_nibble(l(l'left + 1));
        m(i) := std_logic_vector(to_unsigned(v, 8));
      end if;
      i := i + 1;
    end loop;
    return m;
  end function;

  signal mem       : mem_t := load_mem(init_file);
  signal full_addr : unsigned(14 downto 0);
  -- Task-13 rework item 2: the read is now REGISTERED on clk_sys (same
  -- hidden-sampling-clock contract every stateful model already uses),
  -- one clk_sys tick of latency behind the old purely-combinational read
  -- -- invisible at clk_sys >> CLK (the machine's real clock), and the
  -- one shape memory_libmap can map to a DP16KD block instead of falling
  -- back to flip-flops. The tri-state OUTPUT gate stays purely
  -- combinational on ce_n/oe_n, unchanged.
  signal q         : std_logic_vector(7 downto 0);
  signal dq_bus    : std_logic_vector(7 downto 0);
  -- 2-flop sync + history for WE_n, same shape as every stateful model
  -- since Task 5 -- we_m(1) is the settled/current level used to gate the
  -- write commit (level-sensitive, not edge-detected: real async-SRAM
  -- writes commit for the whole low pulse, not on a single edge).
  signal we_m : std_logic_vector(1 downto 0) := (others => '1');
begin
  full_addr <= unsigned(std_logic_vector'(a14 & a13 & a12 & a11 & a10 & a9
                                           & a8 & a7 & a6 & a5 & a4 & a3
                                           & a2 & a1 & a0));
  -- dq_bus is the SENSE side (dq<n>_i) -- an external driver's write data,
  -- exactly the same net the old single `dqN` inout pin read from a
  -- would-be external driver before the Task-13 rework split it.
  dq_bus <= dq7_i & dq6_i & dq5_i & dq4_i & dq3_i & dq2_i & dq1_i & dq0_i;

  process (clk_sys)
  begin
    if rising_edge(clk_sys) then
      we_m <= we_m(0) & we_n;
      if ce_n = '0' and we_m(1) = '0' then
        mem(to_integer(full_addr(addr_bits - 1 downto 0))) <= dq_bus;
      end if;
      q <= mem(to_integer(full_addr(addr_bits - 1 downto 0)));
    end if;
  end process;

  dq0_o <= q(0) when (ce_n = '0' and oe_n = '0') else 'Z';
  dq1_o <= q(1) when (ce_n = '0' and oe_n = '0') else 'Z';
  dq2_o <= q(2) when (ce_n = '0' and oe_n = '0') else 'Z';
  dq3_o <= q(3) when (ce_n = '0' and oe_n = '0') else 'Z';
  dq4_o <= q(4) when (ce_n = '0' and oe_n = '0') else 'Z';
  dq5_o <= q(5) when (ce_n = '0' and oe_n = '0') else 'Z';
  dq6_o <= q(6) when (ce_n = '0' and oe_n = '0') else 'Z';
  dq7_o <= q(7) when (ce_n = '0' and oe_n = '0') else 'Z';
end architecture;
