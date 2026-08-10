library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;

-- AT28C64B: 8K x 8 EEPROM, the machine's microcode ROM pair (U9/U15,
-- roms/U9.bin U15.bin, PIN_MAP["AT28C64B"] in docs/notes/fpga_gen.py).
-- Purely asynchronous read, exactly the brief's contract:
--   d <= mem(addr) when ce_n='0' and oe_n='0' else 'Z'
-- (see io0-io7 assignments below, one bit each -- same "real pin names,
-- not abstracted vectors" convention as every model since Task 2).
--
-- init_file is loaded ONCE, at elaboration, by load_mem() below, reading
-- the one-byte-per-line lowercase "%02x" hex text bin2hex() produces
-- (docs/notes/fpga_gen.py) -- never the raw roms/*.bin directly (VHDL-2008
-- textio has no clean binary-byte reader portable across GHDL builds; the
-- hex reformatting is the bridge, and it round-trips exactly --
-- test_bin2hex_roundtrip in docs/notes/test_fpga_gen.py). init_file and
-- addr_bits are supplied by the sim Makefile via GHDL's `-g` mechanism --
-- specifically SIM_ARGS (NOT GHDL_RUN_ARGS: GHDL_RUN_ARGS lands BEFORE the
-- toplevel unit name on cocotb's generated `ghdl -r` command line, where
-- `-g` overrides are silently ignored -- GHDL falls back to the DEFAULT
-- generic value or errors if there is none; SIM_ARGS lands AFTER the
-- toplevel name, which is where GHDL actually reads generic overrides.
-- Verified directly against GHDL 7.0.0-dev with a standalone spike
-- (entity with a string generic + no default, `ghdl -e` then `ghdl -r
-- <unit> -ginit_file=... -gaddr_bits=...` with the args placed AFTER the
-- unit name), not assumed from documentation -- see fpga/ttl/Makefile's
-- MODEL=ttl_at28c64b/ttl_at28c256/ttl_mcm60256 branches for the mechanism
-- in place.
--
-- addr_bits decouples the DEPTH actually decoded from the fixed physical
-- pin count this entity always declares (13 address pins, matching the
-- real chip): full_addr is always the complete 13-bit concatenation of
-- every address pin, but only its low addr_bits bits
-- (full_addr(addr_bits-1 downto 0)) select into `mem`, whose depth is
-- 2**addr_bits. At addr_bits=13 (the real chip's full depth) this uses
-- every bit; at a smaller addr_bits (this task's cocotb test uses 4, for
-- an exact 16-byte fixture) the upper, unused address pins are still
-- real ports -- wired for netlist fidelity -- but don't affect addressing.
--
-- WE_n (pin 27, PIN_MAP "we_n") is a real netlist-connected pin, kept as
-- a port so the structural emitter (Tasks 7-8) can wire it like any other
-- net, but this model never drives an EEPROM byte-program cycle from it:
-- CLAUDE.md rule 4 is "Rico burns the ROMs (TL866); the rig verifies, it
-- never programs" -- the sim's job is to read back exactly what was
-- burned, not to emulate EEPROM programming.
--
-- Pins 1/26 (A14/A13 on the pin-compatible 32K AT28C256/MCM60256AP) are
-- NC on this 8K part -- confirmed straight off the netlist (dump_pinmap
-- on dino_v0_0_2/microcode.kicad_sch reports "NC_1"/"NC_26" for this
-- symbol), not assumed from "8K only needs 13 address bits" reasoning
-- alone. They get no port at all (PIN_MAP names them "nc", excluded from
-- the port list the same way vcc/gnd are -- see
-- test_vhdl_entities_match_pinmap in docs/notes/test_fpga_gen.py).
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
entity ttl_at28c64b is
  generic (
    init_file : string;
    addr_bits : positive
  );
  port (
    clk_sys : in  std_logic;
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
    we_n : in  std_logic
  );
end entity;

architecture rtl of ttl_at28c64b is
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

  -- One byte per line, lowercase "%02x" -- exactly bin2hex()'s output
  -- format. Reads at most `depth` lines; a short file (fewer lines than
  -- depth, or no file smaller than depth at all) leaves the remainder
  -- zero-filled.
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
  signal full_addr : unsigned(12 downto 0);
  signal q         : std_logic_vector(7 downto 0);
  signal d_i       : std_logic_vector(7 downto 0);
begin
  full_addr <= unsigned(std_logic_vector'(a12 & a11 & a10 & a9 & a8 & a7 & a6
                                           & a5 & a4 & a3 & a2 & a1 & a0));

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
