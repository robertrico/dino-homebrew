#!/usr/bin/env python3
"""Answer key for asm/romsoak.asm: OB per SW1, out of simulate(). The oracle
reads ROM as data perfectly, so every soak slot must finish at 0x00; the
bench's job is the number that is NOT 0x00, and at which clock."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "asm", "romsoak.asm")
EXPECT = {1: 0x00, 2: 0x00, 3: 0x00, 4: 0x00, 0: 0x00, 5: 0x05, 0x1E: 0x1E}

if __name__ == "__main__":
    r = asm.assemble_text(open(SRC).read())
    img = pg.build_image_from_bytes(r.code, r.origin)
    bad = []
    for sw, want in sorted(EXPECT.items()):
        t = time.time()
        st = pg.simulate(None, image=img, switches=sw, max_steps=8_000_000)
        ok = st["out"] == want and st["halted"]
        print(f"  SW1={sw:#04x}  OB={st['out']:#04x}  steps={st['steps']:>8}  "
              f"{time.time()-t:5.1f}s  {'ok' if ok else 'FAIL'}")
        if not ok:
            bad.append(sw)
    print("romsoak:", "FAIL" if bad else "OK")
    sys.exit(1 if bad else 0)
