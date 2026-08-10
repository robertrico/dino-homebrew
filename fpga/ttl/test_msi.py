import cocotb
import itertools
from cocotb.triggers import Timer

# Combinational MSI testbenches (Task 3): '138 decoder, '157 mux, '244
# tri-state buffer, '245 transceiver. One test per entity, all in this one
# file (mirrors test_gates.py's layout); the Makefile's COCOTB_TEST_FILTER
# selects the single test valid for whichever MODEL is being built, same
# mechanism as test_gates.py (see that Makefile's comment for the anchor/
# backslash gotchas already paid for there).


@cocotb.test()
async def decoder_truth_table(dut):
    # '138: every select code (a2 a1 a0) x every enable combination
    # (e3, e1_n, e2_n). Decoder is enabled only when e3='1' and
    # e1_n='0' and e2_n='0' (netlist-derived polarities, see the model's
    # header comment); disabled -> every output idles high (inactive,
    # active-low outputs).
    outs = [dut.o0_n, dut.o1_n, dut.o2_n, dut.o3_n,
            dut.o4_n, dut.o5_n, dut.o6_n, dut.o7_n]
    for e3, e1_n, e2_n in itertools.product((0, 1), repeat=3):
        dut.e3.value = e3
        dut.e1_n.value = e1_n
        dut.e2_n.value = e2_n
        enabled = (e3 == 1 and e1_n == 0 and e2_n == 0)
        for sel in range(8):
            dut.a0.value = sel & 1
            dut.a1.value = (sel >> 1) & 1
            dut.a2.value = (sel >> 2) & 1
            await Timer(1, unit="ns")
            for i, o in enumerate(outs):
                exp = 0 if (enabled and i == sel) else 1
                assert o.value == exp, (
                    f"o{i}_n: sel={sel} e3={e3} e1_n={e1_n} e2_n={e2_n} "
                    f"-> {o.value}, want {exp}"
                )


@cocotb.test()
async def mux_truth_table(dut):
    # '157: both selects, and strobe high forcing all four outputs low
    # regardless of select/inputs (netlist-derived active-low strobe).
    channels = [
        ("i0a", "i1a", "za"), ("i0b", "i1b", "zb"),
        ("i0c", "i1c", "zc"), ("i0d", "i1d", "zd"),
    ]
    for s, e_n, i0v, i1v in itertools.product((0, 1), repeat=4):
        dut.s.value = s
        dut.e_n.value = e_n
        for i0n, i1n, zn in channels:
            getattr(dut, i0n).value = i0v
            getattr(dut, i1n).value = i1v
        await Timer(1, unit="ns")
        for i0n, i1n, zn in channels:
            z = getattr(dut, zn)
            if e_n == 1:
                exp = 0
            else:
                exp = i1v if s == 1 else i0v
            assert z.value == exp, (
                f"{zn}: s={s} e_n={e_n} {i0n}={i0v} {i1n}={i1v} "
                f"-> {z.value}, want {exp}"
            )


@cocotb.test()
async def buffer_tri_state(dut):
    # '244: two independent 4-bit sections. Each section drives its Y
    # outputs from A when its G_n is low, and floats ('Z') when G_n is
    # high -- checked explicitly, not just "some other value", since a
    # buffer that always drove 0 when disabled would also look "different"
    # from the driven case but be functionally wrong.
    sections = [
        ("s1g_n", [("s1a1", "s1y1"), ("s1a2", "s1y2"),
                    ("s1a3", "s1y3"), ("s1a4", "s1y4")]),
        ("s2g_n", [("s2a1", "s2y1"), ("s2a2", "s2y2"),
                    ("s2a3", "s2y3"), ("s2a4", "s2y4")]),
    ]
    for gn_name, pairs in sections:
        gn = getattr(dut, gn_name)
        for g_val in (0, 1):
            gn.value = g_val
            for av in (0, 1):
                for a_name, y_name in pairs:
                    getattr(dut, a_name).value = av
                await Timer(1, unit="ns")
                for a_name, y_name in pairs:
                    y = getattr(dut, y_name)
                    if g_val == 0:
                        assert y.value == av, (
                            f"{y_name}: {gn_name}=0 {a_name}={av} "
                            f"-> {y.value}, want {av}"
                        )
                    else:
                        assert str(y.value) == "Z", (
                            f"{y_name}: {gn_name}=1 {a_name}={av} "
                            f"-> {y.value}, want Z"
                        )


def _set_byte(dut, prefix, val):
    for i in range(8):
        getattr(dut, f"{prefix}{i}_i").value = (val >> i) & 1


def _read_byte(dut, prefix):
    v = 0
    for i in range(8):
        v |= (int(getattr(dut, f"{prefix}{i}_o").value) & 1) << i
    return v


def _assert_side_is_z(dut, prefix, why):
    for i in range(8):
        name = f"{prefix}{i}_o"
        got = str(getattr(dut, name).value)
        assert got == "Z", f"{name}: {why} -> {got}, want Z"


@cocotb.test()
async def xcvr_both_directions(dut):
    # '245: both directions, mirror-witness style (an asymmetric path, not
    # a write-then-read-back-through-the-same-pins round trip -- see
    # CLAUDE.md's "Mirror-witness" rule). Task-13 rework item 1 split
    # a0-7/b0-7 from `inout` into `_i`/`_o` pairs (ghdl-yosys-plugin severs
    # internal nets touching a sub-instance `inout` port at synthesis
    # import): `_i` is the pure sense input, `_o` is this model's own
    # drive. For dir='1' the model drives b_o <= a_i (per its own
    # architecture body: "b_o <= a_i when (ce_n='0' and dir='1')"), so
    # cocotb (the external driver in this testbench) drives a_i and reads
    # b_o. For dir='0' the model drives a_o <= b_i instead, so cocotb
    # drives b_i and reads back what the model relayed onto a_o. No more
    # release-before-switching-direction dance needed -- `_i` and `_o` are
    # now separate wires, so there is no contention to avoid.
    dut.ce_n.value = 0
    dut.dir.value = 1
    _set_byte(dut, "a", 0x3C)
    await Timer(10, unit="ns")
    got = _read_byte(dut, "b")
    assert got == 0x3C, f"dir=1: b_o=0x{got:02X} not 0x3C"

    dut.dir.value = 0
    _set_byte(dut, "b", 0xC3)
    await Timer(10, unit="ns")
    got = _read_byte(dut, "a")
    assert got == 0xC3, f"dir=0: a_o=0x{got:02X} not 0xC3"


@cocotb.test()
async def xcvr_releases_the_side_it_is_not_driving(dut):
    """The '245's RELEASE behaviour, asserted directly rather than assumed.

    This is the load-bearing property behind fpga/synth/dead_tbuf.v, which
    DELETES the tri-state driver on the non-driving side of every
    constant-`dir` '245 in the design (64 of the 68 cells it removes). That
    deletion is only exact if the model really does drive 'Z' there -- and
    after the item-1 `inout` -> `_i`/`_o` split, nothing in this suite
    checked it: xcvr_both_directions reads only the ACTIVE side, so a model
    that drove both sides at once would sail through it.

    Three cases, all straight off ttl_74ls245.vhd's own two concurrent
    assignments:
      ce_n=1, dir=1  -> BOTH sides released (chip deselected)
      ce_n=1, dir=0  -> BOTH sides released (deselect beats direction)
      ce_n=0, dir=1  -> A released while B is actively driven, and vice
      ce_n=0, dir=0  -> B released while A is actively driven
    The active-side value is re-asserted in the last two so this cannot
    pass by the model having stopped driving altogether."""
    # --- deselected: neither side drives, whichever way dir points -------
    dut.ce_n.value = 1
    for d in (1, 0):
        dut.dir.value = d
        _set_byte(dut, "a", 0x5A)
        _set_byte(dut, "b", 0xA5)
        await Timer(10, unit="ns")
        _assert_side_is_z(dut, "a", f"ce_n=1 dir={d} (deselected)")
        _assert_side_is_z(dut, "b", f"ce_n=1 dir={d} (deselected)")

    # --- selected: exactly ONE side drives ------------------------------
    dut.ce_n.value = 0
    dut.dir.value = 1               # A -> B, so a_o is the dead side
    _set_byte(dut, "a", 0x5A)
    _set_byte(dut, "b", 0xA5)
    await Timer(10, unit="ns")
    _assert_side_is_z(dut, "a", "ce_n=0 dir=1 (A is the input side)")
    assert _read_byte(dut, "b") == 0x5A, (
        f"ce_n=0 dir=1: b_o=0x{_read_byte(dut, 'b'):02X} not 0x5A -- the "
        f"active side must still be driving, or the Z check above is "
        f"vacuous")

    dut.dir.value = 0               # B -> A, so b_o is the dead side
    await Timer(10, unit="ns")
    _assert_side_is_z(dut, "b", "ce_n=0 dir=0 (B is the input side)")
    assert _read_byte(dut, "a") == 0xA5, (
        f"ce_n=0 dir=0: a_o=0x{_read_byte(dut, 'a'):02X} not 0xA5 -- the "
        f"active side must still be driving, or the Z check above is "
        f"vacuous")
