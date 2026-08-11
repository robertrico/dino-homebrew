import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

# Module testbench (Task 10, copying Task 9's pattern) -- mdr. Stimulus/
# assertions touch ONLY fpga/gen/mdr.vhd's own contract ports (clk_sys,
# clk, n_alu_out, src_active, n_ir_load, n_mdr_out, n_ram_load, n_ram_out,
# n_rom_out, n_sw_out, irb, write_dir, w, mdr) -- the same signals
# tests/dino_bringup/src/mod_mdr.c's bind() DRIVEs/SAMPLEs on the real
# rig. Every test's docstring names the mod_mdr.c rig test it ports.
#
# Gate equations read straight off fpga/gen/mdr.vhd (Task 8's generated
# output, itself netlist-verified against mdr.kicad_sch per CLAUDE.md):
#   U18 '373  MDR register: D/Q on the SAME mdr0-7 nets (bus-hold latch),
#             LE = le_mdr (internal), OE = n_mdr_out.
#   U25 '245  the ONE w<->mdr bridge: A=w, B=mdr, DIR=bus_dir (internal;
#             1 = A->B = w->mdr), CE = n_mdr_en (internal).
#   U34 '373  IR shadow: D=w0-7, Q=irb0-7, OE grounded (irb always
#             driven), LE = le_ir (internal).
#   U37 '04   write_dir = INV(n_ram_load); mdr_out = INV(n_mdr_out);
#             reads_idle = INV(NAND(n_rom_out, n_ram_out)).
#   U39 '00   bus_dir  = NAND(n_alu_out, n_sw_out)  -- bus direction is a
#             property of the SOURCE (bug-4 fix per CLAUDE.md).
#             le_mdr   = NAND(n_ram_load, reads_idle)
#   U22 '02   le_ir    = NOR(clk, n_ir_load)  -- loads land on CLK low.
#             n_mdr_en = NOR(src_active, mdr_out)  -- bridge on whenever
#             any source drives, or on MDR replay (bug-4 fix).
# le_ir/n_mdr_en/le_mdr/bus_dir are internal nets with no port on this
# sheet (mod_mdr.c's own rig-internal probes have no FPGA-side analogue
# here), so every assertion below is proven through w/mdr/irb readback --
# the same externally-observable behaviour mod_mdr.c itself checks.
#
# w and mdr are Task-13-rework-item-1 split ports (`inout` -> `_i`/`_o`
# pairs, since ghdl-yosys-plugin severs internal nets touching a
# sub-instance `inout` port at synthesis import): `w_i`/`mdr_i` are the
# sense side (this sheet's own U25 bridge and U34 IR-shadow latch both
# read the SENSE side, exactly the net the TB itself supplies when it's
# the one driving); `w_o`/`mdr_o` are this sheet's own drive (U25's
# bridge output on whichever side it's currently driving; 'Z' when the
# bridge is off). No more Force()/Release() needed -- `_i` is a true
# single-driver `in` port (the TB is its only driver) and `_o` is a true
# single-driver `out` port (this sheet is its only driver), so there is
# no more multi-driver contention to route around.
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


def _drive_w(dut, v):
    dut.w_i.value = v & 0xFF


def _release_w(dut):
    dut.w_i.value = "Z" * 8


def _drive_mdr(dut, v):
    dut.mdr_i.value = v & 0xFF


def _release_mdr(dut):
    dut.mdr_i.value = "Z" * 8


async def _w_read(dut):
    await _settle(dut)
    return int(dut.w_o.value)


async def _mdr_read(dut):
    await _settle(dut)
    return int(dut.mdr_o.value)


async def _bind_idle(dut):
    """Mirrors mod_mdr.c bind()'s MDR_IDLE: every strobe idle-high,
    SRC_ACTIVE low (bridge off), CLK idle-high. Neither w_i nor mdr_i is
    pre-driven here -- at idle nothing internal drives either OUTPUT net
    (U25's ce_n=n_mdr_en=1, U18's oe_n=n_mdr_out=1), so w_o/mdr_o already
    read 'Z' from VHDL's own t=0 init, same reasoning as Task 9's
    _bind_idle."""
    await _start(dut)
    dut.n_alu_out.value = 1
    dut.n_ir_load.value = 1
    dut.n_mdr_out.value = 1
    dut.n_ram_load.value = 1
    dut.n_ram_out.value = 1
    dut.n_rom_out.value = 1
    dut.n_sw_out.value = 1
    # The PC->MDR taps (U72/U73, 2026-08-10). Idle-high like every other
    # strobe; pc_i is the PC bus this sheet READS (the '193 outputs live on
    # the pc sheet -- U72/U73 only buffer them onto MDR).
    dut.n_pc_lo_out.value = 1
    dut.n_pc_hi_out.value = 1
    dut.pc_i.value = 0
    dut.src_active.value = 0
    dut.clk.value = 1
    await _settle(dut)


@cocotb.test()
async def test_mdr_bridge_both_directions_asymmetric(dut):
    """Ports mod_mdr.c t_mdr_bridge (a)+(b): W_to_MDR_alu, MDR_to_W --
    the module's REQUIRED minimum ('both bus directions'). Uses two
    DIFFERENT bytes on two DIFFERENT wire sets (mirror-witness: a round
    trip through the SAME bank, ferrying the SAME byte back, cannot
    distinguish a working bridge from one permanently wedged one way)."""
    await _bind_idle(dut)

    # (a) W-side source: SRC_ACTIVE + ~ALU_OUT low -> bus_dir=1 -> W->MDR.
    dut.src_active.value = 1
    dut.n_alu_out.value = 0
    await _settle(dut)
    _drive_w(dut, 0xA5)
    await _settle(dut)
    got = await _mdr_read(dut)
    assert got == 0xA5, (
        f"mdr: SRC_ACTIVE=1 ~{{ALU_OUT}}=0, w=0xA5 -> mdr=0x{got:02X}, "
        f"want 0xA5 (bus_dir=NAND(0,1)=1, W->MDR)"
    )
    _release_w(dut)
    dut.n_alu_out.value = 1
    dut.src_active.value = 0
    await _settle(dut)

    # (b) MDR-side source: SRC_ACTIVE alone (n_alu_out/n_sw_out idle-high)
    # -> bus_dir=NAND(1,1)=0 -> MDR->W. 0x3C shares no bit pattern with
    # 0xA5 above, so a stuck-direction bridge cannot coincidentally pass.
    dut.src_active.value = 1
    await _settle(dut)
    _drive_mdr(dut, 0x3C)
    await _settle(dut)
    got = await _w_read(dut)
    assert got == 0x3C, (
        f"w: SRC_ACTIVE=1 (ALU/SW idle) mdr=0x3C -> w=0x{got:02X}, "
        f"want 0x3C (bus_dir=NAND(1,1)=0, MDR->W)"
    )
    _release_mdr(dut)
    dut.src_active.value = 0
    await _settle(dut)


@cocotb.test()
async def test_mdr_bridge_off_both_float(dut):
    """Ports mod_mdr.c t_mdr_tristate: nothing enabled, SRC_ACTIVE low --
    the bridge off / U18 quiet quiescent contract (bug-4's own retirement
    condition) -- every w and mdr bit must float."""
    await _bind_idle(dut)
    w_str, mdr_str = str(dut.w_o.value), str(dut.mdr_o.value)
    assert all(c == "Z" for c in w_str), f"w_o: idle -> {w_str}, want all-Z"
    assert all(c == "Z" for c in mdr_str), f"mdr_o: idle -> {mdr_str}, want all-Z"


@cocotb.test()
async def test_mdr_ir_capture_gated_by_clk_low(dut):
    """Ports mod_mdr.c t_mdr_ir: load_pattern, holds_after_W_changes,
    load_gated_by_CLK_low -- irb captures w under le_ir = NOR(CLK,
    ~{IR_LOAD}), the same 'loads commit on CLK low' invariant as every
    other latch on the machine."""
    await _bind_idle(dut)

    async def ir_load(v):
        _drive_w(dut, v)
        await _settle(dut)
        await _clk_lo(dut)
        dut.n_ir_load.value = 0
        await _settle(dut)
        dut.n_ir_load.value = 1
        await _settle(dut)
        await _clk_hi(dut)
        _release_w(dut)
        await _settle(dut)

    for pat in (0x00, 0xFF, 0xA5, 0x3C):
        await ir_load(pat)
        got = int(dut.irb.value)
        assert got == pat, f"irb: ir_load(0x{pat:02X}) -> 0x{got:02X}"

    # hold: W changes with the latch closed -- IRB must not move.
    await ir_load(0x3C)
    _drive_w(dut, 0xC3)
    await _settle(dut)
    _release_w(dut)
    await _settle(dut)
    got = int(dut.irb.value)
    assert got == 0x3C, f"irb: W changed after latch closed -> 0x{got:02X}, want held 0x3C"

    # gating: ~IR_LOAD strobed with CLK HIGH must NOT land.
    _drive_w(dut, 0xC3)
    await _settle(dut)
    dut.n_ir_load.value = 0     # CLK stays high
    await _settle(dut)
    dut.n_ir_load.value = 1
    await _settle(dut)
    _release_w(dut)
    await _settle(dut)
    got = int(dut.irb.value)
    assert got == 0x3C, (
        f"irb: ~IR_LOAD strobed with W=0xC3 while CLK stayed HIGH -> "
        f"0x{got:02X}, want unchanged 0x3C (load must be gated by CLK low)"
    )


@cocotb.test()
async def test_mdr_write_dir_follows_ram_load(dut):
    """Ports mod_mdr.c t_mdr_presence/t_mdr_logic (WRITE_DIR row): WRITE_DIR
    = INV(~{RAM_LOAD}) -- the memory sheet's own write-window input, so a
    wrong polarity here would silently disable every RAM write."""
    await _bind_idle(dut)
    dut.n_ram_load.value = 1
    await _settle(dut)
    assert int(dut.write_dir.value) == 0, (
        f"write_dir: ~{{RAM_LOAD}}=1 (idle) -> {dut.write_dir.value}, want 0"
    )
    dut.n_ram_load.value = 0
    await _settle(dut)
    assert int(dut.write_dir.value) == 1, (
        f"write_dir: ~{{RAM_LOAD}}=0 (asserted) -> {dut.write_dir.value}, want 1"
    )
    dut.n_ram_load.value = 1
    await _settle(dut)


# --- PC -> MDR taps (U72/U73, 2026-08-10) ---------------------------------

@cocotb.test()
async def test_pc_taps_put_the_right_half_on_mdr(dut):
    """U72/U73 buffer PC0-7 and PC8-15 onto MDR0-7 so CALL can push a return
    address.

    They tap `PC0-15` -- the '193 Q outputs -- NOT the M bus, and that is the
    whole reason CALL is possible: CALL's push row writes to RAM, so the
    address bus must carry MAR (the stack slot) and M is not carrying the PC
    at all. A tap on M would push MAR's own value.

    Two DIFFERENT halves, so a swapped pair cannot pass: 0x1234 puts 0x34 on
    MDR for PC_LO and 0x12 for PC_HI. Reading 0x12 from the LO code would
    mean U72/U73 were crossed; reading a bit-reversed byte would mean the
    '245 was wired by pin NUMBER rather than by name (B0=18 counts DOWN to
    B7=11 on that package).
    """
    await _bind_idle(dut)
    dut.pc_i.value = 0x1234
    await _settle(dut)

    dut.n_pc_lo_out.value = 0
    await _settle(dut)
    got = int(dut.mdr_o.value)
    assert got == 0x34, (
        f"PC_LO_OUT asserted with PC=0x1234 -> MDR=0x{got:02X}, want 0x34 "
        f"(0x12 would mean the LO and HI taps are crossed)")
    dut.n_pc_lo_out.value = 1
    await _settle(dut)

    dut.n_pc_hi_out.value = 0
    await _settle(dut)
    got = int(dut.mdr_o.value)
    assert got == 0x12, (
        f"PC_HI_OUT asserted with PC=0x1234 -> MDR=0x{got:02X}, want 0x12")
    dut.n_pc_hi_out.value = 1
    await _settle(dut)


@cocotb.test()
async def test_pc_taps_release_mdr_when_idle(dut):
    """Both taps off -> MDR floats. They share MDR0-7 with ROM, RAM, all
    three registers and the stack pointer; a buffer that failed to release
    would fight every one of them, on every cycle."""
    await _bind_idle(dut)
    dut.pc_i.value = 0xBEEF
    await _settle(dut)
    val = dut.mdr_o.value
    assert "Z" in str(val).upper(), (
        f"mdr_o with both PC taps idle -> {val}, want high-Z on every bit")
