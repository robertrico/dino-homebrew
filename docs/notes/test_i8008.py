#!/usr/bin/env python3
"""Host tests for i8008.py -- the 8008 emulator that is PHASE_BASIC's answer key.

The emulator runs ORIGINAL SCELBAL; the DINO port must print what it
prints. So the emulator's semantics are pinned here instruction family by
instruction family, from the 8008 datasheet (Intel, 1972/1974):

  * ALU ops set C Z S P; AND/XOR/OR clear C.
  * SUB/SBB/CMP: C = 1 means BORROW (A < operand) -- the opposite sense
    of DINO's '382 CN+4, which the translator must invert.
  * INr/DCr set Z S P and LEAVE C ALONE.
  * Rotates touch C only.
  * P = 1 means EVEN parity.
  * The stack is 7 levels of return address inside the chip.

Run: python3 test_i8008.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as8                                                    # noqa: E402
import i8008                                                  # noqa: E402


def run(src, **regs):
    img, sym = as8.assemble("\tORG 000#000\n" + src + "\n\tHLT\n")
    cpu = i8008.CPU(img)
    for k, v in regs.items():
        setattr(cpu, k, v)
    cpu.run(max_steps=10_000)
    return cpu


def test_moves_and_memory():
    c = run("\tLHI 003\n\tLLI 004\n\tLMI 125\n\tLAM\n\tLBA\n\tLCB")
    assert c.mem[0o3 * 256 + 4] == 0o125
    assert (c.a, c.b, c.c) == (0o125, 0o125, 0o125)


def test_add_carry_and_flags():
    c = run("\tLAI 377\n\tADI 001")
    assert c.a == 0 and c.cy and c.z and not c.s and c.p
    c = run("\tLAI 177\n\tADI 001")
    assert c.a == 0x80 and not c.cy and c.s and not c.z and not c.p


def test_sub_carry_is_borrow():
    c = run("\tLAI 001\n\tSUI 002")
    assert c.a == 0xFF and c.cy and c.s
    c = run("\tLAI 005\n\tCPI 003")
    assert c.a == 5 and not c.cy and not c.z
    c = run("\tLAI 003\n\tCPI 003")
    assert c.z and not c.cy


def test_adc_sbb_use_carry():
    c = run("\tLAI 377\n\tADI 001\n\tLAI 001\n\tACI 001")
    assert c.a == 3 and not c.cy
    c = run("\tLAI 000\n\tSUI 001\n\tLAI 005\n\tSBI 001")
    assert c.a == 3 and not c.cy


def test_logic_clears_carry():
    c = run("\tLAI 377\n\tADI 001\n\tLAI 360\n\tNDI 017")
    assert c.a == 0 and c.z and not c.cy


def test_inr_dcr_leave_carry():
    c = run("\tLAI 377\n\tADI 001\n\tLBI 377\n\tINB")
    assert c.b == 0 and c.z and c.cy           # carry survived INB
    c = run("\tLAI 000\n\tNDA\n\tLCI 001\n\tDCC")
    assert c.c == 0 and c.z and not c.cy


def test_rotates():
    c = run("\tLAI 201\n\tRLC")
    assert c.a == 0o003 and c.cy
    c = run("\tLAI 201\n\tRRC")
    assert c.a == 0o300 and c.cy
    c = run("\tLAI 000\n\tNDA\n\tLAI 200\n\tRAL")
    assert c.a == 0 and c.cy
    c = run("\tLAI 377\n\tADI 001\n\tLAI 000\n\tRAR")   # C=1 rotates in
    assert c.a == 0x80 and not c.cy


def test_jumps_on_each_flag():
    c = run("\tLAI 000\n\tNDA\n\tJTZ 000#011\n\tLBI 001\n\tHLT\n"
            "\tLBI 002")                          # 000#011 = LBI 002
    assert c.b == 2
    c = run("\tLAI 200\n\tNDA\n\tJFS 000#011\n\tLBI 001\n\tHLT\n\tLBI 002")
    assert c.b == 1


def test_call_ret_and_conditional_return():
    src = ("\tCAL 000#006\n\tLBI 007\n\tHLT\n"     # 000#006 = sub
           "\tLAI 001\n\tNDA\n\tRFZ\n\tLBI 077\n\tRET")
    c = run(src)
    assert c.b == 7 and c.a == 1


def test_stack_wraps_like_silicon():
    """The 8008 keeps 7 return addresses in a circular file; an 8th CAL
    overwrites the oldest SILENTLY. SCELBAL relies on it: its error exits
    JMP to EXEC from deep inside calls and never unwind. Raising here was
    STRICTER than the hardware and made the reference refuse real input."""
    deep = "".join("\tCAL 000#%03o\n" % (3 * (i + 1)) for i in range(8))
    img, _ = as8.assemble("\tORG 000#000\n" + deep + "\tHLT\n")
    cpu = i8008.CPU(img)
    cpu.run(100)
    assert cpu.wraps == 1 and len(cpu.stack) == 7
    assert cpu.stack[0] == 6                    # the oldest (3) is gone


def test_hooks_replace_io_routines():
    """A hooked address behaves as a subroutine: the hook runs, then RET."""
    img, _ = as8.assemble("\tORG 000#000\n\tCAL 000#100\n\tLBA\n\tHLT\n"
                          "\tORG 000#100\n\tHLT\n")
    cpu = i8008.CPU(img)
    cpu.hooks[0o100] = lambda c: setattr(c, "a", 0o301)
    cpu.run(max_steps=100)
    assert cpu.b == 0o301


def test_inp_out_ports_are_hooks():
    """INP p / OUT p go to cpu.inp[p] / cpu.out[p]; neither touches a flag.
    Unhooked I/O still raises: SCELBAL's bit-banged serial must stay
    replaced, never silently executed."""
    img, _ = as8.assemble("\tORG 000#000\n\tLAI 000\n\tNDA\n\tINP 0\n"
                          "\tLBA\n\tLAI 007\n\tOUT 010\n\tHLT\n")
    cpu = i8008.CPU(img)
    seen = []
    cpu.inp[0] = lambda c: 0x5A
    cpu.out[8] = lambda c, v: seen.append(v)
    cpu.run(100)
    assert cpu.b == 0x5A and seen == [7] and cpu.z
    img, _ = as8.assemble("\tORG 000#000\n\tINP 5\n\tHLT\n")
    try:
        i8008.CPU(img).run(10)
    except ValueError:
        return
    raise AssertionError("unhooked INP must raise")


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
    print("OK test_i8008")
