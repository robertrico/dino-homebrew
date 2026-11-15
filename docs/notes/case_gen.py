#!/usr/bin/env python3
"""The DINO case, generated from the Rev 1.0 PCB. Rev 1: a box.

    ~/.venvs/dino-cad/bin/python docs/notes/case_gen.py [--variant plain]
                                    [--power atx|pico|none] [--out case/gen]
    make case                      # the same, defaults
    make case-test                 # test_case_gen.py, solids included

Reads `dino_v0_0_2/dino_v0_0_2.kicad_pcb` READ-ONLY for the outline, H1-H5,
the slots J1-J8 and the power header J9, and `proto_card_gen.py` for the
card envelope. Writes one STEP of the whole tray and lid, and one STL + STEP
per printable piece, cut on seams to fit a Prusa Core One bed and joined
with 1.75 mm filament dowels and glue.

Frame: X = board x, Y = BOARD_H - board y (Y up), Z up from the underside
of the floor. IBM PC order (Rico, 2026-11-05): the BACK wall (X max) faces
the board's right edge (x 298.85), where the slot cards' outboard ends
point; it is the expansion area (keyboard, video, serial: one tall cutout
per slot). The FRONT (X min) is a picture frame on all four sides, after
Rico's 2026-11-06 sketch (a 70s sports-car grille): a flat rim, a
BEVEL_DEG bevel IN, a flat ledge (the inset lip), a square step, then the
flat recessed panel (the brand from docs/brand, the 8 OB LEDs top right) at the old wall plane, so nothing
moves toward the board. A second bevel, EDGE_CH at 45 deg, takes off
the face's outer edges. The lid sits flush with the front frame; a long
shallow roof bevel (LID_BEV_D over LID_BEV_R) runs down the sides and the
back, the frame's top included. The frame is FRONT_D deep and runs the full case
height; the lid butts it from behind. The board's bottom edge (KiCad y 270, J9) faces the SIDE wall
(Y min); power enters there. Both side walls carry 6 intake slots
toward the front, Apple IIe style.

Variants (Rico, 2026-11-05): `plain`, the box; `panel`, the flippy
Altair-style front panel, named and not built (its board is not drawn).

Numbers below are design choices unless a source is named. OPEN: the
Sullins EBC25DCWN standing height (SOCKET_TOP is the ~10 mm of
test_pcb_envelope's note, not a datasheet read).
"""
import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import proto_card_gen as pc                       # noqa: E402
from test_pcb_envelope import load_footprints, PCB   # noqa: E402

VARIANTS = ("plain", "panel")
POWERS = ("atx", "pico", "none")

# --- board (read from the PCB at import; asserted by test_case_gen) -------
def _edge_rect(path=PCB):
    import re
    txt = open(path).read()
    m = re.search(r'\(gr_rect\s+\(start ([-\d.]+) ([-\d.]+)\)\s+\(end ([-\d.]+) ([-\d.]+)\)'
                  r'(?:(?!\(gr_).)*?\(layer "Edge.Cuts"\)', txt, re.S)
    x0, y0, x1, y1 = map(float, m.groups())
    return x0, y0, x1, y1


_BX0, _BY0, _BX1, _BY1 = _edge_rect()
BOARD_W = _BX1 - _BX0
BOARD_H = _BY1 - _BY0
PCB_T = 1.6

# --- case design choices ---------------------------------------------------
WALL = 6.0            # walls: a 2 mm dowel keeps 2 mm each side (Rico, 2026-11-06: 4 was thin)
FLOOR = 8.0           # takes the walls' tabs; with RIM 14 it keeps the brand panel exact
LID_T = 8.0           # thick enough to carry the roof bevel; solid
LID_BEV_D = 6.0       # roof bevel, sides and back (Rico, 2026-11-06): drop ...
LID_BEV_R = 30.0      # ... over this run, ~11 deg: long and shallow
LID_LAND = LID_T - LID_BEV_D  # square edge left under the bevel
CLEAR = 3.0           # board / card envelope to inner wall
STANDOFF_H = 8.0      # floor to board underside: THT leads + air
STANDOFF_OD = 8.0
INSERT_D = 4.0        # M3 heat-set insert (Ruthex M3 x 5.7: 4.0 mm hole)
INSERT_DEPTH = 6.0
SOCKET_TOP = 10.0     # OPEN: socket standing height, board top to card body
TOP_CLEAR = 10.0      # card top to underside of lid
LIP_H = 5.0           # lid lip into the tray
LIP_W = 2.0
LIP_GAP = 0.4
SLOT_CUT_W = 14.0     # DE-15 on end (12.5 shell) or mini-DIN (13 dia) passes
SLOT_CUT_Z0 = 6.0     # above the socket top
SLOT_CUT_TOP = 6.0    # below the wall top
MIN_BAR = 6.0
FINGERS = 7           # box joint bands at each vertical corner (odd: sides own both ends)
TAB_W = 20.0          # wall tabs through slots in the floor
TAB_PITCH = 60.0
RIM = 14.0            # flat rim round the front face (12 before the 6 mm walls)
BEVEL_DEG = 40.0      # bevel to the face plane (sketch: 30-40)
BEVEL_D = 22.0        # bevel depth
LEDGE = 2.0           # the inset lip: flat ledge where the bevel ends
STEP_D = 8.0                  # square step from the ledge to the panel's face
PLATE_T = 3.0                 # the brand plate, printed face up, glued on the wall
PLATE_GAP = 0.2               # glue gap round the plate in its seat
FRONT_D = BEVEL_D + STEP_D + PLATE_T   # front frame depth: face to the wall
VENT_W = 3.0                  # side intakes, after the Apple IIe: narrow,
VENT_H = 40.0                 #   tall, vertical, round ends
VENT_PITCH = 9.0
VENT_N = 6                    # per side wall
VENT_X0 = 20.0                # first slot's edge from the inner front wall
VENT_Z0 = 30.0                # slot bottom above the case underside
LED_D = 5.2                   # 5 mm LED, snug bore
LED_PITCH = 10.0
BRAND_PANEL = "A"             # docs/brand panel: bus bottom to top orange, grey, black
EDGE_CH = 4.0                 # 45 deg chamfer round the face's outer edges
ATX_W, ATX_H = 60.0, 24.0     # 24-pin Mini-Fit plug passes through
DCJACK_D = 12.0               # 5.5/2.1 panel jack
POWER_Z0 = 6.0                # above the floor
PIN_D = 2.0                   # 1.75 filament dowel
PIN_DEPTH = 8.0               # each side of a seam
PIN_PITCH = 40.0
SEAM_KEEP = 3.0               # seam stays this far from holes and cutouts

# Prusa Core One build volume (250 x 220 x 270), less a margin
BED = (250.0, 220.0, 270.0)
BED_MARGIN = 5.0


def fits_bed(dx, dy, dz):
    bx, by, bz = (b - BED_MARGIN for b in BED)
    flat = (dx <= bx and dy <= by) or (dx <= by and dy <= bx)
    return flat and dz <= bz


def board_facts():
    fps = {f["ref"]: f for f in load_footprints()}

    def to_case(f):
        return (f["x"] - _BX0, BOARD_H - (f["y"] - _BY0))

    holes = {r: to_case(f) for r, f in fps.items()
             if r.startswith("H") and "MountingHole" in f["fp"]}
    slots = {r: to_case(f) for r, f in fps.items() if "EdgeSocket" in f["fp"]}
    return {"w": BOARD_W, "h": BOARD_H, "holes": holes, "slots": slots,
            "power": to_case(fps["J9"]), "ob_header": to_case(fps["J11"])}


BRAND_DIR = os.path.join(os.path.dirname(HERE), "brand", "out")


def brand_panel(order=None):
    """The front panel from docs/brand/build.py (its SVG, mm, y down, as seen
    from the front): size, the emboss groups by colour with their heights
    (the group ids carry them: orange_plus0.6mm), and the OB LED guides."""
    import re
    path = os.path.join(BRAND_DIR, f"dino_front_panel_{order or BRAND_PANEL}.svg")
    txt = open(path).read()
    w, h = (float(v) for v in re.search(r'width="([\d.]+)mm" height="([\d.]+)mm"', txt).groups())
    groups = {}
    for name, hh, fill, d in re.findall(
            r'<g id="(\w+)_plus([\d.]+)mm"><path fill-rule="evenodd" fill="(#\w+)" d="([^"]+)"', txt):
        groups[name] = {"h": float(hh), "fill": fill, "d": d}
    guide = txt[txt.index('<g id="guide_OB_LEDs">'):]
    pts = sorted(((float(x), float(y)) for x, y in
                  re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', guide)), reverse=True)
    leds = {f"OB{k}": p for k, p in enumerate(pts)}          # OB0 rightmost, as drawn
    return {"w": w, "h": h, "groups": groups, "leds": leds, "path": path}


def panel_to_case(L, x, y):
    """Brand panel (x right, y down, seen from the front) -> case (Y, Z) on
    the recessed panel. Seen from the front, right is -Y."""
    b = brand_panel()
    py0, pz0, py1, pz1 = L["front"]["panel"]
    oy, oz = ((py1 - py0) - b["w"]) / 2, ((pz1 - pz0) - b["h"]) / 2
    return py1 - oy - x, pz1 - oz - y


def cut_span(c, axis):
    """(lo, hi) of a cutout along x or y."""
    half = {"x": c["dx"] / 2, "y": c["dy"] / 2}[axis]
    mid = c[axis]
    return mid - half, mid + half


def _pick_seams(lo, hi, forbid, max_piece):
    """Seams in (lo, hi) so every piece <= max_piece, none inside forbid.
    Even split first, then slide each seam to the nearest legal spot."""
    n = math.ceil((hi - lo) / max_piece)
    seams = []
    for k in range(1, n):
        ideal = lo + (hi - lo) * k / n
        best = None
        for step in range(0, 2000):
            for s in (ideal + step * 0.5, ideal - step * 0.5):
                if any(a < s < b for a, b in forbid):
                    continue
                best = s
                break
            if best is not None:
                break
        seams.append(round(best, 2))
    edges = [lo] + seams + [hi]
    for a, b in zip(edges, edges[1:]):
        if b - a > max_piece:
            raise ValueError(f"seam search failed: piece {b - a:.1f} > {max_piece}")
    return seams


def finger_bands(L):
    """The box joints' bands, floor top to wall top: even ones are the side
    walls', odd ones the back's or the front's."""
    a, b = FLOOR, L["z"]["interior_top"]
    h = (b - a) / FINGERS
    return [(a + k * h, b if k == FINGERS - 1 else a + (k + 1) * h) for k in range(FINGERS)]


def floor_tabs(L):
    """(panel, (x0, y0, x1, y1)): each wall's tabs, z 0..FLOOR, under its own
    footprint, clear of the corners and of the seams."""
    ox0, oy0, ox1, oy1 = L["outer"]
    ix0, iy0, ix1, iy1 = L["interior"]
    keep = 5.0

    def along(lo, hi, seams):
        lo, hi = lo + WALL + keep + TAB_W / 2, hi - WALL - keep - TAB_W / 2
        n = int((hi - lo) // TAB_PITCH) + 1
        start = lo + (hi - lo - (n - 1) * TAB_PITCH) / 2
        return [c for c in (start + k * TAB_PITCH for k in range(n))
                if all(abs(c - s) > keep + TAB_W / 2 for s in seams)]
    out = []
    for panel, (ya, yb) in (("side", (oy0, iy0)), ("side_far", (iy1, oy1))):
        out += [(panel, (c - TAB_W / 2, ya, c + TAB_W / 2, yb))
                for c in along(ox0, ox1, L["seams_x"])]
    for panel, (xa, xb) in (("back", (ix1, ox1)), ("front", (ox0, ix0))):
        out += [(panel, (xa, c - TAB_W / 2, xb, c + TAB_W / 2))
                for c in along(oy0, oy1, L["seams_y"])]
    return out


def layout(variant="plain", power="atx"):
    if variant not in VARIANTS:
        raise ValueError(f"variant {variant!r}: one of {VARIANTS}")
    if power not in POWERS:
        raise ValueError(f"power {power!r}: one of {POWERS}")
    if variant == "panel":
        raise NotImplementedError("panel: the front-panel board is not drawn yet")

    b = board_facts()
    card_right = max(sx + pc.TAB_W / 2 + pc.OVERHANG_CAP for sx, _ in b["slots"].values())
    ix0, iy0 = -CLEAR, -CLEAR
    ix1 = max(b["w"], card_right) + CLEAR
    iy1 = b["h"] + CLEAR

    z = {"floor_top": FLOOR}
    z["board_bot"] = FLOOR + STANDOFF_H
    z["board_top"] = z["board_bot"] + PCB_T
    z["card_top"] = z["board_top"] + SOCKET_TOP + pc.HEIGHT
    z["interior_top"] = z["card_top"] + TOP_CLEAR      # = tray wall top
    ox0, oy0, ox1, oy1 = ix0 - WALL, iy0 - WALL, ix1 + WALL, iy1 + WALL

    cutouts = []
    for ref, (sx, sy) in sorted(b["slots"].items()):
        cutouts.append({"kind": "slot", "ref": ref, "wall": "back",
                        "x": ix1 + WALL / 2, "y": sy, "dx": WALL + 2, "dy": SLOT_CUT_W,
                        "z0": z["board_top"] + SOCKET_TOP + SLOT_CUT_Z0,
                        "z1": z["interior_top"] - SLOT_CUT_TOP})
    px = b["power"][0]
    if power == "atx":
        cutouts.append({"kind": "atx", "ref": "J9", "wall": "side",
                        "x": px, "y": iy0 - WALL / 2, "dx": ATX_W, "dy": WALL + 2,
                        "z0": FLOOR + POWER_Z0, "z1": FLOOR + POWER_Z0 + ATX_H})
    elif power == "pico":
        zc = FLOOR + POWER_Z0 + DCJACK_D / 2 + 10
        cutouts.append({"kind": "dcjack", "ref": "J9", "wall": "side", "round": True,
                        "x": px, "y": iy0 - WALL / 2, "dx": DCJACK_D, "dy": WALL + 2,
                        "z0": zc - DCJACK_D / 2, "z1": zc + DCJACK_D / 2})

    # side intakes (Rico, 2026-11-06): 6 per side wall, Apple IIe style,
    # toward the front; air leaves through the slot cutouts at the back
    for wall, wy in (("side", iy0 - WALL / 2), ("side_far", iy1 + WALL / 2)):
        for k in range(VENT_N):
            cutouts.append({"kind": "vent", "ref": f"{wall}_{k}", "wall": wall, "slot": True,
                            "x": ix0 + VENT_X0 + VENT_W / 2 + k * VENT_PITCH, "y": wy,
                            "dx": VENT_W, "dy": WALL + 2, "z0": VENT_Z0, "z1": VENT_Z0 + VENT_H})

    top = z["interior_top"]
    full = top + LID_T
    bevel_w = BEVEL_D / math.tan(math.radians(BEVEL_DEG))

    def rect(d):                                   # (y0, z0, y1, z1), inset d
        return (oy0 + d, d, oy1 - d, full - d)
    # panel_x: the wall face the plate glues to; plate_x: the plate's face
    front = {"edge_x": ox0 - FRONT_D, "panel_x": ox0, "plate_x": ox0 - PLATE_T,
             "bevel_w": bevel_w,
             "face": rect(0.0), "opening": rect(RIM), "bevel_end": rect(RIM + bevel_w),
             "panel": rect(RIM + bevel_w + LEDGE),
             "seat": rect(RIM + bevel_w + LEDGE - PLATE_GAP)}
    # OB LEDs: exactly where the brand spec draws them (top right, above the
    # bus); the bores come from the panel SVG's guides. Facing the front (looking +X) right is
    # -Y: OB0 rightmost, a byte as it reads.
    for ref, (gx, gy) in sorted(brand_panel()["leds"].items()):
        y, zc = panel_to_case({"front": front}, gx, gy)
        cutouts.append({"kind": "led", "ref": ref, "wall": "front", "round": True,
                        "x": ox0 + (WALL - PLATE_T) / 2, "y": y, "dx": WALL + PLATE_T + 2,
                        "dy": LED_D,
                        "z0": zc - LED_D / 2, "z1": zc + LED_D / 2})
    bbox = (front["edge_x"], oy0, ox1, oy1)

    def forbid(axis):
        out = []
        for hx, hy in b["holes"].values():
            h = hx if axis == "x" else hy
            r = STANDOFF_OD / 2 + SEAM_KEEP
            out.append((h - r, h + r))
        for c in cutouts:
            lo, hi = cut_span(c, axis)
            out.append((lo - SEAM_KEEP, hi + SEAM_KEEP))
        # never a seam in a wall's own thickness, or across a corner
        lo_o, hi_o = (ox0, ox1) if axis == "x" else (oy0, oy1)
        out += [(lo_o - 1, lo_o + WALL + PIN_PITCH / 4), (hi_o - WALL - PIN_PITCH / 4, hi_o + 1)]
        return out

    bx, by = BED[0] - BED_MARGIN, BED[1] - BED_MARGIN
    # long side of the case on the bed's long side
    # the frame is its own pieces, so the tray and lid start behind it
    seams_x = _pick_seams(ox0, ox1, forbid("x"), bx)
    seams_y = _pick_seams(oy0, oy1, forbid("y"), by)

    # Parted for glue (Rico, 2026-11-06). Each piece names how it prints;
    # size is (bed footprint, height) in that pose. The frame and the plate
    # print face up (back on the bed): neither has an overhang that way.
    # The tray is flat panels, never a corner of floor + two walls (Rico,
    # 2026-11-06: more printing, less risk). The floor has the full
    # footprint, quartered; the walls stand on it, printed flat, outside
    # down. Side walls run the full length, back and front between them.
    # Corners are box joints (Rico, 2026-11-06: thicker walls, interlocking
    # corners), the walls stand on the floor with tabs through it. "cuts"
    # are the boxes a piece takes out of the whole, "less" what it leaves
    # (x0, y0, z0, x1, y1, z1).
    pieces = []
    xs, ys = [ox0] + seams_x + [ox1], [oy0] + seams_y + [oy1]
    hi_z = 1000.0
    part_L = {"outer": (ox0, oy0, ox1, oy1), "interior": (ix0, iy0, ix1, iy1), "z": z,
              "seams_x": seams_x, "seams_y": seams_y}
    bands = finger_bands(part_L)
    tabs = floor_tabs(part_L)
    slots = [(x0, y0, -1.0, x1, y1, FLOOR) for _, (x0, y0, x1, y1) in tabs]
    for j, (ya, yb) in enumerate(zip(ys, ys[1:])):
        for i, (xa, xb) in enumerate(zip(xs, xs[1:])):
            inner = (max(xa, ix0), max(ya, iy0), FLOOR, min(xb, ix1), min(yb, iy1), hi_z)
            pieces.append({"part": "tray", "panel": "floor", "name": f"floor_r{j}c{i}",
                           "print": "underside down", "box": (xa, ya, xb, yb),
                           "cuts": [(xa, ya, -1.0, xb, yb, FLOOR), inner], "less": slots,
                           "size": (xb - xa, yb - ya, z["board_bot"])})

    def own_tabs(panel, lo, hi, ax):
        k = 0 if ax == "x" else 1
        return [(x0, y0, -1.0, x1, y1, FLOOR) for p_, (x0, y0, x1, y1) in tabs
                if p_ == panel and lo <= (x0, y0)[k] and (x1, y1)[k] <= hi]
    for panel, (ya, yb) in (("side", (oy0, iy0)), ("side_far", (iy1, oy1))):
        for i, (xa, xb) in enumerate(zip(xs, xs[1:])):
            cuts = [(max(xa, ix0), ya, FLOOR, min(xb, ix1), yb, hi_z)]
            for cx0, cx1, at_end in ((ox0, ix0, xa == ox0), (ix1, ox1, xb == ox1)):
                if at_end:
                    cuts += [(cx0, ya, a, cx1, yb, b) for a, b in bands[0::2]]
            pieces.append({"part": "tray", "panel": panel, "name": f"{panel}_c{i}",
                           "print": "outside down", "box": (xa, ya, xb, yb),
                           "cuts": cuts + own_tabs(panel, xa, xb, "x"), "size": (xb - xa, top, WALL)})
    wys = [iy0] + seams_y + [iy1]
    for panel, (xa, xb) in (("back", (ix1, ox1)), ("front", (ox0, ix0))):
        for j, (ya, yb) in enumerate(zip(wys, wys[1:])):
            cuts = [(xa, ya, FLOOR, xb, yb, hi_z)]
            by0, by1 = ya, yb
            if ya == iy0:
                cuts += [(xa, oy0, a, xb, iy0, b) for a, b in bands[1::2]]
                by0 = oy0
            if yb == iy1:
                cuts += [(xa, iy1, a, xb, oy1, b) for a, b in bands[1::2]]
                by1 = oy1
            pieces.append({"part": "tray", "panel": panel, "name": f"{panel}_r{j}",
                           "print": "outside down", "box": (xa, by0, xb, by1),
                           "cuts": cuts + own_tabs(panel, ya, yb, "y"),
                           "size": (by1 - by0, top, WALL)})
    for j, (ya, yb) in enumerate(zip(ys, ys[1:])):
        for i, (xa, xb) in enumerate(zip(xs, xs[1:])):
            pieces.append({"part": "lid", "name": f"lid_r{j}c{i}", "print": "roof down",
                           "box": (xa, ya, xb, yb), "size": (xb - xa, yb - ya, LID_T + LIP_H)})
    for j, (ya, yb) in enumerate(zip(ys, ys[1:])):
        pieces.append({"part": "frame", "name": f"frame_r{j}", "print": "face up",
                       "box": (front["edge_x"], ya, ox0, yb), "size": (yb - ya, full, FRONT_D)})
    py0, pz0, py1, pz1 = front["panel"]
    pieces.append({"part": "plate", "name": "plate", "print": "face up",
                   "box": (front["plate_x"], py0, ox0, py1),
                   "size": (py1 - py0, pz1 - pz0, PLATE_T)})

    return {"variant": variant, "power": power, "board": b,
            "interior": (ix0, iy0, ix1, iy1), "outer": (ox0, oy0, ox1, oy1),
            "front": front, "bbox": bbox,
            "z": z, "cutouts": cutouts, "seams_x": seams_x, "seams_y": seams_y,
            "pieces": pieces}


# --- solids (build123d imported here, so the layout tests run without it) --

def _box(x0, y0, z0, x1, y1, z1):
    from build123d import Box, Pos, Align
    return Pos(x0, y0, z0) * Box(x1 - x0, y1 - y0, z1 - z0, align=(Align.MIN,) * 3)


def _cyl(x, y, z0, z1, d):
    from build123d import Cylinder, Pos, Align
    return Pos(x, y, z0) * Cylinder(d / 2, z1 - z0, align=(Align.CENTER, Align.CENTER, Align.MIN))


def _cut_solid(c):
    from build123d import Cylinder, Pos, Rot
    if c.get("slot"):                      # vertical slot, round ends, through a Y wall
        r = c["dx"] / 2
        body = _box(c["x"] - r, c["y"] - c["dy"] / 2, c["z0"] + r,
                    c["x"] + r, c["y"] + c["dy"] / 2, c["z1"] - r)
        for zz in (c["z0"] + r, c["z1"] - r):
            body += Pos(c["x"], c["y"], zz) * Rot(90, 0, 0) * Cylinder(r, c["dy"])
        return body
    if c.get("round"):
        zc = (c["z0"] + c["z1"]) / 2
        if c["wall"] == "front":
            return Pos(c["x"], c["y"], zc) * Rot(0, 90, 0) * Cylinder(c["dy"] / 2, c["dx"])
        return Pos(c["x"], c["y"], zc) * Rot(90, 0, 0) * Cylinder(c["dx"] / 2, c["dy"])
    return _box(c["x"] - c["dx"] / 2, c["y"] - c["dy"] / 2, c["z0"],
                c["x"] + c["dx"] / 2, c["y"] + c["dy"] / 2, c["z1"])


def _yz_face(x, r):
    from build123d import Face, Wire, Vector
    y0, z0, y1, z1 = r
    return Face(Wire.make_polygon([Vector(x, y0, z0), Vector(x, y1, z0),
                                   Vector(x, y1, z1), Vector(x, y0, z1)], close=True))


def _front_pocket(L):
    """What the frame loses: the bevel (a loft from the rim's opening to the
    ledge, started 1 mm proud so it cuts clean) and the square step from
    the ledge to the panel."""
    from build123d import loft
    f = L["front"]
    ex, k = f["edge_x"], 1.0 / math.tan(math.radians(BEVEL_DEG))
    y0, z0, y1, z1 = f["opening"]
    grow = (y0 - k, z0 - k, y1 + k, z1 + k)
    bevel = loft([_yz_face(ex - 1, grow), _yz_face(ex + BEVEL_D, f["bevel_end"])])
    y0, z0, y1, z1 = f["seat"]                    # the step is the plate's seat
    step = _box(ex + BEVEL_D - 0.01, y0, z0, f["panel_x"] + 0.01, y1, z1)
    return bevel + step


def lid_installed(L, s):
    """Lid frame <-> case frame. The lid is built as printed (roof on the
    bed, lip up) and installed flipped about X onto the wall tops. The map
    is its own inverse."""
    from build123d import Pos, Rot
    oy0, oy1 = L["outer"][1], L["outer"][3]
    return Pos(0, oy0 + oy1, L["z"]["interior_top"] + LID_T) * Rot(180, 0, 0) * s


def _roof_cutter(L):
    """Case frame: wedges over the side and back top edges, the roof bevel
    LID_BEV_D down over LID_BEV_R in. Their union mitres the back corners;
    they run out past the front face."""
    from build123d import Plane, Polygon, extrude, Pos
    ox0, oy0, ox1, oy1 = L["outer"]
    full = L["z"]["interior_top"] + LID_T
    D, R, e = LID_BEV_D, LID_BEV_R, 1.0
    x0, x1 = L["front"]["edge_x"] - e, ox1 + e
    # in a wall's own (u inward, z) section: the plane z = full - D + D u / R
    tri = [(R, full), (-e, full - D - D * e / R), (-e, full + e), (R, full + e)]

    def wedge_y(y_edge, sign):
        pts = [(y_edge + sign * u, z) for u, z in tri]
        face = Plane.YZ * Polygon(*pts, align=None)
        return Pos(x0, 0, 0) * extrude(face, amount=x1 - x0, dir=(1, 0, 0))

    side = wedge_y(oy0, 1)
    far = wedge_y(oy1, -1)
    back_face = Plane.XZ * Polygon(*[(ox1 - u, z) for u, z in tri], align=None)
    back = Pos(0, oy0 - e, 0) * extrude(back_face, amount=oy1 - oy0 + 2 * e, dir=(0, 1, 0))
    return side + far + back


def build_logo(L):
    """{colour: solid}: each brand group embossed out of the panel face by
    its height, ready to colour (or to print by filament swap)."""
    import re
    from shapely.geometry import Polygon as SPoly
    from shapely.ops import unary_union
    from build123d import Face, Wire, Vector, extrude
    px = L["front"]["plate_x"]
    out = {}
    for name, g in brand_panel()["groups"].items():
        region = None                                  # evenodd: xor of every ring
        for sub in re.findall(r'M([^Z]+)Z', g["d"]):
            pts = [tuple(map(float, p.split(","))) for p in re.split(r'\s*L\s*|\s+', sub.strip()) if p]
            ring = SPoly(pts).buffer(0)
            region = ring if region is None else region.symmetric_difference(ring)
        polys = region.geoms if hasattr(region, "geoms") else [region]
        solids = []
        for poly in polys:
            def wire(coords):
                return Wire.make_polygon([Vector(px, *panel_to_case(L, x, y))
                                          for x, y in list(coords)[:-1]], close=True)
            face = Face(wire(poly.exterior.coords), [wire(r.coords) for r in poly.interiors])
            solids.append(extrude(face, amount=g["h"], dir=(-1, 0, 0)))
        out[name] = solids[0] if len(solids) == 1 else sum(solids[1:], solids[0])
    return out


def build_tray(L):
    ox0, oy0, ox1, oy1 = L["outer"]
    ix0, iy0, ix1, iy1 = L["interior"]
    z = L["z"]
    top = z["interior_top"]
    ex = L["front"]["edge_x"]
    from build123d import Axis, chamfer
    block = _box(ex, oy0, 0, ox0 + 0.01, oy1, top + LID_T)
    block = chamfer(block.faces().sort_by(Axis.X)[0].edges(), EDGE_CH)
    frame = block - _front_pocket(L) - _roof_cutter(L)
    tray = _box(ox0, oy0, 0, ox1, oy1, top) + frame - _box(ix0, iy0, FLOOR, ix1, iy1, top + 1)
    for hx, hy in L["board"]["holes"].values():
        tray += _cyl(hx, hy, FLOOR - 0.01, z["board_bot"], STANDOFF_OD)
    for hx, hy in L["board"]["holes"].values():
        tray -= _cyl(hx, hy, z["board_bot"] - INSERT_DEPTH, z["board_bot"] + 1, INSERT_D)
    for c in L["cutouts"]:
        tray -= _cut_solid(c)
    return tray


def build_lid(L):
    """Printed as it lies here: plate on the bed, lip up. Flip to fit."""
    ox0, oy0, ox1, oy1 = L["outer"]
    ix0, iy0, ix1, iy1 = L["interior"]
    g = LIP_GAP
    lid = _box(ox0, oy0, 0, ox1, oy1, LID_T)              # butts the front frame, flush
    lid -= lid_installed(L, _roof_cutter(L))          # solid: nothing is hollow
    lid += _box(ix0 + g, iy0 + g, LID_T - 0.01, ix1 - g, iy1 - g, LID_T + LIP_H) - \
        _box(ix0 + g + LIP_W, iy0 + g + LIP_W, LID_T - 1, ix1 - g - LIP_W, iy1 - g - LIP_W,
             LID_T + LIP_H + 1)
    return lid


def build_plate(L):
    """The brand panel: a plate glued onto the wall in the frame's seat,
    printed face up (the logo's colours swap by height). Built in place."""
    f = L["front"]
    y0, z0, y1, z1 = f["panel"]
    plate = _box(f["plate_x"], y0, z0, f["panel_x"], y1, z1)
    for c in L["cutouts"]:
        if c["kind"] == "led":
            plate -= _cut_solid(c)
    return plate


def _pins(L, part):
    """Dowel holes as (axis, seam, a, b, c): along `axis` at `seam`, at
    cross position a, height b. Walls and floor/plate, every PIN_PITCH."""
    ox0, oy0, ox1, oy1 = L["outer"]
    ix0, iy0, ix1, iy1 = L["interior"]
    if part == "tray":
        top = L["z"]["interior_top"]
        wall_zs = [FLOOR + 8 + k * PIN_PITCH for k in range(int((top - FLOOR - 16) // PIN_PITCH) + 1)]
        plate_z = FLOOR / 2
    else:
        wall_zs = []
        plate_z = LID_T / 2
    out = []
    f = L["front"]
    pz0, pz1 = f["panel"][1], f["panel"][3]
    band_zs = [(pz0 + pz1) / 2] if part == "tray" else []
    for axis, seams, (c0, c1), walls in (
            ("x", L["seams_x"], (iy0, iy1), ((oy0 + WALL / 2, wall_zs), (oy1 - WALL / 2, wall_zs))),
            ("y", L["seams_y"], (ix0, ix1), ((f["panel_x"] + WALL / 2, band_zs),
                                              (ox1 - WALL / 2, wall_zs)))):
        for s in seams:
            for w, zs in walls:
                out += [(axis, s, w, zz) for zz in zs]
            n = int((c1 - c0) // PIN_PITCH)
            span = n * PIN_PITCH
            for k in range(n + 1):
                out.append((axis, s, c0 + (c1 - c0 - span) / 2 + k * PIN_PITCH, plate_z))
    if part == "tray":
        # the frame onto the tray: through the joint at the wall face, into
        # the side walls and the floor (the front wall is too thin to take one)
        n = int((iy1 - iy0) // PIN_PITCH)
        span = n * PIN_PITCH
        out += [("x", ox0, w, zz) for w in (oy0 + WALL / 2, oy1 - WALL / 2) for zz in wall_zs]
        front_tabs = [(y0, y1) for p_, (_, y0, _, y1) in floor_tabs(L) if p_ == "front"]
        out += [("x", ox0, y, plate_z)
                for y in (iy0 + (iy1 - iy0 - span) / 2 + k * PIN_PITCH for k in range(n + 1))
                if not any(y0 - PIN_D < y < y1 + PIN_D for y0, y1 in front_tabs)]
        # the frame's halves to each other: in its bottom and top bands
        full = L["z"]["interior_top"] + LID_T
        xs_ = f["panel_x"] - STEP_D / 2 - PLATE_T / 2
        xf = f["edge_x"] + 2 * EDGE_CH
        for s in L["seams_y"]:
            out += [("y", s, xs_, zz) for zz in (8.0, 24.0, full - 8.0, full - 24.0)]
            out += [("y", s, xf, zz) for zz in (8.0, full - 8.0)]
        out = [p for p in out if not _pin_hits_cutout(L, *p)]
    else:
        out = [p for p in out if not _pin_hits_roof(L, *p)]
    return out


def _pin_hits_roof(L, axis, s, a, h):
    """A lid dowel whose bore the roof bevel opens (near the sides or the
    back) is dropped. h is the depth below the roof, as the lid is built."""
    ox0, oy0, ox1, oy1 = L["outer"]
    r = PIN_D / 2
    if axis == "x":
        bx0, bx1, by0, by1 = s - PIN_DEPTH, s + PIN_DEPTH, a - r, a + r
    else:
        bx0, bx1, by0, by1 = a - r, a + r, s - PIN_DEPTH, s + PIN_DEPTH
    u = min(by0 - oy0, oy1 - by1, ox1 - bx1)        # nearest bevelled edge
    cut = LID_BEV_D * (1 - u / LID_BEV_R) if u < LID_BEV_R else 0.0
    return cut > h - r - 0.5


def _pin_hits_cutout(L, axis, s, a, h):
    """A dowel bore that breaks into a cutout is a half-hole: drop it.
    (The Y seam lands in a 6.3 mm bar between slot cutouts.)"""
    r = PIN_D / 2
    if axis == "x":
        bx = (s - PIN_DEPTH, s + PIN_DEPTH, a - r, a + r)
    else:
        bx = (a - r, a + r, s - PIN_DEPTH, s + PIN_DEPTH)
    for c in L["cutouts"]:
        cx0, cx1 = cut_span(c, "x")
        cy0, cy1 = cut_span(c, "y")
        if bx[0] < cx1 and cx0 < bx[1] and bx[2] < cy1 and cy0 < bx[3] \
                and h + r > c["z0"] and h - r < c["z1"]:
            return True
    return False


def pin_volume(L):
    v = math.pi * (PIN_D / 2) ** 2 * 2 * PIN_DEPTH
    return {"tray": v * len(_pins(L, "tray")), "lid": v * len(_pins(L, "lid"))}


def _pin_solid(axis, s, a, h):
    from build123d import Cylinder, Pos, Rot
    cyl = Cylinder(PIN_D / 2, 2 * PIN_DEPTH)
    if axis == "x":
        return Pos(s, a, h) * Rot(0, 90, 0) * cyl
    return Pos(a, s, h) * Rot(90, 0, 0) * cyl


def split(L, tray, lid, plate):
    """{piece name: solid}, dowel holes drilled across every seam. The frame
    pieces come out of the tray solid (they are one shape until parted)."""
    whole = {"tray": tray, "lid": lid}
    for part in whole:
        for p in _pins(L, part):
            whole[part] = whole[part] - _pin_solid(*p)
    whole["frame"] = whole["tray"]
    out = {}
    for p in L["pieces"]:
        if p["part"] == "plate":
            out[p["name"]] = plate
            continue
        x0, y0, x1, y1 = p["box"]
        cuts = p.get("cuts", [(x0, y0, -1.0, x1, y1, 1000.0)])
        keep = _box(*cuts[0])
        for c in cuts[1:]:
            keep = keep + _box(*c)
        for c in p.get("less", []):
            keep = keep - _box(*c)
        out[p["name"]] = whole[p["part"]] & keep
    return out


def write(L, out_dir):
    from build123d import export_step, export_stl, Compound, Pos
    os.makedirs(out_dir, exist_ok=True)
    tray, lid, plate = build_tray(L), build_lid(L), build_plate(L)
    parts = split(L, tray, lid, plate)
    for name, solid in parts.items():
        export_stl(solid, os.path.join(out_dir, name + ".stl"))
        export_step(solid, os.path.join(out_dir, name + ".step"))
    # assembly: lid flipped onto the tray
    lid_on = lid_installed(L, lid)
    logo = build_logo(L)
    for name, solid in logo.items():
        export_step(solid, os.path.join(out_dir, f"logo_{name}.step"))
    export_step(Compound([tray, lid_on, plate, *logo.values()]),
                os.path.join(out_dir, "assembly.step"))
    return parts


def summary(L):
    ox0, oy0, ox1, oy1 = L["bbox"]
    z = L["z"]
    f = L["front"]
    lines = [f"DINO case, variant {L['variant']}, power {L['power']}",
             f"outer {ox1 - ox0:.1f} x {oy1 - oy0:.1f} x {z['interior_top'] + LID_T:.1f} mm "
             f"(tray {z['interior_top']:.1f} + lid {LID_T})",
             f"board top z {z['board_top']:.1f}, card top z {z['card_top']:.1f}",
             f"front frame {FRONT_D} deep: rim {RIM}, bevel {BEVEL_DEG:g} deg x {BEVEL_D}, "
             f"ledge {LEDGE}, step {STEP_D}, edge chamfer {EDGE_CH}; brand plate "
             f"{f['panel'][2] - f['panel'][0]:.2f} x {f['panel'][3] - f['panel'][1]:.2f} x {PLATE_T}, "
             f"seat gap {PLATE_GAP}",
             f"seams x {L['seams_x']}  y {L['seams_y']}",
             f"pieces {len(L['pieces'])}:"]
    for p in L["pieces"]:
        dx, dy, dz = p["size"]
        lines.append(f"  {p['name']:10s} {dx:6.1f} x {dy:6.1f} x {dz:6.1f}  {p['print']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", default="plain", choices=VARIANTS)
    ap.add_argument("--power", default="atx", choices=POWERS)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "..", "case", "gen"))
    ap.add_argument("--dry", action="store_true", help="layout only, no solids")
    a = ap.parse_args(argv)
    L = layout(a.variant, a.power)
    print(summary(L))
    if not a.dry:
        out = os.path.join(a.out, f"{a.variant}_{a.power}")
        write(L, out)
        print(f"wrote {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
