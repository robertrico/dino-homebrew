#!/usr/bin/env python3
"""Answer key for asm/test5.asm: OB per SW1, out of simulate(), nothing by hand."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "asm", "test5.asm")
EXPECT = {1: 0x5A, 2: 0x02, 3: 0x9E, 4: 0x02, 5: 0x5A, 6: 0x5A, 0: 0x00, 7: 0x07}

if __name__ == "__main__":
    r = asm.assemble_text(open(SRC).read())
    img = pg.build_image_from_bytes(r.code, r.origin)
    bad = []
    for sw, want in sorted(EXPECT.items()):
        st = pg.simulate(None, image=img, switches=sw, max_steps=100000)
        ok = st["out"] == want and st["halted"]
        print(f"  SW1={sw}  OB={st['out']:#04x}  {'ok' if ok else 'FAIL'}")
        if not ok:
            bad.append(sw)
    print("test5:", "FAIL" if bad else "OK")
    sys.exit(1 if bad else 0)
