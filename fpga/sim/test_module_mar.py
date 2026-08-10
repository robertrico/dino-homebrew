import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

# Module testbench (Task 10, copying Task 9's test_module_program_counter.py
# pattern exactly) -- mar. Stimulus/assertions touch ONLY
# fpga/gen/mar.vhd's own contract ports (clk_sys, w, clk, n_mar_hi_load,
# n_mar_lo_load, cw14_eq_pc_mar_mux, m, n_pc_mar_mux, n_ram_en,
# m15_eq_rom_en) -- the same signals tests/dino_bringup/src/mod_mar.c's
# bind() DRIVEs/SAMPLEs on the real rig. Every test's docstring names the
# mod_mar.c rig test it ports.
#
# Gate equations read straight off fpga/gen/mar.vhd (Task 8's generated
# output, itself netlist-verified against mar.kicad_sch per CLAUDE.md):
#   U55/U58 '373  LO/HI address latches: D = w0-7 (BOTH halves latch off
#             the SAME w byte, separate LEs), Q -> private mar0-15, OE
#             grounded -- the latches always drive the private bus.
#   U54/U59 '245  MAR -> m port: DIR='1' (A->B), CE = cw14_eq_pc_mar_mux
#             (enabled/driving at 0 -- "PC=1, MAR=0" per CLAUDE.md's bit
#             map).
#   U60 '02   le_mar_lo = NOR(n_mar_lo_load, clk)   (internal net, no port)
#             le_mar_hi = NOR(n_mar_hi_load, clk)   (internal net, no port)
#             n_ram_en  = INV(m15_eq_rom_en)  -- decodes the CURRENT BUS
#             value of M15, so RAM_EN tracks whoever is actually driving
#             m (MAR's own latch at mux=0, or a TB-driven bus at mux=1),
#             never the latch alone.
#             n_pc_mar_mux = INV(cw14_eq_pc_mar_mux)
# le_mar_lo/le_mar_hi have no port on this sheet (mod_mar.c's rig-internal
# probes LE_MAR_LO/LE_MAR_HI have no FPGA-side analogue here), so every
# load here is proven through the LATCHED VALUE on m -- the same
# observable mod_mar.c's own t_mar_hold test uses.
#
# Timing discipline identical to Task 9: clk_sys 100MHz, SETTLE (>=3
# clk_sys cycles) after every stimulus change, HOLD a realistic ~500ns-
# period machine CLK half-cycle.
SETTLE = 50   # ns -- >3 clk_sys cycles
HOLD = 250    # ns -- half-period of a slow, machine-realistic CLK
M_WIDTH = 15  # m(14 downto 0); bit 15 lives on the m15_eq_rom_en port


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


def _drive_m(dut, v16):
    # m_i/m15_eq_rom_en_i (Task-13 rework item 1: the `m`/`m15_eq_rom_en`
    # sheet ports split from `inout` into `_i`/`_o` pairs) are true
    # single-driver `in` ports -- the TB is their only driver, so a plain
    # deposit is safe; no more Force()/Release() needed (that was only
    # ever required because the old single `inout` port was ALSO driven
    # by this sheet's own U54/U59).
    dut.m_i.value = v16 & ((1 << M_WIDTH) - 1)
    dut.m15_eq_rom_en_i.value = (v16 >> M_WIDTH) & 1


def _release_m(dut):
    dut.m_i.value = "Z" * M_WIDTH
    dut.m15_eq_rom_en_i.value = "Z"


def _read_m(dut):
    # m_o/m15_eq_rom_en_o is this sheet's OWN drive -- 'Z' when its '245s
    # are disabled, exactly the observable the old single inout net gave
    # when nothing local was driving it.
    lo = int(dut.m_o.value)
    hi = int(dut.m15_eq_rom_en_o.value)
    return lo | (hi << M_WIDTH)


async def _m_read(dut):
    await _settle(dut)
    return _read_m(dut)


async def _sync_m_loopback(dut):
    """Standalone-TB stand-in for dino_core's own m/m15_eq_rom_en
    pass-through wiring: Task-13 rework item 1 split the `m`/
    `m15_eq_rom_en` sheet ports from a single `inout` into `_i`/`_o`
    pairs. Inside dino_core both bind to the SAME plain resolved signal,
    so a sheet's own drive is automatically visible to its own decode
    logic (n_ram_en reads m15_eq_rom_en_i, tracking "whoever is CURRENTLY
    driving m" -- see the module header). A standalone per-sheet TB has
    to do that mirroring itself when THIS sheet (not the TB) owns the
    bus, or the decode gate never sees mar's own drive at all."""
    await _settle(dut)
    dut.m_i.value = int(dut.m_o.value)
    dut.m15_eq_rom_en_i.value = int(dut.m15_eq_rom_en_o.value)
    # A deposit isn't visible to a read back on THIS handle until the sim
    # advances past the current delta -- settle again so callers can rely
    # on m_i/m15_eq_rom_en_i (and anything combinationally downstream of
    # them, e.g. n_ram_en) reading the just-mirrored value immediately.
    await _settle(dut)


async def _bind_idle(dut):
    """Mirrors mod_mar.c bind()'s MAR_IDLE: both loads idle-high,
    mux=0 (MAR owns m -- tests read it directly). Deliberately does NOT
    pre-drive m_i/m15_eq_rom_en_i here, same reasoning as Task 9's
    _bind_idle: at mux=0 the DUT's own U54/U59 already drive m_o from
    VHDL's own t=0 init, so the TB was never the one supplying it."""
    await _start(dut)
    dut.n_mar_hi_load.value = 1
    dut.n_mar_lo_load.value = 1
    dut.cw14_eq_pc_mar_mux.value = 0   # MAR drives m
    dut.w.value = 0
    dut.clk.value = 1
    await _settle(dut)


async def _mar_load(dut, load_n_pin, v8):
    """Ports mod_mar.c's mar_load(): W = v, strobe the half's /LOAD low
    while CLK is low (the only phase le_mar_{lo,hi} can open), close,
    return CLK high -- the machine invariant (loads commit on CLK low)."""
    dut.w.value = v8
    await _settle(dut)
    await _clk_lo(dut)
    load_n_pin.value = 0
    await _settle(dut)
    load_n_pin.value = 1
    await _settle(dut)
    await _clk_hi(dut)


async def _load16(dut, addr):
    await _mar_load(dut, dut.n_mar_lo_load, addr & 0xFF)
    await _mar_load(dut, dut.n_mar_hi_load, (addr >> 8) & 0xFF)
    # MAR's own drive just changed (m_o) -- mirror it onto m_i so this
    # sheet's own n_ram_en decode (which reads the _i/sense side) sees
    # its own latch, exactly what dino_core's plain-signal wiring gives
    # for free at the whole-core level.
    await _sync_m_loopback(dut)


@cocotb.test()
async def test_mar_latch_holds_per_half(dut):
    """Ports mod_mar.c t_mar_hold: load16, LO_walk1_HI_holds,
    HI_walk0_LO_holds -- both halves latch off the SAME w byte through
    separate LEs, so every check reads the FULL 15-bit m (+ m15) to
    prove half-independence, matching the rig's own approach."""
    await _bind_idle(dut)
    await _load16(dut, 0x4C3A)
    got = await _m_read(dut)
    assert got == 0x4C3A, f"m: load16(0x4C3A) -> 0x{got:04X}, want 0x4C3A"

    for b in range(8):
        v = 1 << b
        await _mar_load(dut, dut.n_mar_lo_load, v)
        got = await _m_read(dut)
        want = 0x4C00 | v
        assert got == want, (
            f"m: LO_walk1 bit{b} (HI must hold 0x4C) -> 0x{got:04X}, "
            f"want 0x{want:04X}"
        )

    await _mar_load(dut, dut.n_mar_lo_load, 0x3A)
    for b in range(8):
        v = (~(1 << b)) & 0xFF
        await _mar_load(dut, dut.n_mar_hi_load, v)
        got = await _m_read(dut)
        want = (v << 8) | 0x3A
        assert got == want, (
            f"m: HI_walk0 bit{b} (LO must hold 0x3A) -> 0x{got:04X}, "
            f"want 0x{want:04X}"
        )


@cocotb.test()
async def test_mar_load_gated_by_clk_low(dut):
    """Ports mod_mar.c t_mar_hold's gating block: load_gated_by_CLK_low."""
    await _bind_idle(dut)
    await _load16(dut, 0x1234)
    dut.w.value = 0xFF
    await _settle(dut)
    # CLK stays HIGH through the whole strobe -- le_mar_lo cannot open.
    dut.n_mar_lo_load.value = 0
    await _settle(dut)
    dut.n_mar_lo_load.value = 1
    await _settle(dut)
    got = await _m_read(dut)
    assert got == 0x1234, (
        f"m: ~MAR_LO_LOAD strobed with W=0xFF while CLK stayed HIGH -> "
        f"0x{got:04X}, want unchanged 0x1234 (load must be gated by CLK low)"
    )


@cocotb.test()
async def test_mar_mux_floats_and_redrives(dut):
    """Ports mod_mar.c t_mar_mux: MAR_drives_M_mux_low, floats,
    MAR_redrives_after_mux -- the ADDRESS DRIVE half of this module's
    minimum ('latch + address drive')."""
    await _bind_idle(dut)
    await _load16(dut, 0xA5C3)
    got = await _m_read(dut)
    assert got == 0xA5C3, f"m: MAR after load16 -> 0x{got:04X}, want 0xA5C3"
    assert int(dut.n_pc_mar_mux.value) == 1, (
        f"n_pc_mar_mux: mux=0 (MAR side) -> {dut.n_pc_mar_mux.value}, "
        f"want 1 (PC-side '245s disabled)"
    )

    dut.cw14_eq_pc_mar_mux.value = 1   # MAR's own '245s off
    await _settle(dut)
    m_str = str(dut.m_o.value)
    assert all(c == "Z" for c in m_str), (
        f"m_o: cw14_eq_pc_mar_mux=1 (MAR side off) -> {m_str}, want all-Z"
    )
    assert str(dut.m15_eq_rom_en_o.value) == "Z", (
        f"m15_eq_rom_en_o: cw14_eq_pc_mar_mux=1 -> "
        f"{dut.m15_eq_rom_en_o.value}, want Z"
    )
    assert int(dut.n_pc_mar_mux.value) == 0, (
        f"n_pc_mar_mux: mux=1 -> {dut.n_pc_mar_mux.value}, "
        f"want 0 (PC-side '245s enabled)"
    )

    dut.cw14_eq_pc_mar_mux.value = 0
    await _settle(dut)
    got = await _m_read(dut)
    assert got == 0xA5C3, (
        f"m: mux back to 0 -> 0x{got:04X}, want 0xA5C3 (MAR redrives after mux)"
    )


@cocotb.test()
async def test_mar_decode_follows_the_bus(dut):
    """Ports mod_mar.c t_mar_decode: ROM_side_0x7FFF, RAM_side_0x8000,
    ROM_side_0x0000, PC_side_0x7FFF, PC_side_0x8000 -- n_ram_en =
    INV(m15_eq_rom_en) decodes whoever is CURRENTLY DRIVING m, not the
    MAR latch: proven by asserting the SAME two addresses twice, once
    through the MAR latch (mux=0) and once through a TB-driven bus value
    (mux=1)."""
    await _bind_idle(dut)
    await _load16(dut, 0x7FFF)
    assert int(dut.n_ram_en.value) == 1, (
        f"n_ram_en: latched 0x7FFF (ROM half) -> {dut.n_ram_en.value}, want 1 (off)"
    )
    await _load16(dut, 0x8000)
    assert int(dut.n_ram_en.value) == 0, (
        f"n_ram_en: latched 0x8000 (RAM half) -> {dut.n_ram_en.value}, want 0 (on)"
    )
    await _load16(dut, 0x0000)
    assert int(dut.n_ram_en.value) == 1, (
        f"n_ram_en: latched 0x0000 (ROM half) -> {dut.n_ram_en.value}, want 1 (off)"
    )

    dut.cw14_eq_pc_mar_mux.value = 1
    await _settle(dut)
    _drive_m(dut, 0x7FFF)
    await _settle(dut)
    assert int(dut.n_ram_en.value) == 1, (
        f"n_ram_en: BUS-driven 0x7FFF (mux=1) -> {dut.n_ram_en.value}, want 1 (off)"
    )
    _drive_m(dut, 0x8000)
    await _settle(dut)
    assert int(dut.n_ram_en.value) == 0, (
        f"n_ram_en: BUS-driven 0x8000 (mux=1) -> {dut.n_ram_en.value}, want 0 (on)"
    )
    _release_m(dut)
    dut.cw14_eq_pc_mar_mux.value = 0
    await _settle(dut)
