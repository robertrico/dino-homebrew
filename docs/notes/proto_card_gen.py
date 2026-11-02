#!/usr/bin/env python3
"""`dino_proto/`: the prototype slot card, drawn. .git/sdd/PROTO_CARD.md.

    python3 docs/notes/proto_card_gen.py --write      the project, unrouted
    python3 docs/notes/proto_card_gen.py --route      Freerouting the fixed
                                                      block, DRC after

One table of parts and one of placements. From them, like bus_gen.py did
for card zero: the schematic (every pin on a global label, no wires), the
project file, the library tables, a project footprint library (the rows-
numbered 2x25 header, the rail hole strips, the perfboard grid) and the
PCB: outline with the finger tab, every footprint placed and netted, the
50 finger-to-J2 tracks, the rail bars, silk. Freerouting does the rest
(--route); its result is what lands on disk, the generator's output is
what the tests prove.

Geometry is card-local, mm, y down; the body's top-left is (BX, BY). The
finger centre FX follows from the Rev 1.0 mainboard file: the card's right
edge is OVERHANG past the mainboard's right edge, never more than 20 mm
(Rico, 2026-11-01), and the tab is where the socket is.
"""
import json
import os
import re
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bus_gen as bg  # noqa: E402
import power_sheet_gen as psg  # noqa: E402
from kicad_netlist import tokenize, parse, children, child  # noqa: E402

PROJECT = "dino_proto"
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
KICAD_APP = "/Applications/KiCad/KiCad.app/Contents"
KICAD_CLI = KICAD_APP + "/MacOS/kicad-cli"
KICAD_PY = KICAD_APP + "/Frameworks/Python.framework/Versions/Current/bin/python3"
STOCK_FP = KICAD_APP + "/SharedSupport/footprints"
NS = uuid.UUID("3b2f5c1e-7d84-4a6b-9e0f-5c2d1a8b7e64")   # dino_proto namespace


def uid(*key):
    return str(uuid.uuid5(NS, "/".join(map(str, key))))


# --- SECTION 1: the board (PROTO_CARD.md SECTION 1, 5b, 5c, 5d) ---------------
TAB_H = 7.8            # finger tab below the body, as Byte Hamr
TAB_W = 65.8
TAB_OVER_R = 18.0      # the body past the tab's RIGHT end: Rico's cap is 20 mm, measured
TAB_OVER_L = 108.0     # past the tab's left end: free; "just a bit longer" than cut 2 (177.8)
WIDTH = TAB_W + TAB_OVER_L + TAB_OVER_R     # 191.8
HEIGHT = 70.0          # Rico: a case height reservation
OVERHANG_CAP = 20.0    # past the mainboard's right edge, as well
CHAMFER = 0.635
BX, BY = 20.0, 20.0    # body top-left on the page
PITCH = 2.54

GRID_REF = "G"
GRID_DRILL = 1.0
GRID_PAD = 1.8
GRID_X0 = BX + 4.6                  # first column
GRID_Y0 = BY + 2.5                  # first row
GRID_COLS = 71                      # x 24.6 .. 202.4, short of the feed verticals
# rows, top to bottom: the three bias rails, then bands of [+5V, 5 free, GND]
ROW_RAIL = {0: "+12V", 1: "-12V", 2: "+3.3V",
            3: "+5V", 9: "GND", 10: "+5V", 16: "GND", 17: "+5V"}
GRID_ROWS = 21                      # rows 18-20 free: the band's three rows, joined to the grid
# the band's own rails, hole-less F.Cu traces between the lanes and the band
BAND_GND_Y, BAND_VCC_Y = 79.4, 78.0
LANE_Y = [74.9, 75.4, 75.9, 76.4, 76.9]              # the lane corridor, B.Cu (IO_SEL on F.Cu)
TRACK = 0.25           # the bus tracks
STUB_W = 0.4           # a band pad's stub to its rail (fits a 0.84 mm pad gap)
RAIL_W = {"GND": 1.5, "+5V": 1.2, "+12V": 0.6, "-12V": 0.6, "+3.3V": 0.6}   # a rail row's masked trace
FEED_W = {"GND": 0.9, "+5V": 0.7, "+12V": 0.6, "-12V": 0.6, "+3.3V": 0.6}   # feed runs and verticals
JOIN_W = 0.6           # J2 same-net joins where the geometry allows

# the vertical feeds, right margin (B.Cu), from J2 up; a via into each row
FEED_X = {"+12V": BX + WIDTH - 6.5, "-12V": BX + WIDTH - 5.4, "+3.3V": BX + WIDTH - 4.3,
          "+5V": BX + WIDTH - 3.2, "GND": BX + WIDTH - 2.1}
LEFT_TIE_X = {"GND": BX + 1.0, "+5V": BX + 2.6}       # the left ties, F.Cu / B.Cu
TIE_W = 0.8


def grid_holes():
    """[(x, y)] of every perfboard hole, rail rows excluded."""
    return [(GRID_X0 + c * PITCH, GRID_Y0 + r * PITCH)
            for r in range(GRID_ROWS) if r not in ROW_RAIL for c in range(GRID_COLS)]


def rail_rows():
    """[(ref, net, y, n_holes)] top to bottom; RBn in row order."""
    return [(f"RB{i + 1}", ROW_RAIL[r], GRID_Y0 + r * PITCH, GRID_COLS)
            for i, r in enumerate(sorted(ROW_RAIL))]


RAILS = [(ref, net) for ref, net, _, _ in rail_rows()]


def grid_rects():
    """The rule areas (no tracks, no vias, both layers): one per run of
    free rows. The bodge's copper, not the card's; the rail rows between
    runs are the card's."""
    m = PITCH / 2
    x1 = GRID_X0 + (GRID_COLS - 1) * PITCH + m
    out, run = [], []
    for r in range(GRID_ROWS + 1):
        if r in ROW_RAIL or r == GRID_ROWS:
            if run:
                out.append((GRID_X0 - m, GRID_Y0 + run[0] * PITCH - m, x1, GRID_Y0 + run[-1] * PITCH + m))
                run = []
        else:
            run.append(r)
    return out


J2_ROW_A_Y = 85.0      # pins 1-25, above the fingers; row B 2.54 above
J2_SHIFT = 1.27        # J2 columns sit 1.27 right of the finger columns
BAND_Y = 84.6          # the band's centre: on the bottom edge (pads 80.79 / 88.41)
BAND_X0 = BX + 5.5     # the band's left end

# --- SECTION 2: parts -----------------------------------------------------------
FP_J2 = "PinHeader_2x25_Rows_P2.54mm"
FP_RAIL = "RailHoles_1x%d_P2.54mm"
FP_GRID = "ProtoGrid_%d_P2.54mm"


# (ref, lib_id, value, footprint, description)
PARTS = [
    ("J1", f"{bg.LIB}:{bg.EDGE}", bg.EDGE, f"{bg.LIB}:{bg.FP_FINGERS}", "DINO peripheral bus"),
    ("J2", "Connector_Generic:Conn_02x25_Top_Bottom", "BUS_BREAKOUT", f"{PROJECT}:{FP_J2}",
     "the edge 1:1 on a 2x25 header: pin n = edge pin n, 50-way IDC"),
    ("U1", "74xx:74LS138", "74LS138", "Package_DIP:DIP-16_W7.62mm_Socket", "slot decode, as dino_serial U101"),
    ("JP1", "Connector_Generic:Conn_02x08_Odd_Even", "SLOT", "Connector_PinHeader_2.54mm:PinHeader_2x08_P2.54mm_Vertical",
     "shunt selector: ONE shunt, O_n to ~{CARD_SEL}"),
    ("U2", "74xx:74LS32", "74LS32", "Package_DIP:DIP-14_W7.62mm_Socket", "~{CARD_RD} ~{CARD_WR}; two gates spare on J4"),
    ("J3", "Connector_Generic:Conn_02x06_Odd_Even", "CARD", "Connector_PinHeader_2.54mm:PinHeader_2x06_P2.54mm_Vertical",
     "~{CARD_SEL} ~{CARD_RD} ~{CARD_WR} O0-O7 GND"),
    ("J4", "Connector_Generic:Conn_01x04", "SPARE32", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
     "the two spare '32 gates: B in, Y out, A pulled up"),
    ("R1", "Device:R", "4.7k", "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal", "~{CARD_SEL} pull-up"),
    ("R2", "Device:R", "4.7k", "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal", "spare gate 3 pull-up"),
    ("R3", "Device:R", "4.7k", "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal", "spare gate 4 pull-up"),
    ("C1", "Device:C", "100n", "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm", "U1 decoupling"),
    ("C2", "Device:C", "100n", "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm", "U2 decoupling"),
    ("C3", "Device:C_Polarized", "10u", "Capacitor_THT:CP_Radial_D5.0mm_P2.50mm", "+5V bulk at the edge"),
] + [(r, "Connector_Generic:Conn_01x01", f"RAIL {n}", f"{PROJECT}:{FP_RAIL % k}",
      f"rail row {n}") for r, n, _, k in rail_rows()]

O_PINS = ["15", "14", "13", "12", "11", "10", "9", "7"]      # 74LS138 O0..O7


def bus_name(pin):
    name, kind = next((n, k) for p, n, k in bg.BUS if p == pin)
    return f"SPARE{pin}" if kind == "spare" else name


# pin -> net, per part (J1/J2 from BUS)
def pin_nets():
    nets = {"J1": {str(p): bus_name(p) for p, _, _ in bg.BUS},
            "J2": {str(p): bus_name(p) for p, _, _ in bg.BUS},
            "U1": {"1": "M11", "2": "M12", "3": "M13", "4": "~{IO_SEL}", "5": "GND",
                   "6": "+5V", "8": "GND", "16": "+5V"},
            "JP1": {}, "U2": {}, "J3": {}, "J4": {},
            "R1": {"1": "~{CARD_SEL}", "2": "+5V"},
            "R2": {"1": "SP3A", "2": "+5V"},
            "R3": {"1": "SP4A", "2": "+5V"},
            "C1": {"1": "+5V", "2": "GND"}, "C2": {"1": "+5V", "2": "GND"},
            "C3": {"1": "+5V", "2": "GND"}}
    for n, p in enumerate(O_PINS):
        nets["U1"][p] = f"O{n}"
        nets["JP1"][str(2 * n + 1)] = f"O{n}"
        nets["JP1"][str(2 * n + 2)] = "~{CARD_SEL}"
    nets["U2"].update({"1": "~{CARD_SEL}", "2": "~{IO_RD_Q}", "3": "~{CARD_RD}",
                       "4": "~{CARD_SEL}", "5": "~{IO_WR}", "6": "~{CARD_WR}",
                       "9": "SP3A", "10": "SP3B", "8": "SP3Y",
                       "12": "SP4A", "13": "SP4B", "11": "SP4Y",
                       "14": "+5V", "7": "GND"})
    j3 = ["~{CARD_SEL}", "~{CARD_RD}", "~{CARD_WR}"] + [f"O{n}" for n in range(8)] + ["GND"]
    nets["J3"] = {str(i): n for i, n in enumerate(j3, 1)}
    nets["J4"] = {"1": "SP3B", "2": "SP3Y", "3": "SP4B", "4": "SP4Y"}
    for r, n in RAILS:
        nets[r] = {"1": n}
    return nets


# --- SECTION 3: the mainboard, read ---------------------------------------------
_GEO = {}


def mainboard_geometry(repo=REPO):
    """The Rev 1.0 socket column x and the board's right edge, from the
    PCB file (regex: the file is 5 MB and only two numbers are wanted)."""
    path = os.path.join(repo, "dino_v0_0_2", "dino_v0_0_2.kicad_pcb")
    if path in _GEO:
        return _GEO[path]
    with open(path) as f:
        s = f.read()
    m = re.search(r'\(footprint "%s:%s".*?\(property "Reference" "J1".*?\(at ([\d.\-]+) ([\d.\-]+)'
                  % (bg.LIB, bg.FP_SOCKET), s, re.S)
    sock = re.search(r'\(footprint "%s:%s"\s*(?:\(layer "[^"]*"\)\s*)?\(uuid "[^"]*"\)\s*\(at ([\d.\-]+) ([\d.\-]+)'
                     % (bg.LIB, bg.FP_SOCKET), s)
    xs = []
    for it in re.findall(r'\(gr_(?:line|rect|arc)\s.*?\(layer "Edge\.Cuts"\).*?\)\s*\)', s, re.S):
        xs += [float(x) for x, _ in re.findall(r'\((?:start|end|mid) ([\d.\-]+) ([\d.\-]+)\)', it)]
    socket_x = float((sock or m).group(1))
    _GEO[path] = {"socket_x": socket_x, "edge_x": max(xs)}
    return _GEO[path]


def card_span(repo=REPO):
    """(left, right) of the body in mainboard x: TAB_OVER_L / TAB_OVER_R
    past the tab (the tab is centred on the socket)."""
    sx = mainboard_geometry(repo)["socket_x"]
    return (sx - TAB_W / 2 - TAB_OVER_L, sx + TAB_W / 2 + TAB_OVER_R)


def finger_x(repo=REPO):
    """FX: the finger centre on the page."""
    left, _ = card_span(repo)
    return BX + (mainboard_geometry(repo)["socket_x"] - left)


# --- SECTION 4: the project library ---------------------------------------------

def _fp_head(name, descr, attr):
    return (f'(footprint "{name}"\n\t(version 20260206)\n\t(generator "proto_card_gen.py")\n'
            f'\t(layer "F.Cu")\n\t(descr {psg._q(descr)})\n\t(tags "DINO proto card")\n'
            '\t(property "Reference" "REF**"\n\t\t(at 0 -3 0)\n\t\t(layer "F.SilkS")\n'
            f'\t\t(uuid "{uid(name, "ref")}")\n'
            "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n"
            f'\t(property "Value" "{name}"\n\t\t(at 0 3 0)\n\t\t(layer "F.Fab")\n'
            f'\t\t(uuid "{uid(name, "val")}")\n'
            "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n"
            f"\t(attr {attr})\n")


def _fp_rect(name, layer, x0, y0, x1, y1, w):
    return (f"\t(fp_rect\n\t\t(start {x0:g} {y0:g})\n\t\t(end {x1:g} {y1:g})\n"
            f"\t\t(stroke\n\t\t\t(width {w})\n\t\t\t(type solid)\n\t\t)\n"
            f'\t\t(fill no)\n\t\t(layer "{layer}")\n\t\t(uuid "{uid(name, layer, x0, y0)}")\n\t)\n')


def _tht(name, num, x, y, size, drill, shape="circle"):
    return (f'\t(pad "{num}" thru_hole {shape}\n\t\t(at {x:.3f} {y:.3f})\n'
            f"\t\t(size {size:g} {size:g})\n\t\t(drill {drill:g})\n"
            '\t\t(layers "*.Cu" "*.Mask")\n\t\t(remove_unused_layers no)\n'
            f'\t\t(uuid "{uid(name, "pad", num)}")\n\t)\n')


def j2_footprint():
    """2x25 0.1in header numbered BY ROWS: 1-25 along row A (y 0), 26-50
    along row B (y -2.54), pin n+25 behind pin n. A 50-way IDC plug seats
    on it; conductor n is bus pin n only if the breadboard end is wired by
    these numbers, not by the odd/even habit."""
    name = FP_J2
    w = 25 * PITCH
    out = _fp_head(name, "2x25 0.1in pin header numbered by rows (1-25 front row, 26-50 "
                         "back row), DINO proto card J2: pin n = edge pin n.", "through_hole")
    out += _fp_rect(name, "F.CrtYd", -1.77, -4.31, w - PITCH + 1.77, 1.27, 0.05)
    out += _fp_rect(name, "F.Fab", -1.27, -3.81, w - PITCH + 1.27, 1.21, 0.1)
    out += _fp_rect(name, "F.SilkS", -1.33, -3.87, w - PITCH + 1.33, 1.27, 0.12)
    for n in range(1, 51):
        col = (n - 1) % 25
        y = 0.0 if n <= 25 else -PITCH
        out += _tht(name, n, col * PITCH, y, 1.7, 1.0, "rect" if n == 1 else "circle")
    return out + "\t(embedded_fonts no)\n)\n"


def rail_footprint(n):
    """n plated holes on 0.1in, all pad 1, SQUARE: a rail row. One net; the
    masked rail trace joins them. Square so the eye tells a rail hole from
    a grid hole before a chip pin lands in it."""
    name = FP_RAIL % n
    out = _fp_head(name, f"{n} square plated holes on 0.1in, all pad 1: a rail row.", "through_hole")
    L = (n - 1) * PITCH
    out += _fp_rect(name, "F.CrtYd", -1.0, -1.0, L + 1.0, 1.0, 0.05)
    out += _fp_rect(name, "F.Fab", -0.95, -0.95, L + 0.95, 0.95, 0.1)
    for i in range(n):
        out += _tht(name, 1, i * PITCH, 0.0, GRID_PAD, GRID_DRILL, "rect")
    return out + "\t(embedded_fonts no)\n)\n"


def grid_footprint():
    """The perfboard: every plated hole of grid_holes(), each pad its own
    number, no net, origin at the first hole. Board-only; the schematic
    does not know it. Courtyard: the top-left hole's cell only (the real
    shape is two rule areas; a courtyard the size of the grid would fight
    the rail rows that run through it)."""
    holes = grid_holes()
    name = FP_GRID % len(holes)
    out = _fp_head(name, f"perfboard, {len(holes)} plated holes, 0.1in, drill {GRID_DRILL} pad {GRID_PAD}.",
                   "through_hole")
    out += _fp_rect(name, "F.CrtYd", -1.2, -1.2, 1.2, 1.2, 0.05)
    out += _fp_rect(name, "F.Fab", -1.0, -1.0, 1.0, 1.0, 0.1)
    x0, y0 = holes[0]
    for k, (x, y) in enumerate(holes, 1):
        out += _tht(name, k, x - x0, y - y0, GRID_PAD, GRID_DRILL)
    return out + "\t(embedded_fonts no)\n)\n"


def write_library(proj):
    d = os.path.join(proj, PROJECT + ".pretty")
    os.makedirs(d, exist_ok=True)
    files = {FP_J2: j2_footprint(), FP_GRID % len(grid_holes()): grid_footprint()}
    for _, _, _, n in rail_rows():
        files[FP_RAIL % n] = rail_footprint(n)
    for name, txt in files.items():
        with open(os.path.join(d, name + ".kicad_mod"), "w") as f:
            f.write(txt)
    # footprints from earlier cuts go; hand-imported ones (hamr_*) stay
    for fn in os.listdir(d):
        if fn.endswith(".kicad_mod") and fn[:-10] not in files and not fn.startswith("hamr_"):
            os.remove(os.path.join(d, fn))


# --- SECTION 5: the schematic ---------------------------------------------------
ROOT_UUID = uid("root")
PATH = f"/{ROOT_UUID}"

# symbol placements on the A3 page (1.27 grid): ref -> (x, y) or per-unit list
SCH_AT = {
    "J1": (60.96, 101.6), "J2": (152.4, 101.6),
    "U1": (254.0, 63.5), "JP1": (309.88, 63.5),
    "U2": [(254.0, 118.11), (254.0, 143.51), (254.0, 168.91), (254.0, 194.31), (309.88, 156.21)],
    "J3": (355.6, 68.58), "J4": (355.6, 118.11),
    "R1": (330.2, 203.2), "R2": (355.6, 203.2), "R3": (381.0, 203.2),
    "C1": (139.7, 228.6), "C2": (165.1, 228.6), "C3": (190.5, 228.6),
}
for i, (r, _) in enumerate(RAILS):
    SCH_AT[r] = (60.96 + 25.4 * i, 254.0)


def _lib_pins(lib, name):
    """[(unit, number, x, y, rot)] of a stock symbol's pins (extends followed)."""
    with open(os.path.join(psg.SYM_DIR, lib + ".kicad_sym")) as f:
        tree = parse(tokenize(f.read()))
    for s in children(tree, "symbol"):
        if s[1] != name:
            continue
        ext = child(s, "extends")
        if ext:
            return _lib_pins(lib, ext[1])
        out = []
        for u in children(s, "symbol"):
            unit = int(u[1].rsplit("_", 2)[-2])
            for p in children(u, "pin"):
                at = child(p, "at")
                out.append((unit, child(p, "number")[1], float(at[1]), float(at[2]), int(float(at[3]))))
        return out
    raise KeyError(f"{lib}:{name}")


def _edge_pins():
    return [(1, str(p), *bg.pin_lib_xy(p), 0 if p <= 25 else 180) for p, _, _ in bg.BUS]


def _text(txt, x, y, key):
    """psg.text with a deterministic uuid."""
    q = psg._q(txt).replace("\n", "\\n")
    return (f'\t(text {q}\n\t\t(exclude_from_sim no)\n\t\t(at {x:g} {y:g} 0)\n'
            "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
            f"\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid \"{uid(key)}\")\n\t)\n")


def _label(name, x, y, pin_rot, key):
    rot = (pin_rot + 180) % 360
    return bg.global_label(name, round(x, 4), round(y, 4), rot, key)


def schematic():
    nets = pin_nets()
    lib_txt = ""
    with open(os.path.join(REPO, bg.LIB, bg.LIB + ".kicad_sym")) as f:
        blk = bg._extract(f.read(), bg.EDGE).replace(f'(symbol "{bg.EDGE}"', f'(symbol "{bg.LIB}:{bg.EDGE}"', 1)
    lib_txt += "\n".join("\t" + l if l else l for l in blk.splitlines()) + "\n"
    seen = set()
    for _, lib_id, *_ in PARTS[1:]:
        if lib_id in seen:
            continue
        seen.add(lib_id)
        lib, name = lib_id.split(":")
        lib_txt += psg.raw_symbol(lib, name)
    body = []
    for ref, lib_id, value, fp, descr in PARTS:
        if ref == "J1":
            pins = _edge_pins()
        else:
            lib, name = lib_id.split(":")
            pins = _lib_pins(lib, name)
        ats = SCH_AT[ref]
        units = sorted({u for u, *_ in pins})
        at_list = ats if isinstance(ats, list) else [ats]
        all_pins = sorted({n for _, n, *_ in pins}, key=lambda s: int(s))
        for unit, (x, y) in zip(units, at_list):
            body.append(bg._instance(lib_id, ref, value, x, y, all_pins, PATH, PROJECT, fp,
                                     unit=unit, descr=descr, key=f"{PROJECT}/{ref}"))
            for u, num, px, py, prot in pins:
                if u != unit:
                    continue
                net = nets[ref].get(num)
                sx, sy = x + px, y - py
                if net is None:
                    body.append(bg.no_connect(round(sx, 4), round(sy, 4), f"{PROJECT}/{ref}/nc/{num}"))
                else:
                    body.append(_label(net, sx, sy, prot, f"{PROJECT}/{ref}/label/{num}"))
    body.append(_text(
        "DINO PROTO CARD -- a perfboard with the bus edge and the slot decode every card repeats.\n"
        "Generated by docs/notes/proto_card_gen.py from bus_gen.BUS; design .git/sdd/PROTO_CARD.md.\n"
        "J1 edge: every pin by name. J2: the edge 1:1 on a 2x25 header (pin n = edge pin n), for a 50-way IDC.\n"
        "U1 '138 as dino_serial U101: A=M11-M13, E1=~{IO_SEL}, E2=GND, E3=+5V. O0-O7 = slots 0-7 = 0x4000+n*0x800.\n"
        "JP1: ONE shunt joins O_n to ~{CARD_SEL} (R1 4.7k up). Two shunts short two '138 outputs.\n"
        "U2 '32: ~{CARD_RD} = ~{CARD_SEL}|~{IO_RD_Q}, ~{CARD_WR} = ~{CARD_SEL}|~{IO_WR}; gates 3,4 spare on J4, A inputs pulled.\n"
        "J3: ~{CARD_SEL} ~{CARD_RD} ~{CARD_WR} O0-O7 GND. RB1-RB7: the rail bars (hole strips on the board).\n"
        "The card gives nothing back on any pin (CARD-2). +12V/-12V/+3.3V draw: none; the bodge declares its own.",
        15.24, 25.4, "note"))
    return (
        "(kicad_sch\n\t(version 20260306)\n\t(generator \"eeschema\")\n"
        "\t(generator_version \"10.0\")\n"
        f'\t(uuid "{ROOT_UUID}")\n\t(paper "A3")\n'
        "\t(title_block\n\t\t(title \"DINO proto card\")\n\t\t(date \"2026-11-01\")\n"
        "\t\t(rev \"0.1\")\n\t\t(comment 1 \"Prototype slot card: edge, slot decode, perfboard\")\n"
        "\t\t(comment 3 \"An 8-bit computer with 16-bit addressing and 16-bit control words\")\n"
        "\t\t(comment 4 \"A Turing-Complete 8-bit \\\"Computer\\\"\")\n\t)\n"
        "\t(lib_symbols\n" + lib_txt + "\t)\n"
        + "".join(body)
        + "\t(sheet_instances\n\t\t(path \"/\"\n\t\t\t(page \"1\")\n\t\t)\n\t)\n"
        "\t(embedded_fonts no)\n)\n")


def project_file(proj):
    with open(os.path.join(REPO, "dino_serial", "dino_serial.kicad_pro")) as f:
        pro = json.load(f)
    pro["meta"]["filename"] = PROJECT + ".kicad_pro"
    pro["sheets"] = [[ROOT_UUID, "Root"]]
    pro.setdefault("erc", {})["erc_exclusions"] = []
    cls = pro["net_settings"]["classes"][0]
    cls.update({"clearance": 0.2, "track_width": TRACK, "via_diameter": 0.8, "via_drill": 0.4})
    rules = pro["board"]["design_settings"]["rules"]
    rules.update({"min_clearance": 0.2, "min_track_width": 0.2, "min_copper_edge_clearance": 0.4,
                  "min_text_height": 0.7, "min_text_thickness": 0.1, "min_via_diameter": 0.6})
    pro["board"]["design_settings"].pop("drc_exclusions", None)
    with open(os.path.join(proj, PROJECT + ".kicad_pro"), "w") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")


def lib_tables(proj):
    with open(os.path.join(proj, "sym-lib-table"), "w") as f:
        f.write("(sym_lib_table\n\t(version 7)\n"
                f'\t(lib (name "{bg.LIB}") (type "KiCad") (uri "${{KIPRJMOD}}/../{bg.LIB}/{bg.LIB}.kicad_sym") (options "") (descr ""))\n'
                ")\n")
    with open(os.path.join(proj, "fp-lib-table"), "w") as f:
        f.write("(fp_lib_table\n\t(version 7)\n"
                f'\t(lib (name "{bg.LIB}") (type "KiCad") (uri "${{KIPRJMOD}}/../{bg.LIB}/{bg.LIB}.pretty") (options "") (descr ""))\n'
                f'\t(lib (name "{PROJECT}") (type "KiCad") (uri "${{KIPRJMOD}}/{PROJECT}.pretty") (options "") (descr ""))\n'
                ")\n")


# --- SECTION 6: the board -------------------------------------------------------

def outline(fx):
    """Edge.Cuts segments: body, then the tab below it, chamfered."""
    L, R, T, B = BX, BX + WIDTH, BY, BY + HEIGHT
    tl, tr, tb = fx - TAB_W / 2, fx + TAB_W / 2, B + TAB_H
    c = CHAMFER
    pts = [(L, T), (R, T), (R, B), (tr, B), (tr, tb - c), (tr - c, tb),
           (tl + c, tb), (tl, tb - c), (tl, B), (L, B)]
    return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


def placements(fx):
    """ref -> (x, y, rot, how): where the footprint's courtyard CENTRE goes,
    except J1/J2/RB*/G* which are placed by origin (their geometry is ours).
    The fixed band runs along the bottom above J2 (Rico, 2026-11-01: chips,
    DIPs and headers along the bottom), 0.6 mm between courtyards: C2 U2
    J4 JP1 C1 U1 J3; U2 by the strobe fingers (cols 3-4), U1 by M11-M13
    (cols 13-15), C1 left of U1 so nothing stands between U1 and J3. The
    pull-ups sit in the pockets beside J2."""
    x0 = fx - 12 * PITCH               # finger column 0
    holes = grid_holes()
    p = {"J1": (fx, BY + HEIGHT + TAB_H, 0, "origin"),
         "J2": (x0 + J2_SHIFT, J2_ROW_A_Y, 0, "origin"),
         "G1": (holes[0][0], holes[0][1], 0, "origin"),
         # left to right (courtyard widths: R 3.3, J4 3.5, J3 16.3, JP1 21.4,
         # C 3.6, DIP-16 20.9, DIP-14 18.4; 0.6 between): J3 R1 JP1 C1 U1 C2
         # U2 J4 R2 R3. Everything a part talks to is beside it; U1 and U2
         # take the six J2 signals on lanes under the band.
         "J3": (BAND_X0 + 8.15, BAND_Y, 90, "centre"),
         "R1": (BAND_X0 + 18.55, BAND_Y, 90, "centre"),
         "JP1": (BAND_X0 + 31.5, BAND_Y, 90, "centre"),
         "C1": (BAND_X0 + 44.6, BAND_Y, 90, "centre"),
         "U1": (BAND_X0 + 57.45, BAND_Y, 270, "centre"),    # pins 1-8 on the top row, pin 1 right
         "C2": (BAND_X0 + 70.3, BAND_Y, 90, "centre"),
         "U2": (BAND_X0 + 81.9, BAND_Y, 270, "centre"),     # pins 1-7 on the top row, pin 1 right
         "J4": (BAND_X0 + 93.45, BAND_Y, 0, "centre"),
         "R2": (BAND_X0 + 97.45, BAND_Y, 90, "centre"),
         "R3": (BAND_X0 + 101.35, BAND_Y, 90, "centre"),
         "C3": (x0 + 25 * PITCH + 4.4, 85.0, 0, "centre")}   # right pocket, by pins 25/50
    for ref, _, y, _ in rail_rows():
        p[ref] = (GRID_X0, y, 0, "origin")
    return p


def bus_tracks(fx):
    """Finger n straight up to J2 pin n (F.Cu), finger n+25 to pin n+25
    (B.Cu, between the row A pads). (layer, net, [(x, y), ...])."""
    x0 = fx - 12 * PITCH
    edge = BY + HEIGHT + TAB_H
    out = []
    for col in range(25):
        x = x0 + col * PITCH
        xa = x + J2_SHIFT
        front, back = bus_name(col + 1), bus_name(col + 26)
        out.append(("F.Cu", front, [(x, edge - 5.5), (x, J2_ROW_A_Y + 1.27), (xa, J2_ROW_A_Y)]))
        out.append(("B.Cu", back, [(x, edge - 5.5), (x, J2_ROW_A_Y - PITCH + 1.27), (xa, J2_ROW_A_Y - PITCH)]))
    return out


# J2 row-B pin that feeds each rail (all at J2's right end, so the runs are
# short and B.Cu under the band stays the router's) and the y of its run:
# the pin furthest right gets the lowest run and the rightmost vertical,
# so no stub crosses a run and no run crosses a vertical
FEED_PIN = {"+12V": 45, "-12V": 46, "+3.3V": 48, "+5V": 49, "GND": 50}
FEED_RUN_Y = {"+12V": 77.2, "-12V": 78.05, "+3.3V": 78.9, "+5V": 79.8, "GND": 80.85}


def feed_tracks(fx):
    """(layer, net, pts, width). B.Cu: each rail from its J2 row-B pin up
    to its run under the band, right to its vertical, up to its topmost
    row. Then the joins Freerouting cannot make (it connects to pads and
    its own wires, never to a seeded trace): J2's same-net pins to each
    other, and the pockets' power."""
    x0 = fx - 12 * PITCH
    yb = J2_ROW_A_Y - PITCH
    top = {}
    for _, net, y, _ in rail_rows():
        top[net] = min(top.get(net, y), y)
    out = []
    for net, pin_no in FEED_PIN.items():
        xp = x0 + (pin_no - 26) * PITCH + J2_SHIFT
        run, xv = FEED_RUN_Y[net], FEED_X[net]
        out.append(("B.Cu", net, [(xp, yb), (xp, run), (xv, run), (xv, top[net])], FEED_W[net]))

    def pin(n):
        return (x0 + ((n - 1) % 25) * PITCH + J2_SHIFT, J2_ROW_A_Y if n <= 25 else yb)
    # J2's +5V/GND pins. 2 up to 27 (F.Cu); 27 and 26 straight up on B.Cu
    # into a via on the band's +5V / GND rail (F.Cu, extended past J2's
    # first columns); 25 to 49 diagonal; 44 along y 80.1 (F.Cu) to 50, the
    # feed. 7, 16, 17 are the router's (pads).
    out.append(("F.Cu", "+5V", [pin(2), pin(27)], JOIN_W))
    out.append(("B.Cu", "+5V", [pin(27), (pin(27)[0], BAND_VCC_Y)], 0.5))
    out.append(("B.Cu", "GND", [pin(26), (pin(26)[0], BAND_GND_Y)], 0.5))
    out.append(("F.Cu", "+5V", [pin(25), pin(49)], TRACK))
    out.append(("F.Cu", "GND", [pin(44), (pin(44)[0], 80.1), (pin(50)[0], 80.1), pin(50)], 0.5))
    out.append(("F.Cu", "GND", [pin(16), pin(17)], JOIN_W))
    # the six J2-to-band signals as lanes above the band, drops on B.Cu so
    # nothing crosses the band's F.Cu rails. Row-B pins (M11-M13) rise on
    # B.Cu; row-A pins rise on F.Cu through the gap right of their column
    # (B.Cu there is the bus) into a via at y 81, then B.Cu. IO_SEL, whose
    # span nests badly with the others, rides F.Cu and drops through a via
    # at its pad column. On one layer, top to bottom, no lane below may
    # cover a lane's riser or pad (both cross the lanes below them). DIPs
    # at 270: top row pad k at centre - (k - 4.5) * 2.54 (DIP-16), centre
    # - (k - 4) * 2.54 (DIP-14), y BAND_Y - 3.81.
    u2c, u1c = BAND_X0 + 81.9, BAND_X0 + 57.45
    yp = BAND_Y - 3.81
    lanes = [("B.Cu", "M13", 41, u1c - (3 - 4.5) * PITCH, LANE_Y[0]),
             ("B.Cu", "M12", 40, u1c - (2 - 4.5) * PITCH, LANE_Y[1]),
             ("B.Cu", "M11", 39, u1c - (1 - 4.5) * PITCH, LANE_Y[2]),
             ("B.Cu", "~{IO_WR}", 5, u2c - (5 - 4) * PITCH, LANE_Y[3]),
             ("B.Cu", "~{IO_RD_Q}", 4, u2c - (2 - 4) * PITCH, LANE_Y[4]),
             ("F.Cu", "~{IO_SEL}", 3, u1c - (4 - 4.5) * PITCH, LANE_Y[3])]
    for layer, net, n, xpad, y in lanes:
        px, py = pin(n)
        if n <= 25:
            xr = px + J2_SHIFT
            if layer == "B.Cu":
                out.append(("F.Cu", net, [(px, py), (xr, py - J2_SHIFT), (xr, 81.0)], TRACK))
                out.append(("B.Cu", net, [(xr, 81.0), (xr, y), (xpad, y), (xpad, yp)], TRACK))
            else:
                out.append(("F.Cu", net, [(px, py), (xr, py - J2_SHIFT), (xr, y), (xpad, y)], TRACK))
                out.append(("B.Cu", net, [(xpad, y), (xpad, yp)], TRACK))
        else:
            out.append(("B.Cu", net, [(px, py), (px, y), (xpad, y), (xpad, yp)], TRACK))
    # C3 in the right pocket: +5V from pin 25 along y 85 to its pad 1, GND
    # down from the GND run to its pad 2 (CP_Radial P2.5: pads at -/+ 1.25)
    c3x = x0 + 25 * PITCH + 4.4
    out.append(("F.Cu", "+5V", [pin(25), (c3x - 1.25, 85.0)], STUB_W))
    out.append(("B.Cu", "GND", [(c3x + 1.25, FEED_RUN_Y["GND"]), (c3x + 1.25, 85.0)], STUB_W))
    return out


def rail_tracks(fx):
    """(layer, net, pts, w): each rail row as a masked trace, B.Cu through
    its square holes on to just short of the verticals, F.Cu from the
    first hole out to its vertical feed. Row 17's (+5V) F.Cu trace runs
    1.3 mm above the band's top pads: the band's VCC is one stub away;
    row 16 (GND) serves the GND pins the same way."""
    out = []
    xa = GRID_X0                         # every trace end lands on a hole or a via: no dangling ends
    for _, net, y, n in rail_rows():
        out.append(("B.Cu", net, [(xa, y), (GRID_X0 + (n - 1) * PITCH, y)], RAIL_W[net]))
        out.append(("F.Cu", net, [(xa, y), (FEED_X[net], y)], RAIL_W[net]))
    # the left ties (Rico, 2026-11-02: "+5V and GND loops"): GND on F.Cu at
    # x 21.0 and +5V on B.Cu at x 22.6, each through every row of its net
    # from the topmost down to the band's rail, with a jog onto each row's
    # first hole. Every GND/+5V row is then fed from both ends: a loop, not
    # a stub. The band's rails (F.Cu, hole-less) hang off the same ties and
    # run on past J2's first columns for pins 26 and 27.
    x0_ = fx - 12 * PITCH
    gnd_end = x0_ + J2_SHIFT                                      # pin 26's via
    vcc_end = x0_ + PITCH + J2_SHIFT                              # pin 27's via
    gnd_rows = [y for _, net, y, _ in rail_rows() if net == "GND"]
    vcc_rows = [y for _, net, y, _ in rail_rows() if net == "+5V"]
    out.append(("F.Cu", "GND", [(LEFT_TIE_X["GND"], min(gnd_rows)), (LEFT_TIE_X["GND"], BAND_GND_Y)], TIE_W))
    out.append(("F.Cu", "GND", [(LEFT_TIE_X["GND"], BAND_GND_Y), (gnd_end, BAND_GND_Y)], 0.6))
    for y in gnd_rows:
        out.append(("F.Cu", "GND", [(xa, y), (LEFT_TIE_X["GND"], y)], TIE_W))
    out.append(("B.Cu", "+5V", [(LEFT_TIE_X["+5V"], min(vcc_rows)), (LEFT_TIE_X["+5V"], BAND_VCC_Y)], TIE_W))
    for y in vcc_rows:
        out.append(("B.Cu", "+5V", [(xa, y), (LEFT_TIE_X["+5V"], y)], TIE_W))
    out.append(("F.Cu", "+5V", [(LEFT_TIE_X["+5V"], BAND_VCC_Y), (vcc_end, BAND_VCC_Y)], 0.6))
    return out


def rail_vias(fx=None):
    """(net, x, y): F.Cu row to B.Cu vertical at the feed; and the two
    GND joins at J2 (pin 44's column and pin 17's gap, y 80.15)."""
    out = [(net, FEED_X[net], y) for _, net, y, _ in rail_rows()]
    out.append(("+5V", LEFT_TIE_X["+5V"], BAND_VCC_Y))              # the left +5V tie onto the band rail
    if fx is not None:
        x0 = fx - 12 * PITCH
        out.append(("+5V", x0 + PITCH + J2_SHIFT, BAND_VCC_Y))       # pin 27
        out.append(("GND", x0 + J2_SHIFT, BAND_GND_Y))               # pin 26
        out.append(("~{IO_SEL}", BAND_X0 + 57.45 - (4 - 4.5) * PITCH, LANE_Y[3]))   # IO_SEL's drop
        for n in (4, 5):                                              # the row-A strobes' risers
            out.append((("~{IO_RD_Q}", "~{IO_WR}")[n - 4], x0 + (n - 1) * PITCH + J2_SHIFT + J2_SHIFT, 81.0))
    return out


RAIL_SHORT = {"+3.3V": "3V3", "+12V": "+12", "-12V": "-12", "+5V": "+5V", "GND": "GND"}


def silk(fx):
    """(layer, text, x, y, rot, size, justify)."""
    x0 = fx - 12 * PITCH
    out = []
    # one label per J2 column, front silk, "front/back": rotated 90 the
    # string reads upward, so its last word stands at the top, over the
    # back row (26-50), and its first word at the bottom, over the front
    # row: the label is a picture of the column (Rico, 2026-11-02). An F/B
    # key at the pin-1 end. Spares shorten to SPnn; +3.3V to 3V3.
    def short(n):
        name = bus_name(n)
        return name.replace("SPARE", "SP") if name.startswith("SPARE") else RAIL_SHORT.get(name, name)
    for col in range(25):
        x = x0 + col * PITCH + J2_SHIFT
        out.append(("F.SilkS", f"{short(col + 1)}/{short(col + 26)}", x, J2_ROW_A_Y - PITCH - 1.4, 90, 0.7, "left"))
    out.append(("F.SilkS", "F/B", x0 + J2_SHIFT - 2.3, J2_ROW_A_Y - PITCH - 1.4, 90, 0.7, "left"))
    # under JP1's digits, between the short W labels (cols 6-10)
    out.append(("F.SilkS", "ONE SHUNT", BAND_X0 + 31.5, 78.4, 0, 0.7, "centre"))
    # no legend line: the header pinouts live in dino_proto/README.md (Rico,
    # 2026-11-02: "this can belong in docs, not silkscreen")
    # the long legends on the back, under the band (the band has no back silk)
    out.append(("F.SilkS", "R1 SEL", BAND_X0 + 18.55, 78.4, 0, 0.7, "centre"))
    for c in range(0, GRID_COLS, 5):
        out.append(("F.SilkS", str(c + 1), GRID_X0 + c * PITCH, GRID_Y0 - 1.5, 0, 0.7, "centre"))
    xr = GRID_X0 + (GRID_COLS - 1) * PITCH + 2.1
    letter = 0
    for r in range(GRID_ROWS):
        y = GRID_Y0 + r * PITCH
        if r in ROW_RAIL:
            name = RAIL_SHORT[ROW_RAIL[r]]
            out.append(("F.SilkS", name, xr, y, 0, 0.7, "centre"))
            out.append(("F.SilkS", name, GRID_X0 - 2.3, y, 0, 0.7, "centre"))
        else:
            out.append(("F.SilkS", chr(ord("A") + letter), xr, y, 0, 0.7, "centre"))
            letter += 1
    return out


def export_netlist(proj, out):
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
                    "-o", out, os.path.join(proj, PROJECT + ".kicad_sch")], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read_netlist(path):
    with open(path) as f:
        tree = parse(tokenize(f.read()))
    comps, nets = {}, []
    for c in children(child(tree, "components"), "comp"):
        sp = child(c, "sheetpath")
        comps[child(c, "ref")[1]] = {
            "value": child(c, "value")[1], "footprint": child(c, "footprint")[1],
            "path": child(sp, "tstamps")[1].rstrip("/") + "/" + child(c, "tstamps")[1]}
    for n in children(child(tree, "nets"), "net"):
        nets.append({"name": child(n, "name")[1],
                     "nodes": [(child(x, "ref")[1], child(x, "pin")[1]) for x in children(n, "node")]})
    return comps, nets


def build_board(proj, repo=REPO):
    fx = finger_x(repo)
    net_path = os.path.join(proj, PROJECT + ".net")
    export_netlist(proj, net_path)
    comps, nets = read_netlist(net_path)
    os.remove(net_path)
    # kicad-cli's component order is not stable run to run; the board's is
    comps = dict(sorted(comps.items(), key=lambda kv: (kv[0].rstrip("0123456789"), int(kv[0].rstrip("0123456789") and kv[0][len(kv[0].rstrip("0123456789")):] or 0))))
    nets.sort(key=lambda n: n["name"])
    libs = {}
    for d in os.listdir(STOCK_FP):
        if d.endswith(".pretty"):
            libs[d[:-7]] = os.path.join(STOCK_FP, d)
    libs[bg.LIB] = os.path.join(repo, bg.LIB, bg.LIB + ".pretty")
    libs[PROJECT] = os.path.join(proj, PROJECT + ".pretty")
    place = placements(fx)
    descr_by_ref = {ref: d for ref, _, _, _, d in PARTS}
    plan = {
        "libs": libs, "out": os.path.join(proj, PROJECT + ".kicad_pcb"),
        "comps": [dict(ref=r, **c, place=place[r], descr=descr_by_ref.get(r, "")) for r, c in comps.items()],
        "board_only": [{"ref": "G1", "footprint": f"{PROJECT}:{FP_GRID % len(grid_holes())}",
                        "place": place["G1"]}],
        "nets": nets, "outline": outline(fx),
        "tracks": [(l, n, pts, TRACK) for l, n, pts in bus_tracks(fx)] + feed_tracks(fx) + rail_tracks(fx),
        "vias": rail_vias(fx), "keepouts": grid_rects(),
        "band": ["U1", "U2", "C1", "C2", "R1", "R2", "R3", "J3"],
        "rail_y": {"+5V": BAND_VCC_Y, "GND": BAND_GND_Y},
        "silk": silk(fx), "hide_ref": ["J1", "J2", "G1", "R1", "R2", "R3", "C1", "C2", "JP1", "J3", "J4"] + [r for r, _ in RAILS],
        "centre_ref": ["U1", "U2"],
    }
    plan_path = plan["out"] + ".plan.json"
    with open(plan_path, "w") as f:
        json.dump(plan, f)
    subprocess.run([KICAD_PY, os.path.abspath(__file__), "--build-in-kicad", plan_path], check=True)
    os.remove(plan_path)
    normalise_uuids(plan["out"])


SORTED_ITEMS = {"footprint", "segment", "arc", "via", "gr_line", "gr_arc", "gr_rect",
                "gr_poly", "gr_circle", "gr_text", "zone"}


def _top_level(s):
    """[(head, text)] of the items inside (kicad_pcb ...), strings respected."""
    i = s.index("(kicad_pcb") + len("(kicad_pcb")
    items, depth, start, in_str, j = [], 0, None, False, i
    while j < len(s):
        c = s[j]
        if in_str:
            if c == "\\":
                j += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            if depth == 0:
                start = j
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0 and start is not None:
                txt = s[start:j + 1]
                items.append((txt[1:].split(None, 1)[0], txt))
                start = None
            elif depth < 0:
                break
        j += 1
    return s[:i], items, s[j:]


def normalise_uuids(path):
    """pcbnew hands every item a random KIID and writes the file in KIID
    order; a rerun must be byte-identical. Items are re-sorted (footprints
    by reference, the rest by their content) and every uuid is rewritten
    in that order from the project namespace."""
    with open(path) as f:
        s = f.read()
    head, items, tail = _top_level(s)
    strip = re.compile(r'\(uuid "[0-9a-f-]{36}"\)')

    def key(item):
        kind, txt = item
        if kind == "footprint":
            ref = re.search(r'\(property "Reference" "([^"]*)"', txt).group(1)
            return ("footprint", ref.rstrip("0123456789"), int(ref[len(ref.rstrip("0123456789")):] or 0), "")
        return (kind, "", 0, strip.sub("", txt))
    fixed = [it for it in items if it[0] not in SORTED_ITEMS]
    moving = sorted((it for it in items if it[0] in SORTED_ITEMS), key=key)
    last_fixed = max((i for i, it in enumerate(items) if it[0] not in SORTED_ITEMS and it[0] != "embedded_fonts"), default=-1)
    # keep the header items where they were; sorted items follow; embedded_fonts stays last
    out_items = [it for it in fixed if it[0] != "embedded_fonts"] + moving + [it for it in fixed if it[0] == "embedded_fonts"]
    body = "".join("\n\t" + txt for _, txt in out_items)
    s = head + body + "\n)\n"
    n = [0]

    def sub(m):
        n[0] += 1
        return f'(uuid "{uid("pcb", n[0])}")'
    s = strip.sub(sub, s)
    with open(path, "w") as f:
        f.write(s)


def _build_in_kicad(plan_path):
    import pcbnew
    with open(plan_path) as f:
        plan = json.load(f)
    MM = pcbnew.VECTOR2I_MM
    board = pcbnew.BOARD()
    board.GetDesignSettings().SetCopperLayerCount(2)
    nets = {}
    for n in plan["nets"]:
        ni = pcbnew.NETINFO_ITEM(board, n["name"])
        board.Add(ni)
        nets[n["name"]] = ni
    pin_net = {(r, p): n["name"] for n in plan["nets"] for r, p in n["nodes"]}
    layer = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "F.SilkS": pcbnew.F_SilkS, "B.SilkS": pcbnew.B_SilkS}

    def seat(c, board_only=False):
        lib, _, name = c["footprint"].partition(":")
        fp = pcbnew.FootprintLoad(plan["libs"][lib], name)
        if fp is None:
            raise SystemExit(f"{c['ref']}: {c['footprint']} not found")
        fp.SetReference(c["ref"])
        fp.SetValue(c.get("value", name))
        fp.SetFPIDAsString(c["footprint"])
        if board_only:
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_BOARD_ONLY
                             | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        else:
            fp.SetPath(pcbnew.KIID_PATH(c["path"]))
        x, y, rot, how = c["place"]
        board.Add(fp)
        fp.SetOrientationDegrees(rot)
        if how == "centre":
            bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
            if bb.GetWidth() == 0:
                bb = fp.GetBoundingBox(False)
            cx, cy = pcbnew.ToMM(bb.GetCenter().x), pcbnew.ToMM(bb.GetCenter().y)
            fp.Move(MM(x - cx, y - cy))
        else:
            fp.SetPosition(MM(x, y))
        if c["ref"] in plan["hide_ref"]:
            fp.Reference().SetVisible(False)
        if c["ref"] in plan.get("centre_ref", []):
            bb = fp.GetBoundingBox(False, False)
            fp.Reference().SetPosition(bb.GetCenter())
            fp.Reference().SetTextAngleDegrees(0)
        if "descr" in c:
            fp.SetField("Description", c["descr"])
        for pad in fp.Pads():
            name = pin_net.get((c["ref"], pad.GetNumber()))
            if name:
                pad.SetNet(nets[name])
        return fp

    seated = {c["ref"]: seat(c) for c in plan["comps"]}
    for c in plan["board_only"]:
        seat(c, board_only=True)
    # the band's power: every +5V pad up to the +5V row (F.Cu), every GND
    # pad up to the GND row (B.Cu), straight or 1.27 to one side, whichever
    # column is clear of every other pad on the way
    y5, yg = plan["rail_y"]["+5V"], plan["rail_y"]["GND"]
    all_pads = [(pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y), p.GetNetname(),
                 pcbnew.ToMM(max(p.GetSize().x, p.GetSize().y)) / 2)
                for f in board.GetFootprints() for p in f.Pads()]
    for ref in plan["band"]:
        for pad in seated[ref].Pads():
            net = pad.GetNetname()
            if net not in ("+5V", "GND"):
                continue
            px, py = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
            # both rails are F.Cu above the band; GND is the nearer, reached on
            # F.Cu; +5V lies beyond it, reached on B.Cu with a via onto it
            ry, lay = (y5, "B.Cu") if net == "+5V" else (yg, "F.Cu")
            for x in (px, px + 1.27, px - 1.27):
                blocked = any(abs(qx - x) < qr + STUB_W / 2 + 0.2 + 0.02 and ry - 0.6 < qy < py - 0.1
                              and qn != net for qx, qy, qn, qr in all_pads)
                if not blocked:
                    pts = [(px, py)] if x == px else [(px, py), (x, py - 1.27)]
                    plan["tracks"].append((lay, net, pts + [(x, ry)], STUB_W))
                    if lay == "B.Cu":
                        plan["vias"].append((net, x, ry))
                    break
            else:
                raise SystemExit(f"{ref} pad {pad.GetNumber()} [{net}]: no clear column to its rail")
    # JP1: the slot number beside each row-A pad, on the side away from row B
    jp1 = seated["JP1"]
    pa = {p.GetNumber(): p.GetPosition() for p in jp1.Pads()}
    away = -1.0 if pa["1"].y < pa["2"].y else 1.0
    for n in range(8):
        pos = pa[str(2 * n + 1)]
        plan["silk"].append(("F.SilkS", str(n), pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y) + away * 2.55, 0, 0.8, "centre"))
    for (x0, y0), (x1, y1) in plan["outline"]:
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(MM(x0, y0))
        s.SetEnd(MM(x1, y1))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(pcbnew.FromMM(0.1))
        board.Add(s)
    for lay, net, pts, w in plan["tracks"]:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(MM(x0, y0))
            t.SetEnd(MM(x1, y1))
            t.SetWidth(pcbnew.FromMM(w))
            t.SetLayer(layer[lay])
            t.SetNet(nets[net])
            board.Add(t)
    for i, (x0, y0, x1, y1) in enumerate(plan["keepouts"]):
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowZoneFills(True)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetLayerSet(pcbnew.LSET.AllCuMask(2))
        z.SetZoneName(f"perfboard{i + 1}")
        pts = z.Outline()
        pts.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            pts.Append(MM(x, y))
        board.Add(z)
    for net, x, y in plan["vias"]:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(MM(x, y))
        v.SetDrill(pcbnew.FromMM(0.4))
        v.SetWidth(pcbnew.FromMM(0.8))
        v.SetNet(nets[net])
        board.Add(v)
    for lay, text, x, y, rot, size, just in plan["silk"]:
        tx = pcbnew.PCB_TEXT(board)
        tx.SetText(text)
        tx.SetLayer(layer[lay])
        tx.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
        tx.SetTextThickness(pcbnew.FromMM(0.12))
        tx.SetHorizJustify({"right": pcbnew.GR_TEXT_H_ALIGN_RIGHT, "left": pcbnew.GR_TEXT_H_ALIGN_LEFT,
                            "centre": pcbnew.GR_TEXT_H_ALIGN_CENTER}[just])
        if lay == "B.SilkS":
            tx.SetMirrored(True)
        tx.SetTextAngleDegrees(rot)
        tx.SetPosition(MM(x, y))
        board.Add(tx)
    pcbnew.SaveBoard(plan["out"], board, True)


# --- SECTION 7: routing the fixed block ----------------------------------------
FREEROUTING = os.path.expanduser("~/Development/tools/freerouting/freerouting-2.4.1.jar")
JAVA = "/opt/homebrew/opt/openjdk@25/bin/java"


def route(proj, passes=40):
    """Freerouting on the generated board: the bus tracks and bars are
    seeded and never ripped up (memory: a seeded DSN keeps its wires); the
    router adds the fixed block's ~40 connections. The result replaces the
    board file, canonicalised like the generator's. Returns the DRC
    (violations, unconnected)."""
    pcb = os.path.join(proj, PROJECT + ".kicad_pcb")
    dsn, ses = pcb[:-10] + ".dsn", pcb[:-10] + ".ses"
    subprocess.run([KICAD_PY, os.path.abspath(__file__), "--dsn", pcb, dsn], check=True)
    log = pcb[:-10] + ".freerouting.log"
    with open(log, "w") as f:
        subprocess.run([JAVA, "-Djava.awt.headless=true", "-jar", FREEROUTING,
                        "-de", dsn, "-do", ses, "-mp", str(passes), "-mt", "4"],
                       stdout=f, stderr=subprocess.STDOUT, check=False)
    if not os.path.exists(ses):
        raise SystemExit(f"Freerouting wrote no session; see {log}")
    subprocess.run([KICAD_PY, os.path.abspath(__file__), "--ses", pcb, ses], check=True)
    for f in (dsn, ses, log):
        os.remove(f)
    normalise_uuids(pcb)
    rep = pcb[:-10] + ".drc.json"
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "--severity-error", "-o", rep, pcb],
                   capture_output=True)
    with open(rep) as f:
        d = json.load(f)
    os.remove(rep)
    return ([(v["type"], [i["description"] for i in v["items"]]) for v in d["violations"]],
            d["unconnected_items"])


def _dsn(pcb, dsn):
    import pcbnew
    pcbnew.GetSettingsManager().LoadProject(pcb[:-10] + ".kicad_pro")   # the netclasses
    b = pcbnew.LoadBoard(pcb)
    print("dsn", pcbnew.ExportSpecctraDSN(b, dsn))


def _ses(pcb, ses):
    import pcbnew
    pcbnew.GetSettingsManager().LoadProject(pcb[:-10] + ".kicad_pro")
    b = pcbnew.LoadBoard(pcb)
    print("ses", pcbnew.ImportSpecctraSES(b, ses), "tracks", len(b.GetTracks()))
    pcbnew.SaveBoard(pcb, b, True)


# --- SECTION 8: the pass ---------------------------------------------------------

def write(dst, repo=REPO):
    """The whole project into dst/dino_proto/ (dst may be a temp dir with a
    copy of dino_bus/ beside it)."""
    proj = os.path.join(dst, PROJECT)
    os.makedirs(proj, exist_ok=True)
    write_library(proj)
    with open(os.path.join(proj, PROJECT + ".kicad_sch"), "w") as f:
        f.write(schematic())
    project_file(proj)
    lib_tables(proj)
    build_board(proj, repo)
    return proj


def hand_edited(board_text):
    """True when the board on disk carries text or footprints the generator
    never draws (Rico's KiCad edits, 2026-11-02 on: a title block, the
    Byte Hamr logo). The generator is frozen then, like card zero's."""
    fx = finger_x(REPO)
    mine = {t for _, t, *_ in silk(fx)} | {str(n) for n in range(8)}
    texts = set(re.findall(r'\(gr_text "((?:[^"\\]|\\.)*)"', board_text))
    refs = set(re.findall(r'\(property "Reference" "([^"]+)"', board_text))
    known = {r for r, *_ in PARTS} | {"G1"}
    return bool(texts - mine) or bool(refs - known)


def main(argv):
    if argv[:1] == ["--build-in-kicad"]:
        return _build_in_kicad(argv[1])
    if argv[:1] == ["--dsn"]:
        return _dsn(argv[1], argv[2])
    if argv[:1] == ["--ses"]:
        return _ses(argv[1], argv[2])
    if "--write" in argv:
        pcb = os.path.join(REPO, PROJECT, PROJECT + ".kicad_pcb")
        if os.path.exists(pcb) and "--force" not in argv:
            with open(pcb) as f:
                board = f.read()
            if hand_edited(board):
                print(f"{pcb}: hand edits present (text or footprints the generator did not draw); "
                      "--write would discard them. Rerun with --force to overwrite.")
                return 1
        print("wrote", write(REPO))
        return 0
    if "--route" in argv:
        i = argv.index("--route")
        passes = int(argv[i + 1]) if len(argv) > i + 1 else 40
        v, u = route(os.path.join(REPO, PROJECT), passes)
        print("violations", len(v), "unconnected", len(u))
        for x in v:
            print(" ", x)
        return 1 if v or u else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
