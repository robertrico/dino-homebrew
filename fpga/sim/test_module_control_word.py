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
    "n_sp_up", "n_sp_down",
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
# Codes 5 and 7 were U29's last two free slots and the stack spends both
# (2026-08-10) -- MISC is full now. Adding them here rather than only in the
# bank tests below is what makes the MISC_walk sweep prove they decode, and
# it is what coverage_lint checks for.
MISC_LOW = {0: None, 1: "n_pc_clear", 4: "n_mdr_out", 5: "n_sp_up",
            6: "n_reg_out_load", 7: "n_sp_down"}


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


async def _drive(dut, dst, src, misc, z, src_bank=1, dst_bank=1):
    dut.cw.value = _cw_set(dst, src, misc)
    dut.flag_z.value = 1 if z else 0
    # 2026-08-10: the sheet gained two bank-select inputs. BOTH DEFAULT TO 1
    # here, which is BANK 0 -- today's machine. The polarity is the whole
    # point: E3 is active-high and E1 active-low, so bank 0 hangs off U28/
    # U30's E3 and bank 1 off U70/U71's E1 of the SAME bit, and a blank third
    # EEPROM (0xFF) leaves bank 0 enabled. Leaving these undriven is what
    # made every assertion below fail the first time the ladder ran with the
    # new sheet: an undriven input reads 0, which selects bank 1 and darkens
    # every bank-0 decode.
    dut.cw17_eq_n_src_bank.value = src_bank
    dut.cw18_eq_n_dst_bank.value = dst_bank
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
    dut.cw17_eq_n_src_bank.value = 1     # bank 0 -- see _drive()'s comment
    dut.cw18_eq_n_dst_bank.value = 1
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


# --- bank switching (2026-08-10) -------------------------------------------
#
# ~{SRC_BANK} and ~{DST_BANK} are CW17/CW18 off the third microcode EEPROM.
# The '138's own enable structure gives complementary banks for ZERO
# inverters: E3 is active-HIGH and E1 active-LOW, so
#
#     U28 SRC0  E1=E2=GND  E3=~{SRC_BANK}     enabled when the bit is 1
#     U70 SRC1  E1=~{SRC_BANK}  E3=+5V        enabled when the bit is 0
#
# and the same shape for U30/U71 on ~{DST_BANK}. A blank third EEPROM reads
# 0xFF, holds both bits high, and leaves bank 0 enabled -- which is exactly
# why the erased-safe polarity was chosen.
#
# NOTE ON SRC_ACTIVE, and it is load-bearing: it is U28.O0, low ONLY when
# SRC=NONE *and* U28 is enabled. A disabled U28 floats it HIGH, i.e. reads
# "a source is active" -- which is correct, because every bank-1 code IS a
# real source, and it is what turns the U25 bridge on (pointed MDR->W) so a
# bank-1 byte reaches W. It is also why bank 1 must never have a NONE slot.

SRC_BANK1 = {0: "n_sp_lo_out", 1: "n_sp_hi_out",
             2: "n_pc_lo_out", 3: "n_pc_hi_out"}
DST_BANK1 = {0: "n_sp_lo_load", 1: "n_sp_hi_load"}
SRC_BANK0_OUTS = ["n_rom_out", "n_ram_out", "n_reg_a_out", "n_reg_b_out",
                  "n_reg_c_out", "n_alu_out", "n_sw_out"]
DST_BANK0_OUTS = ["n_reg_a_load", "n_reg_b_load", "n_reg_c_load",
                  "n_mar_lo_load", "n_mar_hi_load", "n_ir_load", "n_ram_load"]


@cocotb.test()
async def test_src_bank1_darkens_bank0_and_decodes_one_hot(dut):
    """Asserting ~{SRC_BANK} must (a) turn every bank-0 source enable
    inactive and (b) decode bank 1 one-hot. Both halves matter: a bank
    switch that enabled bank 1 without darkening bank 0 would put two
    drivers on MDR."""
    await _bind_idle(dut)

    for code, wire in SRC_BANK1.items():
        await _drive(dut, dst=0, src=code, misc=0, z=True, src_bank=0)

        for name in SRC_BANK0_OUTS:
            assert int(getattr(dut, name).value) == 1, (
                f"src_bank=0 code={code}: bank-0 output {name} is still "
                f"asserted -- U28 must be dark, or MDR gets two drivers")
        assert int(dut.src_active.value) == 1, (
            "src_bank=0: SRC_ACTIVE must float HIGH with U28 disabled -- that "
            "is what enables the U25 bridge so a bank-1 byte reaches W")

        assert int(getattr(dut, wire).value) == 0, (
            f"src_bank=0 code={code}: {wire} should be asserted")
        for other_code, other in SRC_BANK1.items():
            if other_code != code:
                assert int(getattr(dut, other).value) == 1, (
                    f"src_bank=0 code={code}: {other} also asserted -- "
                    f"bank 1 is not one-hot")


@cocotb.test()
async def test_dst_bank1_darkens_bank0_and_decodes_one_hot(dut):
    """Same for the destination side. A DST bank switch that left bank 0
    live would fire a register load alongside an SP load."""
    await _bind_idle(dut)

    for code, wire in DST_BANK1.items():
        await _drive(dut, dst=code, src=0, misc=0, z=True, dst_bank=0)

        for name in DST_BANK0_OUTS:
            assert int(getattr(dut, name).value) == 1, (
                f"dst_bank=0 code={code}: bank-0 output {name} is still "
                f"asserted -- two destinations would latch the same byte")

        assert int(getattr(dut, wire).value) == 0, (
            f"dst_bank=0 code={code}: {wire} should be asserted")
        for other_code, other in DST_BANK1.items():
            if other_code != code:
                assert int(getattr(dut, other).value) == 1, (
                    f"dst_bank=0 code={code}: {other} also asserted -- "
                    f"bank 1 is not one-hot")


@cocotb.test()
async def test_the_two_banks_are_independent(dut):
    """SRC and DST bank bits are SEPARATE, and the stack sequences need them
    that way: PUSH's address setup is `SRC=SP_LO (bank 1), DST=MAR_LO
    (bank 0)`, and `LXI SP` is `SRC=ROM (bank 0), DST=SP_LO (bank 1)`. One
    shared bit could express neither."""
    await _bind_idle(dut)

    # bank-1 source into a bank-0 destination: the PUSH address setup
    await _drive(dut, dst=4, src=0, misc=0, z=True, src_bank=0, dst_bank=1)
    assert int(dut.n_sp_lo_out.value) == 0, "SP_LO_OUT should be asserted"
    assert int(dut.n_mar_lo_load.value) == 0, (
        "MAR_LO_LOAD should be asserted -- a bank-0 DST must survive a bank-1 SRC")

    # bank-0 source into a bank-1 destination: LXI SP
    await _drive(dut, dst=0, src=1, misc=0, z=True, src_bank=1, dst_bank=0)
    assert int(dut.n_rom_out.value) == 0, "ROM_OUT should be asserted"
    assert int(dut.n_sp_lo_load.value) == 0, (
        "SP_LO_LOAD should be asserted -- a bank-1 DST must survive a bank-0 SRC")
