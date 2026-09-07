#!/usr/bin/env python3
"""Host tests for asm.py — the .asm text assembler.

THE LOAD-BEARING TEST IS test_every_coverage_image_round_trips. Everything
else here checks a feature; that one checks that the text path and the Python
path cannot disagree. A second assembler is a second source of truth unless
something continuously proves it is not.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402
from microcode_gen import OPCODES, INSTRUCTIONS               # noqa: E402

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


def check_raises(src, needle, label):
    try:
        asm.assemble_text(src)
    except asm.AsmError as e:
        if needle.lower() in str(e).lower():
            print(f"  ok   {label}")
            return
        print(f"  FAIL {label} — wrong message: {e}")
        FAILS.append(label)
        return
    print(f"  FAIL {label} — no AsmError")
    FAILS.append(label)


def test_literals():
    print("number literals")
    src = "LDAI 0x2C\nLDBI 44\nLDCI %00101100\nADI 'A'\n"
    check_eq(list(asm.assemble_text(src).code),
             [OPCODES["LDAI"], 0x2C, OPCODES["LDBI"], 44,
              OPCODES["LDCI"], 0b00101100, OPCODES["ADI"], 0x41],
             "hex, decimal, binary and character literals")


def test_the_five_operand_shapes():
    """Derived from the microcode, not from a table in the assembler."""
    print("operand shapes")
    r = asm.assemble_text("HALT\n")
    check_eq(list(r.code), [0xFF], "implied: opcode only")
    r = asm.assemble_text("LDAI 0x2C\n")
    check_eq(list(r.code), [OPCODES["LDAI"], 0x2C], "immediate: one byte")
    r = asm.assemble_text("LDA 0x8123\n")
    check_eq(list(r.code), [OPCODES["LDA"], 0x23, 0x81],
             "absolute: two bytes, LOW FIRST")
    r = asm.assemble_text("MVI 0x8123, 0x5B\n")
    check_eq(list(r.code), [OPCODES["MVI"], 0x23, 0x81, 0x5B],
             "absolute + immediate")
    r = asm.assemble_text("LDAM 0x8A00\n")
    check_eq(list(r.code), [OPCODES["LDAM"], 0x00, 0x8A, 0x01, 0x8A],
             "memory-indirect: the pointer, then the pointer PLUS ONE")


def test_memory_indirect_writes_the_address_twice():
    """The programmer writes the pointer ONCE. The instruction needs both
    halves addressed explicitly because the address register cannot
    increment itself, and hiding that is exactly what an assembler is for."""
    print("memory-indirect operand")
    r = asm.assemble_text("PTR: .equ 0x8AFF\nLDAM PTR\n")
    check_eq(list(r.code), [OPCODES["LDAM"], 0xFF, 0x8A, 0x00, 0x8B],
             "ptr+1 carries into the high byte")


def test_labels_and_forward_references():
    print("labels")
    src = ("        JMP done\n"
           "        LDAI 0xEE\n"
           "        OUT\n"
           "done:   HALT\n")
    r = asm.assemble_text(src)
    # JMP 3 + LDAI 2 + OUT 1 = 6. Lengths come from the microcode, so this
    # constant is the one thing in the test that is allowed to be hand-counted.
    check_eq(list(r.code)[:3], [OPCODES["JMP"], 0x06, 0x00],
             "forward reference resolves to the right address")
    check_eq(r.labels["done"], 6, "label address")


def test_byte_selectors():
    """A 16-bit address cannot be an immediate on an 8-bit machine. Without
    `<` and `>` you cannot load half a pointer, which is most of what the
    indexed addressing mode needs."""
    print("byte selectors")
    src = "T: .equ 0x8234\n   LDCI <T\n   LDBI >T\n"
    check_eq(list(asm.assemble_text(src).code),
             [OPCODES["LDCI"], 0x34, OPCODES["LDBI"], 0x82],
             "<T is the low byte, >T is the high byte")
    check_eq(list(asm.assemble_text("T: .equ 0x82FF\n   LDCI <T+1\n").code),
             [OPCODES["LDCI"], 0x00],
             "the selector applies AFTER the arithmetic, so it wraps")


def test_label_arithmetic():
    print("label arithmetic")
    r = asm.assemble_text("here:  .db 1,2,3\n       LDA here+2\n")
    check_eq(list(r.code)[3:], [OPCODES["LDA"], 0x02, 0x00], "label+2")
    r = asm.assemble_text(".org 0x10\nhere: LDA here-1\n")
    check_eq(list(r.code)[1:], [0x0F, 0x00], "label-1")


def test_directives():
    print("directives")
    check_eq(list(asm.assemble_text(".db 1, 0xFF, 'Z'\n").code),
             [1, 0xFF, 0x5A], ".db bytes and characters")
    check_eq(list(asm.assemble_text('.db "HI", 0\n').code),
             [0x48, 0x49, 0x00], ".db strings")
    check_eq(list(asm.assemble_text(".dw 0x1234\n").code), [0x34, 0x12],
             ".dw is little-endian")
    check_eq(list(asm.assemble_text(".ds 3\n").code), [0xFF, 0xFF, 0xFF],
             ".ds fills with HALT, not zero -- unwritten space must stop the "
             "machine, not slide through it")
    r = asm.assemble_text(".org 0x0100\nHALT\n")
    check_eq(r.origin, 0x0100, ".org sets the origin")
    check_eq(r.labels, {}, ".org defines no label")


def test_equ_is_not_an_address():
    print(".equ")
    r = asm.assemble_text("PORT: .equ 0x4000\n      LDA PORT\n")
    check_eq(list(r.code), [OPCODES["LDA"], 0x00, 0x40],
             ".equ binds a value, and the origin does not move")


def test_comments_blank_lines_and_case():
    print("lexing")
    src = ("; a whole-line comment\n"
           "\n"
           "   ldai 0x2c   ; trailing comment\n"
           "   Out\n")
    check_eq(list(asm.assemble_text(src).code),
             [OPCODES["LDAI"], 0x2C, OPCODES["OUT"]],
             "comments stripped, mnemonics case-insensitive")


def test_errors_name_the_line():
    print("diagnostics")
    check_raises("LDAI 0x2C\nFROBNICATE\n", "line 2", "unknown mnemonic")
    check_raises("LDAI 0x2C\nLDAI\n", "line 2", "missing operand")
    check_raises("LDAI 0x2C, 0x30\n", "line 1", "too many operands")
    check_raises("LDAI 0x1FF\n", "range", "immediate out of byte range")
    check_raises("JMP nowhere\n", "nowhere", "undefined label")
    check_raises("a: HALT\na: HALT\n", "duplicate", "duplicate label")
    check_raises(".org 0x10\n.org 0x08\n", "backward", "origin moving back")


def test_a_real_program_runs_in_the_oracle():
    """An assembler that produces bytes the interpreter cannot execute is a
    text editor. This runs the output."""
    print("end to end")
    src = ("        .org 0x0000\n"
           "STACK:  .equ 0x80FF\n"
           "        LDAI 0xFF        ; poison OB\n"
           "        OUT\n"
           "        LXISP STACK\n"
           "        LDAI 0x2F\n"
           "        ADI  0x1E        ; 0x2F + 0x1E = 0x4D\n"
           "        OUT\n"
           "        HALT\n")
    r = asm.assemble_text(src)
    st = pg.simulate(None, image=pg.build_image_from_bytes(r.code, r.origin))
    check_eq(st["out"], 0x4D, "the milestone sum, written in .asm")
    check(st["halted"], "it halts")


def test_unoracled_image_still_assembles_under_run():
    """PHASE_G.md SECTION 5: the oracle models ONLY the scratch register and
    REFUSES every other UART register on purpose. `make burn-prog-serlsr`
    died in that refusal on 2026-09-04 with the chip in the programmer. A
    refusal is 'no answer key', not 'bad program': --run must SAY SO and
    still write the image. A real oracle fault must still be fatal."""
    print("--run on an UNORACLED image")
    import io
    import contextlib
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "lsr.asm")
        out = os.path.join(d, "PROG_lsr.bin")
        open(src, "w").write("LDAI 0xFF\nOUT\nLDA 0x4805\nOUT\nHALT\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = asm.main([src, "--run", "-o", out])
        check_eq(rc, 0, "an unoracled image is not an error")
        check(os.path.exists(out), "the image was written")
        check("UNORACLED" in buf.getvalue(), "the refusal is printed, not hidden")
        check("LSR" in buf.getvalue(), "and names the register")

        # A byte the machine cannot decode is a real fault, not a refusal.
        src2 = os.path.join(d, "bad.asm")
        out2 = os.path.join(d, "PROG_bad.bin")
        open(src2, "w").write("LDAI 0xFF\nOUT\n.db 0x9F\nHALT\n")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                asm.main([src2, "--run", "-o", out2])
            check(False, "an undecodable opcode still raises")
        except pg.BuildError:
            check(True, "an undecodable opcode still raises")
        check(not os.path.exists(out2), "and writes nothing")


def test_every_coverage_image_round_trips():
    """THE EQUIVALENCE TEST. Every image in progrom_gen.COVERAGE is rendered
    to .asm text and reassembled, and the bytes must be IDENTICAL to what
    progrom_gen.assemble() produces from the Python form.

    Two assemblers is two sources of truth unless something proves otherwise
    on every program that exists. This is that proof."""
    print("text path == Python path, on all 28 coverage images")
    bad = []
    for tag, prog in pg.COVERAGE.items():
        want = pg.assemble(prog)
        text = asm.render(prog)
        try:
            got = asm.assemble_text(text).code
        except asm.AsmError as e:
            bad.append(f"{tag}: {e}")
            continue
        if bytes(got) != bytes(want):
            bad.append(f"{tag}: {len(got)}B vs {len(want)}B")
    check_eq(bad, [], "all 28 images assemble byte-identically from text")


def test_fill_directive():
    """`.fill 0x00` makes every unclaimed byte -- .ds, the origin gap, and the
    ROM padding -- NOP instead of HALT. Default stays HALT (0xFF). 2026-09-06:
    Rico's A/B of the fill choice; with NOP fill an escape re-runs the
    program instead of re-halting one byte later, so it is LOUD."""
    print(".fill directive")
    r = asm.assemble_text("LDAI 1\n.ds 2\nHALT\n")
    check_eq(r.fill, 0xFF, "default fill is HALT (0xFF)")
    check_eq(r.code, b"\x11\x01\xff\xff\xff", ".ds pads with HALT by default")
    check_eq(pg.build_image_from_bytes(r.code, r.origin, fill=r.fill)[-1], 0xFF,
             "ROM padding is HALT by default")
    r = asm.assemble_text(".fill 0x00\nLDAI 1\n.ds 2\nHALT\n")
    check_eq(r.fill, 0x00, ".fill 0x00 is recorded on the Result")
    check_eq(r.code, b"\x11\x01\x00\x00\xff", ".ds pads with the fill")
    img = pg.build_image_from_bytes(r.code, r.origin, fill=r.fill)
    check_eq(len(img), pg.ROM_IMAGE, "image is a full ROM")
    check_eq(img[5:21], b"\x00" * 16, "ROM padding uses the fill")
    check_eq(img[-1], 0x00, "last byte of the ROM is the fill")
    check_eq(pg.build_image_from_bytes(r.code, r.origin)[-1], 0xFF,
             "build_image_from_bytes still defaults to HALT")
    r = asm.assemble_text(".fill 0x00\n.org 0x10\nHALT\n")
    img = pg.build_image_from_bytes(r.code, r.origin, fill=r.fill)
    check_eq(img[:0x11], b"\x00" * 16 + b"\xff", "origin gap uses the fill")
    try:
        asm.assemble_text(".fill 0x100\n")
        check(False, ".fill rejects a non-byte")
    except asm.AsmError:
        check(True, ".fill rejects a non-byte")


def test_lengths_come_from_the_microcode():
    """No operand table lives in the assembler. Break the microcode's
    declared length and the assembler must follow it, not a private copy."""
    print("single source of truth")
    for name in ("LDAI", "LDA", "MVI", "LDAM", "HALT"):
        want = INSTRUCTIONS[name][0]
        check_eq(asm.instruction_size(name), want, f"{name} is {want} bytes")


if __name__ == "__main__":
    for _n, _f in sorted((kv for kv in list(globals().items())
                          if kv[0].startswith("test_") and callable(kv[1]))):
        _f()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\nasm: OK")
