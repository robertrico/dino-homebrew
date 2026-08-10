-- versa_top.vhd (Task 13) -- FPGA shell for the Lattice ECP5-5G Versa
-- Development Board (LFE5UM5G-45F, CABGA381), wrapping dino_core (Task 8)
-- for real fabric. Board pin identities/IOStandards below are taken from
-- litex-boards' lattice_versa_ecp5.py (reference platform file, verified
-- this session against the raw source) and cross-checked against the
-- ECP5-5G Versa Development Board User Guide (EB103) for polarity, which
-- litex-boards' own pin table does not state in comments.
--
-- clk_sys comes from an EHXPLLL hard PLL dividing the board's 100MHz LVDS
-- oscillator down to 12MHz (synth-rework-brief.md item 6). Task 13
-- wired clk_sys = clk100 directly and measured Fmax 20MHz on the (then
-- empty) netlist; the REPAIRED netlist measures 16.82MHz post-route, so
-- 100MHz was never reachable and is not a placement-quality problem --
-- clk_sys is the sampling clock every '373/'273/'163/ROM model uses to
-- give GHDL a synchronous handle, and a whole machine bus-and-decode
-- cloud has to settle inside one of its ticks. 12MHz is chosen FROM that
-- measurement with margin, not pre-committed (see the report's gate 4).
--
-- dino_core's second clock input, clk4m_y1 (the Y1-oscillator stand-in
-- that clocks U20's '163 T-state counter on the real board), is generated
-- here by a plain clk_sys-synchronous /25 divider, UNCHANGED from Task 13
-- -- there is no Y1 crystal on the Versa, so the divider IS the Y1
-- stand-in in this shell, not a workaround. U20 then divides by 4, so the
-- machine's own CLK is clk_sys/100 exactly: at clk_sys = 12MHz the
-- machine runs at 120kHz, and the clk_sys : machine-CLK ratio is 100.
--
-- DIP-switch polarity (documented decision, not a guess): the ECP5-5G
-- Versa User Guide states the DIP switches read LOGIC LOW when moved to
-- the "ON" position (pulled to ground; OFF is pulled up to logic 1) --
-- exactly the same convention as the real DINO bench's SW1
-- (docs/notes/microcode_gen.py:137 / progrom_gen.py's IN_SW comment:
-- R17-R24 pull IS0-7 high, a CLOSED switch pulls its bit LOW). dino_core's
-- dip_sw port already expects THAT polarity (Task 10's module contract),
-- so this shell wires dip straight through with NO inversion. If bench
-- bring-up on real Versa hardware ever shows the mapping backwards (wrong
-- board revision, wrong guide, etc.), flip it here to `dip_sw => not dip`
-- and update this comment -- do not silently invert deeper in dino_core.
--
-- halt disposition: dino_core's `halt` output is deliberately NOT routed
-- to any top-level pin in this shell (kept as a dangling internal signal,
-- see halt_nc below). Every one of the 8 physical LEDs is already spoken
-- for by ob_led (CLAUDE.md: OB is the bench's own observable, and this
-- shell preserves that 1:1). HALT remains observable exactly the way the
-- bench already reads it -- OB freezes and stays frozen -- without
-- borrowing a segment display or stealing an OB bit. NC, not an oversight.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity versa_top is
  generic (
    -- Program-ROM (U24/AT28C256) init hex, fpga/-relative (dino_core's
    -- own u24_init_file default convention, Task 8). Overridden per
    -- image tag at synthesis time via the yosys `ghdl` command's own
    -- -g<generic>=<value> passthrough (fpga/Makefile's `bit` target) --
    -- e.g. -gPROG_HEX=sim/hex/PROG_alu.hex for IMAGE=alu. The microcode
    -- (u9/u15) and RAM (u26) generics are left at dino_core's own
    -- defaults: every image tag shares the SAME burned microcode, and
    -- RAM always starts blank, on the real board same as in sim.
    PROG_HEX : string := "sim/hex/PROG.hex"
  );
  port (
    clk100 : in  std_logic;                     -- P3, LVDS, board 100MHz osc
    rst_n  : in  std_logic;                     -- T1, LVCMOS33, active-low button
    dip    : in  std_logic_vector(7 downto 0);  -- H2 K3 G3 F2 J18 K18 K19 K20
    led    : out std_logic_vector(7 downto 0)   -- E16 D17 D18 E18 F17 F18 E17 F16
  );
end entity versa_top;

architecture rtl of versa_top is

  -- Lattice ECP5 hard PLL. Declared as an unbound component so GHDL leaves
  -- it as a black box at import; yosys binds it by name against
  -- +/lattice/cells_bb.v (read in by synth_ecp5's own `begin` label) and
  -- nextpnr places it in one of the four EHXPLLL sites. Generic values are
  -- ecppll's own solution for 100MHz -> 12MHz, verbatim:
  --     $ ecppll -i 100 -o 12
  --     Refclk divisor: 25   Feedback divisor: 3   clkout0 divisor: 50
  --     VCO frequency: 600            (inside the 400-800MHz legal band)
  -- Only the ports actually used are declared; everything else on the
  -- primitive is left off the component and therefore unconnected.
  component EHXPLLL is
    generic (
      PLLRST_ENA      : string  := "DISABLED";
      INTFB_WAKE      : string  := "DISABLED";
      STDBY_ENABLE    : string  := "DISABLED";
      DPHASE_SOURCE   : string  := "DISABLED";
      OUTDIVIDER_MUXA : string  := "DIVA";
      OUTDIVIDER_MUXB : string  := "DIVB";
      OUTDIVIDER_MUXC : string  := "DIVC";
      OUTDIVIDER_MUXD : string  := "DIVD";
      CLKI_DIV        : integer := 1;
      CLKOP_ENABLE    : string  := "ENABLED";
      CLKOP_DIV       : integer := 1;
      CLKOP_CPHASE    : integer := 0;
      CLKOP_FPHASE    : integer := 0;
      FEEDBK_PATH     : string  := "CLKOP";
      CLKFB_DIV       : integer := 1
    );
    port (
      CLKI         : in  std_logic;
      CLKFB        : in  std_logic;
      RST          : in  std_logic;
      STDBY        : in  std_logic;
      PHASESEL0    : in  std_logic;
      PHASESEL1    : in  std_logic;
      PHASEDIR     : in  std_logic;
      PHASESTEP    : in  std_logic;
      PHASELOADREG : in  std_logic;
      PLLWAKESYNC  : in  std_logic;
      ENCLKOP      : in  std_logic;
      CLKOP        : out std_logic;
      LOCK         : out std_logic
    );
  end component EHXPLLL;

  signal clk_sys    : std_logic;
  signal pll_locked : std_logic;
  signal core_rst_n : std_logic;
  signal por_count  : unsigned(15 downto 0) := (others => '0');
  signal por_done   : std_logic;
  signal clk4m_y1   : std_logic;
  signal ob_led     : std_logic_vector(7 downto 0);
  signal halt_nc    : std_logic;  -- dino_core's halt output; see header comment

  -- /25 divider state. The RATIO is what is fixed and sim-verified, not
  -- the absolute rate: at the 12MHz clk_sys this shell now runs (see the
  -- header), clk4m_y1 is 480kHz, not the 4MHz the name and Task 13's
  -- clk_sys = clk100 wiring implied -- and U20's own /4 after it puts the
  -- machine's CLK at 120kHz. Mirrors
  -- fpga/sim/conftest_helpers.py's _drive_clk4m_y1 EXACTLY (Y1_DIVIDE=25,
  -- Y1_LOW_CYCLES=13, Y1_HIGH_CYCLES=12) so the fabric's edge cadence
  -- matches the already sim-verified cadence bit-for-bit -- only the
  -- EDGES matter to U20's cp input, so the asymmetric duty cycle (13 low
  -- / 12 high, not a clean 50%) is a deliberate match, not a shortcut.
  signal div_count : unsigned(4 downto 0) := (others => '0');  -- 0..24

begin

  pll_i : EHXPLLL
    generic map (
      PLLRST_ENA      => "DISABLED",
      INTFB_WAKE      => "DISABLED",
      STDBY_ENABLE    => "DISABLED",
      DPHASE_SOURCE   => "DISABLED",
      OUTDIVIDER_MUXA => "DIVA",
      OUTDIVIDER_MUXB => "DIVB",
      OUTDIVIDER_MUXC => "DIVC",
      OUTDIVIDER_MUXD => "DIVD",
      CLKI_DIV        => 25,
      CLKOP_ENABLE    => "ENABLED",
      CLKOP_DIV       => 50,
      CLKOP_CPHASE    => 24,
      CLKOP_FPHASE    => 0,
      FEEDBK_PATH     => "CLKOP",
      CLKFB_DIV       => 3
    )
    port map (
      CLKI         => clk100,
      CLKFB        => clk_sys,
      RST          => '0',
      STDBY        => '0',
      PHASESEL0    => '0',
      PHASESEL1    => '0',
      PHASEDIR     => '1',
      PHASESTEP    => '1',
      PHASELOADREG => '1',
      PLLWAKESYNC  => '0',
      ENCLKOP      => '0',
      CLKOP        => clk_sys,
      LOCK         => pll_locked
    );

  -- Hold the machine in reset briefly at power-up, then release. This was
  -- originally gated on the PLL's LOCK output -- BENCH-DISPROVEN 2026-08-09:
  -- on the real board LOCK never asserts even though CLKOP runs at exactly
  -- the programmed 12MHz (diag_top.vhd showed clk100 alive, clk_sys alive
  -- at the right rate, rst_n high, LOCK stuck low -- the known-flaky ECP5
  -- open-toolchain LOCK corner). Gating on LOCK therefore held DINO in
  -- reset forever: OB=0x00, all LEDs dark. The deterministic replacement:
  -- a power-on counter on clk_sys holds reset for 2^16 clk_sys cycles
  -- (~5.5ms at 12MHz -- orders of magnitude past real PLL settling), then
  -- releases. The board button still resets any time (active-low AND).
  -- pll_locked stays connected for observability but gates nothing.
  por : process(clk_sys)
  begin
    if rising_edge(clk_sys) then
      if por_count /= x"FFFF" then
        por_count <= por_count + 1;
      end if;
    end if;
  end process;
  core_rst_n <= rst_n and por_done;
  por_done   <= '1' when por_count = x"FFFF" else '0';

  divide_y1 : process(clk_sys)
  begin
    if rising_edge(clk_sys) then
      if div_count = 24 then
        div_count <= (others => '0');
      else
        div_count <= div_count + 1;
      end if;
    end if;
  end process divide_y1;

  clk4m_y1 <= '0' when div_count < 13 else '1';

  dino_core_i : entity work.dino_core
    generic map (
      u24_init_file => PROG_HEX
    )
    port map (
      clk_sys     => clk_sys,
      clk4m_y1    => clk4m_y1,
      dip_sw      => dip,          -- pass-through; see polarity note above
      btn_reset_n => core_rst_n,   -- board button (already active-low) AND pll_locked
      ob_led      => ob_led,
      halt        => halt_nc       -- NC at the board boundary; see header comment
    );

  -- LEDs are active-low on the Versa (EB103/EB98 User Guide: LEDs
  -- illuminate when driven LOW). ob_led itself is the machine's native
  -- active-high OB byte (same sense the bench LEDs already read), so
  -- invert exactly once, here, at the board boundary.
  led <= not ob_led;

end architecture rtl;
