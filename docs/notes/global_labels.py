#!/usr/bin/env python3
"""Make KiCad join dino_v0_0_2's sheets by label name, the way the repo's
tools already do.

    python3 docs/notes/global_labels.py            report: what would change
    python3 docs/notes/global_labels.py --write    convert in place

Two edits:
  * every `(label "X" ...)` whose name X appears on two or more sheets
    becomes `(global_label "X" ...)` at the same anchor. Sheet-local names
    stay local. Bus labels (`W[0..7]`) convert too; global bus labels are
    legal and keep the members' bus-ness.
  * the embedded AT28C64B / AT28C256 symbols get their `I/O` pins retyped
    from `input` to `tri_state`: the ROMs drive those pins.

Global label shape is `passive` everywhere: it joins nets without claiming
a direction, so ERC judges the PINS on the net and nothing else.

2026-09-12. Before this, KiCad's netlist had 122 base names split into
per-sheet fragments and ERC reported 90 undriven inputs whose driver sat
one sheet away. See test_global_labels.py for the proof of equivalence.
"""
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kicad_netlist import tokenize, parse, children, child  # noqa: E402
from footprint_gen import sheets  # noqa: E402

_LABEL = re.compile(
    r'^\t\(label "((?:[^"\\]|\\.)*)"\n'
    r'\t\t\(at ([-\d.]+) ([-\d.]+) (\d+)\)\n'
    r'(?P<body>(?:\t\t.*\n)*?)'
    r'\t\t\(uuid "(?P<uuid>[^"]+)"\)\n'
    r'\t\)\n', re.M)

ROM_SYMBOLS = ("Memory_EEPROM:AT28C64B", "Memory_EEPROM:AT28C256")


def label_names(path):
    with open(path) as f:
        tree = parse(tokenize(f.read()))
    return {l[1] for kind in ("label", "global_label")
            for l in children(tree, kind)}


def cross_sheet_names(paths):
    """Names that appear on two or more sheets."""
    seen = Counter()
    for p in paths:
        seen.update(label_names(p))
    return {n for n, c in seen.items() if c > 1}


def _justify(rot):
    return "left" if rot in ("0", "90") else "right"


def _global(name, x, y, rot, uuid):
    j = _justify(rot)
    return (
        f'\t(global_label "{name}"\n'
        "\t\t(shape passive)\n"
        f"\t\t(at {x} {y} {rot})\n"
        "\t\t(fields_autoplaced yes)\n"
        "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
        f"\t\t\t(justify {j})\n\t\t)\n"
        f'\t\t(uuid "{uuid}")\n'
        '\t\t(property "Intersheetrefs" "${INTERSHEET_REFS}"\n'
        f"\t\t\t(at {x} {y} {rot})\n"
        "\t\t\t(hide yes)\n"
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n"
        f"\t\t\t\t(justify {j})\n\t\t\t)\n\t\t)\n"
        "\t)\n")


def globalise(src, names):
    """Rewrite the cross-sheet labels in one sheet's text. Returns (text, n)."""
    n = 0

    def fix(m):
        nonlocal n
        name = m.group(1)
        if name not in names:
            return m.group(0)
        n += 1
        return _global(name, m.group(2), m.group(3), m.group(4), m.group("uuid"))

    return _LABEL.sub(fix, src), n


_ROM_PIN = re.compile(
    r'\(pin input( line\n\s*\(at [^\n]*\n\s*\(length [^\n]*\n'
    r'(?:\s*\(hide yes\)\n)?\s*\(name "I/O\d")')


def retype_rom_pins(src):
    """AT28Cxx I/O pins: input -> tri_state, inside those symbols only."""
    out, n = [], 0
    pos = 0
    for sym in ROM_SYMBOLS:
        head = f'\t\t(symbol "{sym}"\n'
        i = src.find(head)
        if i < 0:
            continue
        j = src.find("\n\t\t(symbol \"", i + len(head))
        j = len(src) if j < 0 else j
        block, k = _ROM_PIN.subn(r"(pin tri_state\1", src[i:j])
        src = src[:i] + block + src[j:]
        n += k
    return src, n


def alias_pairs(control_word_path):
    """(CWnn, alias) pairs from the Control Word sheet: two labels on one
    horizontal stub wire. This is how the machine names its microcode
    bits; the pairs are what a name-join of per-sheet nets cannot see."""
    with open(control_word_path) as f:
        tree = parse(tokenize(f.read()))
    labs = {}
    for kind in ("label", "global_label"):
        for l in children(tree, kind):
            at = child(l, "at")
            labs[(float(at[1]), float(at[2]))] = l[1]
    pairs = set()
    for w in children(tree, "wire"):
        pts = [(float(x[1]), float(x[2])) for x in children(child(w, "pts"), "xy")]
        if len(pts) != 2 or pts[0][1] != pts[1][1]:
            continue
        ends = [labs.get(p) for p in pts]
        if all(ends) and ends[0] != ends[1]:
            cw = [e for e in ends if re.fullmatch(r"CW\d+", e)]
            other = [e for e in ends if not re.fullmatch(r"CW\d+", e)]
            if cw and other:
                pairs.add((cw[0], other[0]))
    return pairs


def convert(proj, write=True):
    paths = sheets(proj)
    names = cross_sheet_names(paths)
    report = []
    for p in paths:
        with open(p) as f:
            src = f.read()
        new, n = globalise(src, names)
        new, k = retype_rom_pins(new)
        if new != src:
            report.append((os.path.basename(p), n, k))
            if write:
                with open(p, "w") as f:
                    f.write(new)
    return report


def main(argv):
    proj = os.path.join(HERE, "..", "..", "dino_v0_0_2")
    rep = convert(proj, write="--write" in argv)
    for name, n, k in rep:
        print(f"{name:28} {n:4} labels -> global   {k} ROM pins -> tri_state")
    if "--write" not in argv and rep:
        print("(dry run; --write to apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
