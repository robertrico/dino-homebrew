#!/usr/bin/env python3
"""proto_card_gen.py: `dino_proto/`, the prototype slot card.
.git/sdd/PROTO_CARD.md, 2026-11-01.

The card is generated from `bus_gen.BUS` the way card zero was. The proof
is electrical and geometric: kicad-cli's netlist of the generated
schematic carries the bus by name on J1 and 1:1 on J2, the '138 is wired
as the serial card's U101, the shunt selector cannot join two '138
outputs, the strobes come off the '32, and the board outline obeys
Rico's 20 mm overhang cap against the Rev 1.0 mainboard file.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bus_gen as bg  # noqa: E402
import proto_card_gen as pc  # noqa: E402
from kicad_netlist import tokenize, parse, children, child  # noqa: E402

REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
HAVE_KICAD = os.path.exists(KICAD_CLI)

# '32 gates: (in, in, out)
OR_GATES = [("1", "2", "3"), ("4", "5", "6"), ("9", "10", "8"), ("12", "13", "11")]
# '138 outputs O0..O7 by pin, KiCad's 74LS138 symbol
O_PINS = ["15", "14", "13", "12", "11", "10", "9", "7"]


def netlist(proj):
    out = os.path.join(proj, "x.net")
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
                    "-o", out, os.path.join(proj, pc.PROJECT + ".kicad_sch")],
                   check=True, capture_output=True)
    with open(out) as f:
        tree = parse(tokenize(f.read()))
    return {child(n, "name")[1]: {(child(x, "ref")[1], child(x, "pin")[1])
                                  for x in children(n, "node")}
            for n in children(child(tree, "nets"), "net")}


def erc(proj):
    out = os.path.join(proj, "erc.json")
    subprocess.run([KICAD_CLI, "sch", "erc", "--format", "json", "-o", out,
                    os.path.join(proj, pc.PROJECT + ".kicad_sch")], capture_output=True)
    with open(out) as f:
        rep = json.load(f)
    return [(v["severity"], v["type"], [i["description"] for i in v["items"]])
            for s in rep["sheets"] for v in s["violations"]]


def drc(proj, everything=False):
    """(violations, unconnected): errors only, or with `everything` every
    severity plus schematic parity (the routed board on disk is held to
    that: nothing at all)."""
    out = os.path.join(proj, "drc.json")
    sev = ["--schematic-parity"] if everything else ["--severity-error"]
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", *sev,
                    "-o", out, os.path.join(proj, pc.PROJECT + ".kicad_pcb")],
                   capture_output=True)
    with open(out) as f:
        rep = json.load(f)
    viol = [(v["severity"], v["type"], [i["description"] for i in v["items"]]) for v in rep["violations"]]
    viol += [("parity", v["type"], [i["description"] for i in v["items"]]) for v in rep.get("schematic_parity", [])]
    return viol, rep["unconnected_items"]


def net_of(nets, ref, pin):
    for name, nodes in nets.items():
        if (ref, pin) in nodes:
            return name
    return None


@unittest.skipUnless(HAVE_KICAD, "kicad-cli")
class TestCard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        shutil.copytree(os.path.join(REPO, "dino_bus"), os.path.join(cls.tmp, "dino_bus"))
        pc.write(cls.tmp)
        cls.proj = os.path.join(cls.tmp, pc.PROJECT)
        cls.nets = netlist(cls.proj)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    # --- the edge and the breakout ---------------------------------------
    def test_j1_carries_every_bus_signal_by_name(self):
        for pin, name, kind in bg.BUS:
            if kind == "spare":
                continue
            self.assertEqual(net_of(self.nets, "J1", str(pin)), name, f"J1 pin {pin}")

    def test_j2_is_the_edge_one_to_one(self):
        for pin, _, _ in bg.BUS:
            a, b = net_of(self.nets, "J1", str(pin)), net_of(self.nets, "J2", str(pin))
            self.assertIsNotNone(a, f"J1 pin {pin} floating")
            self.assertEqual(a, b, f"pin {pin}: J1 on {a}, J2 on {b}")

    def test_spare_pins_reach_only_the_breakout(self):
        for pin, name, kind in bg.BUS:
            if kind != "spare":
                continue
            nodes = self.nets[net_of(self.nets, "J1", str(pin))]
            self.assertEqual(nodes, {("J1", str(pin)), ("J2", str(pin))}, f"pin {pin}")

    # --- the decoder, as the serial card's U101 -----------------------------
    def test_u1_is_wired_like_the_serial_cards_u101(self):
        want = {"1": "M11", "2": "M12", "3": "M13", "4": "~{IO_SEL}",
                "5": "GND", "6": "+5V", "8": "GND", "16": "+5V"}
        for pin, name in want.items():
            self.assertEqual(net_of(self.nets, "U1", pin), name, f"U1 pin {pin}")

    def test_u1_decouples_on_c1(self):
        self.assertEqual({net_of(self.nets, "C1", "1"), net_of(self.nets, "C1", "2")},
                         {"+5V", "GND"})

    # --- the shunt selector -------------------------------------------------
    def test_each_138_output_reaches_its_own_jp1_column(self):
        for n, pin in enumerate(O_PINS):
            net = net_of(self.nets, "U1", pin)
            self.assertEqual(net, f"O{n}", f"U1 pin {pin}")
            self.assertIn(("JP1", str(2 * n + 1)), self.nets[net], f"O{n} -> JP1 row A")

    def test_no_two_138_outputs_share_a_net(self):
        nets = [net_of(self.nets, "U1", p) for p in O_PINS]
        self.assertEqual(len(set(nets)), 8)
        for n in nets:
            self.assertEqual(sum(1 for r, p in self.nets[n] if r == "U1"), 1, n)

    def test_jp1_row_b_is_card_sel_with_its_pull_up(self):
        sel = self.nets["~{CARD_SEL}"]
        for n in range(8):
            self.assertIn(("JP1", str(2 * n + 2)), sel, f"JP1 column {n} row B")
        r1 = [p for r, p in sel if r == "R1"]
        self.assertEqual(len(r1), 1, "R1 on ~{CARD_SEL} once")
        other = "2" if r1[0] == "1" else "1"
        self.assertEqual(net_of(self.nets, "R1", other), "+5V")

    # --- the strobes --------------------------------------------------------
    def _gate_of(self, out_net):
        outs = [p for r, p in self.nets[out_net] if r == "U2"]
        self.assertEqual(len(outs), 1, out_net)
        for a, b, y in OR_GATES:
            if y == outs[0]:
                return a, b
        self.fail(f"{out_net}: U2 pin {outs[0]} is not a '32 output")

    def test_card_rd_is_card_sel_or_io_rd_q(self):
        a, b = self._gate_of("~{CARD_RD}")
        self.assertEqual({net_of(self.nets, "U2", a), net_of(self.nets, "U2", b)},
                         {"~{CARD_SEL}", "~{IO_RD_Q}"})

    def test_card_wr_is_card_sel_or_io_wr(self):
        a, b = self._gate_of("~{CARD_WR}")
        self.assertEqual({net_of(self.nets, "U2", a), net_of(self.nets, "U2", b)},
                         {"~{CARD_SEL}", "~{IO_WR}"})

    def test_spare_32_gates_are_pulled_and_on_j4(self):
        used = {self._gate_of("~{CARD_RD}"), self._gate_of("~{CARD_WR}")}
        spare = [g for g in OR_GATES if (g[0], g[1]) not in used]
        self.assertEqual(len(spare), 2)
        pulls = set()
        for a, b, y in spare:
            na, nb, ny = (net_of(self.nets, "U2", p) for p in (a, b, y))
            on_j4 = [n for n in (na, nb) if any(r == "J4" for r, _ in self.nets[n])]
            pulled = [n for n in (na, nb) if any(r in ("R2", "R3") for r, _ in self.nets[n])]
            self.assertEqual(len(on_j4), 1, f"gate {a}/{b}: one input on J4")
            self.assertEqual(len(pulled), 1, f"gate {a}/{b}: one input pulled")
            self.assertTrue(any(r == "J4" for r, _ in self.nets[ny]), f"gate out {y} on J4")
            pulls.update(r for r, _ in self.nets[pulled[0]] if r in ("R2", "R3"))
        self.assertEqual(pulls, {"R2", "R3"})
        for r in ("R2", "R3"):
            self.assertIn("+5V", {net_of(self.nets, r, "1"), net_of(self.nets, r, "2")})

    def test_u2_power_and_decoupling(self):
        self.assertEqual(net_of(self.nets, "U2", "14"), "+5V")
        self.assertEqual(net_of(self.nets, "U2", "7"), "GND")
        self.assertEqual({net_of(self.nets, "C2", "1"), net_of(self.nets, "C2", "2")},
                         {"+5V", "GND"})

    # --- J3 -----------------------------------------------------------------
    def test_j3_breakout_order(self):
        want = ["~{CARD_SEL}", "~{CARD_RD}", "~{CARD_WR}"] + [f"O{n}" for n in range(8)] + ["GND"]
        for i, name in enumerate(want, 1):
            self.assertEqual(net_of(self.nets, "J3", str(i)), name, f"J3 pin {i}")

    # --- rails --------------------------------------------------------------
    def test_rail_bars_are_on_their_rails(self):
        for ref, rail in pc.RAILS:
            self.assertEqual(net_of(self.nets, ref, "1"), rail, ref)

    def test_bulk_cap_on_5v(self):
        self.assertEqual({net_of(self.nets, "C3", "1"), net_of(self.nets, "C3", "2")}, {"+5V", "GND"})

    # --- the card gives nothing back ----------------------------------------
    def test_no_bus_signal_meets_another_bus_signal(self):
        signals = {name for _, name, kind in bg.BUS if kind in ("signal", "reserved")}
        for name in signals:
            refs = {r for r, _ in self.nets[name]}
            self.assertTrue(refs <= {"J1", "J2", "U1", "U2"}, f"{name} reaches {refs - {'J1', 'J2'}}")

    # --- checks ---------------------------------------------------------------
    def test_erc_is_silent(self):
        self.assertEqual(erc(self.proj), [])

    def test_drc_has_no_violations_before_routing(self):
        violations, _ = drc(self.proj)
        self.assertEqual(violations, [])

    def test_rerun_is_byte_identical(self):
        before = {}
        for root, _, files in os.walk(self.proj):
            for fn in files:
                if fn.endswith((".kicad_sch", ".kicad_pcb", ".kicad_pro", ".kicad_mod", "-table")):
                    p = os.path.join(root, fn)
                    with open(p, "rb") as f:
                        before[p] = f.read()
        pc.write(self.tmp)
        for p, b in before.items():
            with open(p, "rb") as f:
                self.assertEqual(f.read(), b, p)


@unittest.skipUnless(HAVE_KICAD, "kicad-cli")
class TestBoard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        shutil.copytree(os.path.join(REPO, "dino_bus"), os.path.join(cls.tmp, "dino_bus"))
        pc.write(cls.tmp)
        with open(os.path.join(cls.tmp, pc.PROJECT, pc.PROJECT + ".kicad_pcb")) as f:
            cls.pcb = parse(tokenize(f.read()))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def _edge_pts(self):
        pts = []
        for node in self.pcb:
            if not isinstance(node, list) or not node or not str(node[0]).startswith("gr_"):
                continue
            if child(node, "layer")[1] != "Edge.Cuts":
                continue
            for k in ("start", "end", "mid"):
                v = child(node, k)
                if v:
                    pts.append((float(v[1]), float(v[2])))
            for p in children(node, "pts"):
                for xy in children(p, "xy"):
                    pts.append((float(xy[1]), float(xy[2])))
        return pts

    def _footprints(self):
        out = {}
        for node in children(self.pcb, "footprint"):
            ref = next(p[2] for p in children(node, "property") if p[1] == "Reference")
            out[ref] = node
        return out

    def test_outline_is_body_plus_tab(self):
        pts = self._edge_pts()
        w = max(x for x, _ in pts) - min(x for x, _ in pts)
        h = max(y for _, y in pts) - min(y for _, y in pts)
        self.assertAlmostEqual(w, pc.WIDTH, 3)
        self.assertAlmostEqual(h, pc.HEIGHT + pc.TAB_H, 3)

    def test_no_footprint_carries_edge_cuts(self):
        for ref, node in self._footprints().items():
            for item in node:
                if isinstance(item, list) and str(item[0]).startswith("fp_"):
                    layer = child(item, "layer")
                    self.assertNotEqual(layer and layer[1], "Edge.Cuts", ref)

    def test_overhang_is_under_ricos_cap(self):
        """20 mm past the tab on either side, and under 20 mm past the
        mainboard's right edge."""
        left, right = pc.card_span(REPO)
        geo = pc.mainboard_geometry(REPO)
        tab_l, tab_r = geo["socket_x"] - pc.TAB_W / 2, geo["socket_x"] + pc.TAB_W / 2
        self.assertLessEqual(right - tab_r, 20.0 - 1e-6, "Rico's cap, measured on cut 2 at 20.23")
        self.assertGreater(tab_l - left, 0)
        self.assertLessEqual(right - geo["edge_x"], pc.OVERHANG_CAP)
        self.assertAlmostEqual(right - left, pc.WIDTH, 3)

    def test_fingers_sit_in_the_tab(self):
        pts = self._edge_pts()
        bottom = max(y for _, y in pts)
        j1 = self._footprints()["J1"]
        at = child(j1, "at")
        self.assertAlmostEqual(float(at[2]), bottom, 3)
        self.assertEqual(j1[1], f"{bg.LIB}:{bg.FP_FINGERS}")

    def test_every_pad_is_netted_or_a_grid_hole(self):
        for ref, node in self._footprints().items():
            for pad in children(node, "pad"):
                net = child(pad, "net")
                if ref.startswith(pc.GRID_REF):
                    self.assertIsNone(net, f"{ref} pad {pad[1]} on a net")
                else:
                    self.assertIsNotNone(net, f"{ref} pad {pad[1]} floating")

    def test_rail_rows_are_square_holes_on_their_nets(self):
        fps = self._footprints()
        for ref, net, y, n in pc.rail_rows():
            pads = children(fps[ref], "pad")
            self.assertEqual(len(pads), n, ref)
            for p in pads:
                self.assertEqual(p[3], "rect", f"{ref}: square")
                self.assertEqual(child(p, "net")[-1], net, ref)

    def test_bands_are_5v_five_free_rows_gnd(self):
        """Every +5V row opens a band: five free rows, then a GND row. A
        0.3in DIP sits on the band's rows 1 and 4, VCC and GND a row away."""
        plus = [r for r, n in pc.ROW_RAIL.items() if n == "+5V" and r + 6 < pc.GRID_ROWS]
        self.assertTrue(plus)
        for r in plus:
            for k in range(1, 6):
                self.assertNotIn(r + k, pc.ROW_RAIL, f"row {r + k} should be free")
            self.assertEqual(pc.ROW_RAIL.get(r + 6), "GND", f"row {r + 6}")

    def test_grid_holes_are_plated_at_the_pitch(self):
        fps = self._footprints()
        grid = [n for r, n in fps.items() if r.startswith(pc.GRID_REF)]
        self.assertTrue(grid)
        pads = [p for g in grid for p in children(g, "pad")]
        self.assertEqual(len(pads), len(pc.grid_holes()))
        self.assertGreaterEqual(len(pads), 300)
        for p in pads:
            self.assertEqual(p[2], "thru_hole")
            self.assertEqual(float(child(p, "drill")[1]), pc.GRID_DRILL)
            self.assertEqual(float(child(p, "size")[1]), pc.GRID_PAD)

    def test_two_copper_layers(self):
        layers = child(self.pcb, "layers")
        cu = [l[1] for l in layers[1:] if l[1].endswith(".Cu")]
        self.assertEqual(cu, ["F.Cu", "B.Cu"])


@unittest.skipUnless(HAVE_KICAD, "kicad-cli")
class TestDisk(unittest.TestCase):
    """The committed dino_proto/: the generator's schematic, frozen, and the
    routed board, DRC clean with nothing left unconnected."""
    proj = os.path.join(REPO, pc.PROJECT)

    def test_schematic_on_disk_is_the_generators(self):
        with open(os.path.join(self.proj, pc.PROJECT + ".kicad_sch")) as f:
            self.assertEqual(f.read(), pc.schematic())

    def test_routed_board_is_drc_silent_and_complete(self):
        """No errors, no warnings, no parity items, nothing unconnected
        (2026-11-02: Rico, "clean up DRC/ERC")."""
        violations, unconnected = drc(self.proj, everything=True)
        self.assertEqual(violations, [])
        self.assertEqual(unconnected, [])

    def test_no_copper_crosses_the_grid(self):
        """The perfboard is the bodge's; no track or via of the fixed copper
        may run through it (a rule area says so to the router and to DRC)."""
        with open(os.path.join(self.proj, pc.PROJECT + ".kicad_pcb")) as f:
            pcb = parse(tokenize(f.read()))
        rects = pc.grid_rects()
        inside = lambda x, y: any(x0 < x < x1 and y0 < y < y1 for x0, y0, x1, y1 in rects)  # noqa: E731
        for t in children(pcb, "segment"):
            sx, sy = (float(v) for v in child(t, "start")[1:3])
            ex, ey = (float(v) for v in child(t, "end")[1:3])
            mx, my = (sx + ex) / 2, (sy + ey) / 2
            self.assertFalse(inside(sx, sy) or inside(ex, ey) or inside(mx, my),
                             f"segment {sx},{sy} -> {ex},{ey} in the grid")
        for v in children(pcb, "via"):
            x, y = (float(c) for c in child(v, "at")[1:3])
            self.assertFalse(inside(x, y), f"via at {x},{y} in the grid")

    def test_routed_board_keeps_every_generated_track(self):
        """Routing adds; it never moves the bus tracks or the bars."""
        with open(os.path.join(self.proj, pc.PROJECT + ".kicad_pcb")) as f:
            pcb = parse(tokenize(f.read()))
        segs = {(child(t, "layer")[1], tuple(child(t, "start")[1:]), tuple(child(t, "end")[1:]))
                for t in children(pcb, "segment")}
        fx = pc.finger_x(REPO)
        want = [(l, pts) for l, _, pts in pc.bus_tracks(fx)] + \
               [(l, pts) for l, _, pts, _ in pc.feed_tracks(fx) + pc.rail_tracks(fx)]
        for lay, pts in want:
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                key = (lay, (f"{x0:g}", f"{y0:g}"), (f"{x1:g}", f"{y1:g}"))
                self.assertIn(key, segs, key)


class TestLibraryFix(unittest.TestCase):
    def test_fingers_footprint_carries_no_edge_cuts(self):
        self.assertNotIn("Edge.Cuts", bg.fingers_footprint())


if __name__ == "__main__":
    unittest.main()
