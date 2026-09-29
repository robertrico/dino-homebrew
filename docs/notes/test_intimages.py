#!/usr/bin/env python3
"""Answer keys for the interrupt bench images, asm/int*.asm.

Nothing by hand: every expected OB comes out of simulate(irq_at=...), the
oracle that interprets the same microcode rows the machine will run.
PHASE_INT.md SECTION 4 is the ladder; each test names its rung.

THE UART IS THE ONLY INTERRUPT SOURCE (Rico 2026-09-27: no button, no
555). Every image arms the 16550's THRE interrupt itself, so every run is
repeatable and nothing waits on a human. The oracle does not model UART
time (PHASE_G.md SECTION 5): `irq_at` stands in for "INTR rose here", and
the scripted serial session (serial_in=b"") takes the THR/IER writes so
each image's transmit bytes are checked too.

Run: python3 test_intimages.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                   # noqa: E402
import progrom_gen as pg                                     # noqa: E402

ASM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                   "asm")
MANY = 10 ** 6
# An interrupt every 37 boundaries. NOT 13: intflags' handler is 15
# boundaries long (INT, the vector JMP, 12 instructions, IRET), and a
# request period at or under that re-enters on every IRET and starves main
# -- a live-lock the level-triggered design really has, which the UART's
# one-character THRE period (~1 ms at 9600, ~1000 clocks) stays far from.
DENSE = set(range(12, MANY, 37))


def _text(name):
    with open(os.path.join(ASM, name + ".asm")) as f:
        return f.read()


def _run(text, **kw):
    r = asm.assemble_text(text)
    img = pg.build_image_from_bytes(r.code, r.origin)
    kw.setdefault("max_steps", 400000)
    kw.setdefault("serial_in", b"")           # takes the THR/IER writes
    return pg.simulate(None, image=img, **kw), r.labels


def _sub(text, old, new):
    assert text.count(old) == 1, f"{old!r} not unique in the image"
    return text.replace(old, new)


# ---- I2 intmask ---------------------------------------------------------

def test_intmask_ignores_every_request():
    st, _ = _run(_text("intmask"), irq_at=set(range(1, 2000)),
                 max_steps=3000)
    assert st["ints"] == [] and not st["halted"]
    assert set(st["outs"]) == {0xFF, 0x39}


def test_intmask_raises_intr_itself():
    """IER=THRE, then one byte into THR: INTR rises ~1 char later and is
    never cleared, so it is asserted for the whole loop."""
    st, _ = _run(_text("intmask"), max_steps=3000)
    assert st["tx"] == b"."


def test_intmask_mirror_with_ei_reads_e7():
    """The witness can fail: the same image WITH EI halts on 0xE7."""
    text = _sub(_text("intmask"), "loop:     LDAI  0x39",
                "          EI\nloop:     LDAI  0x39")
    st, _ = _run(text, irq_at={30}, max_steps=3000)   # after EI (25)
    assert st["halted"] and st["out"] == 0xE7


# ---- I3 intresume ------------------------------------------------------

def _fast_resume():
    t = _sub(_text("intresume"), "OUTER:    .equ  128", "OUTER:    .equ  2")
    return _sub(t, "INNER:    .equ  0xFF", "INNER:    .equ  3")


def _counts(outs):
    return [o for o in outs if o not in (0xFF, 0xE7)]


def test_intresume_counts_without_interrupts():
    st, _ = _run(_fast_resume(), max_steps=2000)
    assert _counts(st["outs"])[:5] == [1, 2, 3, 4, 5]


def test_intresume_arms_one_byte_per_count():
    st, _ = _run(_fast_resume(), max_steps=2000)
    assert st["tx"] == b"." * len(_counts(st["outs"]))


def test_intresume_resumes_at_the_next_count():
    """An interrupt every count; the count never restarts or skips."""
    st, _ = _run(_fast_resume(), irq_at=set(range(40, 4000, 90)),
                 max_steps=6000)
    assert st["outs"].count(0xE7) >= 3, st["outs"][:20]
    counts = _counts(st["outs"])
    assert counts == list(range(1, len(counts) + 1)), counts[:20]


# ---- I4 intaddr ---------------------------------------------------------

def test_intaddr_pushes_only_opcode_addresses():
    seen = set()
    # ordinal 28 is the first after EI (UART setup + four THR writes); in
    # copper the FIFO takes ~3 ms to drain, so INTR is always in the loop
    for k in range(29, 80):
        st, lab = _run(_text("intaddr"), irq_at={k}, max_steps=2000)
        assert st["halted"], f"irq at {k}: no halt"
        assert st["out"] in (0x40, 0x42, 0x43, 0x45), \
            f"irq at {k}: OB {st['out']:#04x} is an operand byte"
        seen.add(st["out"])
    assert seen == {0x40, 0x42, 0x43, 0x45}, sorted(hex(x) for x in seen)


def test_intaddr_arms_one_byte():
    st, _ = _run(_text("intaddr"), irq_at={30}, max_steps=2000)
    assert st["tx"] == b"...."


def test_intaddr_loop_is_where_the_header_says():
    _, lab = _run(_text("intaddr"), max_steps=200)
    assert lab["loop"] == 0x0140


# ---- I5/I6 intflags -----------------------------------------------------

def test_intflags_passes_under_dense_interrupts():
    st, _ = _run(_text("intflags"), irq_at=DENSE,
                 max_steps=MANY)
    assert st["halted"] and st["out"] == 0x5A, hex(st["out"] or 0)
    assert len(st["ints"]) > 1000
    # the handler re-arms by writing THR: one priming byte + one per entry
    assert len(st["tx"]) == len(st["ints"]) + 1


def test_intflags_without_interrupts_reads_0e_not_a_pass():
    st, _ = _run(_text("intflags"), max_steps=MANY)
    assert st["halted"] and st["out"] == 0x0E


def test_intflags_mirror_without_pushf_popf_reads_bd():
    """The save/restore witness must be able to FAIL."""
    t = _sub(_text("intflags"), "handler:  PUSHF", "handler:  NOP")
    t = _sub(t, "          POPF\n", "          NOP\n")
    st, _ = _run(t, irq_at=DENSE, max_steps=MANY)
    assert st["halted"] and st["out"] == 0xBD, hex(st["out"] or 0)


# ---- I7 inthalt ---------------------------------------------------------

def test_inthalt_waits_until_intr():
    st, _ = _run(_text("inthalt"))
    assert st["halted"] and st["out"] == 0xFF and st["ints"] == []
    assert st["tx"] == b"DINO"


def test_inthalt_wakes_and_lands_after_the_halt():
    st, lab = _run(_text("inthalt"), irq_at={500})
    assert st["halted"] and st["out"] == 0x5A
    assert st["ints"] == [lab["after"]]


def test_inthalt_bare_wake_reads_3c_not_a_pass():
    """A wake with no handler (a runt on U61.3) must not forge 0x5A.
    Mirror: the handler's SEEN plant deleted stands in for it."""
    t = _sub(_text("inthalt"), "          MVI   SEEN, 0x01\n", "")
    st, _ = _run(t, irq_at={500})
    assert st["halted"] and st["out"] == 0x3C


def test_inthalt_final_halt_cannot_be_woken():
    st, _ = _run(_text("inthalt"), irq_at={500, 501, 502, 900})
    assert st["out"] == 0x5A
    assert st["ie"] == 0


# ---- I8 intser ----------------------------------------------------------

def test_intser_echoes_with_no_poll_loop():
    st, _ = _run(_text("intser"), serial_in=b"Hi!",
                 irq_at={MANY, MANY + 1, MANY + 2})
    assert st["tx"] == b"Hi!"
    assert st["outs"][-1] == ord("!")
    assert len(st["ints"]) == 3 and st["halted"]


def test_intser_never_reads_lsr():
    text = _text("intser")
    assert "SER_LSR" not in text and "0x4805" not in text


# ---- the ruling ---------------------------------------------------------

def test_every_image_arms_the_uart_itself():
    """No button, no 555: each image raises its own interrupt."""
    for name in ("intmask", "inthalt", "intresume", "intaddr",
                 "intflags", "intser"):
        assert "SER_IER" in _text(name), name
    assert not os.path.exists(os.path.join(ASM, "intbtn.asm"))


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
    print("OK test_intimages")
