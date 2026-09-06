#!/usr/bin/env python3
"""Answer key for asm/txsoak.asm: what each slot streams, through the scripted
serial double (a test double, not a UART model). The image never halts, so
the key is the first bytes of the transcript."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "asm", "txsoak.asm")
LINE = b"DINO MON\r\n"
EXPECT = {1: b"D" * 30, 2: LINE * 3, 3: LINE * 3, 4: LINE * 3}

if __name__ == "__main__":
    r = asm.assemble_text(open(SRC).read())
    img = pg.build_image_from_bytes(r.code, r.origin)
    bad = []
    for sw, want in sorted(EXPECT.items()):
        st = pg.simulate(None, image=img, switches=sw, serial_in=b"", max_steps=60000)
        tx = bytes(st.get("tx", b""))
        ok = tx[:len(want)] == want
        print(f"  SW1={sw}  tx[:20]={tx[:20]!r}  {'ok' if ok else 'FAIL'}")
        if not ok:
            bad.append(sw)
    st = pg.simulate(None, image=img, switches=7, max_steps=1000)
    ok = st["out"] == 7 and st["halted"]
    print(f"  SW1=7  OB={st['out']:#04x}  {'ok' if ok else 'FAIL'}")
    if not ok:
        bad.append(7)
    print("txsoak:", "FAIL" if bad else "OK")
    sys.exit(1 if bad else 0)
