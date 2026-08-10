import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

# Module testbench (Task 10, copying Task 9's pattern) -- registers_a_b.
# Stimulus/assertions touch ONLY fpga/gen/registers_a_b.vhd's own
# contract ports (clk_sys, clk, n_reg_a_load, n_reg_b_load, n_reg_a_out,
# n_reg_b_out, n_reg_c_load, n_reg_c_out, n_reg_out_load, mdr, ob) -- the
# same signals tests/dino_bringup/src/mod_registers.c's bind() DRIVEs/
# SAMPLEs on the real rig. Every test's docstring names the
# mod_registers.c rig test it ports.
#
# Gate equations read straight off fpga/gen/registers_a_b.vhd (Task 8's
# generated output, itself netlist-verified against
# registers_a_b.kicad_sch per CLAUDE.md):
#   U31/32/33 '373  A/B/C registers -- bus-hold latches (D and Q PAIRED
#             on the same private ab/bb/cb nets), LE = internal
#             n_reg_x_le, OE = n_reg_x_out (the register drives its
#             private bus ONLY while being read).
#   U41/42/43 '245  register-file port: A side = mdr, B side = the
#             private bus. DIR = n_reg_x_out (1: mdr->reg for loads; 0:
#             reg->mdr for reads). CE = n_x_en (internal).
#   U5   '08  n_x_en = AND(n_reg_x_load, n_reg_x_out) -- port open on
#             load OR read, closed at idle (0 whenever EITHER input is 0).
#   U57  '02  n_reg_x_le = NOR(n_reg_x_load, clk) -- a load lands ONLY
#             while CLK is LOW (this sheet's half of the required
#             minimum: "load commits on CLK low").
#   U44  '245  OUT path: A = mdr, B = U35's D pins, DIR='1' (mdr->D
#             always), CE = n_reg_out_load directly.
#   U35  '373  OUT register (OB): OE grounded -- ob0-7 NEVER floats. This
#             is the REAL location of "OB latch" (mod_io.c's own header:
#             "in the real machine OB comes from the OUT register on the
#             REGISTERS board -- here the rig substitutes for it"); the
#             sibling input_output.vhd sheet's `ob` port is a dead wire
#             (unused in that architecture -- confirmed by reading the
#             generated file, not assumed) since real LEDs are a passive
#             load with no gate logic, so the OB-latch half of this
#             task's input_output minimum is covered HERE instead. See
#             test_module_input_output.py's header for the same note.
#
# mdr is touched by FOUR real internal sources (U41/U42/U43's A-side AND
# U44's A-side), so it's a Task-13-rework-item-1 split port (`mdr_i`/
# `mdr_o`, not `inout` -- ghdl-yosys-plugin severs internal nets touching
# a sub-instance `inout` port at synthesis import): every TB write drives
# `mdr_i` (a true single-driver `in` port, no more Force()/Release()
# needed) and every readback reads `mdr_o` (this sheet's own drive, 'Z'
# when nothing local is enabled).
SETTLE = 50
HOLD = 250


async def _start(dut):
    cocotb.start_soon(Clock(dut.clk_sys, 10, unit="ns").start())
    await Timer(SETTLE, unit="ns")


async def _settle(dut):
    await Timer(SETTLE, unit="ns")


async def _hold(dut):
    await Timer(HOLD, unit="ns")


async def _clk_lo(dut):
    dut.clk.value = 0
    await _hold(dut)


async def _clk_hi(dut):
    dut.clk.value = 1
    await _hold(dut)


def _drive_mdr(dut, v):
    dut.mdr_i.value = v & 0xFF


def _release_mdr(dut):
    dut.mdr_i.value = "Z" * 8


async def _mdr_read(dut):
    await _settle(dut)
    return int(dut.mdr_o.value)


async def _bind_idle(dut):
    """Mirrors mod_registers.c bind()'s REG_IDLE: every /LOAD and /OUT
    idle-high, CLK idle-high. mdr is left untouched (nothing internal
    drives it at idle -- every n_x_en is 1/closed -- so it already reads
    'Z' from VHDL's own t=0 init), same reasoning as every prior module."""
    await _start(dut)
    dut.n_reg_a_load.value = 1
    dut.n_reg_b_load.value = 1
    dut.n_reg_a_out.value = 1
    dut.n_reg_b_out.value = 1
    dut.n_reg_c_load.value = 1
    dut.n_reg_c_out.value = 1
    dut.n_reg_out_load.value = 1
    dut.clk.value = 1
    await _settle(dut)


LOAD_PIN = {"A": "n_reg_a_load", "B": "n_reg_b_load", "C": "n_reg_c_load"}
OUT_PIN = {"A": "n_reg_a_out", "B": "n_reg_b_out", "C": "n_reg_c_out"}


async def _load_reg(dut, r, v):
    """Ports mod_registers.c's load_reg(): mdr = v, strobe the
    register's /LOAD low while CLK is low (the only phase n_reg_x_le can
    open), close, return CLK high, release mdr.

    CLOSING ORDER differs from mod_registers.c's own load_reg() (which
    deasserts /LOAD first, then raises CLK) -- INVESTIGATED, not copied
    blindly: U31/32/33's D pin is the SAME net as its own Q (the
    documented "bus-hold latch", registers_a_b.vhd's header comment), fed
    from mdr only while n_x_en=AND(n_reg_x_load,n_reg_x_out) is open --
    and n_x_en depends on n_reg_x_load, the SAME signal that also gates
    the latch's own LE. ttl_74ls373.vhd's model samples LE through a
    clk_sys 2-flop synchronizer (its own header: "HELD value... registered
    on a detected LE-falling transition"), so the capture happens up to 2
    clk_sys cycles AFTER the raw le pin falls. Closing by deasserting
    /LOAD first (the rig's own order) drops n_x_en in the SAME delta as
    le begins closing, so by the time the model's delayed capture fires
    the bus has ALREADY gone 'Z' -- caught empirically as `Can't convert
    LogicArray to int: it contains non-0/1 values` reading mdr back.
    Closing via CLK instead (raising clk while /LOAD is STILL asserted)
    closes le = NOR(load,clk) the same way, but n_x_en depends only on
    load (unaffected by clk) so the bus stays driven straight through the
    synchronizer's capture window; /LOAD is deasserted only afterward,
    once `held` has already latched -- functionally identical on real
    silicon (both signals settle within a few ns there) but required
    here against a clk_sys-synchronized behavioral model. Every OTHER
    sheet's '373 in this task (mar/mdr's IR, alu's TMP_A/TMP_B) has D
    wired to a plain always-driven port, not a bus-hold loopback, so this
    hazard is unique to this sheet -- confirmed by reading every other
    '373 port map in fpga/gen/*.vhd, not assumed."""
    pin = getattr(dut, LOAD_PIN[r])
    _drive_mdr(dut, v)
    await _settle(dut)
    await _clk_lo(dut)
    pin.value = 0                 # LE opens, bus enabled (mdr -> private bus)
    await _settle(dut)
    await _clk_hi(dut)            # LE closes (le=NOR(0,1)=0); bus STAYS
    #                                enabled (n_x_en only depends on load)
    await _settle(dut)
    pin.value = 1                 # now safe to deassert -- already captured
    await _settle(dut)
    _release_mdr(dut)
    await _settle(dut)


async def _read_reg(dut, r):
    """Ports mod_registers.c's read_reg(): /OUT drives the byte onto
    mdr."""
    pin = getattr(dut, OUT_PIN[r])
    pin.value = 0
    await _settle(dut)
    got = await _mdr_read(dut)
    pin.value = 1
    await _settle(dut)
    return got


async def _load_ob(dut, v):
    """Same CLK-first closing order as _load_reg() and for the identical
    reason: U35's D pin (net_u35_d0-7) is driven by U44 gated off the
    SAME n_reg_out_load signal that also gates U35's own LE
    (n_reg_out_le = NOR(n_reg_out_load, clk))."""
    _drive_mdr(dut, v)
    await _settle(dut)
    await _clk_lo(dut)
    dut.n_reg_out_load.value = 0
    await _settle(dut)
    await _clk_hi(dut)
    await _settle(dut)
    dut.n_reg_out_load.value = 1
    await _settle(dut)
    _release_mdr(dut)
    await _settle(dut)


@cocotb.test()
async def test_registers_load_commits_on_clk_low(dut):
    """Ports mod_registers.c t_registers_load: per-register pattern
    load/readback, A_walk1, load_gated_by_CLK_low -- this sheet's
    REQUIRED minimum half 1 ('load commits on CLK low')."""
    await _bind_idle(dut)
    for r in "ABC":
        for pat in (0x00, 0xFF, 0xAA, 0x55):
            await _load_reg(dut, r, pat)
            got = await _read_reg(dut, r)
            assert got == pat, f"mdr: reg_{r} load 0x{pat:02X} -> read 0x{got:02X}"

    for b in range(8):
        v = 1 << b
        await _load_reg(dut, "A", v)
        got = await _read_reg(dut, "A")
        assert got == v, f"mdr: reg_A_walk1 bit{b} -> loaded 0x{v:02X}, read 0x{got:02X}"

    # gating: /LOAD strobed with CLK HIGH must NOT land.
    await _load_reg(dut, "A", 0x3C)
    _drive_mdr(dut, 0xC3)
    await _settle(dut)
    dut.n_reg_a_load.value = 0     # CLK stays high
    await _settle(dut)
    dut.n_reg_a_load.value = 1
    await _settle(dut)
    _release_mdr(dut)
    await _settle(dut)
    got = await _read_reg(dut, "A")
    assert got == 0x3C, (
        f"mdr: ~REG_A_LOAD strobed with mdr=0xC3 while CLK stayed HIGH -> "
        f"0x{got:02X}, want unchanged 0x3C (load must be gated by CLK low)"
    )


@cocotb.test()
async def test_registers_bus_output_enables(dut):
    """Ports mod_registers.c t_registers_tristate + t_registers_isolation:
    no /OUT asserted -> mdr floats on every bit; three distinct bytes
    loaded, each register's own /OUT (and only its own) drives them back
    without disturbing the others -- this sheet's REQUIRED minimum half 2
    ('bus output enables')."""
    await _bind_idle(dut)
    mdr_str = str(dut.mdr_o.value)
    assert all(c == "Z" for c in mdr_str), (
        f"mdr: idle (no /OUT asserted) -> {mdr_str}, want all-Z"
    )

    await _load_reg(dut, "A", 0xAA)
    await _load_reg(dut, "B", 0x55)
    await _load_reg(dut, "C", 0xC3)
    got_c = await _read_reg(dut, "C")
    assert got_c == 0xC3, f"mdr: reg_C /OUT -> 0x{got_c:02X}, want 0xC3 (isolation: after all 3 loads)"
    got_b = await _read_reg(dut, "B")
    assert got_b == 0x55, f"mdr: reg_B /OUT -> 0x{got_b:02X}, want 0x55 (unaffected by reading C)"
    got_a = await _read_reg(dut, "A")
    assert got_a == 0xAA, f"mdr: reg_A /OUT -> 0x{got_a:02X}, want 0xAA (unaffected by reading B/C)"

    mdr_str = str(dut.mdr_o.value)
    assert all(c == "Z" for c in mdr_str), (
        f"mdr: idle again (all /OUT released) -> {mdr_str}, want all-Z"
    )


@cocotb.test()
async def test_registers_outreg_ob_latch(dut):
    """Ports mod_registers.c t_registers_outreg: OB_pattern, OB_walk1,
    OB_holds -- U35's OE is grounded so ob0-7 never floats; this is the
    module that actually implements 'OB latch' (see the header note:
    input_output.vhd's own `ob` port is unused there)."""
    await _bind_idle(dut)
    for pat in (0x00, 0xFF, 0xAA, 0x55):
        await _load_ob(dut, pat)
        got = int(dut.ob.value)
        assert got == pat, f"ob: load 0x{pat:02X} -> read 0x{got:02X}"

    for b in range(8):
        v = 1 << b
        await _load_ob(dut, v)
        got = int(dut.ob.value)
        assert got == v, f"ob: walk1 bit{b} -> loaded 0x{v:02X}, read 0x{got:02X}"

    # holds: mdr changes after the latch closes must not move ob.
    await _load_ob(dut, 0x96)
    _drive_mdr(dut, 0x69)
    await _settle(dut)
    _release_mdr(dut)
    await _settle(dut)
    got = int(dut.ob.value)
    assert got == 0x96, f"ob: mdr changed after latch closed -> 0x{got:02X}, want held 0x96"
