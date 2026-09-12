#!/usr/bin/env python3
"""pcb_gen.py: a first-draft board for dino_v0_0_2 -- every footprint
placed, every pad on its net, one outline, no tracks.

The placement is a starting point for hand layout, not a layout. What the
tests pin down is that nothing is missing and nothing is on top of
anything else: a footprint dropped here is a chip missing from the PCB.

Needs the KiCad 10 install for the netlist export and the pcbnew build;
those tests skip when it is absent, and say so.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcb_gen as pg  # noqa: E402
import footprint_gen as fg  # noqa: E402
from kicad_netlist import tokenize, parse, children, child  # noqa: E402

PROJ = os.path.join(HERE, "..", "..", "dino_v0_0_2")
HAVE_KICAD = os.path.exists(pg.KICAD_CLI) and os.path.exists(pg.KICAD_PY)

_NET = {}


def netlist():
    """One export per test run; kicad-cli is slow."""
    if "path" not in _NET:
        d = tempfile.mkdtemp()
        _NET["path"] = pg.export_netlist(PROJ, os.path.join(d, "dino.net"))
    return _NET["path"]


@unittest.skipUnless(HAVE_KICAD, "KiCad 10 not installed")
class TestNetlist(unittest.TestCase):
    def test_every_schematic_ref_is_one_component_with_a_footprint(self):
        comps, nets = pg.read_netlist(netlist())
        refs = sorted(c.ref for c in comps)
        want = sorted({i.ref for i in fg.inventory(fg.sheets(PROJ))})
        self.assertEqual(refs, want)
        self.assertEqual([c.ref for c in comps if not c.footprint], [])

    def test_every_component_has_a_sheet_path_for_update_from_schematic(self):
        comps, _ = pg.read_netlist(netlist())
        bad = [c.ref for c in comps
               if not c.path.startswith("/") or c.path.endswith("/")]
        self.assertEqual(bad, [])
        self.assertEqual(len({c.path for c in comps}), len(comps))

    def test_nets_carry_nodes_on_known_refs(self):
        comps, nets = pg.read_netlist(netlist())
        refs = {c.ref for c in comps}
        self.assertGreater(len(nets), 500)
        stray = [(n.name, r, p) for n in nets for r, p in n.nodes
                 if r not in refs]
        self.assertEqual(stray, [])
        self.assertIn("+5V", {n.name for n in nets})
        self.assertIn("GND", {n.name for n in nets})


class TestPlace(unittest.TestCase):
    def comps(self):
        # synthetic: two sheets, mixed sizes, enough to force wrapping
        out = []
        for i in range(30):
            out.append(pg.Comp(f"U{i}", "74LS245", "Package_DIP:DIP-20_W7.62mm",
                               "A" if i < 15 else "B", f"/x/{i}"))
        for i in range(40):
            out.append(pg.Comp(f"C{i}", "0.1µF",
                               "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P2.50mm",
                               "A" if i < 20 else "B", f"/y/{i}"))
        out.append(pg.Comp("U99", "AT28C256", "Package_DIP:DIP-28_W15.24mm",
                           "B", "/z/0"))
        return out

    def test_every_component_is_placed_once(self):
        comps = self.comps()
        pl = pg.place(comps)
        self.assertEqual(sorted(pl), sorted(c.ref for c in comps))

    def test_no_two_courtyards_overlap(self):
        comps = self.comps()
        pl = pg.place(comps)
        self.assertEqual(pg.overlaps(comps, pl), [])

    def test_everything_sits_inside_the_outline(self):
        comps = self.comps()
        pl = pg.place(comps)
        x0, y0, x1, y1 = pg.outline(comps, pl)
        for c in comps:
            bx0, by0, bx1, by1 = pg.bbox(c, pl[c.ref])
            self.assertLessEqual(x0, bx0, c.ref)
            self.assertLessEqual(y0, by0, c.ref)
            self.assertGreaterEqual(x1, bx1, c.ref)
            self.assertGreaterEqual(y1, by1, c.ref)

    def test_unknown_footprint_size_is_refused(self):
        with self.assertRaises(KeyError):
            pg.envelope("Package_DIP:DIP-99_W7.62mm")

    def test_envelope_comes_from_the_courtyard_not_a_table(self):
        # 2026-09-12: a hand table had DIPs long along X; KiCad's are long
        # along Y, and the first render showed every IC row overlapping.
        x0, y0, x1, y1 = pg.envelope("Package_DIP:DIP-20_W7.62mm")
        self.assertGreater(y1 - y0, x1 - x0)
        self.assertGreater(y1 - y0, 25)
        # resistor courtyard is off-centre: origin is pad 1
        x0, y0, x1, y1 = pg.envelope(
            "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal")
        self.assertLess(abs(x0), 3)
        self.assertGreater(x1, 10)

    def test_sheets_do_not_interleave(self):
        comps = self.comps()
        pl = pg.place(comps)
        a = [pg.bbox(c, pl[c.ref]) for c in comps if c.sheet == "A"]
        b = [pg.bbox(c, pl[c.ref]) for c in comps if c.sheet == "B"]
        ax1 = max(r[2] for r in a); bx0 = min(r[0] for r in b)
        ay1 = max(r[3] for r in a); by0 = min(r[1] for r in b)
        self.assertTrue(ax1 <= bx0 or ay1 <= by0)


@unittest.skipUnless(HAVE_KICAD, "KiCad 10 not installed")
class TestBuild(unittest.TestCase):
    def test_board_holds_every_footprint_with_every_pad_on_its_net(self):
        comps, nets = pg.read_netlist(netlist())
        out = os.path.join(tempfile.mkdtemp(), "draft.kicad_pcb")
        pg.build(netlist(), out, PROJ)
        tree = parse(tokenize(open(out).read()))
        fps = children(tree, "footprint")
        self.assertEqual(sorted(_ref(f) for f in fps),
                         sorted(c.ref for c in comps))
        want = {}
        for n in nets:
            for r, p in n.nodes:
                want[(r, p)] = n.name
        got = {}
        for f in fps:
            ref = _ref(f)
            for pad in children(f, "pad"):
                net = child(pad, "net")
                if net:
                    got[(ref, pad[1])] = net[-1]
        self.assertEqual(got, want)
        self.assertTrue(any(child(g, "layer")[1] == "Edge.Cuts"
                            for g in children(tree, "gr_rect")))

    def test_build_does_not_write_a_project_file(self):
        # 2026-09-12: SaveBoard's default wrote a fresh .kicad_pro beside the
        # board -- 433 lines of ERC pin map and DRC rules gone.
        d = tempfile.mkdtemp()
        out = os.path.join(d, "draft.kicad_pcb")
        pg.build(netlist(), out, PROJ)
        self.assertEqual(sorted(os.listdir(d)), ["draft.kicad_pcb"])


def _ref(fp):
    for p in children(fp, "property"):
        if p[1] == "Reference":
            return p[2]
    raise AssertionError("footprint without Reference")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
