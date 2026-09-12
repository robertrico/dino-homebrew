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
        self.assertEqual({p for p, n, _ in bg.BUS if n == "GND"}, {1, 7, 16, 26, 44, 50})
        self.assertEqual((by[7], by[8], by[15], by[16]), ("GND", "W0", "W7", "GND"))
        self.assertEqual((by[26], by[28], by[43], by[44]), ("GND", "M0", "M15", "GND"))
        self.assertEqual((by[1], by[26]), ("GND", "GND"))   # the one true opposite pair

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
        self.assertEqual(by[17], "CLK_B")
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
        new = {f"J{i}" for i in range(1, 9)} | {"U78"}
        got = bg.flatten(self.core_after, {0: self.card_after})
        got = {frozenset(p for p in s if p[0] not in new and p[0] != "J1@card")
               for s in got}
        got = {s for s in got if s}
        want = {frozenset(pins) for pins in self.before.values()}
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
        pins = [s for s in self.core_after.values() if ("U78", "2") in s][0]
        self.assertIn(("J1", "17"), pins)
        src = [s for s in self.core_after.values() if ("U78", "1") in s][0]
        self.assertIn(("U27", "6"), src)          # ~{CLK}

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
