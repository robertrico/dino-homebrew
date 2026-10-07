#!/usr/bin/env python3
"""Host tests for scelbal_xlate.py -- every 8008 macro against i8008.py.

PHASE_BASIC step 4b. ONE 8008 instruction at a time, from the same random
state, on both machines:

    8008   i8008.CPU, the instruction at 0x0200, HLT after it, jump/call
           target 0x0300 (HLT), a return address 0x0400 (HLT) on its stack
    DINO   simulate() on the real microcode: flags set through POPF, the
           macro, then a MARK cell says which way it left (1 fell through,
           2 returned, 3 jumped or called)

and then compares A, the virtual registers, PH, the memory cell H:L points
at, the exit, and every flag the context declares LIVE -- carry through
the polarity the context declares (T same, I inverted, Z0 = 8008 carry 0).
Contexts sweep liveness and polarity, because the macros differ by them.

Run: python3 test_scelbal_xlate.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as8                                                    # noqa: E402
import asm                                                    # noqa: E402
import i8008                                                  # noqa: E402
import progrom_gen as pg                                      # noqa: E402
import scelbal_flow as fl                                     # noqa: E402
import scelbal_xlate as x                                     # noqa: E402

MARK = 0x81F0                   # cells page, clear of 8008 data pages
REGS8 = "bcdehl"
STATES = 4


SW = 0xA5                       # what SW1 reads in these tests


def _dino(lines, st, pol):
    """Run macro lines on simulate() from 8008 state `st`."""
    dc = {"T": st["cy"], "I": not st["cy"], "Z0": True}[pol or "T"]
    fb = (1 if dc else 0) | (2 if st["z"] else 0)
    src = [f"{n}: .equ {a}" for n, a in x.CELL.items()] + [
           ".org 0x0000",
           "LXISP %d" % x.STACK, "CALL sub", "MVI %d, 2" % MARK, "HALT",
           "sub: LDAI %d" % fb, "PUSHA", "POPF", "LDAI %d" % st["a"]]
    src += lines + ["MVI %d, 1" % MARK, "HALT",
                    "tgt: MVI %d, 3" % MARK, "HALT"] + x.library(lines)
    src += x.table_lines()                  # ROM, read as data
    r = asm.assemble_text("\n".join(src) + "\n")
    image = pg.build_image_from_bytes(r.code, r.origin)
    ram = {}
    for n in REGS8:
        ram[x.CELL["V" + n.upper()]] = st[n]
    ram[x.CELL["PH"]] = x.page(st["h"])
    ram[x.CELL["VS"]] = 0x80 if st["s"] else 0
    ram[x.RAM_OF + (((st["h"] & 0x3F) << 8) | st["l"])] = st["m"]
    out = pg.simulate(None, image=image, ram_init=ram, max_steps=20000,
                      switches=SW)
    assert out["halted"], "DINO did not halt"
    return out


def _i8008(mnem, operand, st):
    text = "\tORG 002#000\n\t%s %s\n\tHLT\n\tORG 003#000\n\tHLT\n" \
           "\tORG 004#000\n\tHLT\n" % (mnem, operand)
    img, _ = as8.assemble(text)
    cpu = i8008.CPU(img, pc=0x0200)
    for n in "a" + REGS8:
        setattr(cpu, n, st[n])
    cpu.cy, cpu.z, cpu.s = st["cy"], st["z"], st["s"]
    cpu.mem[cpu.hl] = st["m"]
    cpu.stack = [0x0400]
    cpu.inp[0] = lambda c: SW
    cpu.leds = []
    cpu.out[8] = lambda c, v: cpu.leds.append(v)
    cpu.run(100)
    mark = {0x0300: 3, 0x0400: 2}.get(cpu.pc, 1)
    return cpu, mark


def _state(rng, pol):
    st = {n: rng.randrange(256) for n in "a" + REGS8}
    st["h"] = rng.choice([p for p in range(0o060) if p not in (2, 3, 4)])
    #         a data page <= 057, never the test's own code pages 2-4
    st["m"] = rng.randrange(256)
    st["cy"] = bool(rng.randrange(2)) if pol != "Z0" else False
    st["z"], st["s"] = bool(rng.randrange(2)), bool(rng.randrange(2))
    if rng.randrange(4) == 0:               # edge values
        st["a"] = rng.choice([0, 1, 0x7F, 0x80, 0xFF])
    return st


def check(mnem, operand, live, pol=None, norm=None, seed=0, fused=False,
          dead=frozenset()):
    """fused=True: the context says H and L are KNOWN (the state's own),
    so M becomes an absolute address and LHI/LLI of the held value is
    dropped -- the forms scelbal_flow's constants select."""
    rng = random.Random(f"{mnem}{operand}{sorted(live)}{pol}{norm}{seed}"
                        f"{fused}")
    oper = str(as8.value(operand, {})) if operand and operand[0] in "01234567" \
        else operand
    for _ in range(STATES):
        st = _state(rng, pol)
        if fused and mnem in ("LHI", "LLI") and rng.randrange(2):
            st["h" if mnem == "LHI" else "l"] = as8.value(operand, {})
        ctx = x.Ctx(live=live, pol=pol, norm=norm, label="k", target="tgt",
                    h=st["h"] if fused else None,
                    l=st["l"] if fused else None, dead=dead)
        lines = x.macro(mnem, oper, ctx)
        cpu, mark8 = _i8008(mnem, operand or "", st)
        d = _dino(lines, st, pol)
        ram = d["ram"]
        tag = f"{mnem} {operand} live={sorted(live)} pol={pol} st={st}"
        assert ram.get(MARK) == mark8, f"{tag}: exit {ram.get(MARK)} != {mark8}"
        assert d["A"] == cpu.a, f"{tag}: A {d['A']:#x} != {cpu.a:#x}"
        assert d["outs"] == cpu.leds, f"{tag}: LEDs {d['outs']} {cpu.leds}"
        for n in REGS8:
            if "V" + n.upper() in dead:
                continue
            got = ram[x.CELL["V" + n.upper()]]
            assert got == getattr(cpu, n), f"{tag}: {n} {got:#x}"
        if "PH" not in dead:
            assert ram[x.CELL["PH"]] == x.page(cpu.h), f"{tag}: PH"
        hl0 = ((st["h"] & 0x3F) << 8) | st["l"]     # the cell M was
        assert ram.get(x.RAM_OF + hl0, 0) == cpu.mem[hl0], f"{tag}: M"
        if "Z" in live:
            assert bool(d["flag_z"]) == cpu.z, f"{tag}: Z"
        if "S" in live:
            assert bool(ram[x.CELL["VS"]] & 0x80) == cpu.s, f"{tag}: S"
        if "C" in live:
            po = fl.c_transfer(mnem, frozenset({pol or "T"}), norm)
            (p,) = po
            if p == "Z0":
                assert not cpu.cy, f"{tag}: 8008 C should be 0"
            else:
                assert d["flag_c_defined"], f"{tag}: DINO C undefined"
                want = cpu.cy if p == "T" else not cpu.cy
                assert bool(d["flag_c"]) == want, f"{tag}: C (pol {p})"


def test_oracle_forgets_flags_byte_once_mdr_moves_on():
    """simulate() refuses to let MDR replay a PUSHF byte (it models only C
    and Z of it). After POPF, MVI parks its ROM immediate in MDR and
    replays THAT -- the flags byte is gone from MDR on silicon, so the
    oracle must not still be guarding it."""
    src = ("LXISP 0xB3FF\nLDAI 1\nPUSHA\nPOPF\nPUSHF\nPOPF\n"
           "MVI 0xB3F0, 0x5A\nHALT\n")
    r = asm.assemble_text(src)
    out = pg.simulate(None, image=pg.build_image_from_bytes(r.code, r.origin))
    assert out["halted"] and out["ram"].get(0xB3F0) == 0x5A


LIVES = [fl.ALL, frozenset(), frozenset("C"), frozenset("ZC"),
         frozenset("CS"), frozenset("ZS")]
REG = "ABCDEHLM"


def test_moves():
    for d in REG:
        for s in REG:
            if d == s == "M":
                continue
            check(f"L{d}{s}", "", fl.ALL, pol="T")
            check(f"L{d}{s}", "", fl.ALL, pol="I")


def test_load_immediate():
    for d in REG:
        for v in ("000", "177", "377", "125"):
            check(f"L{d}I", v, fl.ALL, pol="T")


def test_alu_register_and_memory():
    for op in ("AD", "SU", "ND", "XR", "OR", "CP"):
        for s in REG:
            for live in LIVES:
                check(f"{op}{s}", "", live, pol="T")
                if op in ("ND", "XR", "OR") and "C" in live:
                    check(f"{op}{s}", "", live, pol="T", norm="T")
                    check(f"{op}{s}", "", live, pol="T", norm="I")


def test_alu_with_carry():
    for s in REG:
        check(f"AC{s}", "", fl.ALL, pol="T")
        check(f"AC{s}", "", fl.ALL, pol="Z0")
        check(f"SB{s}", "", fl.ALL, pol="I")
        check(f"SB{s}", "", fl.ALL, pol="Z0")


def test_alu_immediate():
    for op in ("AD", "SU", "ND", "XR", "OR", "CP"):
        for v in ("000", "001", "177", "200", "260", "377"):
            for live in LIVES:
                check(f"{op}I", v, live, pol="T")
    for v in ("000", "001", "377"):
        check("ACI", v, fl.ALL, pol="T")
        check("ACI", v, fl.ALL, pol="Z0")
        check("SBI", v, fl.ALL, pol="I")
        check("SBI", v, fl.ALL, pol="Z0")


def test_inc_dec_keep_carry():
    for op in ("IN", "DC"):
        for r in "BCDEHL":
            for live in LIVES:
                pols = ("T", "I") if "C" in live else ("T",)
                for pol in pols:
                    for seed in range(3):
                        check(f"{op}{r}", "", live, pol=pol, seed=seed)


def test_rotates():
    for m in ("RLC", "RRC"):
        for seed in range(4):
            check(m, "", frozenset("C"), pol="I", seed=seed)
    for m in ("RAL", "RAR"):
        for seed in range(4):
            check(m, "", frozenset("C"), pol="T", seed=seed)


def test_branches_every_flag_and_polarity():
    for kind in ("J", "C", "R"):
        for sense in "TF":
            for flag in "ZCS":
                m = f"{kind}{sense}{flag}"
                opd = "003#000" if kind in "JC" else ""
                pols = ("T", "I", "Z0") if flag == "C" else ("T",)
                for pol in pols:
                    for live in (fl.ALL, frozenset(flag)):
                        for seed in range(3):
                            check(m, opd, live, pol=pol, seed=seed)


def test_fused_absolute_forms():
    for m in ("LAM", "LMA", "LBM", "LMB", "ADM", "SUM", "CPM", "NDM"):
        for live in (fl.ALL, frozenset()):
            check(m, "", live, pol="T", fused=True)
    check("ACM", "", fl.ALL, pol="T", fused=True)
    check("SBM", "", fl.ALL, pol="I", fused=True)
    for v in ("000", "125", "377"):
        check("LMI", v, fl.ALL, pol="T", fused=True)
    for v in ("001", "026", "057"):
        check("LHI", v, fl.ALL, pol="T", fused=True)
    for v in ("000", "201"):
        check("LLI", v, fl.ALL, pol="T", fused=True)


def test_io_ports_for_udf():
    """INP 0 = SW1 at 0x4000, OUT 010 = OB. Neither touches a flag."""
    for live in (fl.ALL, frozenset()):
        for seed in range(3):
            check("INP", "0", live, pol="T", seed=seed)
            check("OUT", "010", live, pol="T", seed=seed)


def test_dead_stores_dropped_and_nothing_else_changes():
    """A dead cell may hold anything; every LIVE thing must still match."""
    for d in "BCDEHL":
        cells = ("VH", "PH") if d == "H" else ("V" + d,)
        for sub in ([cells], [[c] for c in cells] if d == "H" else []):
            for dead in sub:
                check(f"L{d}I", "125", fl.ALL, pol="T", dead=frozenset(dead))
                for s_ in "ABM":
                    if s_ != d:
                        check(f"L{d}{s_}", "", fl.ALL, pol="T",
                              dead=frozenset(dead))
    lines = x.macro("LLI", "5", x.Ctx(dead=frozenset({"VL"})))
    assert lines == [], lines


def test_peek_poke_ports_reach_dino_memory():
    """INP 1 / OUT 011 (peekpoke.as8): A <-> DINO [VD:VE], no flag moves."""
    import random as _r
    rng = _r.Random(7)
    for _ in range(6):
        d, e, a, v = 0xF0 + rng.randrange(8), rng.randrange(256), \
            rng.randrange(256), rng.randrange(256)
        for m, port in (("INP", "1"), ("OUT", "9")):
            lines = x.macro(m, port, x.Ctx(label="k"))
            src = [f"{n}: .equ {q}" for n, q in x.CELL.items()] + [
                ".org 0", "LXISP %d" % x.STACK, "LDAI 3", "PUSHA", "POPF",
                "LDAI %d" % a] + lines + ["HALT"]
            r = asm.assemble_text("\n".join(src) + "\n")
            st = pg.simulate(None, image=pg.build_image_from_bytes(r.code, 0),
                             ram_init={x.CELL["VD"]: d, x.CELL["VE"]: e,
                                       (d << 8) | e: v})
            assert st["flag_c"] == 1 and st["flag_z"] == 1, m
            if m == "INP":
                assert st["A"] == v, (hex(st["A"]), hex(v))
            else:
                assert st["ram"][(d << 8) | e] == a and st["A"] == a


def test_table_page_lives_in_rom():
    assert x.page(0o61) < 0x40, hex(x.page(0o61))
    assert x.page(0o60) >= 0x84


def test_unconditional():
    check("JMP", "003#000", fl.ALL, pol="T")
    check("CAL", "003#000", fl.ALL, pol="T")
    check("RET", "", fl.ALL, pol="T")


# ---- runner: ENUMERATED (test_suite_reachability.py) -------------------
if __name__ == "__main__":
    _failed = []
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        try:
            _fn()
            print(f"  ok   {_name}")
        except Exception as _e:                   # noqa: BLE001
            _failed.append((_name, _e))
            print(f"  FAIL {_name}: {type(_e).__name__}: {_e}")
    if _failed:
        print(f"\n{len(_failed)} FAILED")
        sys.exit(1)
    print("OK test_scelbal_xlate")
