library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

-- 4-bit ALU. Ports are individual std_logic pins matching PIN_MAP's real,
-- netlist-derived names verbatim (dino_v0_0_2/alu.kicad_sch, 74F382PC_1_0
-- lib_symbols block, every pin drawn plain "line" -- no active-low bubble
-- anywhere on this part, see fpga_gen.py's PIN_MAP["74F382"] comment).
-- op = s2 & s1 & s0 read as a 3-bit binary number selects the function,
-- per the datasheet's Function Select Table AND
-- docs/notes/dino_alu_74f382_design.md section 1 (both agree -- see the
-- task-4 report for the row-by-row cross-check against the datasheet's
-- Truth Table, all 40 published rows):
--   0 CLEAR (F=0x0, forced)      4 A XOR B
--   1 B MINUS A (B - A)          5 A OR B   (old notation "A + B")
--   2 A MINUS B (A - B)          6 A AND B  (old notation "AB")
--   3 A PLUS B  (A + B)          7 PRESET (F=0xF, forced)
--
-- Arithmetic ops (1-3): 74F382 convention is "subtrahend complemented,
-- carry active-high borrow-free" -- F = X + Y + Cn (mod 16) where
-- (X, Y) = (B, NOT A) for BSUB, (A, NOT B) for SUB, (A, B) for ADD.
-- Cn+4 is bit 4 of that 5-bit sum. OVR is the XOR of Cn+4 and the carry
-- INTO bit 3 (computed the same way over the low 3 bits) -- matches the
-- datasheet's own description ("OVR is the Exclusive-OR of Cn+3 and
-- Cn+4") and every one of the 24 published B-MINUS-A/A-MINUS-B/A-PLUS-B
-- truth-table rows.
--
-- CLEAR/logic/PRESET (0, 4, 5, 6, 7): F is computed (or forced) directly,
-- with NO dependence on Cn -- matches every published row for these five
-- functions (F never varies with Cn there). Cn+4/OVR do NOT follow the
-- arithmetic-op "Cn+3 xor Cn+4" rule for these five; re-deriving Cn+4
-- from the datasheet's own 5-row-per-function samples (each op tested at
-- the representative nibble values A,B in {0x0, 0xF}) via the standard
-- ripple-carry recurrence C(i+1) = G(i) + P(i)*C(i) shows OVR literally
-- equals Cn+4 in all 20 of those rows (not C3 xor C4) -- a documented
-- deviation from the task-4 brief's shorthand ("OVR from bit3/bit4 carry
-- disagreement"), which does not hold for these five ops once checked
-- against the datasheet (the design note is silent on this point, so the
-- datasheet -- the chip's own ground truth -- wins). Per-bit generate/
-- propagate recovered per op (all matched 5/5 rows, see fpga/ttl/
-- test_74f382.py's header for the row-by-row working):
--   CLEAR:   Cn+4 = 1, OVR = 1, always (A/B/Cn-independent)
--   XOR:     C(i+1) = A(i) AND (B(i) OR C(i))
--   OR:      C(i+1) = A(i) AND B(i) AND C(i)
--   AND:     C(i+1) = NOT(B(i)) OR (A(i) AND C(i))
--   PRESET:  same recurrence as OR
-- and OVR = Cn+4 for all five.
entity ttl_74f382 is
  port (
    a0  : in  std_logic;
    a1  : in  std_logic;
    a2  : in  std_logic;
    a3  : in  std_logic;
    b0  : in  std_logic;
    b1  : in  std_logic;
    b2  : in  std_logic;
    b3  : in  std_logic;
    s0  : in  std_logic;
    s1  : in  std_logic;
    s2  : in  std_logic;
    cn  : in  std_logic;
    f0  : out std_logic;
    f1  : out std_logic;
    f2  : out std_logic;
    f3  : out std_logic;
    cn4 : out std_logic;
    ovr : out std_logic);
end entity;

architecture rtl of ttl_74f382 is
begin
  process (a0, a1, a2, a3, b0, b1, b2, b3, s0, s1, s2, cn)
    -- x + y + cin (mod 16) via a 5-bit unsigned add, sharing one code path
    -- for BSUB/SUB/ADD (the only difference between the three is which
    -- (x, y) pair the caller passes in -- see the entity header comment).
    procedure add4 (x, y : unsigned(3 downto 0); cin : std_logic;
                     f_v : out unsigned(3 downto 0);
                     cn4_v, ovr_v : out std_logic) is
      variable sum5 : unsigned(4 downto 0);
      variable low3 : unsigned(3 downto 0);
    begin
      sum5  := resize(x, 5) + resize(y, 5) + resize("" & cin, 5);
      f_v   := sum5(3 downto 0);
      cn4_v := sum5(4);
      low3  := resize(x(2 downto 0), 4) + resize(y(2 downto 0), 4)
               + resize("" & cin, 4);
      ovr_v := low3(3) xor cn4_v;
    end procedure;

    variable a, b  : unsigned(3 downto 0);
    variable op    : unsigned(2 downto 0);
    variable f_v   : unsigned(3 downto 0);
    variable cn4_v : std_logic;
    variable ovr_v : std_logic;
    variable c     : std_logic;
    variable ai, bi : std_logic;
  begin
    a := a3 & a2 & a1 & a0;
    b := b3 & b2 & b1 & b0;
    op := s2 & s1 & s0;

    case op is
      when "000" =>                    -- CLEAR
        f_v   := "0000";
        cn4_v := '1';
        ovr_v := '1';

      when "111" =>                    -- PRESET
        f_v := "1111";
        c := cn;
        for i in 0 to 3 loop
          ai := a(i);
          bi := b(i);
          c := (ai and bi and c);
        end loop;
        cn4_v := c;
        ovr_v := c;

      when "100" =>                    -- XOR
        f_v := a xor b;
        c := cn;
        for i in 0 to 3 loop
          ai := a(i);
          bi := b(i);
          c := (ai and (bi or c));
        end loop;
        cn4_v := c;
        ovr_v := c;

      when "101" =>                    -- OR
        f_v := a or b;
        c := cn;
        for i in 0 to 3 loop
          ai := a(i);
          bi := b(i);
          c := (ai and bi and c);
        end loop;
        cn4_v := c;
        ovr_v := c;

      when "110" =>                    -- AND
        f_v := a and b;
        c := cn;
        for i in 0 to 3 loop
          ai := a(i);
          bi := b(i);
          c := ((not bi) or (ai and c));
        end loop;
        cn4_v := c;
        ovr_v := c;

      when "001" =>                    -- BSUB: B - A = B + NOT(A) + Cn
        add4(b, not a, cn, f_v, cn4_v, ovr_v);

      when "010" =>                    -- SUB: A - B = A + NOT(B) + Cn
        add4(a, not b, cn, f_v, cn4_v, ovr_v);

      when others =>                   -- "011" ADD: A + B + Cn
        add4(a, b, cn, f_v, cn4_v, ovr_v);
    end case;

    f0 <= f_v(0);
    f1 <= f_v(1);
    f2 <= f_v(2);
    f3 <= f_v(3);
    cn4 <= cn4_v;
    ovr <= ovr_v;
  end process;
end architecture;
