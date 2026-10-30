#!/usr/bin/env python3
"""bus_gen.py: the peripheral bus, drawn. PERIPHERAL_BUS.md sections 1-3.

  * `dino_bus/`           generated library: the 50-pin symbol (socket and
                          edge flavours) and two footprints
  * core                  `peripheral_bus.kicad_sch`: J1-J8 sockets, one
                          '04 section for CLK_B; `input.kicad_sch` leaves;
                          `input_output.kicad_sch` -> `front_panel.kicad_sch`
  * `dino_io/`            card zero, its own project, the old Input sheet
                          plus edge connector J1

The proof is electrical: core and card netlists, joined through the slot-0
pin numbers, must partition every pre-existing pin exactly as the core's
netlist did before the split. Nothing else counts.
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
import footprint_gen as fg  # noqa: E402
from kicad_netlist import tokenize, parse, children, child  # noqa: E402

REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
CORE = os.path.join(REPO, "dino_v0_0_2")
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
HAVE_KICAD = os.path.exists(KICAD_CLI)


def copy_repo(dst):
    """Enough of the repo for the generators: the core project and, if the
    split already happened on disk, the card and the library."""
    shutil.copytree(CORE, os.path.join(dst, "dino_v0_0_2"),
                    ignore=shutil.ignore_patterns("*-backups", "_autosave-*", "*.lck"))
    for d in ("dino_io", "dino_bus", "dino_serial"):
        if os.path.exists(os.path.join(REPO, d)):
            shutil.copytree(os.path.join(REPO, d), os.path.join(dst, d),
                            ignore=shutil.ignore_patterns("*-backups", "_autosave-*", "*.lck"))


def netlist(proj, name):
    out = os.path.join(proj, "x.net")
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr",
                    "-o", out, os.path.join(proj, name + ".kicad_sch")],
                   check=True, capture_output=True)
    with open(out) as f:
        tree = parse(tokenize(f.read()))
    return {child(n, "name")[1]: {(child(x, "ref")[1], child(x, "pin")[1])
                                  for x in children(n, "node")}
            for n in children(child(tree, "nets"), "net")}


def erc(proj, name):
    out = os.path.join(proj, "erc.json")
    subprocess.run([KICAD_CLI, "sch", "erc", "--format", "json", "-o", out,
                    os.path.join(proj, name + ".kicad_sch")], capture_output=True)
    with open(out) as f:
        rep = json.load(f)
    return [(v["severity"], v["type"], [i["description"] for i in v["items"]])
            for s in rep["sheets"] for v in s["violations"]]


class TestTable(unittest.TestCase):
    def test_fifty_pins_numbered_once(self):
        self.assertEqual([p for p, _, _ in bg.BUS], list(range(1, 51)))

    def test_grounds_bracket_both_buses(self):
        by = {p: n for p, n, _ in bg.BUS}
        self.assertEqual({p for p, n, _ in bg.BUS if n == "GND"}, {7, 16, 17, 26, 44, 50})
        self.assertEqual((by[7], by[8], by[15], by[16]), ("GND", "W0", "W7", "GND"))
        self.assertEqual((by[26], by[28], by[43], by[44]), ("GND", "M0", "M15", "GND"))

    def test_signal_names_are_spelled_as_the_core_spells_them(self):
        core = set()
        for f in fg.sheets(CORE):
            core |= bg.label_names(f)
        for _, n, kind in bg.BUS:
            if kind == "signal" and n != "CLK_B":
                self.assertIn(n, core, n)

    def test_the_agreed_pins(self):
        by = {p: n for p, n, _ in bg.BUS}
        self.assertEqual(by[3], "~{IO_SEL}")
        # CLK_B at the row end (Rico 2026-10-29): mid-row pin 17 forced every
        # slot-to-slot hop round the other row's end at CLK clearance (~510 mm);
        # pin 1 runs straight down the slot column, +5V beside, GND across.
        self.assertEqual((by[1], by[2], by[26]), ("CLK_B", "+5V", "GND"))
        self.assertEqual(by[17], "GND")
        self.assertEqual([by[p] for p in range(8, 16)], [f"W{i}" for i in range(8)])
        self.assertEqual([by[p] for p in range(28, 44)], [f"M{i}" for i in range(16)])
        self.assertEqual((by[45], by[46], by[47], by[48]), ("+12V", "-12V", "spare", "+3.3V"))


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        bg.write_library(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_symbols_carry_all_fifty_pins_named_by_signal(self):
        with open(os.path.join(self.tmp, "dino_bus", "dino_bus.kicad_sym")) as f:
            tree = parse(tokenize(f.read()))
        names = {s[1] for s in children(tree, "symbol")}
        self.assertEqual(names, {"DINO_BUS_SOCKET", "DINO_BUS_EDGE"})
        for s in children(tree, "symbol"):
            pins = {child(p, "number")[1]: child(p, "name")[1]
                    for sub in children(s, "symbol") for p in children(sub, "pin")}
            self.assertEqual(pins, {str(p): n for p, n, _ in bg.BUS})

    def test_footprints_have_fifty_pads_and_a_courtyard(self):
        for name in ("EdgeFingers_2x25_P2.54mm", "EdgeSocket_2x25_P2.54mm_THT"):
            path = os.path.join(self.tmp, "dino_bus", "dino_bus.pretty", name + ".kicad_mod")
            with open(path) as f:
                tree = parse(tokenize(f.read()))
            self.assertEqual({p[1] for p in children(tree, "pad")}, {str(i) for i in range(1, 51)})
            self.assertTrue(any(child(n, "layer") and child(n, "layer")[1] == "F.CrtYd"
                                for n in tree if isinstance(n, list) and str(n[0]).startswith("fp_")))

    def test_socket_matches_sullins_ebc25dcwn(self):
        # Sullins catalog p.54-55 (.100 HP DS WW RA CE): 2x25, .100 pitch,
        # .200 row to row; CW tail fits min hole .035 (0.89), CS fits .040
        # (1.02): drill 1.1 takes either. Insulator C = 70.10 mm (no ears).
        path = os.path.join(self.tmp, "dino_bus", "dino_bus.pretty",
                            "EdgeSocket_2x25_P2.54mm_THT.kicad_mod")
        with open(path) as f:
            src = f.read()
        tree = parse(tokenize(src))
        pads = {p[1]: p for p in children(tree, "pad")}
        at = lambda n: tuple(float(v) for v in child(pads[n], "at")[1:3])
        self.assertAlmostEqual(at("26")[1] - at("1")[1], 5.08)        # row to row
        self.assertAlmostEqual(at("2")[0] - at("1")[0], 2.54)         # pitch
        self.assertEqual(at("1")[0], at("26")[0])                     # n opposite n+25
        for p in pads.values():
            self.assertAlmostEqual(float(child(p, "drill")[1]), 1.1)
            self.assertAlmostEqual(float(child(p, "size")[1]), 1.7)
        crt = [n for n in tree if isinstance(n, list) and n[0] == "fp_rect"
               and child(n, "layer")[1] == "F.CrtYd"][0]
        x0, x1 = float(child(crt, "start")[1]), float(child(crt, "end")[1])
        self.assertGreaterEqual(x1 - x0, 70.10)
        self.assertIn("EBC25DCWN", src)
        self.assertNotIn("PLACEHOLDER", src)
        # the socket is unkeyed and a reversed card shorts +5V: silk outline
        # plus a pin-1 mark outside the outline at pin 1's end (Rico 2026-10-29)
        silk = [n for n in tree if isinstance(n, list) and str(n[0]).startswith("fp_")
                and child(n, "layer") and child(n, "layer")[1] == "F.SilkS"]
        rects = [n for n in silk if n[0] == "fp_rect"]
        self.assertEqual(len(rects), 1)
        sx0 = float(child(rects[0], "start")[1])
        sy0 = float(child(rects[0], "start")[2])
        self.assertLess(sx0, at("1")[0] - 1.7)                        # outline clears pin 1
        marks = [n for n in silk if n[0] == "fp_poly"]
        self.assertEqual(len(marks), 1)
        xs = [float(p[1]) for p in children(child(marks[0], "pts"), "xy")]
        ys = [float(p[2]) for p in children(child(marks[0], "pts"), "xy")]
        self.assertLess(max(ys), sy0)                                 # above the outline...
        self.assertLess(abs(sum(xs) / len(xs) - at("1")[0]), 1.5)    # ...over pin 1
        # Rico's Sullins STEP (inch, Y up, top of insulator at y=0): stood up
        # about X and lifted by the insulator height so it sits on the board.
        model = child(tree, "model")
        self.assertTrue(model and model[1].endswith("dino_bus.3dshapes/EBC25DCWN_color.step"))
        self.assertEqual([float(v) for v in child(child(model, "offset"), "xyz")[1:]], [0.0, 0.0, 15.49])
        self.assertEqual([float(v) for v in child(child(model, "rotate"), "xyz")[1:]], [-90.0, 0.0, 0.0])


class TestFlatten(unittest.TestCase):
    def test_a_card_ref_that_repeats_a_core_ref_stays_its_own_part(self):
        # 2026-10-06 the ALU board took U76 ('157); card zero's '138 is U76
        # too. Joined by name, the two chips' pins merged and +5V met GND.
        core = {"VCC": {("U76", "16"), ("C1", "1")},
                "GND": {("U76", "8"), ("C1", "2")}}
        # one card net touching both pin numbers: by name, core VCC and GND
        card = {"N": {("U76", "8"), ("R1", "1"), ("U76", "16")}}
        parts = bg.flatten(core, {0: card})
        self.assertFalse(any({("C1", "1"), ("C1", "2")} <= set(s) for s in parts))


@unittest.skipUnless(HAVE_KICAD, "KiCad 10 not installed")
class TestSplit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        copy_repo(cls.tmp)
        cls.core = os.path.join(cls.tmp, "dino_v0_0_2")
        cls.card = os.path.join(cls.tmp, "dino_io")
        cls.before = netlist(cls.core, "dino_v0_0_2")
        cls.report = bg.run(cls.tmp)
        cls.core_after = netlist(cls.core, "dino_v0_0_2")
        cls.card_after = netlist(cls.card, "dino_io")
        cls.core_erc = erc(cls.core, "dino_v0_0_2")
        cls.card_erc = erc(cls.card, "dino_io")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_input_sheet_is_gone_from_the_core_and_front_panel_is_renamed(self):
        files = os.listdir(self.core)
        self.assertNotIn("input.kicad_sch", files)
        self.assertNotIn("input_output.kicad_sch", files)
        self.assertIn("front_panel.kicad_sch", files)
        self.assertIn("peripheral_bus.kicad_sch", files)
        with open(os.path.join(self.core, "dino_v0_0_2.kicad_sch")) as f:
            root = f.read()
        self.assertNotIn('"input.kicad_sch"', root)
        self.assertIn('"front_panel.kicad_sch"', root)
        self.assertIn('"peripheral_bus.kicad_sch"', root)

    def test_card_zero_holds_exactly_the_old_input_parts_plus_its_edge(self):
        refs = {r for pins in self.card_after.values() for r, _ in pins}
        self.assertEqual(refs, {"SW1", "U76", "SWITCH-GATE1", "R17", "R18", "R19",
                                "R20", "R21", "R22", "R23", "R24", "C48", "C81", "J1"})

    def test_joined_through_slot_zero_nothing_electrical_changed(self):
        # The split is in the tree since 2026-09-12, so `before` is already
        # split: compare the core alone, slots and card parts left out on
        # both sides. Plugging card zero into slot zero must not join or
        # break any core net.
        new = {f"J{i}" for i in range(1, 9)} | {"U78"}

        def core_only(nets):
            out = {frozenset(p for p in s if p[0] not in new and "@card" not in p[0])
                   for s in nets}
            return {s for s in out if s}
        got = core_only(bg.flatten(self.core_after, {0: self.card_after}))
        want = core_only(self.before.values())
        self.assertEqual(sorted(map(sorted, got - want)), [])
        self.assertEqual(sorted(map(sorted, want - got)), [])

    def test_every_bus_signal_reaches_all_eight_sockets(self):
        for p, n, kind in bg.BUS:
            if kind in ("signal", "power", "reserved") and n != "CLK_B":
                net = [pins for pins in self.core_after.values()
                       if ("J1", str(p)) in pins]
                self.assertEqual(len(net), 1, n)
                self.assertTrue({(f"J{i}", str(p)) for i in range(1, 9)} <= net[0], n)

    def test_clk_b_is_one_gate_off_the_inverted_clock(self):
        # U78.2 -> R34 (100R series, S4.2) -> CLK_B on every slot's pin 1
        out = [s for s in self.core_after.values() if ("U78", "2") in s][0]
        self.assertIn(("R34", "1"), out)
        clk_b = [s for s in self.core_after.values() if ("R34", "2") in s][0]
        self.assertEqual({p for r, p in clk_b if r.startswith("J")}, {"1"})
        self.assertEqual({r for r, p in clk_b if r.startswith("J")}, {"J%d" % i for i in range(1, 9)})
        src = [s for s in self.core_after.values() if ("U78", "1") in s][0]
        self.assertIn(("U27", "6"), src)          # ~{CLK}

    def test_card_zero_edge_follows_the_bus_pinout(self):
        # 2026-10-29 CLK_B moved to pin 1, GND to 17; card zero was written
        # 09-12 on the old table. Every taken pin carries its bus name, and
        # nothing else on the edge is wired (Rico 2026-10-30: redraw it).
        name = {}
        for net, pins in self.card_after.items():
            for r, p in pins:
                if r == "J1":
                    name[int(p)] = net
        for pin, n, kind in bg.BUS:
            if kind != "spare" and n in bg.CARD_ZERO_TAKES:
                self.assertEqual(name.get(pin), n, pin)
            else:
                self.assertTrue(name.get(pin, "unconnected").startswith("unconnected"),
                                (pin, n, name.get(pin)))

    def test_erc_core_zero_errors_zero_warnings(self):
        self.assertEqual([v for v in self.core_erc if v[0] == "error"], [])
        self.assertEqual([v for v in self.core_erc if v[0] == "warning"], [])

    def test_erc_card_zero_errors(self):
        self.assertEqual([v for v in self.card_erc if v[0] == "error"], [])

    def test_every_symbol_in_both_projects_has_a_footprint_that_exists(self):
        for proj in (self.core, self.card):
            libs = fg.footprint_libs(proj)
            for i in fg.inventory(fg.sheets(proj)):
                self.assertTrue(i.footprint, i)
                self.assertTrue(fg.footprint_exists(i.footprint, libs), i)

    def test_run_is_idempotent(self):
        snap = {p: open(p).read() for p in fg.sheets(self.core) + fg.sheets(self.card)}
        bg.run(self.tmp)
        self.assertEqual({p: open(p).read() for p in fg.sheets(self.core) + fg.sheets(self.card)}, snap)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
