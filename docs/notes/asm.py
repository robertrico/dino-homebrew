#!/usr/bin/env python3
"""DINO assembler — .asm text in, ROM bytes out.

    python3 docs/notes/asm.py prog.asm -o roms/PROG_prog.bin
    python3 docs/notes/asm.py prog.asm --list          # annotated listing
    python3 docs/notes/asm.py prog.asm --run           # what OB should read

THERE IS NO INSTRUCTION TABLE IN THIS FILE. Opcodes, byte lengths and operand
shapes are all read out of `microcode_gen`, which is the same table that burns
U9/U15/U23. An assembler carrying its own copy of the ISA is a second source
of truth, and the two drift the first time an instruction is added.

Operand SHAPE is derived rather than declared: an instruction's shape is
fixed by how many of its microcode rows fetch a byte through the PC.

    ROM-fetching rows   shape           example
    0                   implied         HALT
    1                   immediate       LDAI 0x2C
    2                   address         LDA 0x8123
    3                   address, imm    MVI 0x8123, 0x5B
    4                   pointer         LDAM 0x8A00

The pointer shape is the interesting one. Memory-indirect instructions need
BOTH halves of the pointer addressed explicitly, because the address register
cannot increment itself -- so the machine wants `ptr` and `ptr+1`. The
programmer writes the pointer ONCE and this file emits both. Hiding that is
what an assembler is for.

SYNTAX

    ; comment                       to end of line
    label:                          defines a label at the current address
    label: .equ 0x4000              binds a value; the origin does not move
            .org 0x0100             sets the assembly origin (forward only)
            .db 1, 0xFF, 'A', "HI"  raw bytes, characters and strings
            .dw 0x1234, label       16-bit words, LOW BYTE FIRST
            .ds 8                   reserve 8 bytes, filled with HALT

    Numbers:  0x2C  44  %00101100  'A'
    Operands: a number, a label, or label+n / label-n
    Mnemonics and directives are case-insensitive; labels are NOT.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from microcode_gen import OPCODES, INSTRUCTIONS, SRC, SRC_BANK_N   # noqa: E402

SAFE_FILL = 0xFF            # HALT. Unclaimed space must STOP the machine.


class AsmError(Exception):
    pass


# ---- shapes, derived from the microcode --------------------------------
def _rom_fetches(rows):
    """How many of an instruction's rows pull a byte through the PC."""
    return sum(1 for w in rows
               if ((w >> 3) & 7) == SRC["ROM"] and (w & SRC_BANK_N))


IMPLIED, IMMEDIATE, ADDRESS, ADDR_IMM, POINTER = range(5)
_SHAPE_OF_FETCHES = {0: IMPLIED, 1: IMMEDIATE, 2: ADDRESS,
                     3: ADDR_IMM, 4: POINTER}
SHAPE = {n: _SHAPE_OF_FETCHES[_rom_fetches(r)]
         for n, (_, r) in INSTRUCTIONS.items()}
ARGC = {IMPLIED: 0, IMMEDIATE: 1, ADDRESS: 1, ADDR_IMM: 2, POINTER: 1}


def instruction_size(name):
    """Byte length, straight out of the microcode table."""
    return INSTRUCTIONS[name][0]


# ---- lexing ------------------------------------------------------------
_NUM = re.compile(r"^(0[xX][0-9a-fA-F]+|%[01]+|\d+)$")
_SYM = re.compile(r"^[A-Za-z_.][A-Za-z0-9_.]*$")


def _strip_comment(line):
    """Remove a ; comment, but not one inside a string literal."""
    out, in_str = [], False
    for ch in line:
        if ch == '"':
            in_str = not in_str
        elif ch == ";" and not in_str:
            break
        out.append(ch)
    return "".join(out)


def _split_args(text):
    """Split on commas outside string literals."""
    args, cur, in_str = [], [], False
    for ch in text:
        if ch == '"':
            in_str = not in_str
            cur.append(ch)
        elif ch == "," and not in_str:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        args.append("".join(cur).strip())
    return args


def _number(tok, ln):
    if tok.startswith(("0x", "0X")):
        return int(tok, 16)
    if tok.startswith("%"):
        return int(tok[1:], 2)
    if tok.isdigit():
        return int(tok, 10)
    raise AsmError(f"line {ln}: {tok!r} is not a number")


def _value(tok, labels, ln):
    """A number, a character, a label, label+n / label-n, or a byte selector.

    `<expr` is expr's LOW byte and `>expr` its HIGH byte. A 16-bit address
    cannot be an immediate operand on an 8-bit machine, so without these you
    cannot write the low half of a pointer into a register or a RAM cell --
    which is most of what indexed addressing needs.
    """
    tok = tok.strip()
    if tok[:1] in ("<", ">"):
        v = _value(tok[1:], labels, ln)
        return v & 0xFF if tok[0] == "<" else (v >> 8) & 0xFF
    if len(tok) == 3 and tok[0] == "'" and tok[2] == "'":
        return ord(tok[1])
    if _NUM.match(tok):
        return _number(tok, ln)
    m = re.match(r"^([A-Za-z_.][A-Za-z0-9_.]*)\s*([+-])\s*(\S+)$", tok)
    if m:
        base, sign, off = m.groups()
        if base not in labels:
            raise AsmError(f"line {ln}: undefined label {base!r}")
        d = _number(off, ln)
        return labels[base] + (d if sign == "+" else -d)
    if _SYM.match(tok):
        if tok not in labels:
            raise AsmError(f"line {ln}: undefined label {tok!r}")
        return labels[tok]
    raise AsmError(f"line {ln}: cannot parse operand {tok!r}")


def _parse(text):
    """(line_no, label, op, args) per meaningful line. No values resolved."""
    items = []
    for ln, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        label = None
        m = re.match(r"^\s*([A-Za-z_.][A-Za-z0-9_.]*)\s*:\s*(.*)$", line)
        if m:
            label, line = m.group(1), m.group(2)
        elif not line[0].isspace():
            # a bare word at column 0 with no colon is still a label if
            # nothing follows it -- but requiring the colon keeps the one
            # ambiguous case (a mnemonic at column 0) unambiguous.
            pass
        line = line.strip()
        if not line:
            items.append((ln, label, None, []))
            continue
        parts = line.split(None, 1)
        op = parts[0]
        args = _split_args(parts[1]) if len(parts) > 1 else []
        items.append((ln, label, op, args))
    return items


# ---- assembly ----------------------------------------------------------
class Result:
    def __init__(self, code, origin, labels, listing):
        self.code = bytes(code)
        self.origin = origin
        self.labels = labels
        self.listing = listing


def _sizeof(ln, op, args, labels):
    """Byte length of one line, for pass 1."""
    d = op.lower()
    if d == ".equ":
        return 0
    if d == ".org":
        return 0
    if d == ".db":
        n = 0
        for a in args:
            n += len(_unquote(a, ln)) if a.startswith('"') else 1
        return n
    if d == ".dw":
        return 2 * len(args)
    if d == ".ds":
        return _value(args[0], labels, ln) if args else 0
    name = op.upper()
    if name not in INSTRUCTIONS:
        raise AsmError(f"line {ln}: unknown mnemonic {op!r}")
    return instruction_size(name)


def _unquote(a, ln):
    if not (a.startswith('"') and a.endswith('"') and len(a) >= 2):
        raise AsmError(f"line {ln}: unterminated string {a!r}")
    return a[1:-1].encode("ascii", "strict")


def assemble_text(text, origin=0):
    items = _parse(text)
    labels, org, addr = {}, origin, origin
    seen_org = False

    # pass 1 -- addresses. .equ values must be known before any use, which is
    # the one thing a two-pass assembler cannot defer: a label's ADDRESS can
    # be forward-referenced, a symbolic CONSTANT cannot.
    for ln, label, op, args in items:
        if op and op.lower() == ".equ":
            if label is None:
                raise AsmError(f"line {ln}: .equ needs a label")
            if label in labels:
                raise AsmError(f"line {ln}: duplicate label {label!r}")
            if not args:
                raise AsmError(f"line {ln}: .equ needs a value")
            labels[label] = _value(args[0], labels, ln)
            continue
        if op and op.lower() == ".org":
            if not args:
                raise AsmError(f"line {ln}: .org needs an address")
            new = _value(args[0], labels, ln)
            if seen_org and new < addr:
                raise AsmError(f"line {ln}: .org moves backward, "
                               f"{new:#06x} < {addr:#06x}")
            if not seen_org:
                org = new
            addr, seen_org = new, True
            continue
        if label is not None:
            if label in labels:
                raise AsmError(f"line {ln}: duplicate label {label!r}")
            labels[label] = addr
        if op:
            addr += _sizeof(ln, op, args, labels)

    # pass 2 -- emit
    out, listing, addr = bytearray(), [], org
    for ln, label, op, args in items:
        if not op or op.lower() == ".equ":
            continue
        d, start = op.lower(), addr
        if d == ".org":
            target = _value(args[0], labels, ln)
            out.extend([SAFE_FILL] * (target - org - len(out)))
            addr = target
            continue
        emitted = bytearray()
        if d == ".db":
            for a in args:
                if a.startswith('"'):
                    emitted.extend(_unquote(a, ln))
                else:
                    emitted.append(_byte(_value(a, labels, ln), ln))
        elif d == ".dw":
            for a in args:
                v = _value(a, labels, ln)
                emitted.extend([v & 0xFF, (v >> 8) & 0xFF])
        elif d == ".ds":
            emitted.extend([SAFE_FILL] * (_value(args[0], labels, ln)
                                          if args else 0))
        else:
            emitted.extend(_encode(ln, op.upper(), args, labels))
        out.extend(emitted)
        addr += len(emitted)
        listing.append((start, bytes(emitted), ln))
    return Result(out, org, labels, listing)


def _byte(v, ln):
    if not 0 <= v <= 0xFF:
        raise AsmError(f"line {ln}: {v:#x} out of byte range")
    return v


def _word(v, ln):
    if not 0 <= v <= 0xFFFF:
        raise AsmError(f"line {ln}: {v:#x} out of address range")
    return [v & 0xFF, (v >> 8) & 0xFF]


def _encode(ln, name, args, labels):
    if name not in INSTRUCTIONS:
        raise AsmError(f"line {ln}: unknown mnemonic {name!r}")
    shape = SHAPE[name]
    want = ARGC[shape]
    if len(args) != want:
        word = "operand" if want == 1 else "operands"
        raise AsmError(f"line {ln}: {name} takes {want} {word}, got "
                       f"{len(args)}" + ("  (missing operand)" if
                                         len(args) < want else ""))
    out = [OPCODES[name]]
    if shape == IMMEDIATE:
        out.append(_byte(_value(args[0], labels, ln), ln))
    elif shape == ADDRESS:
        out += _word(_value(args[0], labels, ln), ln)
    elif shape == ADDR_IMM:
        out += _word(_value(args[0], labels, ln), ln)
        out.append(_byte(_value(args[1], labels, ln), ln))
    elif shape == POINTER:
        # The pointer, then the pointer PLUS ONE. Written once by the
        # programmer because the address register cannot increment itself.
        p = _value(args[0], labels, ln)
        out += _word(p, ln) + _word((p + 1) & 0xFFFF, ln)
    n = instruction_size(name)
    if len(out) != n:
        raise AsmError(f"line {ln}: {name} emitted {len(out)} bytes, "
                       f"microcode declares {n}")
    return out


# ---- the other direction, for the equivalence test ---------------------
def render(program):
    """A progrom_gen program list -> .asm text.

    Exists so `test_asm` can prove the text path and the Python path agree on
    every image that exists, rather than on a handful someone chose."""
    from progrom_gen import Ref
    lines = []
    for step in program:
        if isinstance(step, str):
            lines.append(f"{step}:")
            continue
        name, ops = step[0], list(step[1:])
        shape = SHAPE[name]
        flat = []
        for v in ops:
            flat += [Ref, v.name] if isinstance(v, Ref) else [v]
        if shape == IMPLIED:
            lines.append(f"        {name}")
        elif shape == IMMEDIATE:
            lines.append(f"        {name} {_lit(flat[0])}")
        elif shape == ADDRESS:
            lines.append(f"        {name} {_addr_arg(flat)}")
        elif shape == ADDR_IMM:
            lines.append(f"        {name} {_addr_arg(flat[:2])}, "
                         f"{_lit(flat[2])}")
        elif shape == POINTER:
            lines.append(f"        {name} {_addr_arg(flat[:2])}")
    return "\n".join(lines) + "\n"


def _lit(v):
    return v if isinstance(v, str) else f"{v:#04x}"


def _addr_arg(flat):
    from progrom_gen import Ref
    if flat and flat[0] is Ref:
        return flat[1]
    return f"{(flat[0] | (flat[1] << 8)):#06x}"


# ---- CLI ---------------------------------------------------------------
def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    src = argv[0]
    out = listing = run = None
    i = 1
    while i < len(argv):
        if argv[i] == "-o":
            out = argv[i + 1]
            i += 2
        elif argv[i] == "--list":
            listing = True
            i += 1
        elif argv[i] == "--run":
            run = True
            i += 1
        else:
            print(f"unknown option {argv[i]!r}")
            return 2
    try:
        r = assemble_text(open(src).read())
    except AsmError as e:
        print(f"{src}: {e}", file=sys.stderr)
        return 1
    print(f"{src}: {len(r.code)} bytes at {r.origin:#06x}, "
          f"{len(r.labels)} symbols")
    if listing:
        text = open(src).read().splitlines()
        for a, b, ln in r.listing:
            print(f"  {a:04X}  {b.hex(' '):<14}  {text[ln - 1].rstrip()}")
    if run:
        import progrom_gen as pg
        try:
            st = pg.simulate(None,
                             image=pg.build_image_from_bytes(r.code, r.origin))
        except pg.Unoracled as e:
            # By design, not a fault: the oracle has no answer key for this
            # image (PHASE_G.md SECTION 5). Say so and keep building; the
            # expected value is datasheet-sourced and lives in roms/README.md.
            print(f"  OB = UNORACLED -- {e}")
        else:
            ob = ("never reached an OUT" if st["out"] is None
                  else f"{st['out']:#04x}")
            print(f"  OB = {ob}   halted={st['halted']}   steps={st['steps']}")
    if out:
        import progrom_gen as pg
        img = pg.build_image_from_bytes(r.code, r.origin)
        open(out, "wb").write(bytes(img))
        print(f"  wrote {out}  {len(img)} bytes  crc={pg.crc16(img):#06x}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
