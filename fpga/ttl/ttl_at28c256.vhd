library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

-- AT28C256: 32K x 8 EEPROM, the machine's program ROM (roms/PROG*.bin,
-- PIN_MAP["AT28C256"] in docs/notes/fpga_gen.py). Same asynchronous read
-- contract, generic-passing mechanism (SIM_ARGS, not GHDL_RUN_ARGS -- see
-- ttl_at28c64b.vhd's header for the full derivation) and addr_bits/full
-- physical pin-width decoupling as ttl_at28c64b.vhd -- read that file's
-- header for the shared design rationale. The only real difference: this
-- part has NO NC pins -- pins 1/26 (A14/A13, NC on the pin-compatible 8K
-- AT28C64B) are genuine address lines here (confirmed off the netlist,
-- dump_pinmap on dino_v0_0_2/memory.kicad_sch reports "A14_1"/"A13_26"
-- for this symbol), so this entity's address bus is the full 15 bits
-- (32K = 2**15) and full_addr is 15 bits wide, not 13.
-- Task-13 rework item 2: the read is now REGISTERED on clk_sys (same
-- hidden-sampling-clock contract every stateful model already uses --
-- this part joins CLK_SYS_TYPES in docs/notes/fpga_gen.py, NOT
-- STATEFUL_TYPES itself: it has no real schematic clock/latch pin to
-- sample, this is purely a synthesis-mapping concern), one clk_sys tick
-- of latency behind the old purely-combinational read -- invisible at
-- clk_sys >> CLK (the machine's real clock), and the one shape
-- memory_libmap can map to a DP16KD block instead of falling back to
-- flip-flops. The tri-state gate stays purely combinational on
-- ce_n/oe_n, unchanged.
entity ttl_at28c256 is
  generic (
    init_file : string;
    addr_bits : positive
  );
  port (
    clk_sys : in  std_logic;
    a14  : in  std_logic;
    a12  : in  std_logic;
    a7   : in  std_logic;
    a6   : in  std_logic;
    a5   : in  std_logic;
    a4   : in  std_logic;
    a3   : in  std_logic;
    a2   : in  std_logic;
    a1   : in  std_logic;
    a0   : in  std_logic;
    io0  : out std_logic;
    io1  : out std_logic;
    io2  : out std_logic;
    io3  : out std_logic;
    io4  : out std_logic;
    io5  : out std_logic;
    io6  : out std_logic;
    io7  : out std_logic;
    ce_n : in  std_logic;
    a10  : in  std_logic;
    oe_n : in  std_logic;
    a11  : in  std_logic;
    a9   : in  std_logic;
    a8   : in  std_logic;
    a13  : in  std_logic;
    we_n : in  std_logic
  );
end entity;

architecture rtl of ttl_at28c256 is
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
  signal q         : std_logic_vector(7 downto 0);
  signal d_i       : std_logic_vector(7 downto 0);
begin
  full_addr <= unsigned(std_logic_vector'(a14 & a13 & a12 & a11 & a10 & a9
                                           & a8 & a7 & a6 & a5 & a4 & a3
                                           & a2 & a1 & a0));

  process (clk_sys)
  begin
    if rising_edge(clk_sys) then
      q <= mem(to_integer(full_addr(addr_bits - 1 downto 0)));
    end if;
  end process;

  d_i <= q when ce_n = '0' and oe_n = '0' else (others => 'Z');

  io0 <= d_i(0);
  io1 <= d_i(1);
  io2 <= d_i(2);
  io3 <= d_i(3);
  io4 <= d_i(4);
  io5 <= d_i(5);
  io6 <= d_i(6);
  io7 <= d_i(7);
end architecture;
