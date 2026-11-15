#!/usr/bin/env python3
"""case_gen.py: the DINO case, held against the saved Rev 1.0 PCB.

Two halves. The LAYOUT tests (numbers: interior, standoffs, cutouts, seams,
pieces) run anywhere. The SOLID tests build the real geometry with
build123d and skip, visibly, where it is not installed; run them with

    make case-test        # ~/.venvs/dino-cad (build123d + pytest)
"""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import case_gen as cg                      # noqa: E402
import proto_card_gen as pc                # noqa: E402
from test_pcb_envelope import load_footprints   # noqa: E402

try:
    import build123d                       # noqa: F401
    HAVE_B3D = True
except ImportError:
    HAVE_B3D = False


def board_xy_to_case(x, y):
    return (x, cg.BOARD_H - y)


class BoardFacts(unittest.TestCase):
    """The case reads the board; nothing is retyped."""

    def setUp(self):
        self.b = cg.board_facts()
        self.fps = {f["ref"]: f for f in load_footprints()}

    def test_outline(self):
        self.assertAlmostEqual(self.b["w"], 298.85, places=2)
        self.assertAlmostEqual(self.b["h"], 270.0, places=2)

    def test_five_mounting_holes_from_the_pcb(self):
        refs = sorted(self.b["holes"])
        self.assertEqual(refs, ["H1", "H2", "H3", "H4", "H5"])
        for r, (x, y) in self.b["holes"].items():
            self.assertEqual((x, y), board_xy_to_case(self.fps[r]["x"], self.fps[r]["y"]))

    def test_eight_slots_from_the_pcb(self):
        self.assertEqual(sorted(self.b["slots"]), [f"J{i}" for i in range(1, 9)])
        for r, (x, y) in self.b["slots"].items():
            self.assertEqual((x, y), board_xy_to_case(self.fps[r]["x"], self.fps[r]["y"]))

    def test_power_connector_from_the_pcb(self):
        self.assertEqual(self.b["power"], board_xy_to_case(self.fps["J9"]["x"], self.fps["J9"]["y"]))


class Layout(unittest.TestCase):

    def setUp(self):
        self.L = cg.layout("plain", power="atx")

    def test_board_inside_interior_with_clearance(self):
        ix0, iy0, ix1, iy1 = self.L["interior"]
        b = self.L["board"]
        self.assertLessEqual(ix0, 0 - cg.CLEAR)
        self.assertLessEqual(iy0, 0 - cg.CLEAR)
        self.assertGreaterEqual(ix1, b["w"] + cg.CLEAR)
        self.assertGreaterEqual(iy1, b["h"] + cg.CLEAR)

    def test_every_card_envelope_fits(self):
        """A card at the proto card's limits: TAB_OVER_L left, the 20 mm
        overhang cap right, HEIGHT tall above the socket."""
        ix0, iy0, ix1, iy1 = self.L["interior"]
        top = self.L["z"]["interior_top"]
        for r, (sx, sy) in self.L["board"]["slots"].items():
            left = sx - pc.TAB_W / 2 - pc.TAB_OVER_L
            right = sx + pc.TAB_W / 2 + pc.OVERHANG_CAP
            self.assertGreaterEqual(left, ix0, r)
            self.assertLessEqual(right + cg.CLEAR, ix1, r)
            card_top = self.L["z"]["board_top"] + cg.SOCKET_TOP + pc.HEIGHT
            self.assertLessEqual(card_top + cg.TOP_CLEAR, top + 1e-9, r)
            # the lid's lip must stay above every card
            self.assertGreater(top - cg.LIP_H, card_top, r)

    def test_one_cable_cutout_per_slot_in_the_back_wall(self):
        cuts = [c for c in self.L["cutouts"] if c["kind"] == "slot"]
        self.assertEqual(sorted(c["ref"] for c in cuts), [f"J{i}" for i in range(1, 9)])
        ix1 = self.L["interior"][2]
        for c in cuts:
            sx, sy = self.L["board"]["slots"][c["ref"]]
            self.assertEqual(c["wall"], "back")
            self.assertAlmostEqual(c["y"], sy)
            self.assertAlmostEqual(c["x"], ix1 + cg.WALL / 2)
            self.assertGreater(c["z0"], self.L["z"]["board_top"] + cg.SOCKET_TOP)
            self.assertLess(c["z1"], self.L["z"]["interior_top"])
        # bars between neighbouring cutouts
        ys = sorted(c["y"] for c in cuts)
        for a, b in zip(ys, ys[1:]):
            self.assertGreaterEqual(b - a - cg.SLOT_CUT_W, cg.MIN_BAR)

    def test_power_variants(self):
        for power, kind in (("atx", "atx"), ("pico", "dcjack")):
            L = cg.layout("plain", power=power)
            pw = [c for c in L["cutouts"] if c["kind"] == kind]
            self.assertEqual(len(pw), 1, power)
            self.assertEqual(pw[0]["wall"], "side")
            self.assertAlmostEqual(pw[0]["x"], L["board"]["power"][0])
        L = cg.layout("plain", power="none")
        self.assertFalse([c for c in L["cutouts"] if c["kind"] in ("atx", "dcjack")])
        with self.assertRaises(ValueError):
            cg.layout("plain", power="aa_batteries")

    def test_front_is_a_bevelled_frame_opposite_the_slots(self):
        """IBM PC order: cards at the back (x max), the front at x min.
        Rico, 2026-11-06 (sketch, a 70s sports-car grille): a picture
        frame on all four sides. Flat rim, a BEVEL_DEG bevel IN, a flat
        ledge (the inset lip), a square step, then the flat recessed panel
        at the old wall plane, so nothing moves toward the board. The frame
        runs the full height, lid included."""
        f = self.L["front"]
        ox0, oy0, _, oy1 = self.L["outer"]
        full = self.L["z"]["interior_top"] + cg.LID_T
        self.assertAlmostEqual(f["edge_x"], ox0 - cg.FRONT_D)
        self.assertAlmostEqual(f["panel_x"], ox0)
        self.assertEqual(self.L["bbox"][0], f["edge_x"])
        # the brand plate glues onto the wall in the step; the frame is
        # PLATE_T deeper so the step still shows STEP_D (look unchanged)
        self.assertAlmostEqual(cg.BEVEL_D + cg.STEP_D + cg.PLATE_T, cg.FRONT_D)
        self.assertAlmostEqual(f["plate_x"], ox0 - cg.PLATE_T)
        self.assertTrue(30 <= cg.BEVEL_DEG <= 40)            # the sketch's 30-40
        self.assertEqual(f["face"], (oy0, 0.0, oy1, full))
        w = cg.BEVEL_D / math.tan(math.radians(cg.BEVEL_DEG))
        self.assertAlmostEqual(f["bevel_w"], w)
        inset = {"opening": cg.RIM, "bevel_end": cg.RIM + w, "panel": cg.RIM + w + cg.LEDGE}
        for k, d in inset.items():
            self.assertEqual(f[k], (oy0 + d, d, oy1 - d, full - d), k)
        # aggressive, not a drawer (Rico, 2026-11-06): a deep recess, a
        # step deep enough to throw a shadow line round the panel; then
        # "make the flat rim wider"
        self.assertGreaterEqual(cg.FRONT_D, 25)
        self.assertGreaterEqual(cg.RIM, 10)
        self.assertGreaterEqual(cg.STEP_D, 2 * cg.LEDGE)
        y0, z0, y1, z1 = f["panel"]
        self.assertGreater(y1 - y0, 0.65 * (oy1 - oy0))      # still a wide grille
        self.assertGreaterEqual(z1 - z0, 25)                 # room for logo + intake

    def test_ob_leds_where_the_brand_spec_puts_them(self):
        """The 8 OB LEDs exactly where DINO_logo_mockup_spec (Rev 1,
        2026-11-06) and docs/brand/build.py draw them: top right of the
        panel, above the bus, 5.2 mm bores at 10 mm pitch, OB0 at right
        (Rico: "It should match exactly"). Facing the front (looking +X)
        right is -Y. J11 (the OB header) is on that side."""
        leds = [c for c in self.L["cutouts"] if c["kind"] == "led"]
        self.assertEqual([c["ref"] for c in sorted(leds, key=lambda c: c["y"])],
                         [f"OB{i}" for i in range(8)])
        f = self.L["front"]
        y0, z0, y1, z1 = f["panel"]
        guides = cg.brand_panel()["leds"]
        pw = cg.brand_panel()["w"]
        for k in range(8):                       # the spec's numbers, pinned
            self.assertAlmostEqual(guides[f"OB{k}"][0] - guides["OB0"][0], -10 * k, places=2)
            self.assertAlmostEqual(guides[f"OB{k}"][1], 7.6, places=2)
        r = cg.LED_D / 2
        ys = sorted(c["y"] for c in leds)
        for a, b in zip(ys, ys[1:]):
            self.assertAlmostEqual(b - a, cg.LED_PITCH, places=2)
        for c in leds:
            self.assertEqual(c["wall"], "front")
            self.assertTrue(c["round"])
            # through the brand plate and the wall behind it
            self.assertAlmostEqual(c["x"], (f["plate_x"] + f["panel_x"] + cg.WALL) / 2)
            zc = (c["z0"] + c["z1"]) / 2
            gx, gy = guides[c["ref"]]
            self.assertAlmostEqual((c["y"], zc), cg.panel_to_case(self.L, gx, gy))
            self.assertLess(c["y"], (y0 + y1) / 2)            # right half
            self.assertGreater(c["y"] - r, y0 + 2)
            self.assertGreater(zc - r, z0 + 2)
        j11 = cg.board_facts()["ob_header"]
        self.assertEqual(j11, board_xy_to_case(*(lambda f: (f["x"], f["y"]))(
            {f["ref"]: f for f in load_footprints()}["J11"])))
        self.assertLess(j11[1], (y0 + y1) / 2)

    def test_brand_panel_symmetry(self):
        """Rico, 2026-11-06: the LED row ends where the bus's longest line
        (the top one, black) ends, and that end stands as far from the
        right edge as the D does from the left."""
        import re
        b = cg.brand_panel()
        xs = lambda d: [float(v) for v in re.findall(r'([\d.]+),[\d.]+', d)]
        d_left = min(xs(b["groups"]["orange"]["d"]))          # the D's left edge
        black_end = max(xs(b["groups"]["black"]["d"]))
        for name in ("orange", "grey"):
            self.assertLess(max(xs(b["groups"][name]["d"])), black_end, name)   # black longest
        ob0_right = b["leds"]["OB0"][0] + cg.LED_D / 2
        self.assertAlmostEqual(ob0_right, black_end, places=2)
        self.assertAlmostEqual(b["w"] - black_end, d_left, places=2)

    def test_brand_panel_matches_the_case_panel(self):
        """The brand panel is drawn at the case panel's size; one emboss
        group per colour at the spec's heights (orange 0.6, grey 1.0,
        black 1.4 mm)."""
        b = cg.brand_panel()
        y0, z0, y1, z1 = self.L["front"]["panel"]
        self.assertAlmostEqual(b["w"], y1 - y0, delta=0.1)
        self.assertAlmostEqual(b["h"], z1 - z0, delta=0.1)
        self.assertEqual({k: v["h"] for k, v in b["groups"].items()},
                         {"orange": 0.6, "grey": 1.0, "black": 1.4})
        self.assertEqual(sorted(b["leds"]), [f"OB{i}" for i in range(8)])

    def test_side_intakes(self):
        """Rico, 2026-11-06: 12 intakes, 6 in each side wall, after the
        Apple IIe: tall narrow vertical slots, round ends. Toward the front,
        so air comes in there and leaves through the slot cutouts at the back."""
        vents = [c for c in self.L["cutouts"] if c["kind"] == "vent"]
        self.assertEqual(len(vents), 12)
        ox0, oy0, ox1, oy1 = self.L["outer"]
        ix0, iy0, ix1, iy1 = self.L["interior"]
        by = {}
        for c in vents:
            by.setdefault(c["wall"], []).append(c)
            self.assertTrue(c["slot"])
            self.assertAlmostEqual(c["dx"], cg.VENT_W)
            self.assertGreater(c["z1"] - c["z0"], 3 * cg.VENT_W)       # vertical
            self.assertGreaterEqual(c["x"] - cg.VENT_W / 2, ix0 + cg.VENT_X0 - 1e-9)
            self.assertLess(c["x"], (ix0 + ix1) / 2)                    # front half
            self.assertGreater(c["z0"], cg.FLOOR)
            self.assertLess(c["z1"], self.L["z"]["interior_top"] - cg.LIP_H)  # below the lid lip
        self.assertEqual(sorted(by), ["side", "side_far"])
        self.assertTrue(all(abs(c["y"] - (iy0 - cg.WALL / 2)) < 1e-9 for c in by["side"]))
        self.assertTrue(all(abs(c["y"] - (iy1 + cg.WALL / 2)) < 1e-9 for c in by["side_far"]))
        for w in by.values():
            xs = sorted(c["x"] for c in w)
            self.assertEqual(len(xs), 6)
            for a, b in zip(xs, xs[1:]):
                self.assertAlmostEqual(b - a, cg.VENT_PITCH)
        self.assertEqual(sorted(c["x"] for c in by["side"]), sorted(c["x"] for c in by["side_far"]))

    def test_panel_variant_is_named_and_not_built(self):
        self.assertIn("plain", cg.VARIANTS)
        self.assertIn("panel", cg.VARIANTS)
        with self.assertRaises(NotImplementedError):
            cg.layout("panel", power="atx")

    def test_seams_clear_of_standoffs_and_cutouts(self):
        for axis, seams in (("x", self.L["seams_x"]), ("y", self.L["seams_y"])):
            for s in seams:
                for r, (hx, hy) in self.L["board"]["holes"].items():
                    h = hx if axis == "x" else hy
                    self.assertGreater(abs(s - h), cg.STANDOFF_OD / 2 + cg.SEAM_KEEP, (axis, s, r))
                for c in self.L["cutouts"]:
                    lo, hi = cg.cut_span(c, axis)
                    self.assertFalse(lo - cg.SEAM_KEEP < s < hi + cg.SEAM_KEEP, (axis, s, c))

    def test_every_piece_fits_the_core_one(self):
        pieces = self.L["pieces"]
        self.assertGreaterEqual(len(pieces), 2)
        for p in pieces:
            dx, dy, dz = p["size"]
            self.assertTrue(cg.fits_bed(dx, dy, dz), p)
        # the lid is cut on the tray's seams
        nx, ny = len(self.L["seams_x"]) + 1, len(self.L["seams_y"]) + 1
        self.assertEqual(len([p for p in pieces if p["part"] == "lid"]), nx * ny)

    def test_parted_for_glue(self):
        """Rico, 2026-11-06: the front frame is its own pieces (two halves on
        the Y seam), the brand panel a separate plate glued in, the tray
        starts behind the frame. Each piece carries its print orientation:
        the frame and plate print face up, so neither has an overhang."""
        L, f = self.L, self.L["front"]
        ox0, oy0, ox1, oy1 = L["outer"]
        full = L["z"]["interior_top"] + cg.LID_T
        by = {p["name"]: p for p in L["pieces"]}
        frames = [p for p in L["pieces"] if p["part"] == "frame"]
        self.assertEqual(len(frames), len(L["seams_y"]) + 1)
        for p in frames:
            x0, y0, x1, y1 = p["box"]
            self.assertEqual((x0, x1), (f["edge_x"], ox0))
            self.assertEqual(p["print"], "face up")
            self.assertEqual(p["size"], (y1 - y0, full, cg.FRONT_D))
        for p in L["pieces"]:
            if p["part"] in ("tray", "lid"):
                self.assertGreaterEqual(p["box"][0], ox0, p["name"])
        plate = by["plate"]
        b = cg.brand_panel()
        self.assertEqual(plate["part"], "plate")
        self.assertEqual(plate["print"], "face up")
        self.assertAlmostEqual(plate["size"][0], b["w"], places=2)
        self.assertAlmostEqual(plate["size"][1], b["h"], places=2)
        self.assertEqual(plate["size"][2], cg.PLATE_T)
        # the plate's seat leaves a glue gap all round
        sy0, sz0, sy1, sz1 = f["seat"]
        py0, pz0, py1, pz1 = f["panel"]
        for a, b_ in ((py0, sy0), (pz0, sz0), (sy1, py1), (sz1, pz1)):
            self.assertAlmostEqual(a - b_, cg.PLATE_GAP)

    def test_tray_is_flat_panels_not_corners(self):
        """Rico, 2026-11-06: more printing, less risk: no corner piece of
        floor + two walls. The floor (full footprint, standoffs on it) is
        quartered on the seams; the walls stand on it, each printed flat,
        outside down. The side walls run the full length; the back and the
        front fit between them. The 90 deg joints are butt joints, glue
        only; dowels only where a seam runs in a panel's own plane."""
        L = self.L
        ox0, oy0, ox1, oy1 = L["outer"]
        ix0, iy0, ix1, iy1 = L["interior"]
        top = L["z"]["interior_top"]
        tray = [p for p in L["pieces"] if p["part"] == "tray"]
        nx, ny = len(L["seams_x"]) + 1, len(L["seams_y"]) + 1
        kinds = {}
        for p in tray:
            kinds.setdefault(p["panel"], []).append(p)
        self.assertEqual({k: len(v) for k, v in kinds.items()},
                         {"floor": nx * ny, "side": nx, "side_far": nx, "back": ny, "front": ny})
        h = top                                   # the wall plus its tabs into the floor
        for p in kinds["floor"]:
            self.assertEqual(p["print"], "underside down")
            self.assertEqual(p["size"][2], L["z"]["board_bot"])     # the standoffs on it
        for k, (lo, hi) in {"side": (oy0, iy0), "side_far": (iy1, oy1)}.items():
            for p in kinds[k]:
                self.assertEqual(p["print"], "outside down")
                x0, y0, x1, y1 = p["box"]
                self.assertEqual((y0, y1), (lo, hi))
                self.assertEqual(p["size"], (x1 - x0, h, cg.WALL))
            ends = sorted(v for p in kinds[k] for v in (p["box"][0], p["box"][2]))
            self.assertEqual((ends[0], ends[-1]), (ox0, ox1))             # full length
        for k, (lo, hi) in {"back": (ix1, ox1), "front": (ox0, ix0)}.items():
            for p in kinds[k]:
                self.assertEqual(p["print"], "outside down")
                x0, y0, x1, y1 = p["box"]
                self.assertEqual((x0, x1), (lo, hi))
                # between the side walls, its end fingers reaching the outside
                self.assertEqual(y0, oy0 if y0 < iy0 + 1 else y0)
                self.assertEqual(p["size"], (y1 - y0, h, cg.WALL))
            ends = sorted(v for p in kinds[k] for v in (p["box"][1], p["box"][3]))
            self.assertEqual((ends[0], ends[-1]), (oy0, oy1))
        for p in L["pieces"]:
            self.assertTrue(cg.fits_bed(*p["size"]), p["name"])

    def test_walls_are_thick_enough_for_their_dowels(self):
        """Rico, 2026-11-06: thin walls are a risk. A 2 mm dowel keeps 2 mm
        of plastic each side; the floor takes the walls' tabs."""
        self.assertGreaterEqual(cg.WALL, cg.PIN_D + 4)
        self.assertGreaterEqual(cg.FLOOR, cg.PIN_D + 4)

    def test_box_joint_corners(self):
        """Each vertical corner is a box (finger) joint: the corner column
        is cut into FINGERS bands, odd in number so the side walls own the
        top and bottom ones; the back or front wall owns the others."""
        L = self.L
        self.assertEqual(cg.FINGERS % 2, 1)
        self.assertGreaterEqual(cg.FINGERS, 5)
        bands = cg.finger_bands(L)
        self.assertEqual(len(bands), cg.FINGERS)
        self.assertEqual(bands[0][0], cg.FLOOR)
        self.assertEqual(bands[-1][1], L["z"]["interior_top"])
        for (a, b), (c, d) in zip(bands, bands[1:]):
            self.assertEqual(b, c)

    def test_floor_tabs(self):
        """Every wall stands on the floor with tabs through slots in it."""
        L = self.L
        tabs = cg.floor_tabs(L)
        for panel in ("side", "side_far", "back", "front"):
            self.assertGreaterEqual(len([t for t in tabs if t[0] == panel]), 3, panel)
        seams = {"x": L["seams_x"], "y": L["seams_y"]}
        ox0, oy0, ox1, oy1 = L["outer"]
        for panel, (x0, y0, x1, y1) in tabs:
            along = (x0, x1, "x", ox0, ox1) if panel.startswith("side") else (y0, y1, "y", oy0, oy1)
            lo, hi, ax, e0, e1 = along
            self.assertGreaterEqual(lo, e0 + cg.WALL + 5)       # clear of the corners
            self.assertLessEqual(hi, e1 - cg.WALL - 5)
            for s in seams[ax]:                                 # clear of the seams
                self.assertFalse(lo - 5 < s < hi + 5, (panel, s))

    def test_dowels_only_in_a_panels_own_plane(self):
        """A 2 mm dowel 2 x PIN_DEPTH long fits a 4 mm panel only along it."""
        L = self.L
        ox0, oy0, ox1, oy1 = L["outer"]
        ix0, iy0, ix1, iy1 = L["interior"]
        for axis, s, a, h in cg._pins(L, "tray"):
            if h < cg.FLOOR:
                continue                                  # in the floor slab
            if axis == "x":                               # along x: in a side wall, or the frame
                self.assertTrue(a < iy0 or a > iy1, (axis, s, a, h))
            else:                                         # along y: back, front, or frame
                self.assertTrue(a > ix1 or ix0 > a, (axis, s, a, h))

    def test_led_bores_run_through_plate_and_wall(self):
        for c in [c for c in self.L["cutouts"] if c["kind"] == "led"]:
            lo, hi = cg.cut_span(c, "x")
            self.assertLess(lo, self.L["front"]["plate_x"])
            self.assertGreater(hi, self.L["outer"][0] + cg.WALL)

    def test_fits_bed(self):
        self.assertTrue(cg.fits_bed(240, 210, 100))
        self.assertTrue(cg.fits_bed(210, 240, 100))     # rotated on the bed
        self.assertFalse(cg.fits_bed(260, 100, 100))
        self.assertFalse(cg.fits_bed(100, 100, 280))


@unittest.skipUnless(HAVE_B3D, "build123d not installed: make case-test")
class Solids(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.L = cg.layout("plain", power="atx")
        cls.tray = cg.build_tray(cls.L)
        cls.lid = cg.build_lid(cls.L)
        cls.plate = cg.build_plate(cls.L)
        cls.parts = cg.split(cls.L, cls.tray, cls.lid, cls.plate)

    def inside(self, solid, x, y, z):
        from build123d import Vector
        return solid.is_inside(Vector(x, y, z))

    def test_standoff_has_an_insert_hole_at_every_mounting_hole(self):
        z = self.L["z"]
        zmid = z["board_bot"] - cg.INSERT_DEPTH / 2
        for r, (hx, hy) in self.L["board"]["holes"].items():
            self.assertFalse(self.inside(self.tray, hx, hy, zmid), r)
            ring = (cg.INSERT_D / 2 + cg.STANDOFF_OD / 2) / 2
            self.assertTrue(self.inside(self.tray, hx + ring, hy, zmid), r)

    def test_slot_cutouts_are_open_and_bars_stand(self):
        cuts = [c for c in self.L["cutouts"] if c["kind"] == "slot"]
        for c in cuts:
            zm = (c["z0"] + c["z1"]) / 2
            self.assertFalse(self.inside(self.tray, c["x"], c["y"], zm), c["ref"])
            bar_y = c["y"] + cg.SLOT_CUT_W / 2 + cg.MIN_BAR / 2
            self.assertTrue(self.inside(self.tray, c["x"], bar_y, zm), c["ref"])

    def test_ob_led_holes_are_open(self):
        for c in [c for c in self.L["cutouts"] if c["kind"] == "led"]:
            zc = (c["z0"] + c["z1"]) / 2
            self.assertFalse(self.inside(self.tray, c["x"], c["y"], zc), c["ref"])
            self.assertTrue(self.inside(self.tray, c["x"], c["y"] + cg.LED_PITCH / 2, zc), c["ref"])

    def test_side_intakes_are_open(self):
        for c in [c for c in self.L["cutouts"] if c["kind"] == "vent"]:
            zm = (c["z0"] + c["z1"]) / 2
            self.assertFalse(self.inside(self.tray, c["x"], c["y"], zm))
            self.assertFalse(self.inside(self.tray, c["x"], c["y"], c["z1"] - 0.5))  # round end
            self.assertTrue(self.inside(self.tray, c["x"] + 1.4, c["y"], c["z1"] - 0.3))  # not square
            self.assertTrue(self.inside(self.tray, c["x"] + cg.VENT_PITCH / 2, c["y"], zm))

    def test_power_cutout_is_open(self):
        c = [c for c in self.L["cutouts"] if c["kind"] == "atx"][0]
        self.assertFalse(self.inside(self.tray, c["x"], c["y"], (c["z0"] + c["z1"]) / 2))

    def test_front_frame(self):
        f = self.L["front"]
        ex, px = f["edge_x"], f["panel_x"]
        top = self.L["z"]["interior_top"]
        full = top + cg.LID_T
        _, oy0, _, _ = self.L["outer"]
        y0, z0, y1, z1 = f["panel"]
        ym, zm = (y0 + y1) / 2, (z0 + z1) / 2
        t = self.tray
        # flat rim: bottom, top (above the tray wall, beside the lid), side
        self.assertTrue(self.inside(t, ex + 0.5, ym, cg.RIM / 2))
        self.assertTrue(self.inside(t, ex + 0.5, ym, full - cg.RIM / 2))
        self.assertTrue(self.inside(t, ex + 0.5, oy0 + cg.RIM / 2, zm))
        # the bevel, half way in, on the bottom: just outside it solid, inside air
        d = cg.BEVEL_D / 2
        zb = cg.RIM + d / math.tan(math.radians(cg.BEVEL_DEG))
        self.assertTrue(self.inside(t, ex + d, ym, zb - 0.5))
        self.assertFalse(self.inside(t, ex + d, ym, zb + 0.5))
        # the ledge (inset lip) stands in the step's depth, the step is air
        xs = ex + cg.BEVEL_D + cg.STEP_D / 2
        self.assertTrue(self.inside(t, xs, ym, z0 - cg.LEDGE / 2))
        self.assertFalse(self.inside(t, xs, ym, z0 + 0.5))
        self.assertFalse(self.inside(t, px - 0.5, ym, zm))     # pocket open to the panel
        self.assertTrue(self.inside(t, px + cg.WALL / 2, ym, zm))   # the flat panel
        self.assertFalse(self.inside(t, self.L["interior"][0] + 1, ym, zm))

    def test_front_face_edges_are_chamfered(self):
        """Rico, 2026-11-06: a second bevel round the outside takes off the
        face's edges (top, bottom, both sides), 45 deg, EDGE_CH each way."""
        f = self.L["front"]
        ex, c = f["edge_x"], cg.EDGE_CH
        full = self.L["z"]["interior_top"] + cg.LID_T
        _, oy0, _, oy1 = self.L["outer"]
        ym, zm = (oy0 + oy1) / 2, (f["panel"][1] + f["panel"][3]) / 2
        t = self.tray
        self.assertTrue(0 < c < cg.RIM)
        for y, z in ((ym, 0.0), (ym, full), (oy0, zm), (oy1, zm)):
            dy = 1 if y == oy0 else -1 if y == oy1 else 0
            dz = 1 if z == 0.0 else -1 if z == full else 0
            # inside the chamfer's corner: air; just behind its plane: solid
            self.assertFalse(self.inside(t, ex + 1, y + dy, z + dz), (y, z))
            self.assertTrue(self.inside(t, ex + c + 0.5, y + 0.5 * dy, z + 0.5 * dz), (y, z))
        # the flat rim is still there, narrower
        self.assertTrue(self.inside(t, ex + 0.5, ym, (c + cg.RIM) / 2))

    def test_lid_butts_the_frame(self):
        f = self.L["front"]
        ym = (self.L["outer"][1] + self.L["outer"][3]) / 2
        self.assertTrue(self.inside(self.lid, f["panel_x"] + 0.5, ym, cg.LID_T / 2))
        self.assertFalse(self.inside(self.lid, f["edge_x"] + 0.5, ym, cg.LID_T / 2))

    def test_roof_bevel_sides_and_back_not_front(self):
        """Rico, 2026-11-06: the lid flush with the front, a long shallow
        bevel down the sides and the back. The bevel runs the full length,
        the front frame's top included; a LID_LAND stays square at the edge."""
        lid = cg.lid_installed(self.L, self.lid)
        top = self.L["z"]["interior_top"]
        full = top + cg.LID_T
        ox0, oy0, ox1, oy1 = self.L["outer"]
        ex = self.L["front"]["edge_x"]
        D, R = cg.LID_BEV_D, cg.LID_BEV_R
        self.assertAlmostEqual(cg.LID_T - D, cg.LID_LAND)
        self.assertLess(math.degrees(math.atan2(D, R)), 20)          # long and shallow
        xm, ym = (ox0 + ox1) / 2, (oy0 + oy1) / 2
        z_edge = full - D + D * 0.5 / R                              # the plane 0.5 in
        for name, pt in (("side", lambda u, z: (xm, oy0 + u, z)),
                         ("side_far", lambda u, z: (xm, oy1 - u, z)),
                         ("back", lambda u, z: (ox1 - u, ym, z))):
            self.assertFalse(self.inside(lid, *pt(0.5, z_edge + 0.7)), name)
            self.assertTrue(self.inside(lid, *pt(0.5, full - D - 0.5)), name)   # the land
            self.assertTrue(self.inside(lid, *pt(R + 1, full - 0.5)), name)     # flat roof
        # front: no bevel, the lid meets the frame flush and square
        self.assertTrue(self.inside(lid, ox0 + 0.5, ym, full - 0.5))
        self.assertTrue(self.inside(self.tray, ex + cg.EDGE_CH + 2, ym, full - 0.5))
        # the side bevel runs on through the frame's top
        self.assertFalse(self.inside(self.tray, ex + cg.EDGE_CH + 2, oy0 + 0.5, z_edge + 0.7))
        self.assertTrue(self.inside(self.tray, ex + cg.EDGE_CH + 2, oy0 + 0.5, full - D - 0.5))
        # solid, never hollow (Rico, 2026-11-06: no part of this computer is)
        self.assertTrue(self.inside(lid, xm, ym, top + 0.5))
        self.assertAlmostEqual(self.lid.volume, cg.build_lid(self.L).volume)

    def test_logo_embosses_on_the_panel_clear_of_the_bores(self):
        logo = cg.build_logo(self.L)
        f = self.L["front"]
        y0, z0, y1, z1 = f["panel"]
        b = cg.brand_panel()
        self.assertEqual(sorted(logo), sorted(b["groups"]))
        for name, solid in logo.items():
            h = b["groups"][name]["h"]
            self.assertTrue(solid.is_valid, name)
            self.assertGreater(solid.volume, 1.0, name)
            bb = solid.bounding_box()
            self.assertAlmostEqual(bb.min.X, f["plate_x"] - h, places=3)
            self.assertAlmostEqual(bb.max.X, f["plate_x"], places=3)
            self.assertGreaterEqual(bb.min.Y, y0 - 1e-6)
            self.assertLessEqual(bb.max.Y, y1 + 1e-6)
            self.assertGreaterEqual(bb.min.Z, z0 - 1e-6)
            self.assertLessEqual(bb.max.Z, z1 + 1e-6)
            for c in [c for c in self.L["cutouts"] if c["kind"] == "led"]:
                zc = (c["z0"] + c["z1"]) / 2
                bore = cg._cut_solid(dict(c, dx=10, dy=cg.LED_D + 1.0))  # bore + 0.5 ring
                self.assertLess((solid & bore).volume, 1e-6, (name, c["ref"]))

    def test_plate(self):
        f = self.L["front"]
        y0, z0, y1, z1 = f["panel"]
        bb = self.plate.bounding_box()
        self.assertAlmostEqual(bb.min.X, f["plate_x"], places=3)
        self.assertAlmostEqual(bb.max.X, f["panel_x"], places=3)
        self.assertAlmostEqual(bb.size.Y, y1 - y0, places=3)
        self.assertAlmostEqual(bb.size.Z, z1 - z0, places=3)
        bores = len([c for c in self.L["cutouts"] if c["kind"] == "led"])
        full = (y1 - y0) * (z1 - z0) * cg.PLATE_T
        self.assertAlmostEqual(self.plate.volume,
                               full - bores * math.pi * (cg.LED_D / 2) ** 2 * cg.PLATE_T, delta=0.5)
        # the plate drops into the frame's seat: no overlap with the tray
        self.assertLess((self.plate & self.tray).volume, 1e-6)

    def test_frame_and_plate_print_face_up_without_overhangs(self):
        """Printed back down (x max on the bed, up = -X): no surface may face
        the bed except the bed face itself."""
        from build123d import GeomType
        for p in self.L["pieces"]:
            if p["part"] not in ("frame", "plate"):
                continue
            solid = self.parts[p["name"]]
            bed = solid.bounding_box().max.X
            for face in solid.faces():
                c = face.center()
                n = face.normal_at(c)
                if abs(c.X - bed) < 1e-3:
                    continue                      # the bed face
                if face.geom_type == GeomType.CYLINDER or face.area < 4:
                    continue                      # bores, dowels and their 2 mm bridged ends
                self.assertLess(n.X, 0.01, (p["name"], c, n))

    def test_frame_is_doweled_to_the_tray_and_across_its_halves(self):
        ox0 = self.L["outer"][0]
        pins = cg._pins(self.L, "tray")
        at_frame = [p for p in pins if p[0] == "x" and p[1] == ox0]
        self.assertGreaterEqual(len(at_frame), 6)
        f = self.L["front"]
        for s in self.L["seams_y"]:
            across = [p for p in pins if p[0] == "y" and p[1] == s and p[2] < ox0]
            self.assertGreaterEqual(len(across), 4)
            for _, _, x, z in across:
                self.assertGreater(x - cg.PIN_D / 2, f["edge_x"] + cg.EDGE_CH)

    def test_corner_fingers_alternate(self):
        L = self.L
        ox0, oy0, ox1, oy1 = L["outer"]
        w = cg.WALL / 2
        names = {p["name"]: p for p in L["pieces"]}
        e = 1.0                                   # off the dowel line in the wall's middle
        corners = {(ox0 + w, oy0 + e): ("side_c0", "front_r0"),
                   (ox1 - w, oy0 + e): (f"side_c{len(L['seams_x'])}", "back_r0"),
                   (ox0 + w, oy1 - e): ("side_far_c0", f"front_r{len(L['seams_y'])}"),
                   (ox1 - w, oy1 - e): (f"side_far_c{len(L['seams_x'])}", f"back_r{len(L['seams_y'])}")}
        for k, (a, b) in enumerate(cg.finger_bands(L)):
            zm = (a + b) / 2
            for (x, y), (side, end) in corners.items():
                own, other = (side, end) if k % 2 == 0 else (end, side)
                self.assertTrue(self.inside(self.parts[own], x, y, zm), (own, k))
                self.assertFalse(self.inside(self.parts[other], x, y, zm), (other, k))

    def test_tabs_go_through_the_floor(self):
        for panel, (x0, y0, x1, y1) in cg.floor_tabs(self.L):
            x, y = (x0 + x1) / 2, (y0 + y1) / 2
            floors = [p["name"] for p in self.L["pieces"] if p.get("panel") == "floor"]
            walls = [p["name"] for p in self.L["pieces"] if p.get("panel") == panel]
            self.assertFalse(any(self.inside(self.parts[n], x, y, cg.FLOOR / 2) for n in floors),
                             (panel, x, y))
            self.assertTrue(any(self.inside(self.parts[n], x, y, cg.FLOOR / 2) for n in walls),
                            (panel, x, y))

    def test_panels_are_panels(self):
        """Each wall piece is WALL thick, its tabs reach the floor's
        underside; each floor piece is the slab plus what stands inside."""
        ix0, iy0, ix1, iy1 = self.L["interior"]
        for p in self.L["pieces"]:
            if p["part"] != "tray":
                continue
            bb = self.parts[p["name"]].bounding_box()
            if p["panel"] == "floor":
                self.assertAlmostEqual(bb.min.Z, 0.0, places=3)
                self.assertLessEqual(bb.max.Z, self.L["z"]["board_bot"] + 1e-3, p["name"])
            else:
                self.assertAlmostEqual(bb.min.Z, 0.0, places=3, msg=p["name"])
                thin = bb.size.Y if p["panel"].startswith("side") else bb.size.X
                self.assertAlmostEqual(thin, cg.WALL, places=3, msg=p["name"])

    def test_pieces_are_valid_and_fit_the_bed(self):
        self.assertEqual(len(self.parts), len(self.L["pieces"]))
        for name, solid in self.parts.items():
            self.assertTrue(solid.is_valid, name)
            bb = solid.bounding_box()
            self.assertTrue(cg.fits_bed(bb.size.X, bb.size.Y, bb.size.Z), (name, bb.size))

    def test_pieces_add_up_to_the_whole(self):
        """Only the dowel holes are lost in the cut."""
        part = {p["name"]: p["part"] for p in self.L["pieces"]}
        tray_sum = sum(s.volume for n, s in self.parts.items() if part[n] in ("tray", "frame"))
        lid_sum = sum(s.volume for n, s in self.parts.items() if part[n] == "lid")
        pins = cg.pin_volume(self.L)
        self.assertAlmostEqual(tray_sum, self.tray.volume - pins["tray"], delta=1.0)
        self.assertAlmostEqual(lid_sum, self.lid.volume - pins["lid"], delta=1.0)
        self.assertAlmostEqual(self.parts["plate"].volume, self.plate.volume, delta=1e-3)


if __name__ == "__main__":
    unittest.main()
