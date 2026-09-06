#!/usr/bin/env python3
"""Answer key for asm/wander.asm -- what OB reads for each SW1 setting.

Every expected value comes out of simulate(); nothing is computed by hand.
The oracle stops at HALT, so what it scores is the value each slot puts on
OB BEFORE the wait. The wait itself -- does that value hold, step down the
escape ladder, or corrupt -- is the bench's question and cannot be modelled.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "asm", "wander.asm")

# SW1 -> the id the slot OUTs. Out of range echoes SW1 raw.
EXPECT = {1: 0x11, 2: 0x12, 3: 0x13, 4: 0x14, 5: 0x15, 6: 0x16,
          7: 0x17, 8: 0x18, 9: 0x19, 10: 0x1A,
          0: 0x00, 11: 0x0B, 0x1E: 0x1E, 0xFE: 0xFE}
FAILS = []


def run(sw):
    r = asm.assemble_text(open(SRC).read())
    img = pg.build_image_from_bytes(r.code, r.origin)
    return pg.simulate(None, image=img, switches=sw, max_steps=3_000_000)


def test_every_slot_halts_on_its_id():
    print("  SW1   OB      halted  steps")
    for sw, want in sorted(EXPECT.items()):
        st = run(sw)
        ok = st["out"] == want and st["halted"]
        print(f"  {sw:#04x}  {st['out']:#04x}  {'ok  ' if ok else 'FAIL'}"
              f"  {st['halted']}  {st['steps']}")
        if not ok:
            FAILS.append(f"SW1={sw:#04x}: got {st['out']:#04x} "
                         f"halted={st['halted']}, want {want:#04x}")


def test_ladder_is_behind_every_halt():
    """Each slot's HALT must be followed by JMP ladder, so an escape reads
    0xE1 and not the next slot's id. Walks the listing, not the bytes: the
    poison's LDAI 0xFF operand is a 0xFF that is not a HALT."""
    r = asm.assemble_text(open(SRC).read())
    text = open(SRC).read().splitlines()
    rows = [(a, text[ln - 1].split(";")[0].split()) for a, _, ln in r.listing]
    ladder = r.labels["ladder"]
    bad = []
    for i, (a, toks) in enumerate(rows):
        if "HALT" in toks and a < ladder:
            nxt = rows[i + 1][1] if i + 1 < len(rows) else []
            if nxt[-2:] != ["JMP", "ladder"]:
                bad.append(a)
    print(f"  {'ok  ' if not bad else 'FAIL'} every HALT before the ladder "
          f"is followed by JMP ladder ({len(bad)} bare)")
    if bad:
        FAILS.append(f"HALTs without ladder at {[hex(a) for a in bad]}")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print()
    if FAILS:
        print("wander: FAIL")
        for f in FAILS:
            print("   ", f)
        sys.exit(1)
    print("wander: OK")
