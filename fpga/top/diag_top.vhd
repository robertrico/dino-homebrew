-- Bring-up diagnostic shell: answers, in one bitstream, the three
-- questions the cylon no-LED symptom cannot separate:
--   led(0)  blinks ~1.5Hz from clk100 directly  -> LVDS clock reaches fabric
--   led(1)  blinks ~1.5Hz from PLL clk_sys      -> PLL produces a clock
--   led(6)  ON iff rst_n pin reads HIGH          -> button line level at rest
--   led(7)  ON iff PLL LOCK is asserted          -> LOCK works in silicon
--   led(5 downto 2) OFF (driven, not floating)
-- LEDs are active-low on the Versa; inverted here so ON means TRUE.
-- Same EHXPLLL instantiation as versa_top.vhd, verbatim generics.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity diag_top is
  port (
    clk100 : in  std_logic;
    rst_n  : in  std_logic;
    led    : out std_logic_vector(7 downto 0));
end entity;

architecture rtl of diag_top is
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
  signal cnt100     : unsigned(25 downto 0) := (others => '0');  -- 2^26/100MHz ~ 0.67s period MSB
  signal cnt12      : unsigned(22 downto 0) := (others => '0');  -- 2^23/12MHz  ~ 0.70s period MSB
begin

  pll_i : EHXPLLL
    generic map (
      CLKI_DIV     => 25,
      CLKOP_ENABLE => "ENABLED",
      CLKOP_DIV    => 50,
      CLKOP_CPHASE => 24,
      CLKOP_FPHASE => 0,
      FEEDBK_PATH  => "CLKOP",
      CLKFB_DIV    => 3
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

  tick100 : process(clk100)
  begin
    if rising_edge(clk100) then
      cnt100 <= cnt100 + 1;
    end if;
  end process;

  tick12 : process(clk_sys)
  begin
    if rising_edge(clk_sys) then
      cnt12 <= cnt12 + 1;
    end if;
  end process;

  -- Active-low LEDs: invert once so lit = '1' = TRUE.
  led(0) <= not std_logic(cnt100(cnt100'high));
  led(1) <= not std_logic(cnt12(cnt12'high));
  led(2) <= '1';                    -- driven OFF
  led(3) <= '1';
  led(4) <= '1';
  led(5) <= '1';
  led(6) <= not rst_n;              -- lit iff rst_n reads HIGH
  led(7) <= not pll_locked;         -- lit iff LOCK asserted
end architecture;
