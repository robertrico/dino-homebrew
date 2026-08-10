import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# Stateful-model testbenches (Task 5): '74 dual D flip-flop, '163 sync
# counter, '193 async up/down counter, '273 async octal register, '373
# transparent octal latch. All five share the SAME architectural core: a
# hidden 100MHz clk_sys the DUT's own "clock"/"latch" pin is sampled
# against through a 2-flop synchronizer + edge/level detector -- NO fabric
# register in any of these models clocks directly on the modeled logic
# net (task-5-brief.md's central rule). The Makefile's COCOTB_TEST_FILTER
# selects the one test valid for whichever MODEL is being built, same
# mechanism as test_gates.py/test_msi.py/test_74f382.py.
#
# Timing discipline (brief's own warning): clk_sys is 100MHz (10ns
# period), so the 2-flop sync + edge detect needs >=2 clk_sys ticks (20ns)
# after a real pin transition before the detector fires, and up to a
# further clk_sys tick for a downstream effect to be visible -- call it
# >=3 cycles (30ns) minimum. Every stimulus change below is followed by a
# SETTLE (50ns, 5 clk_sys cycles) before any assertion reads a result, and
# "machine clock" pins (cp/clk/up/down/le) are held at each level for
# HOLD (250ns) -- a realistic ~500ns-period machine clock, not a race
# against the synchronizer.
SETTLE = 50  # ns -- >3 clk_sys cycles, comfortably clears the 2-flop sync
HOLD = 250   # ns -- half-period of a slow, machine-realistic "clock" pin


async def _start(dut):
    cocotb.start_soon(Clock(dut.clk_sys, 10, unit="ns").start())
    await Timer(SETTLE, unit="ns")


async def _settle(dut):
    await Timer(SETTLE, unit="ns")


async def _hold(dut):
    await Timer(HOLD, unit="ns")


def _set_bus(dut, prefix, n, val):
    for i in range(n):
        getattr(dut, f"{prefix}{i}").value = (val >> i) & 1


def _read_bus(dut, prefix, n):
    v = 0
    for i in range(n):
        v |= (int(getattr(dut, f"{prefix}{i}").value) & 1) << i
    return v


# --- '74: dual D flip-flop -----------------------------------------------

@cocotb.test()
async def ff74_edge_and_async(dut):
    await _start(dut)

    # Start quiescent: no async assert, clock low, D=0.
    dut.pre1_n.value = 1
    dut.clr1_n.value = 1
    dut.d1.value = 0
    dut.clk1.value = 0
    await _hold(dut)

    # D captured on CLK RISE only. Set D=1, rise CLK -> Q must follow.
    dut.d1.value = 1
    await _hold(dut)
    dut.clk1.value = 1
    await _hold(dut)
    assert dut.q1.value == 1, f"q1: after D=1 CLK rise -> {dut.q1.value}, want 1"
    assert dut.q1_n.value == 0, f"q1_n: after D=1 CLK rise -> {dut.q1_n.value}, want 0"

    # Now change D while CLK is HIGH and steady, then bring CLK back down
    # (a FALL, not a rise) -- Q must NOT follow this new D; only a RISE
    # captures.
    dut.d1.value = 0
    await _hold(dut)
    dut.clk1.value = 0  # falling edge
    await _hold(dut)
    assert dut.q1.value == 1, (
        f"q1: CLK FALL with D=0 changed Q to {dut.q1.value}, want unchanged 1 "
        f"(capture must be rising-edge only)"
    )

    # PRE_n asynchronous dominance: CLK held low (no edge), PRE_n asserted
    # -> Q forced 1 immediately, no clock edge required.
    dut.clr1_n.value = 1
    dut.d1.value = 0
    dut.pre1_n.value = 0
    await _settle(dut)
    assert dut.q1.value == 1, f"q1: PRE_n=0 (no CLK edge) -> {dut.q1.value}, want 1"
    dut.pre1_n.value = 1
    await _settle(dut)

    # CLR_n asynchronous dominance: CLK held low, CLR_n asserted -> Q
    # forced 0 immediately.
    dut.clr1_n.value = 0
    await _settle(dut)
    assert dut.q1.value == 0, f"q1: CLR_n=0 (no CLK edge) -> {dut.q1.value}, want 0"
    assert dut.q1_n.value == 1, f"q1_n: CLR_n=0 -> {dut.q1_n.value}, want 1"

    # Both asserted together: PRE_n wins (brief's canonical priority order
    # checks pre1_n first).
    dut.pre1_n.value = 0
    dut.clr1_n.value = 0
    await _settle(dut)
    assert dut.q1.value == 1, (
        f"q1: PRE_n=0 AND CLR_n=0 -> {dut.q1.value}, want 1 (PRE dominates)"
    )
    # Releasing PRE_n/CLR_n leaves Q1 holding whichever won (PRE, so 1) --
    # drive FF1 to a known, DIFFERENT-from-FF2's-target state before the
    # independence check below, so a real cross-wire would be caught.
    dut.pre1_n.value = 1
    dut.clr1_n.value = 0
    await _settle(dut)
    dut.clr1_n.value = 1
    await _settle(dut)
    assert dut.q1.value == 0, f"q1: setup for independence check -> {dut.q1.value}, want 0"

    # Second flip-flop is independent -- same behaviour on its own pins.
    dut.pre2_n.value = 1
    dut.clr2_n.value = 1
    dut.d2.value = 1
    dut.clk2.value = 0
    await _hold(dut)
    dut.clk2.value = 1
    await _hold(dut)
    assert dut.q2.value == 1, f"q2: after D=1 CLK rise -> {dut.q2.value}, want 1"
    assert dut.q1.value == 0, "q1/q2 aren't independent -- FF1 state leaked into FF2's test"


# --- '163: synchronous 4-bit counter --------------------------------------

@cocotb.test()
async def counter163_sync(dut):
    await _start(dut)

    dut.mr_n.value = 1
    dut.pe_n.value = 1
    dut.cep.value = 1
    dut.cet.value = 1
    _set_bus(dut, "d", 4, 0)
    dut.cp.value = 0
    await _hold(dut)

    # Load a known nonzero value first (D=0101) via synchronous load, so
    # the "no edge -> unchanged" clear check below isn't vacuously true
    # against a reset-default zero.
    dut.pe_n.value = 0
    _set_bus(dut, "d", 4, 0b0101)
    dut.cp.value = 1
    await _hold(dut)
    got = _read_bus(dut, "q", 4)
    assert got == 0b0101, f"q: after sync load D=0101 -> {got:04b}, want 0101"
    dut.cp.value = 0
    dut.pe_n.value = 1
    await _hold(dut)

    # Synchronous clear, part 1: CLR_n asserted but held with NO clock
    # edge -> count must stay UNCHANGED (this is what makes it
    # synchronous, not asynchronous like '273's MR_n).
    dut.mr_n.value = 0
    await _settle(dut)
    got = _read_bus(dut, "q", 4)
    assert got == 0b0101, (
        f"q: MR_n=0 held with NO CP edge -> {got:04b}, want unchanged 0101 "
        f"(clear is synchronous -- must not fire without an edge)"
    )

    # Synchronous clear, part 2: same CLR_n=0, now WITH a clock edge -> 0.
    dut.cp.value = 1
    await _hold(dut)
    got = _read_bus(dut, "q", 4)
    assert got == 0, f"q: MR_n=0 + CP rise -> {got:04b}, want 0000"
    dut.cp.value = 0
    dut.mr_n.value = 1
    await _hold(dut)

    # Count only when CEP AND CET are both asserted -- test each held low
    # individually and confirm no count, then both high and confirm count.
    dut.cep.value = 0
    dut.cet.value = 1
    dut.cp.value = 1
    await _hold(dut)
    got = _read_bus(dut, "q", 4)
    assert got == 0, f"q: CEP=0 CET=1 + CP rise -> {got:04b}, want unchanged 0000"
    dut.cp.value = 0
    await _hold(dut)

    dut.cep.value = 1
    dut.cet.value = 0
    dut.cp.value = 1
    await _hold(dut)
    got = _read_bus(dut, "q", 4)
    assert got == 0, f"q: CEP=1 CET=0 + CP rise -> {got:04b}, want unchanged 0000"
    dut.cp.value = 0
    await _hold(dut)

    dut.cep.value = 1
    dut.cet.value = 1
    dut.cp.value = 1
    await _hold(dut)
    got = _read_bus(dut, "q", 4)
    assert got == 1, f"q: CEP=1 CET=1 + CP rise -> {got:04b}, want 0001 (count)"
    dut.cp.value = 0
    await _hold(dut)

    # RCO (TC) at 15: load 1111 via sync load, CET=1 -> TC='1'
    # combinationally (no further CP edge needed once loaded); dropping
    # CET alone (no CP edge) must drop TC immediately too.
    dut.pe_n.value = 0
    _set_bus(dut, "d", 4, 0b1111)
    dut.cp.value = 1
    await _hold(dut)
    dut.cp.value = 0
    dut.pe_n.value = 1
    await _hold(dut)
    got = _read_bus(dut, "q", 4)
    assert got == 0b1111, f"q: after loading 1111 -> {got:04b}"
    assert dut.tc.value == 1, f"tc: q=1111 CET=1 -> {dut.tc.value}, want 1"

    dut.cet.value = 0
    await _settle(dut)
    assert dut.tc.value == 0, (
        f"tc: CET dropped to 0 (no CP edge) -> {dut.tc.value}, want 0 "
        f"(TC is combinational in CET, not clocked)"
    )
    dut.cet.value = 1
    await _settle(dut)
    assert dut.tc.value == 1, f"tc: CET restored to 1 -> {dut.tc.value}, want 1"


# --- '193: async load/clear, dual up/down clocks --------------------------

@cocotb.test()
async def counter193_async(dut):
    await _start(dut)

    dut.clr.value = 0
    dut.load_n.value = 1
    dut.up.value = 1
    dut.down.value = 1
    dut.a.value = 0
    dut.b.value = 0
    dut.c.value = 0
    dut.d.value = 0
    await _hold(dut)

    # Asynchronous LOAD: LOAD_n low loads D/C/B/A into Q IMMEDIATELY, no
    # clock edge on either UP or DOWN.
    dut.a.value = 1  # A=1,B=0,C=1,D=0 -> QA=1 QB=0 QC=1 QD=0 = 0b0101
    dut.c.value = 1
    dut.load_n.value = 0
    await _settle(dut)
    got = (int(dut.qa.value) | (int(dut.qb.value) << 1)
           | (int(dut.qc.value) << 2) | (int(dut.qd.value) << 3))
    assert got == 0b0101, (
        f"q: LOAD_n=0 A=1 B=0 C=1 D=0, NO clock edge -> {got:04b}, want 0101"
    )
    dut.load_n.value = 1
    await _settle(dut)

    # Asynchronous CLR (active HIGH): asserted with no clock edge -> 0
    # immediately.
    dut.clr.value = 1
    await _settle(dut)
    got = (int(dut.qa.value) | (int(dut.qb.value) << 1)
           | (int(dut.qc.value) << 2) | (int(dut.qd.value) << 3))
    assert got == 0, f"q: CLR=1, NO clock edge -> {got:04b}, want 0000"
    dut.clr.value = 0
    await _settle(dut)

    # Count UP: DOWN held high (idle), pulse UP rising edge.
    dut.down.value = 1
    dut.up.value = 0
    await _hold(dut)
    dut.up.value = 1
    await _hold(dut)
    got = (int(dut.qa.value) | (int(dut.qb.value) << 1)
           | (int(dut.qc.value) << 2) | (int(dut.qd.value) << 3))
    assert got == 1, f"q: UP rising edge from 0000 -> {got:04b}, want 0001"

    # Count DOWN: UP held high (idle), pulse DOWN rising edge -> back to 0.
    dut.up.value = 1
    dut.down.value = 0
    await _hold(dut)
    dut.down.value = 1
    await _hold(dut)
    got = (int(dut.qa.value) | (int(dut.qb.value) << 1)
           | (int(dut.qc.value) << 2) | (int(dut.qd.value) << 3))
    assert got == 0, f"q: DOWN rising edge from 0001 -> {got:04b}, want 0000"

    # Carry (CO_n): load 1111, hold DOWN high (idle); CO_n low iff UP is
    # currently LOW while count=15 -- combinational, no clock edge.
    dut.a.value = 1
    dut.b.value = 1
    dut.c.value = 1
    dut.d.value = 1
    dut.load_n.value = 0
    await _settle(dut)
    dut.load_n.value = 1
    await _settle(dut)
    got = (int(dut.qa.value) | (int(dut.qb.value) << 1)
           | (int(dut.qc.value) << 2) | (int(dut.qd.value) << 3))
    assert got == 0b1111, f"q: after async load 1111 -> {got:04b}"

    dut.up.value = 1
    await _settle(dut)
    assert dut.co_n.value == 1, f"co_n: q=1111 UP=1 -> {dut.co_n.value}, want 1 (not asserted)"
    dut.up.value = 0
    await _settle(dut)
    assert dut.co_n.value == 0, f"co_n: q=1111 UP=0 -> {dut.co_n.value}, want 0 (asserted)"
    dut.up.value = 1
    await _settle(dut)

    # Borrow (BO_n): load 0000, hold UP high (idle); BO_n low iff DOWN is
    # currently LOW while count=0.
    dut.a.value = 0
    dut.b.value = 0
    dut.c.value = 0
    dut.d.value = 0
    dut.load_n.value = 0
    await _settle(dut)
    dut.load_n.value = 1
    await _settle(dut)
    got = (int(dut.qa.value) | (int(dut.qb.value) << 1)
           | (int(dut.qc.value) << 2) | (int(dut.qd.value) << 3))
    assert got == 0, f"q: after async load 0000 -> {got:04b}"

    dut.down.value = 1
    await _settle(dut)
    assert dut.bo_n.value == 1, f"bo_n: q=0000 DOWN=1 -> {dut.bo_n.value}, want 1 (not asserted)"
    dut.down.value = 0
    await _settle(dut)
    assert dut.bo_n.value == 0, f"bo_n: q=0000 DOWN=0 -> {dut.bo_n.value}, want 0 (asserted)"


# --- '273: octal register, async MR_n --------------------------------------

@cocotb.test()
async def register273_async_clear(dut):
    await _start(dut)

    dut.mr_n.value = 1
    _set_bus(dut, "d", 8, 0)
    dut.cp.value = 0
    await _hold(dut)

    # Normal capture on CLK rise.
    _set_bus(dut, "d", 8, 0xA5)
    dut.cp.value = 1
    await _hold(dut)
    got = _read_bus(dut, "q", 8)
    assert got == 0xA5, f"q: after D=0xA5 CP rise -> 0x{got:02X}, want 0xA5"

    # A falling edge must not re-capture (rising-edge-only, like '74).
    _set_bus(dut, "d", 8, 0x00)
    dut.cp.value = 0
    await _hold(dut)
    got = _read_bus(dut, "q", 8)
    assert got == 0xA5, f"q: CP fall with new D=0x00 -> 0x{got:02X}, want unchanged 0xA5"

    # Asynchronous MR_n: asserted with NO CP edge -> Q forced to 0
    # immediately (unlike '163's synchronous MR_n).
    dut.mr_n.value = 0
    await _settle(dut)
    got = _read_bus(dut, "q", 8)
    assert got == 0, f"q: MR_n=0, NO CP edge -> 0x{got:02X}, want 0x00"

    # MR_n dominates even across a CP rise while still asserted.
    _set_bus(dut, "d", 8, 0xFF)
    dut.cp.value = 1
    await _hold(dut)
    got = _read_bus(dut, "q", 8)
    assert got == 0, f"q: MR_n=0 through a CP rise with D=0xFF -> 0x{got:02X}, want 0x00 (MR dominates)"

    # Releasing MR_n restores normal capture.
    dut.mr_n.value = 1
    dut.cp.value = 0
    await _hold(dut)
    _set_bus(dut, "d", 8, 0x3C)
    dut.cp.value = 1
    await _hold(dut)
    got = _read_bus(dut, "q", 8)
    assert got == 0x3C, f"q: MR_n released, D=0x3C CP rise -> 0x{got:02X}, want 0x3C"


@cocotb.test()
async def register273_captures_pre_edge_d(dut):
    """Regression for the FLAG_Z-capture-races-the-ALU's-own-write-back
    finding (Task 12, fpga/sim/test_core_coverage.py's flow/loop whole-core
    tests): a '273 whose D-input is fed, through combinational logic, by a
    CO-COMMITTING '373's own restamped output (exactly alu.vhd's FLAG_Z
    register, U49, sampling the ALU's zero-detect -- itself downstream of
    TMP_A/TMP_B's (U45/U46, '373s) write-back on the SAME clk-falling edge
    that also closes U49's own capture window) must still capture the
    value D held AT the CP edge, never whatever D becomes a couple of
    clk_sys ticks later once that '373 has recomputed.

    Real 74LS273 hold time (th) is ~5ns; the corrupting recompute in this
    exact circuit (TMP_A/TMP_B restamp -> ALU recompute -> flag mux) needs
    roughly 4 real chip propagation delays (tens of ns, comfortably more
    than th=5ns) to reach the D-input -- sound synchronous design on real
    silicon. The bug this regresses was sim-only: this register's own
    edge-detector fired ONE clk_sys tick LATER than a co-committing '373
    detects ITS OWN commit (ttl_74ls373.vhd's le_m(1)/le_m(0) pair), so it
    sampled D one tick too late -- AFTER the '373's restamp had already
    propagated through. Fixed by aligning this register's detect stage to
    the SAME (0,1) pair '373 uses (cp_m(0)='1' and cp_m(1)='0', not
    cp_m(1)/cp_m(2)) -- see this file's own header for the derivation.

    Drives D to change EXACTLY 2 clk_sys ticks after CP rises -- matching
    a co-committing '373's own commit latency -- and asserts q captured
    the PRE-edge value, never the post-restamp one. Against the PRE-fix
    model (cp_m(1)/cp_m(2), one stage later) this fails RED, capturing the
    post-restamp value; confirmed by temporarily reverting the fix and
    re-running before committing either."""
    await _start(dut)

    dut.mr_n.value = 1
    PRE, POST = 0xA5, 0x5A
    _set_bus(dut, "d", 8, PRE)
    dut.cp.value = 0
    await _hold(dut)

    dut.cp.value = 1
    await RisingEdge(dut.clk_sys)   # tick 0: cp_m(0) samples the new CP=1
    await RisingEdge(dut.clk_sys)   # tick 1: 2 ticks after CP's rise --
                                     # a co-committing '373 restamps HERE
    _set_bus(dut, "d", 8, POST)     # D changes to a DIFFERENT value now
    await _hold(dut)

    got = _read_bus(dut, "q", 8)
    assert got == PRE, (
        f"q: D=0x{PRE:02X} at CP's rise, changed to 0x{POST:02X} exactly "
        f"2 clk_sys ticks later (a co-committing '373's own commit "
        f"latency) -> 0x{got:02X}, want the PRE-edge 0x{PRE:02X} -- "
        f"capturing 0x{POST:02X} instead means this register's own "
        f"edge-detector fired too late, AFTER a co-committing '373 had "
        f"already restamped its output back into this D-input")


# --- '373: transparent octal latch ------------------------------------------

@cocotb.test()
async def latch373_transparent(dut):
    await _start(dut)

    dut.oe_n.value = 0
    dut.le.value = 0
    _set_bus(dut, "d", 8, 0)
    await _hold(dut)

    # Transparent while LE high: output follows D combinationally. Bring
    # LE high first and let it settle (so the sync chain has genuinely
    # registered "LE is high"), THEN change D and confirm the output
    # follows WITHOUT any further clock-edge-shaped wait -- this is the
    # brief's "assert a mid-level change propagates" requirement.
    dut.le.value = 1
    _set_bus(dut, "d", 8, 0x3C)
    await _hold(dut)
    got = _read_bus(dut, "o", 8)
    assert got == 0x3C, f"o: LE=1 D=0x3C -> 0x{got:02X}, want 0x3C (transparent)"

    _set_bus(dut, "d", 8, 0x81)  # mid-level change, LE still steady high
    await Timer(1, unit="ns")    # deliberately NOT a full HOLD/SETTLE --
                                  # proves this is combinational, not
                                  # waiting for another clk_sys edge
    got = _read_bus(dut, "o", 8)
    assert got == 0x81, (
        f"o: D changed to 0x81 while LE steady high -> 0x{got:02X}, want 0x81 "
        f"(transparent path must be combinational, not clocked)"
    )

    # Latched on LE fall: drop LE, then change D again -- output must hold
    # the value D had at the fall, ignoring the new D.
    dut.le.value = 0
    await _hold(dut)
    _set_bus(dut, "d", 8, 0xFF)
    await _hold(dut)
    got = _read_bus(dut, "o", 8)
    assert got == 0x81, f"o: LE fell, D now 0xFF -> 0x{got:02X}, want held 0x81"

    # OE_n tristates Q; the held value is unaffected and reappears when
    # OE_n is released.
    dut.oe_n.value = 1
    await _settle(dut)
    for i in range(8):
        v = getattr(dut, f"o{i}").value
        assert str(v) == "Z", f"o{i}: OE_n=1 -> {v}, want Z"
    dut.oe_n.value = 0
    await _settle(dut)


@cocotb.test()
async def latch373_no_stale_glitch_on_le_fall(dut):
    """Regression, found via whole-core simulation (Task 11 review round),
    NOT by this module's own suite: the detector that captures `held` on
    LE's fall was reading the 2-clk_sys-cycle-delayed synchronizer stage
    (le_m(2)/le_m(1)) while the TRANSPARENT mux gates on the
    1-cycle-delayed stage (le_m(1)) alone. For the ONE clk_sys tick
    between the mux switching off the transparent d_bus path (le_m(1)
    falls) and the detector actually firing (still watching le_m(2)),
    `held` had not yet been updated for THIS latch cycle -- so `o` briefly
    reverted to whatever `held` carried from the PREVIOUS latch cycle
    before jumping to the correct new value one tick later. Every
    dependent sheet built on this model (MDR, IR, MAR hi/lo, ALU TMP A/B,
    registers A/B/C/OUT) inherited this glitch on every LE fall; the
    per-sheet module tests never sampled fast enough (clk_sys-tick
    granularity) across a fall to catch it, and this file's own
    latch373_transparent above only reads `o` long AFTER settling, same
    gap. This test samples every clk_sys tick across the fall instead."""
    await _start(dut)
    dut.oe_n.value = 0

    # First latch cycle: establish a KNOWN "previous held" value, distinct
    # from everything used below, so a stale revert is unambiguous.
    STALE = 0x11
    dut.le.value = 1
    _set_bus(dut, "d", 8, STALE)
    await _hold(dut)
    dut.le.value = 0
    await _hold(dut)
    got = _read_bus(dut, "o", 8)
    assert got == STALE, (
        f"o: fixture setup, first latch cycle -> 0x{got:02X}, "
        f"want held 0x{STALE:02X}")

    # Second latch cycle: transparent value NEW, held STEADY across the
    # fall (D does not change), so a correct model shows NEW on EVERY
    # tick, with no dip back to STALE at any point.
    NEW = 0x22
    dut.le.value = 1
    _set_bus(dut, "d", 8, NEW)
    await _hold(dut)
    got = _read_bus(dut, "o", 8)
    assert got == NEW, (
        f"o: LE=1 D=0x{NEW:02X} -> 0x{got:02X}, want transparent 0x{NEW:02X}")

    dut.le.value = 0    # the fall under test
    samples = []
    for _ in range(8):   # comfortably spans the (buggy) 2-tick detector delay
        await RisingEdge(dut.clk_sys)
        samples.append(_read_bus(dut, "o", 8))
    hex_samples = [f"0x{s:02X}" for s in samples]
    assert STALE not in samples, (
        f"o: sampled every clk_sys tick across LE's fall -> {hex_samples}, "
        f"STALE (0x{STALE:02X}, the PREVIOUS latch cycle's value) must "
        f"never reappear")
    assert all(s == NEW for s in samples), (
        f"o: sampled every clk_sys tick across LE's fall -> {hex_samples}, "
        f"want every sample == 0x{NEW:02X} (D never changed across the "
        f"fall, so transparent and latched must read identically the "
        f"whole way through, no glitch)")
    await _hold(dut)
    got = _read_bus(dut, "o", 8)
    assert got == NEW, f"o: settled after LE fell -> 0x{got:02X}, want held 0x{NEW:02X}"
