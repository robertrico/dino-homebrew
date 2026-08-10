import cocotb
from cocotb.triggers import Timer

# Module testbench (Task 10, copying Task 9's pattern) -- control_word.
# Stimulus/assertions touch ONLY fpga/gen/control_word.vhd's own contract
# ports (clk_sys, cw, flag_z, + the 20 decode outputs) -- the same
# signals tests/dino_bringup/src/mod_control_word.c's bind() DRIVEs/
# SAMPLEs on the real rig. Every test's docstring names the
# mod_control_word.c rig test it ports. Pure combinational sheet -- no
# CLK port at all, matching mod_control_word.c's own header note.
#
# Gate equations read straight off fpga/gen/control_word.vhd (Task 8's
# generated output, itself netlist-verified against control_word.kicad_sch
# per CLAUDE.md):
#   U30 (a0=cw0,a1=cw1,a2=cw2) DST: o1..o7_n -> n_reg_a_load n_reg_b_load
#       n_reg_c_load n_mar_lo_load n_mar_hi_load n_ir_load n_ram_load;
#       o0 NC (code 0 = DST NONE).
#   U28 (a0=cw3,a1=cw4,a2=cw5) SRC: o0_n -> src_active (LOW only at code 0
#       = SRC NONE -- contract OUT since the bug-4 U25 bridge fix);
#       o1..o7_n -> n_rom_out n_ram_out n_reg_a_out n_reg_b_out
#       n_reg_c_out n_alu_out n_sw_out.
#   U29 (a0=cw6,a1=cw7,a2=cw8) MISC: o1_n -> n_pc_clear; o2_n -> internal
#       n_pc_load_jmp; o3_n -> internal n_cond; o4_n -> n_mdr_out;
#       o6_n -> n_reg_out_load; o0/o5/o7 NC.
#   U62 '02: cond_taken=NOR(n_cond,flag_z); pc_load_jmp=INV(n_pc_load_jmp);
#       n_pc_load=NOR(cond_taken,pc_load_jmp) -- the ONE externally
#       observable signal for MISC codes 2 (PC_LOAD)/3 (COND); n_cond,
#       pc_load_jmp, cond_taken are internal nets with no port on this
#       sheet (mod_control_word.c's own rig-internal probes for them have
#       no FPGA-side analogue here).
#   All three '138s: E1=E2='0', E3='1' -- always enabled, totem-pole
#       outputs (never high-Z).
#
# "Strobe decode one-hot" (this module's REQUIRED minimum) means: for any
# one DST/SRC/MISC code, exactly the ONE output the netlist above names
# for that code goes low, every other output in ALL THREE groups stays at
# its own NONE-code level -- proven below by checking the FULL 20-signal
# vector on every drive, not just the signal under test (a stray decode
# in another group fails right there, under its own name).
SETTLE = 50   # ns -- >3 clk_sys cycles


async def _settle(dut):
    await Timer(SETTLE, unit="ns")


# All 20 decode outputs this sheet exposes, in an arbitrary but fixed
# order used by every assertion below.
OUT_NAMES = [
    "n_reg_a_load", "n_reg_b_load", "n_reg_c_load", "n_mar_lo_load",
    "n_mar_hi_load", "n_ir_load", "n_ram_load",
    "src_active", "n_rom_out", "n_ram_out", "n_reg_a_out", "n_reg_b_out",
    "n_reg_c_out", "n_alu_out", "n_sw_out",
    "n_pc_clear", "n_mdr_out", "n_reg_out_load", "n_pc_load",
]

# DST code -> the ONE n_* output that must read LOW (0 = no output wired).
DST_LOW = {
    0: None, 1: "n_reg_a_load", 2: "n_reg_b_load", 3: "n_reg_c_load",
    4: "n_mar_lo_load", 5: "n_mar_hi_load", 6: "n_ir_load", 7: "n_ram_load",
}
# SRC code -> the ONE output that must read LOW. code 0 (NONE) is special:
# src_active ITSELF is the low-at-NONE signal (o0_n), not a separate wire.
SRC_LOW = {
    0: "src_active", 1: "n_rom_out", 2: "n_ram_out", 3: "n_reg_a_out",
    4: "n_reg_b_out", 5: "n_reg_c_out", 6: "n_alu_out", 7: "n_sw_out",
}
# MISC code -> the ONE directly-wired output that must read LOW (codes 2/3
# drive internal n_pc_load_jmp/n_cond instead -- handled via n_pc_load in
# _expect below, not listed here).
MISC_LOW = {0: None, 1: "n_pc_clear", 4: "n_mdr_out", 6: "n_reg_out_load"}


def _expect(dst, src, misc, z):
    """The full 20-signal expectation for one (dst,src,misc,FLAG_Z) state,
    derived directly from the gate equations in the header comment above
    -- an independent restatement from the generated netlist, not a
    re-import of the rig's own cw_expect.h model."""
    e = {name: True for name in OUT_NAMES}   # every '138 output idles HIGH;
    #   src_active is just SRC's own code-0 target (SRC_LOW[0]) below, no
    #   different from any other decode output -- it only READS low at
    #   idle because idle SRC *is* code 0.
    lo = DST_LOW.get(dst)
    if lo:
        e[lo] = False
    lo = SRC_LOW.get(src)
    if lo:
        e[lo] = False
    lo = MISC_LOW.get(misc)
    if lo:
        e[lo] = False
    # n_pc_load = NOR(cond_taken, pc_load_jmp)
    #   pc_load_jmp = INV(n_pc_load_jmp); n_pc_load_jmp is U29's o2_n,
    #     LOW only at misc==2 (PC_LOAD) -> pc_load_jmp True only there.
    #   cond_taken = NOR(n_cond, flag_z); n_cond is U29's o3_n, LOW only
    #     at misc==3 (COND) -> cond_taken True only when misc==3 and Z=0.
    pc_load_jmp = (misc == 2)
    n_cond = (misc != 3)
    cond_taken = (not n_cond) and (not z)
    e["n_pc_load"] = not (cond_taken or pc_load_jmp)
    return e


def _cw_set(dst, src, misc):
    return dst | (src << 3) | (misc << 6)


async def _drive(dut, dst, src, misc, z):
    dut.cw.value = _cw_set(dst, src, misc)
    dut.flag_z.value = 1 if z else 0
    await _settle(dut)


def _sample(dut):
    return {name: bool(int(getattr(dut, name).value)) for name in OUT_NAMES}


def _check(dut, dst, src, misc, z, tag):
    got = _sample(dut)
    want = _expect(dst, src, misc, z)
    bad = [n for n in OUT_NAMES if got[n] != want[n]]
    assert not bad, (
        f"{tag} dst={dst} src={src} misc={misc} z={int(z)}: "
        + ", ".join(f"{n}={int(got[n])}(want {int(want[n])})" for n in bad)
    )


async def _bind_idle(dut):
    # clk_sys is a dead port on this purely combinational sheet (nothing
    # in the architecture references it -- no clock needed).
    #
    # INVESTIGATED, not silently accepted: this test run prints three
    # "NUMERIC_STD.TO_INTEGER: metavalue detected" warnings at @0ms, one
    # per '138 instance. Root cause traced (not guessed) to
    # fpga/gen/control_word.vhd's own port maps -- U28/U29/U30's e1_n/
    # e2_n/e3 are wired to VHDL LITERAL constants ('0'/'0'/'1'), matching
    # the real board (mod_control_word.c: "E1=E2=GND, E3=+5V -- always
    # enabled"), not to signals. A literal constant is defined at
    # elaboration with no 'U' state, so each '138's enable guard is
    # already TRUE on VHDL's own mandatory once-only t=0 initial process
    # pass -- which runs before ANY external VPI stimulus (cocotb) can
    # possibly execute, by the language's own initialization-phase
    # semantics. That first pass calls to_integer on cw's still-'U'
    # address bits once, then never again (confirmed: exactly 3
    # occurrences, always at 0.00ns, never mid-run) -- reordering this
    # helper to deposit cw before any `await` (tried first) made no
    # difference, which is the confirming experiment, not a guess. Unlike
    # Task 4's ALU metavalue fix (a real modeling bug in an editable TTL
    # primitive), this is a simulation-only artifact of a `DO NOT EDIT`
    # generated file whose wiring is correct and matches the schematic;
    # there is no testbench-side fix, and none is warranted here.
    dut.cw.value = 0
    dut.flag_z.value = 1
    await _settle(dut)


@cocotb.test()
async def test_control_word_dst_group_one_hot(dut):
    """Ports mod_control_word.c t_control_word_walk's DST sweep: each
    code 0-7 with SRC/MISC held at NONE -- exactly the one named DST
    output goes low, and SRC/MISC's own outputs never move."""
    await _bind_idle(dut)
    for dst in range(8):
        await _drive(dut, dst, 0, 0, True)
        _check(dut, dst, 0, 0, True, "DST_walk")


@cocotb.test()
async def test_control_word_src_group_one_hot(dut):
    """Ports mod_control_word.c t_control_word_walk's SRC sweep, incl.
    the src_active=LOW-only-at-NONE special case (bug-4 fix)."""
    await _bind_idle(dut)
    for src in range(8):
        await _drive(dut, 0, src, 0, True)
        _check(dut, 0, src, 0, True, "SRC_walk")


@cocotb.test()
async def test_control_word_misc_group_one_hot(dut):
    """Ports mod_control_word.c t_control_word_walk's MISC sweep (the
    directly-wired codes: NONE, PC_CLEAR, MDR_OUT, REG_OUT_LOAD)."""
    await _bind_idle(dut)
    for misc in (0, 1, 4, 6):
        await _drive(dut, 0, 0, misc, True)
        _check(dut, 0, 0, misc, True, "MISC_walk")


@cocotb.test()
async def test_control_word_all_groups_active_no_interaction(dut):
    """Ports mod_control_word.c t_control_word_walk's cross-group rows
    (0x1FF/7-7-7, 0x0AA/2-5-2, 0x155/5-2-5) -- all three '138s driven
    non-NONE simultaneously must decode independently; the old NONE/NC
    tie-together fight (CLAUDE.md session ledger) would show up here as
    an extra low bit somewhere in the 20-wire vector."""
    await _bind_idle(dut)
    for dst, src, misc in ((7, 7, 7), (2, 5, 2), (5, 2, 5)):
        await _drive(dut, dst, src, misc, True)
        _check(dut, dst, src, misc, True, "all_active")


@cocotb.test()
async def test_control_word_cond_truth(dut):
    """Ports mod_control_word.c t_control_word_truth: the 4 documented
    U62 rows for JNZ (misc=COND=3) and JMP (misc=PC_LOAD=2), both Z
    values -- n_pc_load is the ONE externally observable signal carrying
    the COND logic on this sheet (n_cond/pc_load_jmp/cond_taken are
    internal nets with no port here)."""
    await _bind_idle(dut)
    # JNZ, Z=0 (not-zero -> taken -> loads)
    await _drive(dut, 0, 0, 3, False)
    assert int(dut.n_pc_load.value) == 0, "n_pc_load: JNZ Z=0 (taken) -> want 0 (loads)"
    # JNZ, Z=1 (zero -> not taken -> no load)
    await _drive(dut, 0, 0, 3, True)
    assert int(dut.n_pc_load.value) == 1, "n_pc_load: JNZ Z=1 (not taken) -> want 1 (no load)"
    # JMP, Z don't-care -> always loads
    await _drive(dut, 0, 0, 2, False)
    assert int(dut.n_pc_load.value) == 0, "n_pc_load: JMP Z=0 -> want 0 (loads)"
    await _drive(dut, 0, 0, 2, True)
    assert int(dut.n_pc_load.value) == 0, "n_pc_load: JMP Z=1 -> want 0 (loads)"
    # idle -> never loads, either Z
    await _drive(dut, 0, 0, 0, False)
    assert int(dut.n_pc_load.value) == 1, "n_pc_load: idle Z=0 -> want 1 (no load)"
    await _drive(dut, 0, 0, 0, True)
    assert int(dut.n_pc_load.value) == 1, "n_pc_load: idle Z=1 -> want 1 (no load)"
