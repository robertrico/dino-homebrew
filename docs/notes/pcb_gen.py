#!/usr/bin/env python3
"""A first-draft PCB for dino_v0_0_2: every footprint placed, every pad on
its net, one board outline, no tracks.

    python3 docs/notes/pcb_gen.py --write      dino_v0_0_2/dino_v0_0_2.kicad_pcb
    python3 docs/notes/pcb_gen.py -o X.kicad_pcb

Placement is one block per schematic sheet -- the same partition the
breadboards use -- ICs in rows, passives below them. It is where hand
layout STARTS, not a layout. Footprints are the schematic's own Footprint
fields (see footprint_gen.py); pads get their nets from the kicad-cli
netlist export; each footprint carries its sheet path so "Update PCB from
Schematic" in pcbnew matches it instead of duplicating it.

Two interpreters: the host python does the parsing and placement, KiCad's
bundled python does the pcbnew build (`--build-in-kicad`, internal).
"""
import json
import math
import os
import subprocess
import sys
from collections import namedtuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kicad_netlist import tokenize, parse, children, child  # noqa: E402
from footprint_gen import footprint_libs  # noqa: E402

KICAD_APP = "/Applications/KiCad/KiCad.app/Contents"
KICAD_CLI = KICAD_APP + "/MacOS/kicad-cli"
KICAD_PY = (KICAD_APP + "/Frameworks/Python.framework/Versions/Current/"
            "bin/python3")

Comp = namedtuple("Comp", "ref value footprint sheet path")
Net = namedtuple("Net", "name code nodes")

PROJ = os.path.join(HERE, "..", "..", "dino_v0_0_2")

# Sheet blocks in the order the breadboards sit; unknown sheets go last.
SHEET_ORDER = ["root", "Power", "Microcode", "Control Word", "Program Counter",
               "MAR", "Memory", "MDR", "Registers A B", "ALU",
               "Stack Pointer", "Input", "Input Output"]
BLOCK_W = 120.0     # mm, width of one sheet block
BLOCKS_ACROSS = 3
GRID = 2.54
GAP = 2.54
MARGIN = 5.0


_ENV = {}


def envelope(footprint, libs=None):
    """(x0, y0, x1, y1) mm around the footprint origin: the F.CrtYd bbox
    plus half a GAP each side. Read from the .kicad_mod, never a table --
    the first draft (2026-09-12) guessed DIPs long along X and every IC row
    overlapped. KeyError when the footprint is not on disk."""
    if footprint in _ENV:
        return _ENV[footprint]
    libs = libs or footprint_libs(PROJ)
    lib, _, name = footprint.partition(":")
    path = os.path.join(libs.get(lib, "/nonexistent"), name + ".kicad_mod")
    if not os.path.exists(path):
        raise KeyError(footprint)
    with open(path) as f:
        tree = parse(tokenize(f.read()))
    pts = []
    for node in tree:
        if not isinstance(node, list) or not node or \
                not str(node[0]).startswith("fp_"):
            continue
        layer = child(node, "layer")
        if not layer or layer[1] != "F.CrtYd":
            continue
        for k in ("start", "end", "center"):
            v = child(node, k)
            if v:
                pts.append((float(v[1]), float(v[2])))
        for p in children(node, "pts"):
            for xy in children(p, "xy"):
                pts.append((float(xy[1]), float(xy[2])))
    if not pts:
        raise KeyError(f"{footprint}: no F.CrtYd")
    h = GAP / 2
    _ENV[footprint] = (min(x for x, _ in pts) - h, min(y for _, y in pts) - h,
                       max(x for x, _ in pts) + h, max(y for _, y in pts) + h)
    return _ENV[footprint]


def export_netlist(proj, out):
    sch = os.path.join(proj, "dino_v0_0_2.kicad_sch")
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format",
                    "kicadsexpr", "-o", out, sch], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out


def _sheet_name(names):
    n = names.strip("/")
    return n.split("/")[-1] if n else "root"


def read_netlist(path):
    with open(path) as f:
        tree = parse(tokenize(f.read()))
    comps, nets = [], []
    for c in children(child(tree, "components"), "comp"):
        sp = child(c, "sheetpath")
        names = child(sp, "names")[1]
        stamps = child(sp, "tstamps")[1]
        uuid = child(c, "tstamps")[1]
        fp = child(c, "footprint")
        comps.append(Comp(child(c, "ref")[1], child(c, "value")[1],
                          fp[1] if fp and len(fp) > 1 else "",
                          _sheet_name(names),
                          stamps.rstrip("/") + "/" + uuid))
    for n in children(child(tree, "nets"), "net"):
        nodes = [(child(x, "ref")[1], child(x, "pin")[1])
                 for x in children(n, "node")]
        nets.append(Net(child(n, "name")[1], int(child(n, "code")[1]), nodes))
    return comps, nets


def _snap_up(v):
    return math.ceil(v / GRID - 1e-9) * GRID


def _pack(items, width):
    """Row-pack (ref, envelope) into a block `width` wide. Returns
    {ref: (x, y)} of footprint ORIGINS snapped to the grid, and the height.
    Snapping rounds up, so an envelope never creeps back over its
    neighbour."""
    out, x, y, row_h = {}, 0.0, 0.0, 0.0
    for ref, (x0, y0, x1, y1) in items:
        w, h = x1 - x0, y1 - y0
        if x > 0 and x + w > width:
            x, y, row_h = 0.0, y + row_h + GAP, 0.0
        ox, oy = _snap_up(x - x0), _snap_up(y - y0)
        out[ref] = (ox, oy)
        x = ox + x1 + GAP
        row_h = max(row_h, oy + y1 - y)
    return out, y + row_h


def _refkey(ref):
    head = ref.rstrip("0123456789")
    tail = ref[len(head):]
    return (head, int(tail) if tail else 0)


def place(comps):
    """{ref: (x, y, rot)} in mm. ICs first, then passives, per sheet."""
    by_sheet = {}
    for c in comps:
        by_sheet.setdefault(c.sheet, []).append(c)
    order = [s for s in SHEET_ORDER if s in by_sheet] + \
            sorted(s for s in by_sheet if s not in SHEET_ORDER)
    placed = {}
    bx = by = 0.0
    row_h = 0.0
    for i, sheet in enumerate(order):
        if i and i % BLOCKS_ACROSS == 0:
            bx, by, row_h = 0.0, by + row_h + 4 * GAP, 0.0
        cs = sorted(by_sheet[sheet], key=lambda c: _refkey(c.ref))
        ics = [c for c in cs if c.ref[0] in "UY" or c.ref.startswith("SW")]
        rest = [c for c in cs if c not in ics]
        h = 0.0
        for group in (ics, rest):
            if not group:
                continue
            pos, gh = _pack([(c.ref, envelope(c.footprint)) for c in group],
                            BLOCK_W)
            for ref, (x, y) in pos.items():
                placed[ref] = (bx + x, by + h + y, 0)
            h += gh + GAP
        row_h = max(row_h, h)
        bx += BLOCK_W + 4 * GAP
    return placed


def bbox(c, pos):
    x0, y0, x1, y1 = envelope(c.footprint)
    x, y = pos[0], pos[1]
    return (x + x0, y + y0, x + x1, y + y1)


def overlaps(comps, placed):
    boxes = [(c.ref, bbox(c, placed[c.ref])) for c in comps]
    bad = []
    for i, (ra, a) in enumerate(boxes):
        for rb, b in boxes[i + 1:]:
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                bad.append((ra, rb))
    return bad


def outline(comps, placed):
    bs = [bbox(c, placed[c.ref]) for c in comps]
    return (min(b[0] for b in bs) - MARGIN, min(b[1] for b in bs) - MARGIN,
            max(b[2] for b in bs) + MARGIN, max(b[3] for b in bs) + MARGIN)


def build(netlist, out, proj):
    """Host side: place, then hand the plan to KiCad's python for pcbnew."""
    comps, nets = read_netlist(netlist)
    placed = place(comps)
    plan = {
        "libs": footprint_libs(proj),
        "comps": [dict(c._asdict(), pos=placed[c.ref]) for c in comps],
        "nets": [n._asdict() for n in nets],
        "outline": outline(comps, placed),
        "out": out,
    }
    plan_path = out + ".plan.json"
    with open(plan_path, "w") as f:
        json.dump(plan, f)
    subprocess.run([KICAD_PY, os.path.abspath(__file__), "--build-in-kicad",
                    plan_path], check=True)
    os.remove(plan_path)
    return out


def _build_in_kicad(plan_path):
    import pcbnew
    with open(plan_path) as f:
        plan = json.load(f)
    board = pcbnew.BOARD()
    nets = {}
    for n in plan["nets"]:
        ni = pcbnew.NETINFO_ITEM(board, n["name"])
        board.Add(ni)
        nets[n["name"]] = ni
    pin_net = {}
    for n in plan["nets"]:
        for ref, pin in n["nodes"]:
            pin_net[(ref, pin)] = n["name"]
    for c in plan["comps"]:
        lib, _, name = c["footprint"].partition(":")
        fp = pcbnew.FootprintLoad(plan["libs"][lib], name)
        if fp is None:
            raise SystemExit(f"{c['ref']}: {c['footprint']} not found")
        fp.SetReference(c["ref"])
        fp.SetValue(c["value"])
        fp.SetFPIDAsString(c["footprint"])
        fp.SetPath(pcbnew.KIID_PATH(c["path"]))
        x, y, rot = c["pos"]
        fp.SetPosition(pcbnew.VECTOR2I_MM(x, y))
        fp.SetOrientationDegrees(rot)
        board.Add(fp)
        for pad in fp.Pads():
            name = pin_net.get((c["ref"], pad.GetNumber()))
            if name:
                pad.SetNet(nets[name])
    x0, y0, x1, y1 = plan["outline"]
    rect = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_RECT)
    rect.SetStart(pcbnew.VECTOR2I_MM(x0, y0))
    rect.SetEnd(pcbnew.VECTOR2I_MM(x1, y1))
    rect.SetLayer(pcbnew.Edge_Cuts)
    rect.SetWidth(pcbnew.FromMM(0.1))
    board.Add(rect)
    pcbnew.SaveBoard(plan["out"], board, True)  # aSkipSettings: no .kicad_pro


def main(argv):
    if argv[:1] == ["--build-in-kicad"]:
        return _build_in_kicad(argv[1])
    proj = os.path.join(HERE, "..", "..", "dino_v0_0_2")
    if "--write" in argv:
        out = os.path.join(proj, "dino_v0_0_2.kicad_pcb")
    elif "-o" in argv:
        out = argv[argv.index("-o") + 1]
    else:
        print(__doc__)
        return 2
    net = export_netlist(proj, out + ".net")
    build(net, out, proj)
    os.remove(net)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
