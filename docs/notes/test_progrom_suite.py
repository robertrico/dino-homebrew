#!/usr/bin/env python3
"""Host tests for PROG_suite — the whole coverage regression in ONE burn.

WHY IT EXISTS. The twelve-image regression costs twelve ROM pulls, and on a
breadboard machine with no ZIF on the program socket every pull is a chance
to disturb the setup. Card zero made the machine readable at run time, so the
selector can be a DIP setting instead of a chip swap: set SW1 to 1-12, press
RESET, read OB.

Nothing here hand-computes an expected result. `progrom_gen.simulate()`
interprets the burned microcode rows, so the expectation and the hardware
cannot disagree by construction — the same discipline as the per-image
coverage tests this replaces the burning of, not the checking of.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import progrom_gen as pg

FAILS = []


def check_eq(got, want, label):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")
        FAILS.append(label)


# The answer key. These are the SAME twelve values the standalone images
# return on the bench, and they are pinned here as literals on purpose: if
# the suite's dispatch lands on the wrong slot, an expectation computed from
# the suite itself would move with the fault and prove nothing.
SUITE_EXPECTED = {
    1:  ("mardisc", 0x6B),
    2:  ("pads",    0x40),
    3:  ("mem",     0xC5),
    4:  ("flow",    0x39),
    5:  ("alu",     0x39),
    6:  ("loop",    0x15),
    7:  ("sp",      0x27),
    8:  ("sp2",     0x53),
    9:  ("sp3",     0x2C),
    10: ("call",    0x4B),
    11: ("stack",   0x27),
    12: ("ramexec", 0x6E),
}


def test_every_selector_runs_its_own_test():
    """SW1 = n runs test n and OB reads what the standalone image reads."""
    print("suite: each selector reaches its own slot")
    img = pg.build_suite()
    for sel, (tag, want) in sorted(SUITE_EXPECTED.items()):
        r = pg.simulate(None, image=img, switches=sel)
        check_eq(r["out"], want, f"SW1={sel:2d} -> {tag} OB=0x{want:02X}")


def test_a_selector_that_matches_nothing_reports_the_switch_byte_raw():
    """A setting outside 1-12 OUTs SW1 itself, not a verdict.

    Raw report beats assertion when the observable is a selector: a stuck
    switch or an inverted bank then names its own value instead of reporting
    the useless "no test ran". 0x00 and 0x0D bracket the live range."""
    print("suite: no-match arm reports SW1 raw")
    img = pg.build_suite()
    for sw in (0x00, 0x0D, 0x5A, 0xFF):
        r = pg.simulate(None, image=img, switches=sw)
        check_eq(r["out"], sw, f"SW1=0x{sw:02X} -> OB=0x{sw:02X}")


def test_each_slot_holds_the_test_its_selector_names():
    """The BYTES at slot n are test n, assembled at that base.

    THE BLINDNESS THIS EXISTS FOR. `flow` and `alu` both answer 0x39, and
    `sp` and `stack` both answer 0x27, so swapping either pair in
    SUITE_TESTS leaves test_every_selector_runs_its_own_test fully green
    while the dispatch lands on the wrong slot. OB cannot tell them apart;
    the image can. Mirror-witness rule, pointed at the selector."""
    print("suite: slot contents match the selector map")
    img = pg.build_suite()
    # SUITE_EXPECTED, never pg.SUITE_TESTS. Reading the production tuple
    # would make this test move WITH a reordering fault -- it caught itself
    # doing exactly that on the first run.
    for sel, (tag, _ob) in sorted(SUITE_EXPECTED.items()):
        base = pg.SUITE_SLOT * sel
        want = pg.assemble(pg.COVERAGE[tag], base=base)
        check_eq(bytes(img[base:base + len(want)]), want,
                 f"slot {sel:2d} at 0x{base:04X} is {tag}")


def check_raises(fn, label):
    try:
        fn()
    except pg.BuildError:
        print(f"  ok   {label}")
        return
    print(f"  FAIL {label} — no BuildError")
    FAILS.append(label)


def test_a_test_too_big_for_its_slot_is_an_error_not_a_silent_overwrite():
    """An overrunning slot would scribble the next test's first bytes.

    Silent, and it would present as the NEXT selector failing -- a fault
    reported one slot away from its cause. `call` is already 305B of a
    1024B slot and phase F will add images."""
    print("suite: an oversized test raises rather than overwriting")
    pg.COVERAGE["__oversized__"] = [("HALT",)] * (pg.SUITE_SLOT + 1)
    try:
        check_raises(lambda: pg.build_suite(tests=("__oversized__",)),
                     "a test larger than SUITE_SLOT")
    finally:
        del pg.COVERAGE["__oversized__"]


def test_a_slot_past_the_rom_window_is_an_error():
    """Slot 16 starts at 0x4000, which is the I/O window, not ROM.

    Bytes written there land in the image but the machine can never fetch
    them -- ROM is deselected above 0x3FFF since phase E step A."""
    print("suite: a slot past the ROM window raises")
    check_raises(lambda: pg.build_suite(tests=("probe",) * 16),
                 "16 tests -- slot 16 would start at 0x4000")


def test_the_burnable_image_on_disk_is_the_suite():
    """roms/PROG_suite.bin must exist and BE build_suite()'s bytes.

    Rico burns from roms/. An image the generator can build but never wrote
    is an image nobody can burn, and `make burn-prog-suite` would die with
    "No rule to make target" at the bench with the chip already seated --
    which is exactly how PROG_window and PROG_dip were found missing."""
    print("suite: the burnable .bin is on disk and current")
    path = os.path.join(os.path.dirname(os.path.abspath(pg.__file__)),
                        "..", "..", "roms", "PROG_suite.bin")
    path = os.path.normpath(path)
    check_eq(os.path.exists(path), True, "roms/PROG_suite.bin exists")
    if not os.path.exists(path):
        return
    with open(path, "rb") as f:
        on_disk = f.read()
    check_eq(on_disk, pg.build_suite(), "on-disk image == build_suite()")


if __name__ == "__main__":
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        _fn()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\nsuite ROM: OK")
