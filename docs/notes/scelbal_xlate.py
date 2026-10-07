#!/usr/bin/env python3
"""scelbal_xlate -- SCELBAL (8008) -> DINO assembly. PHASE_BASIC step 4.

    python3 docs/notes/scelbal_xlate.py            # writes asm/ram/scelbal.asm

asm/ram/scelbal.asm is GENERATED from the vendored upstream source; never
edit it by hand. The answer key is scelbal_ref.py (original SCELBAL on
i8008.py); test_scelbal_xlate.py runs every macro against it one 8008
instruction at a time, and the whole interpreter against it session by
session.

THE MODEL
    8008 A            DINO A
    8008 B C D E H L  RAM cells VB VC VD VE VH VL
    pointer H:L       VL then PH, adjacent, so LDAM/STAM/LDBM VL is M.
                      PH = page(H) = PAGE0 + (H & 0x3F), through the ROM table
                      PHT -- the 8008 drops H's top two bits -- kept in
                      step with every write of H. VH keeps all 8 bits.
    8008 address a    DINO page(a >> 8):(a & 0xFF), for data. Code is
                      relocated into ROM; the three initialised data pages
                      are copied out of a ROM template at cold start.
    8008 S            cell VS: every S producer whose S is live stores
                      its result there; JTS/JFS test VS bit 7. DINO has no
                      sign branch (CW22 is a no-connect).
    8008 C            DINO C, in the POLARITY scelbal_flow reports:
                      T same, I inverted (SU/SB/CP: DINO gives NOT-borrow).
                      A logic op whose carry is live is normalized to the
                      polarity its consumers need (ADI 0 -> T, CPI 0 -> I).
    8008 Z            DINO Z.   P is never read by SCELBAL.
    DINO B and C      scratch, never 8008 state (RET clobbers C, every
                      immediate ALU op and INR/DCR/SHL clobber B).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as8                                                    # noqa: E402
import scelbal_flow as fl                                     # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
SRC = os.path.join(ROOT, "asm", "scelbal", "upstream", "sc1fast.asm")
OUT = os.path.join(ROOT, "asm", "basic.asm")       # imon + SCELBAL, U24
IMON = os.path.join(ROOT, "asm", "imon.asm")

# ---- layout: ROM U24 (0x0000-0x3FFF, M14 decoded out: netlist 2026-10-06) --
IMON_END = 0x0500           # imon owns 0x0000-0x04FF of the image
RRT0 = 0x0500               # x >> 1                       (ROM, read as data)
PHT = 0x0600                # DINO page of 8008 page x
TEMPLATE = 0x0700           # 8008 pages 001, 026, 027 as assembled
TEMPLATE_PAGES = (0o001, 0o026, 0o027)
CODE = 0x0A00               # cold entry; warm entry = CODE + 3
ROM_END = 0x4000
CELLS = 0x8100              # RAM. imon owns 0x80A0-0x80FF
CELL_NAMES = ("VB", "VC", "VD", "VE", "VL", "PH", "VH", "VS",
              "TA", "TC", "TR")
CELL = {n: CELLS + i for i, n in enumerate(CELL_NAMES)}
STACK = 0x83FF              # SCELBAL's own stack, 0x8200-0x83FF
PAGE0 = 0x84                # 8008 page p lives at DINO page PAGE0 + p
ROM_PAGES = {0o61: 0x3F}    # read-only 8008 pages served straight from ROM
                            # (peekpoke.as8's tables): no RAM copy, no template


def page(p):
    """DINO page of 8008 page p (the 8008 drops H's top two bits)."""
    p &= 0x3F
    return ROM_PAGES.get(p, PAGE0 + p)


RAM_OF = PAGE0 << 8         # kept for the tests: 8008 a -> RAM_OF + a
VREG = {"B": "VB", "C": "VC", "D": "VD", "E": "VE", "H": "VH", "L": "VL"}
DINO_ALU = {"AD": "ADD", "AC": "ADC", "SU": "SUB", "SB": "SBB",
            "ND": "AND", "XR": "XOR", "OR": "OR", "CP": "CMP"}
DINO_IMM = {"AD": "ADI", "AC": "ACI", "SU": "SUI", "SB": "SBI",
            "ND": "ANI", "XR": "XRI", "OR": "ORI", "CP": "CPI"}


class XlateError(Exception):
    pass


def tables():
    """(address, bytes) for the three lookup pages."""
    return [(RRT0, bytes(x >> 1 for x in range(256))),
            (PHT, bytes(page(x) for x in range(256)))]


def table_lines():
    out = []
    for base, data in tables():
        out.append(f".org {base}")
        for i in range(0, 256, 16):
            out.append(".db " + ", ".join(str(b) for b in data[i:i + 16]))
    return out


# ---- out-of-line helpers ------------------------------------------------
# A macro too big to repeat becomes `CALL h_...`, one copy per variant.
# CALL/RET touch no flag; RET clobbers DINO C, which is scratch. Helpers
# may assume nothing about B and C on entry.
LIB = {}


def helper(name, body):
    """Register a helper (body without RET) and return the call."""
    if name not in LIB:
        LIB[name] = [f"{name}:"] + body + ["RET"]
    return ["CALL " + name]


def library(lines):
    """Helper definitions for every `CALL h_...` in `lines`, transitively."""
    want, out, seen = [l.split()[1] for l in lines
                       if l.startswith("CALL h_")], [], set()
    while want:
        n = want.pop()
        if n in seen:
            continue
        seen.add(n)
        out += LIB[n]
        want += [l.split()[1] for l in LIB[n] if l.startswith("CALL h_")]
    return out


# ---- macros -----------------------------------------------------------
class Ctx:
    """What the analysis says about one 8008 instruction.

    live      8008 flags read after it (scelbal_flow live_out)
    pol       DINO-carry polarity on entry, one of T I Z0 (or None if no
              carry is read here)
    norm      for a logic op whose carry is live: the polarity to leave
    label     unique prefix for local labels
    target    the DINO label of a jump/call target
    """
    def __init__(self, live=fl.ALL, pol=None, norm=None, label="L",
                 target=None, h=None, l=None, dead=frozenset()):
        self.h, self.l = h, l           # 8008 H, L known on entry, or None
        self.dead = frozenset(dead)     # cells this writes that nobody reads
        self.live = frozenset(live)
        self.pol = pol
        self.norm = norm
        self.label = label
        self.target = target


def _dead(r, ctx):
    """Every cell register r owns is dead after this instruction."""
    cells = ("VH", "PH") if r == "H" else (VREG[r],)
    return all(c in ctx.dead for c in cells)


def _set_h_from_a():
    """A holds the new 8008 H: store it and its pointer page. Clobbers
    A, B, C; touches no flag."""
    return ["STA VH", "MOVCA", "LDBI >%d" % PHT, "LDAX", "STA PH"]


def _m_abs(ctx):
    """DINO address of M when H and L are both known, else None."""
    if ctx is None or ctx.h is None or ctx.l is None:
        return None
    return (page(ctx.h) << 8) | ctx.l


def _src_to_b(s, ctx=None):
    """Operand register s into DINO B, flags untouched, A untouched."""
    if s == "A":
        return ["MOVBA"]
    if s == "M":
        a = _m_abs(ctx)
        return ["LDBM VL"] if a is None else [f"LDB {a}"]
    return ["LDB " + VREG[s]]


def _store_s(ctx):
    return ["STA VS"] if "S" in ctx.live else []


def _norm(ctx):
    if ctx.norm == "T":
        return ["ADI 0"]            # C = 0 = 8008's cleared carry, A and Z kept
    if ctx.norm == "I":
        return ["CPI 0"]            # NOT-borrow 1 = 8008 carry 0, A and Z kept
    return []


def jump_if(flag, sense, dest, ctx):
    """Lines that jump to `dest` when 8008 flag `flag` == `sense`, and fall
    through otherwise, leaving every live 8008 flag as it was."""
    k = ctx.label
    if flag == "Z":
        # DINO's one polarity: JNZ taken when Z == 0
        return ["JNZ " + dest] if not sense else [
            f"JNZ {k}_n", "JMP " + dest, f"{k}_n:"]
    if flag == "C":
        pol = ctx.pol
        if pol == "Z0":                     # 8008 carry is known 0
            return [] if sense else ["JMP " + dest]
        if pol not in ("T", "I"):
            raise XlateError(f"{k}: carry polarity {pol!r} at a C test")
        dino_c_when_taken = sense if pol == "T" else not sense
        # JNC is taken when DINO C == 0
        return ["JNC " + dest] if not dino_c_when_taken else [
            f"JNC {k}_n", "JMP " + dest, f"{k}_n:"]
    if flag == "S":
        keep = ctx.live & {"Z", "C"}
        test = helper("h_stest", ["STA TA", "LDA VS", "ANI 0x80",
                                  "LDA TA"])               # Z = !S
        if not keep:
            return test + (["JNZ " + dest] if sense else [
                f"JNZ {k}_n", "JMP " + dest, f"{k}_n:"])
        if sense:
            return ["PUSHF"] + test + [
                f"JNZ {k}_t", "POPF", f"JMP {k}_n",
                f"{k}_t:", "POPF", "JMP " + dest, f"{k}_n:"]
        return ["PUSHF"] + test + [
            f"JNZ {k}_t", "POPF", "JMP " + dest,
            f"{k}_t:", "POPF"]
    raise XlateError(f"{k}: no branch on 8008 flag {flag}")


def _inc_dec(m, r, ctx):
    """INr/DCr. Always stores VS: if this S is dead, another S definer
    comes before any S reader, so the store is never seen."""
    op = "INR" if m == "IN" else "DCR"
    body = ["LDA " + VREG[r], op, "STA " + VREG[r], "STA VS"]
    if r == "H":
        body += _set_h_from_a()
    if "C" not in ctx.live:
        return helper(f"h_{m}{r}", ["STA TA"] + body + ["LDA TA"])
    if ctx.pol not in ("T", "I"):
        raise XlateError(f"{ctx.label}: {m}{r} keeps carry of polarity "
                         f"{ctx.pol!r}")
    if "Z" not in ctx.live:
        # the old carry (and the old Z, dead) come back whole
        return helper(f"h_{m}{r}_c", ["PUSHF", "STA TA"] + body
                      + ["LDA TA", "POPF"])
    # Z is new, C is old: build the flags byte. LDA leaves the flags, so
    # the DINO carry is still the entry carry when ACI reads it.
    k = f"h_{m}{r}_cz"
    return helper(k, ["STA TA", "LDAI 0", "ACI 0", "STA TC"] + body + [
        f"JNZ {k}_z", "LDA TC", "ORI 2", f"JMP {k}_f",
        f"{k}_z:", "LDA TC", f"{k}_f:", "PUSHA", "POPF", "LDA TA"])


def _rotate(m, ctx):
    if m == "RLC":
        return ["CPI 0x80", "MOVBA", "ADC"]    # C = A7, then A+A+C
    if m == "RAL":
        if ctx.pol != "T":
            raise XlateError(f"{ctx.label}: RAL with carry polarity "
                             f"{ctx.pol!r}")
        return ["MOVBA", "ADC"]
    # Right rotates: x >> 1 from RRT0, bit 7 from the bit that comes in
    # (TC), carry out = x & 1, all in one shared tail.
    tail = helper("h_rrtail", [
        "LDC TR", "LDBI >%d" % RRT0, "LDAX", "STA TA",
        "LDA TC", "ORI 0", "JNZ h_rrtail_s",
        "h_rrtail_c:", "LDA TR", "ANI 1", "CPI 1", "LDA TA", "RET",
        "h_rrtail_s:", "LDA TA", "ORI 0x80", "STA TA", "JMP h_rrtail_c"])
    if m == "RRC":
        return helper("h_RRC", ["STA TR", "ANI 1", "STA TC"] + tail)
    if ctx.pol != "T":
        raise XlateError(f"{ctx.label}: RAR with carry polarity {ctx.pol!r}")
    return helper("h_RAR", ["STA TR", "LDAI 0", "ACI 0", "STA TC"] + tail)


def macro(mnem, operand, ctx):
    """8008 instruction -> DINO assembly lines."""
    m = mnem.upper()
    regs = "ABCDEHLM"
    # ---- loads
    if len(m) == 3 and m[0] == "L" and m[1] in regs and m[2] in regs:
        d, s = m[1], m[2]
        if d == s:
            return []
        if d in VREG and _dead(d, ctx):
            return []                       # a store nobody reads
        a = _m_abs(ctx)
        if d == "A":
            if s == "M":
                return ["LDAM VL"] if a is None else [f"LDA {a}"]
            return ["LDA " + VREG[s]]
        if d == "M":
            if s == "A":
                return ["STAM VL"] if a is None else [f"STA {a}"]
            return helper(f"h_LM{s}", ["STA TA", "LDA " + VREG[s],
                                       "STAM VL", "LDA TA"])
        if s == "A":
            return (helper("h_LHA", ["STA TA"] + _set_h_from_a()
                           + ["LDA TA"]) if d == "H"
                    else ["STA " + VREG[d]])
        if d == "H":
            return helper(f"h_LH{s}", ["STA TA", "LDBM VL" if s == "M"
                                       else "LDB " + VREG[s], "MOVAB"]
                          + _set_h_from_a() + ["LDA TA"])
        if s == "M":
            return helper(f"h_L{d}M", ["LDBM VL", "STB " + VREG[d]])
        return _src_to_b(s) + ["STB " + VREG[d]]
    if len(m) == 3 and m[0] == "L" and m[1] in regs and m[2] == "I":
        d, n = m[1], operand
        if d == "A":
            return ["LDAI " + n]
        if d == "M":
            a = _m_abs(ctx)
            return (["LDC VL", "LDB PH", "MVIX " + n] if a is None
                    else [f"MVI {a}, {n}"])
        v = int(n, 0)
        if (d == "H" and ctx.h == v) or (d == "L" and ctx.l == v):
            return []                       # already holds it
        if d == "H":
            return ([] if "VH" in ctx.dead else [f"MVI VH, {v}"]) + \
                   ([] if "PH" in ctx.dead else [f"MVI PH, {page(v)}"])
        if _dead(d, ctx):
            return []
        return [f"MVI {VREG[d]}, {n}"]
    # ---- ALU
    if len(m) == 3 and m[:2] in DINO_ALU and (m[2] in regs or m[2] == "I"):
        op = m[:2]
        if m[2] == "I":
            ins = DINO_IMM[op]
            if op == "AC" and ctx.pol == "Z0":
                ins = "ADI"
            elif op == "SB" and ctx.pol == "Z0":
                ins = "SUI"
            elif op == "AC" and ctx.pol != "T":
                raise XlateError(f"{ctx.label}: ACI with polarity {ctx.pol!r}")
            elif op == "SB" and ctx.pol != "I":
                raise XlateError(f"{ctx.label}: SBI with polarity {ctx.pol!r}")
            core = [f"{ins} {operand}"]
            s_src = [f"SUI {operand}"]
        else:
            s = m[2]
            if op in ("ND", "OR") and s == "A":
                core = ["ORI 0"]                # A unchanged; Z, S from A
            elif op == "XR" and s == "A":
                core = ["CLR"]
            else:
                ins = DINO_ALU[op]
                if op == "AC" and ctx.pol == "Z0":
                    ins = "ADD"
                elif op == "SB" and ctx.pol == "Z0":
                    ins = "SUB"
                elif op == "AC" and ctx.pol != "T":
                    raise XlateError(f"{ctx.label}: AC with polarity "
                                     f"{ctx.pol!r}")
                elif op == "SB" and ctx.pol != "I":
                    raise XlateError(f"{ctx.label}: SB with polarity "
                                     f"{ctx.pol!r}")
                core = _src_to_b(s, ctx) + [ins]
            s_src = _src_to_b(s, ctx) + ["SUB"]
        if op == "CP":
            s_part = (["STA TA"] + s_src + ["STA VS", "LDA TA"]
                      if "S" in ctx.live else [])
            return s_part + core if s_part else core
        return core + _norm(ctx) + _store_s(ctx)
    # ---- increment / decrement
    if len(m) == 3 and m[:2] in ("IN", "DC") and m[2] in "BCDEHL":
        return _inc_dec(m[:2], m[2], ctx)
    # ---- rotates
    if m in ("RLC", "RRC", "RAL", "RAR"):
        return _rotate(m, ctx)
    # ---- control
    if m == "JMP":
        return ["JMP " + ctx.target]
    if m == "CAL":
        return ["CALL " + ctx.target]
    if m == "RET":
        return ["RET"]
    if m == "HLT":
        return ["HALT"]
    # ---- the two ports asm/scelbal/udf.as8 uses; nothing else is wired
    if m == "INP" and int(operand, 0) == 0:
        return ["LDA 0x4000"]               # SW1, card zero; no flag moves
    if m == "OUT" and int(operand, 0) == 8:
        return ["OUT"]                      # OB latches MDR = A
    # peekpoke.as8: DINO memory at the 16-bit address in D:E
    if m == "INP" and int(operand, 0) == 1:
        return ["LDC VE", "LDB VD", "LDAX"]
    if m == "OUT" and int(operand, 0) == 9:
        return ["LDC VE", "LDB VD", "STAX"]
    if m in ("INP", "OUT"):
        raise XlateError(f"{ctx.label}: no DINO device for {m} {operand}")
    k, c = fl.classify(m)
    if k == "jcc":
        return jump_if(c[0], c[1], ctx.target, ctx)
    if k == "ccc":
        skip = ctx.label + "_s"
        return jump_if(c[0], not c[1], skip, ctx) + [
            "CALL " + ctx.target, skip + ":"]
    if k == "rcc":
        skip = ctx.label + "_s"
        return jump_if(c[0], not c[1], skip, ctx) + ["RET", skip + ":"]
    raise XlateError(f"no macro for {mnem} {operand}")


# ---- the whole interpreter ---------------------------------------------
def imon_labels():
    import asm
    with open(IMON) as f:
        return asm.assemble_text(f.read()).labels


def translate(src_path=SRC, standalone=True):
    """-> (asm text, flow). The SCELBAL part of the U24 image: tables and
    data template at 0x0500, code from CODE. imon fills 0x0000-0x04FF."""
    import scelbal_ref
    text = scelbal_ref.source(src_path)     # upstream + udf.as8
    items = as8.parse(text)
    sym = as8.parse.symbols
    img, _ = as8.assemble(text)
    flow = fl.Flow(items, sym, entries=["EXEC"], native=["CINP", "CPRINT"])
    mon = imon_labels()
    out = [f"{n}: .equ {a}" for n, a in CELL.items()]
    if standalone:                      # basic.asm gets them from imon's text
        out += [f"getc: .equ {mon['getc']}", f"putc: .equ {mon['putc']}"]
    out += table_lines()
    out.append(f".org {TEMPLATE}")
    for p in TEMPLATE_PAGES:
        data = img[p << 8:(p << 8) + 256]
        for i in range(0, 256, 16):
            out.append(".db " + ", ".join(str(v) for v in data[i:i + 16]))
    exec_ = f"a_{sym['EXEC']:04X}"
    out += [f".org {CODE}",
            "cold: JMP cold1",                      # G 0B00: fresh data pages
            f"warm: LXISP {STACK}",                 # G 0B03: keep the program
            f"JMP {exec_}",
            f"cold1: LXISP {STACK}"]
    # copy each template page to its 8008 page: B:C walks the source,
    # SP-free, a byte at a time (LDAX from ROM is ROM-as-data)
    for i, p in enumerate(TEMPLATE_PAGES):
        src_pg, dst_pg, k = (TEMPLATE >> 8) + i, page(p), f"cp{i}"
        out += [f"MVI TR, 0", f"{k}:", "LDC TR", f"LDBI {src_pg}", "LDAX",
                f"LDBI {dst_pg}", "STAX", "LDA TR", "INR", "STA TR",
                f"JNZ {k}"]
    out.append(f"JMP {exec_}")
    if any(flow.kind[c] in ("cal", "ccc") and flow.target[c] == sym["EXEC"]
           for c in flow.items):
        raise XlateError("something CALs EXEC: resetting SP there is wrong")
    order = sorted(flow.reached)
    native = {sym["CINP"]: ["CALL getc", "CALL putc", "ORI 0x80", "RET"],
              sym["CPRINT"]: ["STA TA", "ANI 0x7F", "CALL putc", "LDA TA",
                              "RET"]}
    for i, a in enumerate(order):
        it = flow.items[a]
        out.append(f"a_{a:04X}:   ; {it.mnem} {it.operand}")
        if a == sym["EXEC"]:
            # SCELBAL's error exits and END JMP here from inside calls; the
            # 8008's circular stack forgets those returns, DINO's RAM stack
            # would grow. Nothing CALs EXEC (checked below), so reset SP.
            out.append(f"LXISP {STACK}")
        if a in native:
            out += native[a]
            continue
        k = flow.kind[a]
        target = (f"a_{flow.target[a]:04X}" if a in flow.target else None)
        opd = it.operand
        if fl.classify(it.mnem)[0] in ("op", "io") and opd:
            opd = str(as8.value(opd, sym) & 0xFF)
        pol = flow.c_pol_in[a]
        reads_c = "C" in flow.du(a)[1] or (
            len(it.mnem) == 3 and it.mnem[:2] in ("IN", "DC")
            and "C" in flow.live_out[a])
        p = None
        if reads_c:
            if len(pol) != 1:
                raise XlateError(f"{a:#06x}: carry polarity {set(pol)}")
            (p,) = pol
        c = flow.consts[a]
        written, _ = flow.cell_du(a)
        ctx = Ctx(live=flow.live_out[a], pol=p, norm=flow.c_norm.get(a),
                  label=f"a_{a:04X}", target=target, h=c["H"], l=c["L"],
                  dead=written - flow.cell_live_out[a])
        out += macro(it.mnem, opd, ctx)
        falls = k not in ("jmp", "ret", "hlt")
        nxt = order[i + 1] if i + 1 < len(order) else None
        if falls and flow.nxt[a] != nxt:
            out.append(f"JMP a_{flow.nxt[a]:04X}")
    out += ["; ---- helpers"] + library(out)
    for p8, rp in sorted(ROM_PAGES.items(), key=lambda kv: kv[1]):
        out.append(f".org {rp << 8}          ; 8008 page {p8:03o}, read-only")
        data = img[p8 << 8:(p8 << 8) + 256]
        for i in range(0, 256, 16):
            out.append(".db " + ", ".join(str(v) for v in data[i:i + 16]))
    return "\n".join("  " + l if not l.endswith(":") and ":" not in l.split(";")[0]
                     else l for l in out) + "\n", flow


def license_header(src_path=SRC):
    """The upstream comment block, which must travel with every copy."""
    lines = []
    for l in open(src_path):
        if not l.startswith(";;;"):
            break
        lines.append("; " + l.rstrip()[3:].lstrip())
    return lines


def basic_asm():
    """asm/basic.asm: imon verbatim, then SCELBAL. GENERATED."""
    text, flow = translate(standalone=False)
    head = [
        "; basic.asm -- GENERATED by docs/notes/scelbal_xlate.py. DO NOT EDIT.",
        "; U24 image: PROG_imon (verbatim, 0x0000) + SCELBAL Fast translated",
        "; from 8008 (0x0500-). From the imon prompt:",
        f";     G {CODE:04X}   cold start: fresh data pages (then SCR)",
        f";     G {CODE + 3:04X}   warm start: keeps the program after Ctrl-C",
        "; Answer key: docs/notes/test_scelbal_dino.py (byte-for-byte vs the",
        "; original on i8008.py). Design: .git/sdd/PHASE_BASIC.md.",
        ";",
        "; ---- upstream notice (sc1fast.asm), carried as its terms require ----",
    ] + license_header() + [";", "; ==== imon.asm, verbatim " + "=" * 40]
    imon = open(IMON).read().rstrip("\n").split("\n")
    return "\n".join(head + imon + [
        "", "; ==== SCELBAL, translated " + "=" * 40]) + "\n" + text


if __name__ == "__main__":
    with open(OUT, "w") as f:
        f.write(basic_asm())
    print(f"wrote {os.path.relpath(OUT, ROOT)}")
