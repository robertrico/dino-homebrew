#!/usr/bin/env python3
"""Host tests for progrom_gen.py — the program ROM image generator.

Assertions come from the DESIGN CONTRACT (memory map + ISA + test spec),
not from the generator's own structure:
  - ROM 0x0000-0x7FFF, one AT28C256, all 32768 bytes programmed
  - safe-fill = HALT opcode, so an erased/short program halts
  - opcodes and instruction LENGTHS come from microcode_gen (single
    source of truth — the assembler validates operand counts against it)
  - diag image is content-addressed and SELF-NAMING on the 16 witness
    addresses (0 and each 2^k), so a swapped/stuck address line reports
    the address the chip actually decoded
"""
import sys
import unittest

import progrom_gen as pg
from microcode_gen import OPCODES, INSTRUCTIONS

SIZE = 32768


class TestDiagImage(unittest.TestCase):
    def test_size_and_selfconsistency(self):
        img = pg.build_diag()
        self.assertEqual(len(img), SIZE)
        for a in (0, 1, 0x1234, 0x4000, SIZE - 1):
            self.assertEqual(img[a], pg.diag_byte(a))

    def test_address_zero_marker(self):
        self.assertEqual(pg.diag_byte(0), pg.DIAG_ZERO)

    def test_walking_ones_are_self_naming(self):
        """value at 2^k encodes k — a mis-decoded line names itself."""
        for k in range(15):
            self.assertEqual(pg.diag_byte(1 << k), pg.DIAG_WALK | k)

    def test_witness_values_pairwise_distinct(self):
        vals = [pg.diag_byte(a) for a in pg.WITNESS_ADDRS]
        self.assertEqual(len(set(vals)), len(vals))

    def test_not_blank_like(self):
        """an erased chip reads 0xFF everywhere; diag must not look like one"""
        img = pg.build_diag()
        self.assertLess(img.count(0xFF), SIZE // 64)

    def test_all_bytes_exercised_on_every_data_line(self):
        """every data line must be seen both high and low somewhere"""
        img = pg.build_diag()
        ored = 0
        anded = 0xFF
        for b in img:
            ored |= b
            anded &= b
        self.assertEqual(ored, 0xFF)
        self.assertEqual(anded, 0x00)


class TestRealImage(unittest.TestCase):
    def test_size_and_safe_fill(self):
        img = pg.build_real()
        self.assertEqual(len(img), SIZE)
        self.assertEqual(pg.SAFE_FILL, OPCODES["HALT"])
        tail = img[len(pg.assemble(pg.PROGRAM)):]
        self.assertEqual(set(tail), {pg.SAFE_FILL})

    def test_signature_distinguishes_the_two_burns(self):
        self.assertNotEqual(pg.build_real()[0], pg.build_diag()[0])

    def test_milestone_program_is_the_gate(self):
        """the hard gate: machine adds two numbers, shows the result, halts"""
        names = [step[0] for step in pg.PROGRAM]
        self.assertEqual(names, ["LDAI", "OUT", "LDAI", "LDBI", "ADD",
                                 "OUT", "HALT"])
        # locate the addend loads by walking the encoding rather than by
        # hard-coded offsets — the poison prologue moved them once already
        img = pg.build_real()
        off, loads = 0, []
        for step in pg.PROGRAM:
            if step[0] in ("LDAI", "LDBI") and step[1:] != (pg.POISON,):
                loads.append((img[off], img[off + 1]))
            off += INSTRUCTIONS[step[0]][0]
        self.assertEqual([op for op, _ in loads],
                         [OPCODES["LDAI"], OPCODES["LDBI"]])
        self.assertEqual(sum(v for _, v in loads), pg.EXPECT_SUM)

    def test_program_poisons_OB_before_it_computes(self):
        """U35 has no reset and the machine free-runs at power-up, so OB always
        already holds the previous run's answer — nothing the RIG does can
        clear it. The program must destroy the old answer itself, before it
        computes, or a test cannot tell a fresh result from a leftover."""
        first = pg.PROGRAM[0]
        self.assertEqual(first, ("LDAI", pg.POISON),
                         "the program must load the poison FIRST")
        self.assertEqual(pg.PROGRAM[1], ("OUT",),
                         "and drive it to OB before anything else")
        self.assertNotEqual(pg.POISON, pg.EXPECT_SUM,
                            "a poison equal to the answer proves nothing")
        # and it must really be on the bus before the addends are loaded
        out_idx = [i for i, s in enumerate(pg.PROGRAM) if s[0] == "OUT"]
        add_idx = [i for i, s in enumerate(pg.PROGRAM) if s[0] == "ADD"][0]
        self.assertLess(out_idx[0], add_idx)
        self.assertGreater(out_idx[-1], add_idx, "the sum is still shown")

    def test_assembler_emits_declared_lengths(self):
        for name, _ops in [(s[0], s[1:]) for s in pg.PROGRAM]:
            self.assertIn(name, INSTRUCTIONS)
        self.assertEqual(len(pg.assemble(pg.PROGRAM)),
                         sum(INSTRUCTIONS[s[0]][0] for s in pg.PROGRAM))

    def test_assembler_rejects_unknown_mnemonic(self):
        with self.assertRaises(pg.BuildError):
            pg.assemble([("FLOOP",)])

    def test_assembler_rejects_wrong_operand_count(self):
        with self.assertRaises(pg.BuildError):
            pg.assemble([("LDAI",)])            # needs 1 operand
        with self.assertRaises(pg.BuildError):
            pg.assemble([("ADD", 1)])           # takes none

    def test_assembler_rejects_out_of_range_operand(self):
        with self.assertRaises(pg.BuildError):
            pg.assemble([("LDAI", 256)])

    def test_assembler_is_little_endian_on_addresses(self):
        """operands LO then HI (8008 lineage, session state)"""
        code = pg.assemble([("JMP", 0x34, 0x12)])
        self.assertEqual(list(code), [OPCODES["JMP"], 0x34, 0x12])


class TestCrc(unittest.TestCase):
    def test_ccitt_false_known_answer(self):
        self.assertEqual(pg.crc16(b"123456789"), 0x29B1)

    def test_images_have_distinct_crcs(self):
        self.assertNotEqual(pg.crc16(pg.build_real()),
                            pg.crc16(pg.build_diag()))


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
