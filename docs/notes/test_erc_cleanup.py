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


def copy_project(top):
    """The project into top/dino_v0_0_2, with ../dino_bus beside it as the
    lib tables expect (${KIPRJMOD}/../dino_bus). Returns the project dir."""
    dst = os.path.join(top, "dino_v0_0_2")
    os.mkdir(dst)
    for f in fg.sheets(PROJ) + [os.path.join(PROJ, "dino_v0_0_2.kicad_pro"),
                                os.path.join(PROJ, "fp-lib-table"),
                                os.path.join(PROJ, "sym-lib-table")]:
        shutil.copy(f, dst)
    for d in ("74F382PC", "dino.pretty"):
        shutil.copytree(os.path.join(PROJ, d), os.path.join(dst, d))
    os.symlink(os.path.abspath(os.path.join(PROJ, "..", "dino_bus")),
               os.path.join(top, "dino_bus"))
    lib = os.path.join(PROJ, ec.LIB_FILE)
    if os.path.exists(lib):
        shutil.copy(lib, dst)
    return dst


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


class TestWrite(unittest.TestCase):
    def test_write_merges_and_never_drops_an_existing_exclusion(self):
        # 2026-10-30: write_exclusions REPLACED the list, so a re-run that
        # only sees the still-visible warnings wiped every working key.
        # KiCad 10 stores entries as [key, comment]; both shapes count.
        d = tempfile.mkdtemp()
        pro = os.path.join(d, "dino_v0_0_2.kicad_pro")
        with open(pro, "w") as f:
            json.dump({"erc": {"erc_exclusions": [["old|1", ""], "older|2"]}}, f)
        ec.write_exclusions(d, ["new|3", "old|1"])
        with open(pro) as f:
            keys = json.load(f)["erc"]["erc_exclusions"]
        self.assertEqual(keys, [["old|1", ""], "older|2", "new|3"])
        shutil.rmtree(d)


class TestAliasMarker(unittest.TestCase):
    def test_alias_pair_is_excluded_at_either_label(self):
        # KiCad puts the multiple_net_names marker on either label of the
        # pair, run to run (three identical runs: 0, 0, 4 left). Both keys.
        a = {"pos": {"x": 1.0, "y": 1.0}, "uuid": "A", "description": "Global Label 'CW15'"}
        b = {"pos": {"x": 2.0, "y": 3.0}, "uuid": "B", "description": "Global Label 'HALT'"}
        rep = {"sheets": [{"uuid_path": "/S", "violations": [
            {"type": "multiple_net_names", "items": [a, b]}]}]}
        self.assertEqual(sorted(ec.exclusions(rep)), sorted([
            "multiple_net_names|2000000|3000000|A|B|/S|/S|/S",
            "multiple_net_names|1000000|1000000|B|A|/S|/S|/S"]))


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
        self.assertEqual(added, 2)          # the alias pair, at either label
        self.assertEqual(added_again, 0)
        self.assertEqual(keys, ["old|1|2|A|B|/S|/S|/S",
                                "multiple_net_names|2000000|3000000|A|B|/S|/S|/S",
                                "multiple_net_names|1000000|1000000|B|A|/S|/S|/S"])
        shutil.rmtree(d)


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.top = tempfile.mkdtemp()
        self.tmp = copy_project(self.top)

    def tearDown(self):
        shutil.rmtree(self.top)

    def test_the_project_carries_no_orphan_and_the_library_holds_each(self):
        # the 2026-09-12 move is done: the checked-in sheets name only the
        # project library, and it holds every former orphan
        with open(os.path.join(PROJ, ec.LIB_FILE)) as fh:
            lib = fh.read()
        for lib_id in ec.ORPHANS:
            name = lib_id.split(":")[1]
            self.assertIn(f'(symbol "{name}"', lib, name)
            for f in fg.sheets(PROJ):
                with open(f) as fh:
                    self.assertNotIn(f'"{lib_id}"', fh.read(), (f, lib_id))

    def test_orphan_symbols_move_into_a_project_library_unchanged(self):
        # replays the move on a copy whose sheets still embed the orphans
        for f in fg.sheets(self.tmp):
            with open(f) as fh:
                src = fh.read()
            for lib_id in ec.ORPHANS:
                src = src.replace(f'"dino:{lib_id.split(":")[1]}"', f'"{lib_id}"')
            with open(f, "w") as fh:
                fh.write(src)
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
        cls.top = tempfile.mkdtemp()
        cls.tmp = copy_project(cls.top)
        cls.nets_before = nets(cls.tmp)
        cls.before = counts(erc(cls.tmp))
        cls.report = ec.run(cls.tmp)
        cls.after = counts(erc(cls.tmp))
        cls.excluded = counts(erc(cls.tmp, ["--severity-exclusions"]))
        cls.nets_after = nets(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.top)

    def test_connectivity_is_byte_for_byte_the_same(self):
        self.assertEqual(self.nets_after, self.nets_before)

    def test_every_visible_warning_becomes_an_excluded_one(self):
        # what was visible before the pass is listed back by KiCad under
        # --severity-exclusions, kind for kind
        for kind in ("pin_to_pin", "multiple_net_names", "isolated_pin_label"):
            self.assertGreaterEqual(self.excluded[kind], self.before[kind], kind)

    def test_nothing_is_left(self):
        # RESET_B and ~{IO_WR} were the last two (KEEP_VISIBLE); the bus
        # sheet consumes both now, so the pass leaves a clean ERC. Run three
        # times: the alias-pair marker moves between runs.
        for _ in range(3):
            rep = erc(self.tmp)
            self.assertEqual(sum(1 for s in rep["sheets"] for v in s["violations"]
                                 if v["severity"] == "error"), 0)
            self.assertEqual(dict(counts(rep)), {})


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
