#!/usr/bin/env python3
"""The card-edge slots' physical envelope, enforced against the saved PCB.

Konnect has no keepout-rule-area tool, and a graphic on a User layer stops
nobody. This file is the keepout: it parses `dino_v0_0_2.kicad_pcb`
READ-ONLY (never writes it -- konnect rule) and asserts the geometry the
spec in `.git/sdd/PCB_LAYOUT.md` SECTION 2/4 depends on.

Geometry, FACT from the dino_bus footprints (2026-09-12):

    EdgeSocket_2x25   67.5 mm long, origin centre, pads x +/-30.48
    EdgeFingers_2x25  card is 103.5 mm wide (Edge.Cuts +/-51.75)

so a seated card overhangs its socket by 18 mm at EACH end. The outboard
end hangs past the board edge in free air; the INBOARD end sweeps a strip
of the mainboard. Apple II / 5150 rule (Rico, 2026-09-12): the card body
emerges ~10 mm above the board at the socket's top face and passes over
DIPs, so the strip MAY hold low-profile parts; only part HEIGHT matters.
Cards are 0.8 in apart; anything tall beside a slot collides with the
card or the parts on it. An earlier cut of this file forbade any part in
the strip -- that was a routing convenience, not mechanics, and is gone.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, "..", "..", "dino_v0_0_2", "dino_v0_0_2.kicad_pcb")

SLOT_PITCH = 20.32          # Rico, 2026-09-12: 0.8 in (ISA); was 0.7 in until the hand layout
SLOT_TOL = 0.02
CARD_HALF = 51.75           # EdgeFingers Edge.Cuts half-width
SOCKET_HALF = 33.75         # EdgeSocket courtyard half-length
CARD_ZONE_HALF_Y = 9.0      # card + its parts, either side of the slot line
STRIP_Y_MARGIN = 6.0        # socket courtyard half-height

# Footprint name fragments taller than a seated card's underside (~8 mm
# above the board). DIPs, disc caps and a DIP-14 oscillator (5 mm) are not.
TALL = ("Molex_Mini-Fit", "CP_Radial", "LED_D5", "SW_PUSH", "PinHeader")

# CLK budget, mm of copper per net, checked only once tracks exist.
# REGRESSION GUARD, not physics: measured 2026-09-12 after the annealed
# placement + Freerouting run 6 was CLK 338 / ~{CLK} 318 / CLK_B 230 mm;
# budgets are that +20%. The physics limit (LS edge ~5 ns -> ~125 mm per
# unterminated branch) is per BRANCH and needs connectivity to check.
CLK_BUDGET = {"CLK": 405.0, "~{CLK}": 380.0, "CLK_B": 275.0}


def load_footprints(path=PCB):
    """[{ref, fp, x, y, rot, pads:[(x,y)]}] from the board file, read-only."""
    with open(path) as fh:
        txt = fh.read()
    out = []
    for blk in re.split(r"\n\t\(footprint ", txt)[1:]:
        fp = blk.split('"', 2)[1]
        ref = re.search(r'\(property "Reference" "([^"]+)"', blk).group(1)
        m = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", blk)
        x, y = float(m.group(1)), float(m.group(2))
        rot = float(m.group(3) or 0)
        pads = []
        for px, py in re.findall(r'\(pad "[^"]*"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)', blk):
            pads.append(_rotate(float(px), float(py), rot, x, y))
        out.append({"ref": ref, "fp": fp, "x": x, "y": y, "rot": rot, "pads": pads})
    return out


def _rotate(px, py, rot, ox, oy):
    """Footprint-local pad offset -> board space. KiCad rotates CCW, Y down."""
    import math
    a = math.radians(rot)
    c, s = math.cos(a), math.sin(a)
    return (ox + px * c + py * s, oy - px * s + py * c)


def load_segments(path=PCB):
    """[(net_name, length_mm)] for every track segment on the board."""
    with open(path) as fh:
        txt = fh.read()
    names = dict(re.findall(r'\n\t\(net (\d+) "([^"]*)"\)', txt))
    segs = []
    # bounded: a segment block is a handful of short lines; never scan across the file
    # KiCad 10 writes (net "NAME") on a segment; older files wrote (net N)
    for m in re.finditer(r"\(segment\n\s*\(start ([-\d.]+) ([-\d.]+)\)\n\s*\(end ([-\d.]+) ([-\d.]+)\)\n(?:[^\n]*\n){0,4}?\s*\(net (?:\"([^\"]*)\"|(\d+))\)", txt):
        x1, y1, x2, y2, name, num = m.groups()
        net = name if name is not None else names.get(num, num)
        segs.append((net, ((float(x2) - float(x1)) ** 2 + (float(y2) - float(y1)) ** 2) ** 0.5))
    return segs


def board_right(path=PCB):
    with open(path) as fh:
        txt = fh.read()
    xs = []
    for blk in re.findall(r"\(gr_(?:rect|line|arc)\n\s*\(start ([-\d.]+) [-\d.]+\)\n(?:\s*\(mid [-\d.]+ [-\d.]+\)\n)?\s*\(end ([-\d.]+) [-\d.]+\)\n(?:[^\n]*\n){0,8}?\s*\(layer \"Edge.Cuts\"\)", txt):
        xs += [float(blk[0]), float(blk[1])]
    return max(xs)


def slots(fps):
    """J1..J8 sorted by y."""
    return sorted((f for f in fps if f["fp"].endswith("EdgeSocket_2x25_P2.54mm_THT")), key=lambda f: f["y"])


def strip_rect(fps):
    """(x0, x1, y0, y1) of the inboard card-overhang strip."""
    js = slots(fps)
    cx = js[0]["x"]
    return (cx - CARD_HALF, cx - SOCKET_HALF, js[0]["y"] - STRIP_Y_MARGIN, js[-1]["y"] + STRIP_Y_MARGIN)


class Envelope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fps = load_footprints()
        cls.js = slots(cls.fps)

    def test_eight_slots(self):
        self.assertEqual([j["ref"] for j in self.js], ["J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8"])

    def test_slot_pitch_and_column(self):
        ys = [j["y"] for j in self.js]
        for a, b in zip(ys, ys[1:]):
            self.assertAlmostEqual(b - a, SLOT_PITCH, delta=SLOT_TOL, msg=f"{ys}")
        self.assertEqual(len({round(j["x"], 3) for j in self.js}), 1, "sockets not in one column")
        self.assertEqual({j["rot"] for j in self.js}, {0.0}, "sockets must be rot 0 (long axis X)")

    def test_socket_on_board(self):
        right = board_right()
        for j in self.js:
            self.assertGreaterEqual(right - (j["x"] + SOCKET_HALF), 0.0, f"{j['ref']} off the board")

    def test_strip_low_profile_only(self):
        x0, x1, y0, y1 = strip_rect(self.fps)
        bad = sorted({f["ref"] for f in self.fps if not f["ref"].startswith("J")
                      and any(t in f["fp"] for t in TALL)
                      for px, py in f["pads"] if x0 <= px <= x1 and y0 <= py <= y1})
        self.assertEqual(bad, [], f"tall parts inside the card-overhang strip x{x0:.1f}..{x1:.1f}: {bad}")

    def test_tall_parts_clear_of_cards(self):
        cx = self.js[0]["x"]
        x0, x1 = cx - CARD_HALF, board_right()
        bad = []
        for f in self.fps:
            if not any(t in f["fp"] for t in TALL):
                continue
            for px, py in f["pads"]:
                if x0 <= px <= x1 and any(abs(py - j["y"]) <= CARD_ZONE_HALF_Y for j in self.js):
                    bad.append(f["ref"])
                    break
        self.assertEqual(bad, [], f"tall parts under a card: {bad}")

    def test_clk_branch_length(self):
        segs = load_segments()
        if not segs:
            self.skipTest("board has no tracks yet")
        for net, budget in CLK_BUDGET.items():
            total = sum(l for n, l in segs if n == net)
            self.assertGreater(total, 0.0, f"{net} unrouted")
            self.assertLess(total, budget, f"{net} is {total:.0f} mm of copper, budget {budget:.0f}")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
