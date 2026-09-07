#!/usr/bin/env python3
"""Answer key for asm/txlive.asm -- as far as one exists. The image streams
"DINO MON\\r\\n" forever through the monitor's putc route and puts
(IIR & 0xC0) | LCR on OB after every byte. The oracle models neither IIR
nor LCR (PHASE_G.md SECTION 5), so simulate() REFUSES it: that refusal is
asserted here so it is by design and not a regression. The OB key is
datasheet-sourced, in the .asm header, and read by a human on the LEDs."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "asm", "txlive.asm")
LINE = b"DINO MON\r\n\x00"
T_CH = 0x80EC                       # the monitor's putc scratch, verbatim


def check():
    bad = []
    r = asm.assemble_text(open(SRC).read())
    code = bytes(r.code)
    if LINE not in code:
        bad.append("the string is not in the image")
    if r.labels.get("T_CH") != T_CH:
        bad.append(f"T_CH is {r.labels.get('T_CH')!r}, monitor's is {T_CH:#06x}")
    img = pg.build_image_from_bytes(code, r.origin)
    try:
        st = pg.simulate(None, image=img, serial_in=b"", max_steps=20000)
        bad.append(f"simulate() answered {st.get('tx')!r}: it must REFUSE an "
                   f"IIR/LCR read, or the oracle grew a model nobody checked")
    except pg.Unoracled as e:
        if "IIR" not in str(e) and "LCR" not in str(e):
            bad.append(f"refused for the wrong reason: {e}")
        print(f"  simulate() refuses, as designed: {str(e)[:60]}...")
    return bad


if __name__ == "__main__":
    bad = check()
    for b in bad:
        print("  FAIL", b)
    print("txlive:", "FAIL" if bad else "OK")
    sys.exit(1 if bad else 0)
