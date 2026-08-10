import cocotb
from cocotb.triggers import Timer

# Exhaustive testbench for the '382 4-bit ALU (Task 4): all 8 select codes x
# all 256 (a, b) pairs x both carry-in values = 4096 vectors. Expected F,
# Cn+4, OVR are computed in Python, independently of the VHDL, from the
# 74F382 datasheet (datasheets/74F382.pdf) -- NOT from memory (CLAUDE.md
# rule 5's spirit applied to a datasheet instead of a netlist):
#
# - The Function Select Table (datasheet p2) and design note section 1
#   fix the op<->S2:S1:S0 mapping (both agree, no conflict -- see the
#   task-4 report for the cross-check): op = S2*4 + S1*2 + S0, i.e. op IS
#   the 3-bit S2:S1:S0 word read as a binary number.
# - The three arithmetic ops (BSUB=1 B-A, SUB=2 A-B, ADD=3 A+B) were
#   validated bit-exact against ALL 8 rows of each of the datasheet's
#   "B MINUS A" / "A MINUS B" / "A PLUS B" Truth Table sections (24 rows
#   total) using the standard "subtrahend complemented, Cn active-high
#   borrow-free" convention: F = X + Y + Cn (mod 16), Cn+4 = bit 4 of that
#   5-bit sum, where (X, Y) = (B, ~A) for BSUB, (A, ~B) for SUB, (A, B)
#   for ADD. OVR = XOR of the carry INTO bit 3 (computed the same way,
#   ripple of the low 3 bits) and Cn+4 -- matches the datasheet prose
#   ("OVR is the Exclusive-OR of Cn+3 and Cn+4") and every sampled row.
# - CLEAR (op 0) and PRESET (op 7) force F to 0x0/0xF per the design note
#   ("free" ops). CLEAR additionally forces OVR=1, Cn+4=1 unconditionally
#   -- datasheet's "CLEAR" truth-table rows show this fixed regardless of
#   Cn/An/Bn (both listed as "X", immaterial).
# - XOR/OR/AND (ops 4/5/6) and PRESET (op 7) do NOT follow "OVR = C3 xor
#   C4": re-deriving Cn+4 from the datasheet's 5-row-per-function samples
#   (2 representative nibble values, 0x0 and 0xF, per operand -- the
#   datasheet's own reduction, not this test's) via C(i+1)=G(i)+P(i)*C(i)
#   shows each op has its own generate/propagate pair, and in EVERY
#   sampled row (20/20) OVR literally equals Cn+4, not C3^C4. This is a
#   documented deviation from the task-4 brief's shorthand ("OVR from
#   bit3/bit4 carry disagreement") -- the brief's phrasing turned out not
#   to hold for the five non-arithmetic ops once checked against the
#   datasheet; the datasheet wins (design note is silent on this point).
#   Per-bit formulas recovered (all matched 5/5 rows for their op):
#     XOR: C(i+1) = A(i) AND (B(i) OR C(i))
#     OR:  C(i+1) = A(i) AND B(i) AND C(i)
#     AND: C(i+1) = NOT(B(i)) OR (A(i) AND C(i))
#     PRESET: same recurrence as OR
#   See the task-4 report for the full row-by-row derivation.


def _ripple(a, b, cin, step):
    """4-bit ripple carry using per-bit recurrence `step(ai, bi, ci) -> c(i+1)`.
    Returns the carry out of bit 3 (== Cn+4)."""
    c = cin
    for i in range(4):
        ai = (a >> i) & 1
        bi = (b >> i) & 1
        c = step(ai, bi, c)
    return c & 1


def expected(op, a, b, cin):
    """Reference model, independent of the VHDL. op: 0-7 (S2:S1:S0 as a
    binary number). a, b: 0-15. cin: 0/1. Returns (f, cn4, ovr)."""
    if op == 0:  # CLEAR
        return 0x0, 1, 1
    if op == 7:  # PRESET
        cn4 = _ripple(a, b, cin, lambda ai, bi, c: ai & bi & c)
        return 0xF, cn4, cn4
    if op == 4:  # XOR
        cn4 = _ripple(a, b, cin, lambda ai, bi, c: ai & (bi | c))
        return (a ^ b) & 0xF, cn4, cn4
    if op == 5:  # OR
        cn4 = _ripple(a, b, cin, lambda ai, bi, c: ai & bi & c)
        return (a | b) & 0xF, cn4, cn4
    if op == 6:  # AND
        cn4 = _ripple(a, b, cin, lambda ai, bi, c: ((~bi) & 1) | (ai & c))
        return (a & b) & 0xF, cn4, cn4
    # Arithmetic: BSUB=1 (B-A), SUB=2 (A-B), ADD=3 (A+B) -- subtrahend
    # complemented, Cn is the carry/borrow-free-1 convention.
    if op == 1:
        x, y = b, (~a) & 0xF
    elif op == 2:
        x, y = a, (~b) & 0xF
    else:
        x, y = a, b
    sum5 = x + y + cin
    f = sum5 & 0xF
    cn4 = (sum5 >> 4) & 1
    low3 = (x & 0x7) + (y & 0x7) + cin
    c3 = (low3 >> 3) & 1
    ovr = c3 ^ cn4
    return f, cn4, ovr


@cocotb.test()
async def alu_exhaustive(dut):
    for op in range(8):
        s0 = op & 1
        s1 = (op >> 1) & 1
        s2 = (op >> 2) & 1
        dut.s0.value = s0
        dut.s1.value = s1
        dut.s2.value = s2
        for a in range(16):
            dut.a0.value = a & 1
            dut.a1.value = (a >> 1) & 1
            dut.a2.value = (a >> 2) & 1
            dut.a3.value = (a >> 3) & 1
            for b in range(16):
                dut.b0.value = b & 1
                dut.b1.value = (b >> 1) & 1
                dut.b2.value = (b >> 2) & 1
                dut.b3.value = (b >> 3) & 1
                for cin in (0, 1):
                    dut.cn.value = cin
                    await Timer(1, unit="ns")
                    f, cn4, ovr = expected(op, a, b, cin)
                    got_f = (int(dut.f0.value) | (int(dut.f1.value) << 1) |
                             (int(dut.f2.value) << 2) | (int(dut.f3.value) << 3))
                    got_cn4 = int(dut.cn4.value)
                    got_ovr = int(dut.ovr.value)
                    assert got_f == f, (
                        f"F: op={op} a=0x{a:X} b=0x{b:X} cin={cin} "
                        f"-> F=0x{got_f:X}, want 0x{f:X}"
                    )
                    assert got_cn4 == cn4, (
                        f"Cn+4: op={op} a=0x{a:X} b=0x{b:X} cin={cin} "
                        f"-> Cn+4={got_cn4}, want {cn4}"
                    )
                    assert got_ovr == ovr, (
                        f"OVR: op={op} a=0x{a:X} b=0x{b:X} cin={cin} "
                        f"-> OVR={got_ovr}, want {ovr}"
                    )
