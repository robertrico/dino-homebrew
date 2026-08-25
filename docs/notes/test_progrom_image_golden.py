#!/usr/bin/env python3
"""Change-detection pins for every burnable program-ROM image.

These are NOT design-contract assertions -- test_progrom_gen.py holds those.
A CRC here moving means a BURNED ARTIFACT CHANGED. That is sometimes correct
(an image was deliberately rewritten) and sometimes a refactor leaking into
the burn. Either way it must be a decision, never a surprise.

Modelled on test_microcode_gen.py, which pins the three microcode images the
same way and for the same reason.

TO UPDATE: change the literal in the same commit that changes the image, and
say in the commit message which image and why.
"""
import unittest

import progrom_gen as pg

GOLDEN_CRC = {
    "probe":     0x254E,
    "adda":      0xAC3D,
    "addb":      0x8DAE,
    "real":      0x8577,
    "in":        0x2B9C,
    "alu":       0x642A,
    "mem":       0x3E4B,
    "flow":      0xCED0,
    "loop":      0x8727,
    "mardisc":   0x2066,
    "pads":      0x749A,
    "sp1":       0x5F58,
    "sp2":       0xFBA3,
    "sp3":       0x76FF,
    "sp":        0xC047,
    "calladdr":  0x7D79,
    "callraw":   0xD709,
    "call":      0x14C9,
    "stack":     0x1A77,
    "ramexec":   0x9BC7,
}
GOLDEN_DIAG_CRC = 0xDFE7


class TestImageCrcsArePinned(unittest.TestCase):
    def test_every_coverage_image_matches_its_pin(self):
        for tag, program in pg.COVERAGE.items():
            with self.subTest(tag=tag):
                self.assertIn(tag, GOLDEN_CRC,
                              "new coverage tag %r has no pinned CRC" % tag)
                self.assertEqual(pg.crc16(pg.build_image(program)),
                                 GOLDEN_CRC[tag], tag)

    def test_diag_image_matches_its_pin(self):
        self.assertEqual(pg.crc16(pg.build_diag()), GOLDEN_DIAG_CRC)

    def test_no_pin_is_orphaned(self):
        """a pin with no image is a stale literal -- delete it deliberately"""
        self.assertEqual(set(GOLDEN_CRC) - set(pg.COVERAGE), set())


if __name__ == "__main__":
    unittest.main()
