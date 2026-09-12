#!/usr/bin/env python3
"""power_sheet_gen.py: the core gets a Power sheet -- one 24-pin ATX header
the picoPSU plugs into, its rails on the project's power nets, PS_ON# on a
2-pin header for the panel switch.

Rico, 2026-09-12: power is off the shelf (picoPSU-160-XT or -120-WI-25).
Rails on the sheet are exactly what those deliver: +5V, +3.3V, +12V, -12V,
GND. No -5V, no regulator on the core.
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
import power_sheet_gen as psg  # noqa: E402
import footprint_gen as fg  # noqa: E402
from kicad_netlist import tokenize, parse, children, child  # noqa: E402

PROJ = os.path.join(HERE, "..", "..", "dino_v0_0_2")
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
HAVE_KICAD = os.path.exists(KICAD_CLI)

ATX_RAILS = {
    "+3.3V": {"1", "2", "12", "13"},
    "+5V": {"4", "6", "21", "22", "23"},
    "+12V": {"10", "11"},
    "-12V": {"14"},
    "GND": {"3", "5", "7", "15", "17", "18", "19", "24"},
}


def symbols(tree):
    out = {}
    for s in children(tree, "symbol"):
        props = {p[1]: p[2] for p in children(s, "property") if len(p) > 2}
        out[props["Reference"]] = (child(s, "lib_id")[1], props)
    return out


class TestSheet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for f in fg.sheets(PROJ) + [os.path.join(PROJ, "dino_v0_0_2.kicad_pro"),
                                    os.path.join(PROJ, "fp-lib-table"),
                                    os.path.join(PROJ, "sym-lib-table")]:
            shutil.copy(f, self.tmp)
        psg.unlink(self.tmp)          # the generator, not the checked-in file
        psg.generate(self.tmp)
        with open(os.path.join(self.tmp, "power.kicad_sch")) as f:
            self.tree = parse(tokenize(f.read()))
        with open(os.path.join(self.tmp, "dino_v0_0_2.kicad_sch")) as f:
            self.root = parse(tokenize(f.read()))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_atx_header_with_footprint_and_all_24_pins(self):
        syms = symbols(self.tree)
        lib, props = syms[psg.ATX_REF]
        self.assertEqual(lib, "Connector:ATX-24")
        self.assertEqual(props["Footprint"], fg.assign(lib, props["Value"]))
        atx = [s for s in children(self.tree, "symbol")
               if child(s, "lib_id")[1] == "Connector:ATX-24"][0]
        self.assertEqual({p[1] for p in children(atx, "pin")},
                         {str(n) for n in range(1, 25)})

    def test_ps_on_header_present(self):
        syms = symbols(self.tree)
        lib, props = syms[psg.PSON_REF]
        self.assertEqual(lib, "Connector_Generic:Conn_01x02")
        self.assertTrue(props["Footprint"])

    def test_only_the_rails_the_picopsu_delivers(self):
        rails = {props["Value"] for lib, props in symbols(self.tree).values()
                 if lib.startswith("power:")}
        self.assertEqual(rails, {"+5V", "+3.3V", "+12V", "-12V", "GND"})

    def test_every_embedded_lib_symbol_is_defined(self):
        used = {child(s, "lib_id")[1] for s in children(self.tree, "symbol")}
        defined = {s[1] for s in children(child(self.tree, "lib_symbols"),
                                          "symbol")}
        self.assertEqual(used - defined, set())

    def test_root_sheet_links_the_power_page(self):
        blocks = [sh for sh in children(self.root, "sheet")
                  if any(p[1] == "Sheetfile" and p[2] == "power.kicad_sch"
                         for p in children(sh, "property"))]
        self.assertEqual(len(blocks), 1)
        pages = [child(child(child(sh, "instances"), "project"), "path")
                 for sh in children(self.root, "sheet")]
        nums = [int(child(p, "page")[1]) for p in pages]
        self.assertEqual(len(nums), len(set(nums)))

    def test_every_line_has_balanced_quotes(self):
        # the failure mode KiCad reports as nothing at all
        with open(os.path.join(self.tmp, "power.kicad_sch")) as f:
            for i, line in enumerate(f, 1):
                self.assertEqual(line.replace('\\"', "").count('"') % 2, 0,
                                 (i, line))

    def test_note_newlines_are_single_escaped(self):
        # 2026-09-12: `\\n` in the file rendered as a literal backslash-n
        with open(os.path.join(self.tmp, "power.kicad_sch")) as f:
            src = f.read()
        self.assertNotIn("\\\\n", src)
        self.assertIn("\\n", src)

    def test_generate_is_idempotent(self):
        before = open(os.path.join(self.tmp, "dino_v0_0_2.kicad_sch")).read()
        psg.generate(self.tmp)
        after = open(os.path.join(self.tmp, "dino_v0_0_2.kicad_sch")).read()
        self.assertEqual(before, after)
        blocks = [sh for sh in children(self.root, "sheet")]
        self.assertEqual(len(blocks), 12)

    def test_no_reference_collides_with_the_core(self):
        others = [f for f in fg.sheets(PROJ)
                  if os.path.basename(f) != psg.SHEET_FILE]
        core = {i.ref for i in fg.inventory(others)}
        new = {r for r in symbols(self.tree) if not r.startswith("#")}
        self.assertEqual(core & new, set())
        pwr = set()
        for f in others:
            with open(f) as fh:
                pwr |= psg.power_refs(fh.read())
        self.assertEqual(pwr & set(symbols(self.tree)), set())


@unittest.skipUnless(HAVE_KICAD, "KiCad 10 not installed")
class TestKiCadAgrees(unittest.TestCase):
    """The netlist KiCad itself exports is the authority on connectivity."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        for f in fg.sheets(PROJ) + [os.path.join(PROJ, "dino_v0_0_2.kicad_pro"),
                                    os.path.join(PROJ, "fp-lib-table"),
                                    os.path.join(PROJ, "sym-lib-table")]:
            shutil.copy(f, cls.tmp)
        psg.unlink(cls.tmp)
        psg.generate(cls.tmp)
        cls.net = os.path.join(cls.tmp, "x.net")
        subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format",
                        "kicadsexpr", "-o", cls.net,
                        os.path.join(cls.tmp, "dino_v0_0_2.kicad_sch")],
                       check=True, capture_output=True)
        cls.erc = os.path.join(cls.tmp, "erc.json")
        subprocess.run([KICAD_CLI, "sch", "erc", "--format", "json", "-o",
                        cls.erc, os.path.join(cls.tmp, "dino_v0_0_2.kicad_sch")],
                       capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def nets(self):
        with open(self.net) as f:
            tree = parse(tokenize(f.read()))
        out = {}
        for n in children(child(tree, "nets"), "net"):
            out[child(n, "name")[1]] = {(child(x, "ref")[1], child(x, "pin")[1])
                                        for x in children(n, "node")}
        return out

    def test_every_atx_rail_pin_lands_on_its_power_net(self):
        nets = self.nets()
        for rail, pins in ATX_RAILS.items():
            got = {p for r, p in nets[rail] if r == psg.ATX_REF}
            self.assertEqual(got, pins, rail)

    def test_the_rails_join_the_core_not_a_sheet_local_copy(self):
        nets = self.nets()
        self.assertIn(("U24", "28"), nets["+5V"])   # ROM VCC
        self.assertIn(("U24", "14"), nets["GND"])   # ROM GND

    def test_ps_on_reaches_the_switch_header_and_ground(self):
        nets = self.nets()
        pson = [n for n, nodes in nets.items() if (psg.ATX_REF, "16") in nodes]
        self.assertEqual(len(pson), 1)
        self.assertIn((psg.PSON_REF, "1"), nets[pson[0]])
        self.assertIn((psg.PSON_REF, "2"), nets["GND"])

    def test_power_sheet_adds_no_erc_errors(self):
        with open(self.erc) as f:
            rep = json.load(f)
        bad = [v for s in rep["sheets"] if "Power" in s["path"]
               for v in s["violations"] if v["severity"] == "error"]
        self.assertEqual([v["description"] for v in bad], [])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
