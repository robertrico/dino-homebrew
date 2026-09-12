#!/usr/bin/env python3
"""erc_cleanup.py: take dino_v0_0_2's ERC from 135 warnings to the two the
peripheral bus will consume, without moving a wire.

2026-09-12, after global labels landed and every ERC error went to zero.
What is left is configuration and cosmetics:

  * 48 pin_to_pin      '245 B side on counter Q outputs -- the PC and SP
                       readback buffers. Real, one-directional, by design.
  * 34 multiple_net_names   the alias stubs, CW12=END. By design; the
                       contracts tool depends on them.
  * 40 isolated_pin_label   unwired microcode bits and their alias names
                       (CW16/19/20/22/23), and TO0-15, the one-hot T-state
                       outputs nothing consumes. Documentation labels on
                       real pins. (RESET_B and ~{IO_WR} are NOT excluded:
                       the bus sheet consumes them.)
  * 8  lib_symbol_issues    74LS244N, AT28C64B, AT28C256, MCM60256AP no
                       longer exist under those names in KiCad 10's
                       libraries. The embedded copies move into a project
                       library, `dino`, byte for byte.
  * 1  unconnected_wire_endpoint   a 1.27 mm stub on the root, to nothing.
  * 1  no_connect_dangling         an NC flag on the root, on nothing.

The exclusions are KiCad's own mechanism, keyed on item uuids, so if a
pin or label is ever deleted the exclusion expires and the warning comes
back. The key format was found empirically against kicad-cli 10.0.4:

    type|x|y|main_uuid|aux_uuid|sheet_path|sheet_path|sheet_path

with x, y the FIRST item's position in schematic internal units (the JSON
report writes positions through the PCB scale, so its numbers are those
units divided by 1e6).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import erc_cleanup as ec  # noqa: E402
import footprint_gen as fg  # noqa: E402
from kicad_netlist import tokenize, parse, children, child  # noqa: E402

PROJ = os.path.join(HERE, "..", "..", "dino_v0_0_2")
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
HAVE_KICAD = os.path.exists(KICAD_CLI)


def copy_project(dst):
    for f in fg.sheets(PROJ) + [os.path.join(PROJ, "dino_v0_0_2.kicad_pro"),
                                os.path.join(PROJ, "fp-lib-table"),
                                os.path.join(PROJ, "sym-lib-table")]:
        shutil.copy(f, dst)
    shutil.copytree(os.path.join(PROJ, "74F382PC"), os.path.join(dst, "74F382PC"))
    lib = os.path.join(PROJ, ec.LIB_FILE)
    if os.path.exists(lib):
        shutil.copy(lib, dst)


def erc(proj, extra=()):
    out = os.path.join(proj, "erc.json")
    subprocess.run([KICAD_CLI, "sch", "erc", "--format", "json", "-o", out,
                    os.path.join(proj, "dino_v0_0_2.kicad_sch"), *extra],
                   capture_output=True)
    with open(out) as f:
        return json.load(f)


def counts(rep):
    return Counter(v["type"] for s in rep["sheets"] for v in s["violations"])


def nets(proj):
    out = os.path.join(proj, "x.net")
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format",
                    "kicadsexpr", "-o", out,
                    os.path.join(proj, "dino_v0_0_2.kicad_sch")],
                   check=True, capture_output=True)
    with open(out) as f:
        tree = parse(tokenize(f.read()))
    return {frozenset((child(x, "ref")[1], child(x, "pin")[1])
                      for x in children(n, "node"))
            for n in children(child(tree, "nets"), "net")}


class TestKey(unittest.TestCase):
    def test_key_is_eight_fields_in_schematic_units(self):
        item = {"pos": {"x": 2.2352, "y": 0.3429}, "uuid": "A", "description": "Symbol U1 Pin 3 [x]"}
        aux = {"pos": {"x": 1.0, "y": 1.0}, "uuid": "B", "description": "Symbol U13 Pin 18 [x]"}
        self.assertEqual(ec.key("pin_to_pin", "/S", [item, aux]),
                         "pin_to_pin|2235200|342900|A|B|/S|/S|/S")

    def test_single_item_key_has_the_null_uuid_and_no_item_sheets(self):
        item = {"pos": {"x": 1.0, "y": 2.0}, "uuid": "A"}
        self.assertEqual(ec.key("isolated_pin_label", "/S", [item]),
                         "isolated_pin_label|1000000|2000000|A|"
                         "00000000-0000-0000-0000-000000000000|/S||")

    def test_alias_stub_key_uses_the_second_label_position(self):
        a = {"pos": {"x": 1.0, "y": 1.0}, "uuid": "A"}
        b = {"pos": {"x": 2.0, "y": 3.0}, "uuid": "B"}
        self.assertEqual(ec.key("multiple_net_names", "/S", [a, b]),
                         "multiple_net_names|2000000|3000000|A|B|/S|/S|/S")

    def test_cross_sheet_pin_pair_names_each_symbols_sheet(self):
        a = {"pos": {"x": 1.0, "y": 1.0}, "uuid": "A", "description": "Symbol U72 Pin 2 [x]"}
        b = {"pos": {"x": 2.0, "y": 2.0}, "uuid": "B", "description": "Symbol U1 Pin 3 [x]"}
        self.assertEqual(ec.key("pin_to_pin", "/M", [a, b], {"U72": "/M", "U1": "/P"}),
                         "pin_to_pin|1000000|1000000|A|B|/M|/M|/P")


class TestAppend(unittest.TestCase):
    def test_append_merges_new_keys_and_keeps_existing_ones_once(self):
        d = tempfile.mkdtemp()
        pro = os.path.join(d, "dino_v0_0_2.kicad_pro")
        with open(pro, "w") as f:
            json.dump({"erc": {"erc_exclusions": ["old|1|2|A|B|/S|/S|/S"]}}, f)
        rep = {"sheets": [{"uuid_path": "/S", "violations": [
            {"type": "multiple_net_names", "items": [
                {"pos": {"x": 1.0, "y": 1.0}, "uuid": "A", "description": "Global Label 'CW17'"},
                {"pos": {"x": 2.0, "y": 3.0}, "uuid": "B", "description": "Global Label '~{SRC_BANK}'"}]},
            {"type": "isolated_pin_label", "items": [
                {"pos": {"x": 1.0, "y": 1.0}, "uuid": "C", "description": "Label 'RESET_B'"}]}]}]}
        rp = os.path.join(d, "r.json")
        with open(rp, "w") as f:
            json.dump(rep, f)
        added = ec.append_report(d, rp)
        added_again = ec.append_report(d, rp)
        with open(pro) as f:
            keys = json.load(f)["erc"]["erc_exclusions"]
        self.assertEqual(added, 1)
        self.assertEqual(added_again, 0)
        self.assertEqual(keys, ["old|1|2|A|B|/S|/S|/S",
                                "multiple_net_names|2000000|3000000|A|B|/S|/S|/S"])
        shutil.rmtree(d)


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        copy_project(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_orphan_symbols_move_into_a_project_library_unchanged(self):
        before = {}
        for f in fg.sheets(self.tmp):
            with open(f) as fh:
                src = fh.read()
            for lib_id in ec.ORPHANS:
                blk = ec.embedded_block(src, lib_id)
                if blk:
                    before[lib_id] = blk
        self.assertEqual(set(before), set(ec.ORPHANS))
        ec.rehome_symbols(self.tmp)
        with open(os.path.join(self.tmp, ec.LIB_FILE)) as fh:
            lib = fh.read()
        for lib_id, blk in before.items():
            name = lib_id.split(":")[1]
            want = "\n".join(l[1:] if l.startswith("\t") else l
                             for l in blk.splitlines())
            want = want.replace(f'(symbol "{lib_id}"', f'(symbol "{name}"', 1)
            self.assertIn(want, lib, name)
        for f in fg.sheets(self.tmp):
            with open(f) as fh:
                src = fh.read()
            for lib_id in ec.ORPHANS:
                self.assertNotIn(f'"{lib_id}"', src, (f, lib_id))
        with open(os.path.join(self.tmp, "sym-lib-table")) as fh:
            self.assertIn('(name "dino")', fh.read())

    def test_footprints_still_assign_after_rehoming(self):
        ec.rehome_symbols(self.tmp)
        for i in fg.inventory(fg.sheets(self.tmp)):
            self.assertTrue(fg.assign(i.lib_id, i.value), i)

    def test_rehome_is_idempotent(self):
        ec.rehome_symbols(self.tmp)
        snap = {f: open(f).read() for f in fg.sheets(self.tmp)}
        ec.rehome_symbols(self.tmp)
        self.assertEqual({f: open(f).read() for f in fg.sheets(self.tmp)}, snap)


@unittest.skipUnless(HAVE_KICAD, "KiCad 10 not installed")
class TestWholePass(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        copy_project(cls.tmp)
        cls.nets_before = nets(cls.tmp)
        cls.before = counts(erc(cls.tmp))
        cls.report = ec.run(cls.tmp)
        cls.after = counts(erc(cls.tmp))
        cls.excluded = counts(erc(cls.tmp, ["--severity-exclusions"]))
        cls.nets_after = nets(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_connectivity_is_byte_for_byte_the_same(self):
        self.assertEqual(self.nets_after, self.nets_before)

    def test_every_written_exclusion_is_honoured(self):
        # each exclusion silences exactly one warning, and KiCad lists it
        # back under --severity-exclusions
        self.assertEqual(sum(self.excluded.values()), self.report["exclusions"])
        for kind in ("pin_to_pin", "multiple_net_names", "isolated_pin_label"):
            self.assertEqual(self.before[kind] - self.after[kind],
                             self.excluded[kind], kind)

    def test_only_the_bus_signals_remain(self):
        self.assertEqual(sum(1 for s in erc(self.tmp)["sheets"]
                             for v in s["violations"] if v["severity"] == "error"), 0)
        self.assertEqual(dict(self.after), {"isolated_pin_label": 2})
        left = [i["description"] for s in erc(self.tmp)["sheets"]
                for v in s["violations"] for i in v["items"]]
        self.assertEqual(sorted(left), ["Label 'RESET_B'", "Label '~{IO_WR}'"])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
