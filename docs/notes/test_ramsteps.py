#!/usr/bin/env python3
"""Answer key for asm/ram/step*.asm -- the execute-from-RAM staircase.

Each step adds ONE thing no RAM-resident code has been seen to do on the
bench (2026-09-08: ramexec proved LDBI/SUB/OUT/HALT from RAM and nothing
else), and reports with OB. Driven exactly as the bench drives it: the REAL
monitor image, `L`, the hex, `G`. Pass = the step's OB code and, for the
RET steps, the prompt coming back.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import dinoload                                               # noqa: E402
import progrom_gen as pg                                      # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
MON = os.path.join(ROOT, "asm", "monitor.asm")
RAM = os.path.join(ROOT, "asm", "ram")
FAILS = []

# step -> (OB, returns to the prompt, text it prints)
STEPS = {
    "step1": (0x11, False, b""),          # JMPX into RAM, fetch, OUT, HALT
    "step2": (0x22, True, b""),           # + RET from RAM back into ROM
    "step3": (0x33, True, b""),           # + 3-byte STA/LDA absolute from RAM
    "step4": (0x44, True, b""),           # + JMP taken, JNZ not taken, from RAM
    "step5": (0x55, True, b"K"),          # + CALL from RAM into ROM, RET back
    "step6": (0x66, True, b""),           # + LDAX through B:C from RAM code
    "step7": (0x77, True, b""),           # + MVI from RAM: a PC-fetched byte
                                          #   parked in MDR and replayed
    "step8": (0x88, True, b""),           # + a counted JNZ loop from RAM
    # step 2 splits, 2026-09-08: RET from RAM froze on the bench
    "step2pop": (0x01, False, b""),       # RET's pops as POPA; frame is 01 B3
    "step2ram": (0x2A, False, b""),       # CALL/RET within RAM
    "step2jmp": (0x2D, True, b""),        # JMP from RAM to new_line: prompt
    "step2a": (0x22, True, b""),          # LDAI between OUT and RET
    "step2b": (0xFF, True, b""),          # no OUT: OB stays the poison
}


def check(cond, label):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        FAILS.append(label)


_MON = None


def mon():
    global _MON
    if _MON is None:
        r = asm.assemble_text(open(MON).read())
        _MON = pg.build_image_from_bytes(r.code, r.origin)
    return _MON


def run(name):
    r = asm.assemble_text(open(os.path.join(RAM, name + ".asm")).read())
    dinoload.check_placement(r.code, r.origin)
    script = (b"\r" + dinoload.load_line(r.origin, r.code)
              + dinoload.hexed(r.code) + dinoload.go_line(r.origin))
    st = pg.simulate(None, image=mon(), serial_in=script, max_steps=5_000_000)
    tx = st["tx"]
    i = tx.rfind(b"G %04X\r\n" % r.origin)
    return r, st, (tx[i + 8:] if i >= 0 else b"")


def test_every_step_exists_and_is_small():
    print("files")
    for name in STEPS:
        path = os.path.join(RAM, name + ".asm")
        check(os.path.exists(path), f"{name}.asm exists")
        if os.path.exists(path):
            r = asm.assemble_text(open(path).read())
            check(len(r.code) <= 40, f"{name}: {len(r.code)} bytes, small enough "
                  "to load through a flaky wire")


def test_each_step_answers_on_ob():
    for name, (ob, rets, text) in STEPS.items():
        print(name)
        if not os.path.exists(os.path.join(RAM, name + ".asm")):
            check(False, f"{name} missing")
            continue
        r, st, out = run(name)
        check(st["out"] == ob, f"OB {st['out']:#04x} == {ob:#04x}")
        if rets:
            check(out.endswith(dinoload.PROMPT), "RET landed on the prompt")
            check(not st.get("halted"), "did not HALT")
        else:
            check(st.get("halted"), "HALTed, as designed")
        if text:
            check(text in out, f"printed {text!r}")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED"); return 1
    print("\nOK"); return 0


if __name__ == "__main__":
    sys.exit(main())
