#!/usr/bin/env python3
"""roms/README.md must match its generator, byte for byte.

The hand-maintained version drifted until it was missing ten of twenty-one
images and had never heard of U23 — and that is the document read AT THE
BURNER. This test is the thing that stops it happening again: it does not
check that the README is *nice*, it checks that nobody has hand-edited it and
that no image was added without regenerating.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roms_readme_gen as gen                                  # noqa: E402
import progrom_gen as pr                                       # noqa: E402
import microcode_gen as mc                                     # noqa: E402

FAILS = []


def check(cond, label):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILS.append(label)


def test_readme_is_current():
    print("roms/README.md matches its generator")
    want = gen.build()
    got = open(gen.OUT).read() if os.path.exists(gen.OUT) else ""
    if want == got:
        print("  ok   byte-identical")
        return
    FAILS.append("roms/README.md is STALE")
    print("  FAIL roms/README.md is STALE — run:")
    print("       python3 docs/notes/roms_readme_gen.py")
    wl, gl = want.splitlines(), got.splitlines()
    for i in range(max(len(wl), len(gl))):
        w = wl[i] if i < len(wl) else "<missing>"
        g = gl[i] if i < len(gl) else "<missing>"
        if w != g:
            print(f"       first diff, line {i + 1}:")
            print(f"         on disk:   {g!r}")
            print(f"         generated: {w!r}")
            break


def test_every_image_on_disk_is_listed():
    """A .bin in roms/ that the README does not mention is exactly the failure
    that happened: PROG_sp, PROG_stack, U23 and seven others existed on disk
    and in the burn targets while the README said nothing about them."""
    print("every roms/*.bin appears in the README")
    roms = os.path.dirname(gen.OUT)
    text = gen.build()
    for fn in sorted(os.listdir(roms)):
        if not fn.endswith(".bin"):
            continue
        check(fn in text, f"{fn} listed")


def test_coverage_tags_all_present():
    """Every registered coverage image needs a NOTES entry, so adding one to
    COVERAGE without describing it fails here rather than emitting a blank."""
    print("every COVERAGE tag has a note")
    for tag in pr.COVERAGE:
        check(tag in gen.NOTES, f"NOTES has {tag!r}")


def test_crcs_match_the_generators():
    """The README's numbers must come from the generators, not from a typed
    copy — the whole reason it is generated."""
    print("README CRCs are computed, not transcribed")
    text = gen.build()
    real = mc.build_real()
    lo, hi = mc.split(real)
    for chip, half in (("U9", lo), ("U15", hi), ("U23", mc.third(real))):
        crc = mc.crc16(half)
        check(f"0x{crc:04X}" in text, f"{chip} REAL crc 0x{crc:04X} present")
    check(f"0x{pr.crc16(pr.build_real()):04X}" in text, "PROG.bin crc present")


def main():
    for fn in (test_readme_is_current,
               test_every_image_on_disk_is_listed,
               test_coverage_tags_all_present,
               test_crcs_match_the_generators):
        fn()
        print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("roms README: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
