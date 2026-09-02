#!/usr/bin/env python3
"""Host tests for isatest_gen.py — PROG_isa, the self-checking ISA test.

The important one is test_no_subtest_is_blind. A count of subtests is a blind
counter unless something proves each one discriminates, and this project has
been bitten by exactly that shape before (test_microcode_gen printed OK while
asserting nothing for weeks).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import isatest_gen as g                                       # noqa: E402
import progrom_gen as pr                                      # noqa: E402
from microcode_gen import INSTRUCTIONS                        # noqa: E402

FAILS = []


def check(cond, label):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILS.append(label)


def check_eq(got, want, label):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")
        FAILS.append(label)


def test_the_program_passes_its_own_test():
    print("PROG_isa passes in the oracle")
    prog, ids, _ = g.build()
    st = pr.simulate(prog, max_steps=400000)
    check(st["halted"], "it halts")
    if st["out"] != g.PASS:
        check(False, f"OB is {st['out']:#04x}, not the pass byte "
                     f"{g.PASS:#04x} — it names {ids.get(st['out'], '?')}")
    else:
        check(True, f"OB = {g.PASS:#04x}, the pass byte")


def test_no_subtest_is_blind():
    """Break each instruction's final row and require the program to notice.

    A subtest that still passes with its own instruction broken proves
    nothing, and counting it as coverage is worse than not having it."""
    print("mutation: every subtest discriminates")
    named, detected, blind, silent = g.mutate()
    check_eq(blind, [], "no subtest survives its instruction being broken")
    check(len(named) >= 130,
          f"{len(named)} subtests name their own instruction (want >= 130)")


def test_ids_start_at_one():
    """0x00 is a rail. A subtest numbered 0 could not be told from a dead
    output latch."""
    print("id numbering")
    _, ids, _ = g.build()
    check(min(ids) == 1, "ids start at 1, so 0x00 is never a test number")
    check(g.PASS not in ids, "the pass byte is not also a test id")
    check(pr.POISON not in ids, "the poison byte is not also a test id")
    check(max(ids) < g.PASS, "every id sorts below the pass byte")


def test_coverage_is_accounted_for():
    """Whatever is not covered here must be covered somewhere, or named."""
    print("coverage")
    _, ids, skipped = g.build()
    check_eq(len(ids) + len(skipped), len(INSTRUCTIONS),
             "every instruction is either tested or listed as skipped")
    out_family = {n for n in skipped if n.startswith("OUT")}
    pc_high = {n for n in skipped
               if n.endswith("PCH") or n in ("STPCL", "STPCH")}
    rest = set(skipped) - out_family - pc_high
    check_eq(sorted(rest), ["HALT", "NOP", "RET", "RST"],
             "the only un-grouped skips are the four with no readable result")
    check_eq(len(out_family), 17,
             "the OUT family needs a DIP-selected image: OB is write-only, so "
             "an OUT cannot be read back and compared inside the program")


def test_the_poison_prologue_is_first():
    """A wild jump can halt before reaching any OUT. Without a poison byte
    the display holds the PREVIOUS program's answer, which could read as a
    pass."""
    print("poison prologue")
    prog, _, _ = g.build()
    check_eq(prog[:2], [("LDAI", pr.POISON), ("OUT",)],
             "the program poisons OB before doing anything else")


def test_image_fits_and_is_pinned():
    print("image")
    prog, _, _ = g.build()
    code = pr.assemble(prog)
    check(len(code) < pr.ROM_WINDOW,
          f"{len(code)} bytes fits the {pr.ROM_WINDOW}-byte ROM window")
    img = pr.build_image(prog)
    check_eq(pr.crc16(img), 0xB96F, "PROG_isa crc — a move means a reburn")


if __name__ == "__main__":
    for _n, _f in sorted((kv for kv in list(globals().items())
                          if kv[0].startswith("test_") and callable(kv[1]))):
        _f()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\nPROG_isa: OK")
