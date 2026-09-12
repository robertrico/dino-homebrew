#!/usr/bin/env python3
"""footprint_gen.py: every symbol in dino_v0_0_2 gets a THT footprint that
exists on disk, written into the schematic's own Footprint field.

Plain DIP, not `_Socket` -- Rico, 2026-09-12: sockets do not change the
footprint, and the 3D render should show the ICs.
"""
import difflib
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import footprint_gen as fg  # noqa: E402

PROJ = os.path.join(HERE, "..", "..", "dino_v0_0_2")


class TestAssign(unittest.TestCase):
    def test_every_symbol_in_the_project_gets_a_footprint(self):
        inv = fg.inventory(fg.sheets(PROJ))
        self.assertGreater(len(inv), 190)
        missing = [(i.ref, i.lib_id, i.value) for i in inv
                   if not fg.assign(i.lib_id, i.value)]
        self.assertEqual(missing, [])

    def test_no_socket_footprints(self):
        inv = fg.inventory(fg.sheets(PROJ))
        socketed = [i.ref for i in inv
                    if "Socket" in fg.assign(i.lib_id, i.value)]
        self.assertEqual(socketed, [])

    def test_dip_width_follows_pin_count_and_family(self):
        self.assertEqual(fg.assign("74xx:74LS02", "74LS02"),
                         "Package_DIP:DIP-14_W7.62mm")
        self.assertEqual(fg.assign("74xx:74LS138", "74LS138"),
                         "Package_DIP:DIP-16_W7.62mm")
        self.assertEqual(fg.assign("74xx:74LS245", "74LS245"),
                         "Package_DIP:DIP-20_W7.62mm")
        # the '382 pair leaves the one-off vendor library for the stock one
        self.assertEqual(fg.assign("2026-07-13_03-50-17:74F382PC", "74F382N"),
                         "Package_DIP:DIP-20_W7.62mm")
        # memories are 0.6" wide
        self.assertEqual(fg.assign("Memory_RAM:MCM60256AP", "MCM60256AP"),
                         "Package_DIP:DIP-28_W15.24mm")
        self.assertEqual(fg.assign("Memory_EEPROM:AT28C64B", "AT28C64B"),
                         "Package_DIP:DIP-28_W15.24mm")

    def test_unknown_symbol_is_refused_not_guessed(self):
        with self.assertRaises(KeyError):
            fg.assign("74xx:74LS999", "74LS999")

    def test_every_assigned_footprint_exists_on_disk(self):
        inv = fg.inventory(fg.sheets(PROJ))
        libs = fg.footprint_libs(PROJ)
        gone = sorted({fg.assign(i.lib_id, i.value) for i in inv
                       if not fg.footprint_exists(
                           fg.assign(i.lib_id, i.value), libs)})
        self.assertEqual(gone, [])


class TestApply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for f in fg.sheets(PROJ):
            shutil.copy(f, self.tmp)
        self.copy = fg.sheets(self.tmp)
        # start from the state the project was in before 2026-09-12
        for f in self.copy:
            with open(f) as fh:
                src = fh.read()
            with open(f, "w") as fh:
                fh.write(fg._FP.sub(r'\1\3', src))
        self.assertEqual([i.ref for i in fg.inventory(self.copy)
                          if i.footprint], [])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_apply_fills_every_field_and_touches_only_footprint_lines(self):
        before = {}
        for f in self.copy:
            with open(f) as fh:
                before[f] = fh.read()
        changed = sum(fg.apply(f) for f in self.copy)
        self.assertGreater(changed, 0)
        inv = fg.inventory(self.copy)
        self.assertEqual([i.ref for i in inv if not i.footprint], [])
        self.assertEqual([i.ref for i in inv
                          if i.footprint != fg.assign(i.lib_id, i.value)], [])
        for f in self.copy:
            diff = [l for l in difflib.unified_diff(
                before[f].splitlines(), open(f).read().splitlines(),
                lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
            for l in diff:
                self.assertIn('(property "Footprint"', l, (f, l))

    def test_apply_is_idempotent(self):
        for f in self.copy:
            fg.apply(f)
        self.assertEqual(sum(fg.apply(f) for f in self.copy), 0)


class TestProjectState(unittest.TestCase):
    """The gate: the checked-in schematic carries the footprints."""

    def test_no_symbol_in_dino_v0_0_2_has_an_empty_footprint(self):
        inv = fg.inventory(fg.sheets(PROJ))
        self.assertEqual([i.ref for i in inv if not i.footprint], [])

    def test_checked_in_footprints_match_the_generator(self):
        inv = fg.inventory(fg.sheets(PROJ))
        self.assertEqual([(i.ref, i.footprint) for i in inv
                          if i.footprint != fg.assign(i.lib_id, i.value)], [])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
