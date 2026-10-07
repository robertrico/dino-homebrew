#!/usr/bin/env python3
"""as8 -- an 8008 assembler for the as8 dialect SCELBAL is written in.

    python3 docs/notes/as8.py asm/scelbal/upstream/sc1fast.asm -o out.bin

PHASE_BASIC step 2. Not a DINO tool: it reads the ORIGINAL 8008 source so
the translator (scelbal_xlate.py) gets labels and the code/data split, and
the 8008 emulator (i8008.py) gets the image. test_as8.py pins it byte for
byte against upstream's published sc1fast.bin.

DIALECT (Thomas E. Jones' as8 with -octal, as sc1fast.asm uses it)

    LABEL:  MNEM operand   ; comment     labels end in ':'
    NAME:   EQU 027#000                  binds a value
            ORG 001#272                  page#offset, both octal = page*256+off
            DATA 000,120,004             bytes, octal
            DATA "READY"                 characters, MARK PARITY (bit 7 set);
                                         a missing closing quote ends the line
            DATA *79                     reserve n bytes, n DECIMAL, zero fill
            LHI \\HB\\LABEL                high byte of a 14-bit address
            \\LB\\LABEL                    low byte

Numbers are octal. Labels are case-blind (`save:` is called as SAVE). Mnemonics are the original Intel 8008 set (LAB, LMI,
NDA, JTZ, CAL, RFC ...).
"""
import re
import sys
from dataclasses import dataclass, field

REGS = "ABCDEHLM"
ALU = {"AD": 0, "AC": 1, "SU": 2, "SB": 3, "ND": 4, "XR": 5, "OR": 6, "CP": 7}
COND = {"C": 0, "Z": 1, "S": 2, "P": 3}
MEMSIZE = 0x4000            # 14-bit address space


class As8Error(Exception):
    pass


@dataclass
class Item:
    """One emitting line. kind 'code' (one instruction) or 'data'."""
    addr: int
    size: int
    kind: str
    mnem: str
    operand: str
    line: int
    labels: list = field(default_factory=list)
    text: str = ""


def encode_shape(mnem):
    """mnem -> (opcode, operand kind) where kind is None, 'imm', 'addr',
    'port' or 'rst'. Raises on an unknown mnemonic."""
    m = mnem.upper()
    fixed = {"RLC": 0o002, "RRC": 0o012, "RAL": 0o022, "RAR": 0o032,
             "RET": 0o007, "JMP": 0o104, "CAL": 0o106,
             "HLT": 0o001}          # as8 emits 001 (upstream .bin agrees)
    if m in fixed:
        return fixed[m], ("addr" if m in ("JMP", "CAL") else None)
    if m == "INP":
        return 0o101, "port"
    if m == "OUT":
        return 0o101, "port"
    if m == "RST":
        return 0o005, "rst"
    if len(m) == 3 and m[0] == "L" and m[1] in REGS:
        d = REGS.index(m[1])
        if m[2] == "I":
            return (d << 3) | 0o006, "imm"
        if m[2] in REGS:
            s = REGS.index(m[2])
            if d == 7 and s == 7:
                raise As8Error("LMM is HLT")
            return 0o300 | (d << 3) | s, None
    if len(m) == 3 and m[:2] in ("IN", "DC") and m[2] in "BCDEHL":
        r = REGS.index(m[2])
        return (r << 3) | (0 if m[:2] == "IN" else 1), None
    if len(m) == 3 and m[:2] in ALU:
        op = ALU[m[:2]]
        if m[2] == "I":
            return (op << 3) | 0o004, "imm"
        if m[2] in REGS:
            return 0o200 | (op << 3) | REGS.index(m[2]), None
    if len(m) == 3 and m[2] in COND and m[:2] in ("JF", "JT", "CF", "CT",
                                                  "RF", "RT"):
        c = COND[m[2]]
        t = 0o040 if m[1] == "T" else 0
        base = {"J": 0o100, "C": 0o102, "R": 0o003}[m[0]]
        return base | t | (c << 3), ("addr" if m[0] in "JC" else None)
    raise As8Error(f"unknown mnemonic {mnem}")


def _size(kind):
    return {None: 1, "imm": 2, "addr": 3, "port": 1, "rst": 1}[kind]


def _num(tok):
    tok = tok.strip()
    if "#" in tok:
        p, o = tok.split("#")
        return _num(p) * 256 + _num(o)
    if not re.fullmatch(r"[0-7]+", tok):
        raise ValueError(tok)
    return int(tok, 8)


def value(expr, sym):
    e = expr.strip()
    m = re.fullmatch(r"\\(HB|LB)\\(.+)", e)
    if m:
        v = value(m.group(2), sym)
        return (v >> 8) & 0xFF if m.group(1) == "HB" else v & 0xFF
    try:
        return _num(e)
    except ValueError:
        pass
    if e.upper() in sym:
        return sym[e.upper()]
    raise As8Error(f"undefined {e!r}")


def _data_items(operand):
    """DATA operand -> list of ('str', s) / ('res', n) / ('expr', e)."""
    op = operand.strip()
    if op.startswith('"'):
        body = op[1:]
        if body.endswith('"'):
            body = body[:-1]
        return [("str", body)]
    if op.startswith("*"):
        return [("res", int(op[1:]))]           # DECIMAL
    return [("expr", t) for t in op.split(",")]


def _data_size(operand):
    n = 0
    for k, v in _data_items(operand):
        n += len(v) if k == "str" else v if k == "res" else 1
    return n


def _strip_comment(line):
    """Comment is ';' outside a string."""
    out, q = [], False
    for ch in line:
        if ch == '"':
            q = not q
        if ch == ";" and not q:
            break
        out.append(ch)
    return "".join(out).rstrip()


def _lines(src):
    """-> (lineno, label or None, mnem or None, operand)."""
    for n, raw in enumerate(src.splitlines(), 1):
        line = _strip_comment(raw)
        if not line.strip():
            continue
        label = None
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            label, rest = m.group(1).upper(), m.group(2)   # case-blind
        else:
            rest = line.strip()
        if not rest:
            yield n, label, None, ""
            continue
        parts = rest.split(None, 1)
        yield n, label, parts[0].upper(), parts[1].strip() if len(parts) > 1 else ""


def parse(src):
    """Pass 1 + layout: every emitting line as an Item, plus the symbols."""
    items, sym, pc, pending = [], {}, 0, []
    for n, label, mnem, operand in _lines(src):
        if mnem == "EQU":
            sym[label] = value(operand, sym)
            continue
        if label:
            if label in sym:
                raise As8Error(f"line {n}: {label} defined twice")
            sym[label] = pc
            pending.append(label)
        if mnem is None:
            continue
        if mnem == "ORG":
            pc = _num(operand)
            for lab in pending:
                sym[lab] = pc
            continue
        if mnem == "DATA":
            size, kind = _data_size(operand), "data"
        else:
            size, kind = _size(encode_shape(mnem)[1]), "code"
        items.append(Item(pc, size, kind, mnem, operand, n, pending))
        pending = []
        pc += size
    parse.symbols = sym
    return items


def assemble(src):
    """-> (bytearray image of MEMSIZE, symbols)."""
    items = parse(src)
    sym = parse.symbols
    img = bytearray(MEMSIZE)
    for it in items:
        out = []
        if it.kind == "data":
            for k, v in _data_items(it.operand):
                if k == "str":
                    out += [ord(c) | 0x80 for c in v]
                elif k == "res":
                    out += [0] * v
                else:
                    out.append(value(v, sym) & 0xFF)
        else:
            op, kind = encode_shape(it.mnem)
            if kind == "imm":
                out = [op, value(it.operand, sym) & 0xFF]
            elif kind == "addr":
                a = value(it.operand, sym)
                out = [op, a & 0xFF, (a >> 8) & 0x3F]
            elif kind == "port":
                p = value(it.operand, sym)
                if it.mnem == "INP" and not 0 <= p < 8:
                    raise As8Error(f"line {it.line}: INP port {p}")
                if it.mnem == "OUT" and not 8 <= p < 32:
                    raise As8Error(f"line {it.line}: OUT port {p}")
                out = [op | (p << 1)]
            elif kind == "rst":
                out = [op | (value(it.operand, sym) << 3)]
            else:
                out = [op]
        assert len(out) == it.size, it
        img[it.addr:it.addr + it.size] = bytes(out)
    return img, sym


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    with open(a.src) as f:
        img, sym = assemble(f.read())
    if a.out:
        with open(a.out, "wb") as f:
            f.write(bytes(img))
    print(f"{len(sym)} symbols")
