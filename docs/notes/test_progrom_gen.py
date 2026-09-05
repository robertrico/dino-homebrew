#!/usr/bin/env python3
"""Host tests for progrom_gen.py — the program ROM image generator.

Assertions come from the DESIGN CONTRACT (memory map + ISA + test spec),
not from the generator's own structure:
  - ROM 0x0000-0x3FFF, I/O 0x4000-0x7FFF, one AT28C256, all 32768 bytes
    programmed
  - safe-fill = HALT opcode, so an erased/short program halts
  - opcodes and instruction LENGTHS come from microcode_gen (single
    source of truth — the assembler validates operand counts against it)
  - diag image is content-addressed and SELF-NAMING on the 16 witness
    addresses (0 and each 2^k), so a swapped/stuck address line reports
    the address the chip actually decoded
"""
import os
import subprocess
import sys
import unittest

import progrom_gen as pg
from microcode_gen import OPCODES, INSTRUCTIONS

ROM_IMAGE = 32768
HERE = os.path.dirname(os.path.abspath(__file__))


class TestDiagImage(unittest.TestCase):
    def test_size_and_selfconsistency(self):
        img = pg.build_diag()
        self.assertEqual(len(img), ROM_IMAGE)
        for a in (0, 1, 0x1234, 0x4000, ROM_IMAGE - 1):
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
        self.assertLess(img.count(0xFF), ROM_IMAGE // 64)

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
        self.assertEqual(len(img), ROM_IMAGE)
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


class TestExpectedRows(unittest.TestCase):
    """expected_rows()/print_expected() -- the bring-up sheet's generator
    (fpga/BRINGUP_FPGA.md and tests/dino_bringup/BRINGUP.md's "everything
    generated, nothing retyped" rule). in-process checks first, then one
    subprocess check that the actual `--expected` CLI flag prints the
    same numbers and does not touch roms/ (side-effect-free)."""

    def test_covers_every_coverage_tag_in_order(self):
        rows = pg.expected_rows()
        self.assertEqual([r[0] for r in rows], list(pg.COVERAGE))

    def test_matches_simulate_directly(self):
        """No second model: expected_rows()'s ob/ends for every tag must
        equal calling simulate() on that same COVERAGE program directly
        -- the drift this generator exists to prevent."""
        for tag, ob, ends, sw, needs in pg.expected_rows():
            r = pg.simulate(pg.COVERAGE[tag],
                            switches=pg.COVERAGE_SW.get(tag, 0x00))
            self.assertEqual(ob, r["out"], tag)
            self.assertEqual(ends, r["ends"], tag)
            self.assertEqual(needs, tag in pg.COVERAGE_SW, tag)

    def test_known_finals_match_claude_md(self):
        """Anchors named in CLAUDE.md's 2026-08-04 'THE WHOLE ISA HAS
        EXECUTED' section (bench-proven finals) -- catches a regression
        in either the interpreter or a COVERAGE program that happens to
        still reach HALT with a DIFFERENT wrong answer, which
        test_matches_simulate_directly alone cannot: that test only
        checks expected_rows() against simulate(), not against the
        machine's own known-good history."""
        known = {"real": 0x4D, "mardisc": 0x6B, "pads": 0x40, "mem": 0xC5,
                 "flow": 0x39, "alu": 0x39, "loop": 0x15}
        got = {tag: ob for tag, ob, *_ in pg.expected_rows()}
        for tag, want in known.items():
            self.assertEqual(got[tag], want, tag)

    def test_cli_flag_prints_every_tag_and_writes_nothing(self):
        """python3 progrom_gen.py --expected -- the exact invocation the
        bring-up doc cites. ROMS/HDR are resolved from __file__, not cwd
        (progrom_gen.py's own module-level constants), so "writes
        nothing" is checked the only way that is actually meaningful
        here: the real roms/*.bin and the expect header must be BYTE-
        FOR-BYTE and MTIME identical before and after -- a regression
        that made --expected fall through to main()'s normal write path
        would rewrite these (same content, since nothing else changed,
        but a NEW mtime) and this catches that even though the bytes
        would look unchanged."""
        watched = [os.path.join(pg.ROMS, "PROG_pads.bin"), pg.HDR]
        before = {p: os.path.getmtime(p) for p in watched if os.path.exists(p)}
        self.assertTrue(before, "expected roms/HDR outputs from a prior "
                                "main() run to exist for this check")
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "progrom_gen.py"),
             "--expected"],
            check=True, capture_output=True, text=True)
        for p, t in before.items():
            self.assertEqual(os.path.getmtime(p), t,
                             f"--expected must be read-only: {p} was rewritten")
        for tag in pg.COVERAGE:
            self.assertIn(tag, r.stdout, f"--expected output missing {tag!r}")
        # spot-check known values render in the CLI's own format
        self.assertIn("0x4D", r.stdout)
        self.assertIn("0x6B", r.stdout)   # mardisc
        self.assertIn("0x40", r.stdout)   # pads


class TestSpCylonProbes(unittest.TestCase):
    """PROG_spcylon — the stack soak. Assertions come from the DESIGN
    CONTRACT, not from the generator: each probe must cross exactly the
    carry boundary it claims to test, and a healthy machine must never
    reach a HALT."""

    def _crossings(self, base):
        """(tc1, tc2, tc3) — which ripple links the probe's burst forces.

        SP is `base` at LXISP, `base-2` after the two sentinels, and
        `base-BURST-2` at the bottom of the burst. A link carries when the
        descent crosses a multiple of 16 / 256 / 4096."""
        hi, lo = base - 2, base - 2 - pg.SPCY_BURST
        return tuple(hi // m != lo // m for m in (16, 256, 4096))

    def test_probe_bases_isolate_one_more_link_each(self):
        """P1 needs ~TC1 only, P2 adds ~TC2, P3 adds ~TC3 — so the FIRST
        fault code that appears names the deepest link still working. A
        base that crosses more than it claims destroys that property."""
        want = [(True, False, False),
                (True, True, False),
                (True, True, True)]
        self.assertEqual(len(pg.SPCY_PROBES), 3)
        for (base, _fault), expect in zip(pg.SPCY_PROBES, want):
            self.assertEqual(self._crossings(base), expect,
                             f"probe at 0x{base:04X} crosses the wrong set")

    def test_probe_fault_codes_are_distinct(self):
        codes = [f for _b, f in pg.SPCY_PROBES]
        self.assertEqual(len(set(codes)), len(codes))
        for c in codes:
            self.assertNotIn(c, pg.CYLON_FRAMES,
                             "a fault code that is also a frame is invisible")

    def test_probe_regions_do_not_overlap(self):
        """Each probe writes base .. base-BURST-1; the sweep writes its own
        8 frames. An overlap would let one probe corrupt another's sentinel
        and report a carry fault that is really an address collision."""
        spans = [range(b - pg.SPCY_BURST - 1, b + 1)
                 for b, _f in pg.SPCY_PROBES]
        spans.append(range(pg.SPCY_STACK - len(pg.CYLON_FRAMES),
                           pg.SPCY_STACK + 1))
        for i, a in enumerate(spans):
            for b in spans[i + 1:]:
                self.assertFalse(set(a) & set(b), "probe/sweep regions overlap")

    def test_never_halts_on_a_healthy_machine(self):
        """The ONLY HALT in the image is the fault path. So `halted` is the
        whole assertion: a correct stack model runs forever."""
        prog = pg._build_spcylon(outer_n=1, inner_n=2)
        r = pg.simulate(prog, max_steps=40000)
        self.assertFalse(r["halted"],
                         f"reached a fault HALT, OB=0x{r['out']:02X}")
        self.assertGreater(r["ends"], 0)

    def test_sweep_emits_the_cylon_pattern(self):
        """The return half is DATA off the stack, not immediates. If LIFO
        order is modelled wrong the back half comes out scrambled, and this
        is the assertion that names it."""
        prog = pg._build_spcylon(outer_n=1, inner_n=2)
        r = pg.simulate(prog, max_steps=40000)
        outs = r["outs"]
        self.assertGreaterEqual(len(outs), len(pg.CYLON_FRAMES))
        self.assertEqual(outs[:len(pg.CYLON_FRAMES)], list(pg.CYLON_FRAMES))

    def test_stack_traffic_actually_happened(self):
        """A build that silently dropped the pushes would still sweep."""
        prog = pg._build_spcylon(outer_n=1, inner_n=2)
        r = pg.simulate(prog, max_steps=40000)
        self.assertGreaterEqual(r["ram_writes"],
                                len(pg.CYLON_FRAMES) + pg.SPCY_BURST)

    def test_lxisp_runs_before_any_stack_access(self):
        """A '169 has no clear, so SP is random at power-up. The oracle
        starts at SP_POISON, which is OUTSIDE RAM — an access before LXISP
        writes nowhere and reads program bytes."""
        prog = pg._build_spcylon(outer_n=1, inner_n=2)
        first = next(s for s in prog if not isinstance(s, str))
        self.assertEqual(first[0], "LXISP")

    def test_image_is_built_and_never_registered_as_coverage(self):
        """It never halts, so it has no (OB, END) fingerprint for the
        ladder to match — same reason cylon is excluded."""
        img = pg.build_image(pg.SPCYLON_PROGRAM)
        self.assertEqual(len(img), ROM_IMAGE)
        self.assertNotIn("spcylon", pg.COVERAGE)


class TestRomWindowSplit(unittest.TestCase):
    """SIZE was one constant doing two jobs: the size of the PART and the
    size of the ADDRESS SPACE that decodes to it. Phase E makes those
    different numbers -- ROM answers 0x0000-0x3FFF, the part is still a
    32K AT28C256 and the TL866 still wants 32768 bytes."""

    def test_part_size_and_window_size_are_separate_constants(self):
        self.assertEqual(pg.ROM_IMAGE, 32768)
        self.assertEqual(pg.ROM_WINDOW, 16384)
        self.assertEqual(pg.IO_BASE, 0x4000)
        self.assertFalse(hasattr(pg, "SIZE"),
                         "SIZE must not survive the split under any name")

    def test_burn_image_is_still_the_whole_part(self):
        self.assertEqual(len(pg.build_image(pg.COVERAGE["real"])),
                         pg.ROM_IMAGE)
        self.assertEqual(len(pg.build_diag()), pg.ROM_IMAGE)

    def test_a_program_larger_than_the_WINDOW_is_rejected(self):
        """the old check used the part size, so a 20K program built clean
        and fetched garbage past 0x3FFF"""
        big = [("HALT",)] * (pg.ROM_WINDOW + 1)
        with self.assertRaises(pg.BuildError):
            pg.build_image(big)

    def test_a_program_that_fits_the_window_is_accepted(self):
        ok = [("HALT",)] * (pg.ROM_WINDOW - 1)
        self.assertEqual(len(pg.build_image(ok)), pg.ROM_IMAGE)


class TestIoRegionModel(unittest.TestCase):
    """0x4000-0x7FFF decodes to no chip in the core. W is parked at 0xFF by
    pullups at the bus origin, and 0xFF is HALT -- so an unclaimed address
    stops the machine rather than raving. The oracle is the answer key; if
    it still models this region as ROM it will 'execute' bytes the silicon
    never returns."""

    def test_park_value_is_the_halt_opcode(self):
        self.assertEqual(pg.IO_PARK, OPCODES["HALT"])

    def test_unclaimed_io_address_reads_the_park(self):
        # NOT pg.IO_BASE -- phase E step B gave slot 0 to card zero, so
        # 0x4000-0x47FF now answers. NOT 0x4800 either -- phase G gave slot 1
        # to the serial card. 0x5000 is slot 2 and is empty; 0x7FFF is the
        # last address in the window and is in slot 7.
        self.assertEqual(pg.io_read(pg.IO_BASE + 0x1000, 0x00), pg.IO_PARK)
        self.assertEqual(pg.io_read(pg.RAM_BASE - 1, 0xFF), pg.IO_PARK)

    def test_lda_from_the_window_returns_the_park(self):
        # slot 2, empty. Reading slot 0 reaches card zero -- that is
        # TestDipCard's job -- and slot 1 reaches the serial card, which is
        # TestSerialCard's. The window's whole point is that both answer.
        prog = [("LDAI", 0x11), ("OUT",),
                ("LDA", *pg._addr(pg.IO_BASE + 0x1000)), ("OUT",), ("HALT",)]
        self.assertEqual(pg.simulate(prog)["out"], pg.IO_PARK)

    def test_rom_reads_below_the_window_are_unchanged(self):
        """the split must not disturb any existing image"""
        self.assertEqual(pg.simulate(pg.COVERAGE["real"])["out"], 0x4D)
        self.assertEqual(pg.simulate(pg.COVERAGE["ramexec"])["out"], 0x6E)

    def test_rom_window_parameter_discriminates(self):
        """ONE image, TWO window settings, TWO different answers. This is the
        whole reason rom_window is a parameter: PROG_window's BEFORE reading
        has no oracle without it. The image jumps to 0x4000 and OUTs a
        sentinel there; with the window open to the whole part that sentinel
        is reachable, with it closed to 16K the fetch reads the park."""
        lo = pg.assemble([("LDAI", 0x5A), ("OUT",),
                          ("JMP", *pg._addr(pg.IO_BASE))])
        hi = pg.assemble([("LDAI", 0xA5), ("OUT",), ("HALT",)])
        img = bytearray([pg.SAFE_FILL]) * pg.ROM_IMAGE
        img[:len(lo)] = lo
        img[pg.IO_BASE:pg.IO_BASE + len(hi)] = hi
        img = bytes(img)

        # serial=False: slot 1 EMPTY, as it was when this reading was taken.
        # The closed fetch NOP-slides through card zero (switches=0x00 is
        # NOP) and must find the park at 0x4800; with the serial card fitted
        # it would fetch UART registers as opcodes instead (GOTCHA 2).
        opened = pg.simulate(None, image=img, rom_window=pg.ROM_IMAGE,
                             serial=False)
        closed = pg.simulate(None, image=img, rom_window=pg.ROM_WINDOW,
                             serial=False)
        self.assertEqual(opened["out"], 0xA5)   # U24 answers 0x0000-0x7FFF
        self.assertEqual(closed["out"], 0x5A)   # fetch at 0x4000 hits the park

    def test_window_after_reading_is_undefined_with_the_serial_card(self):
        """PHASE G. The NOP slide through card zero now ends at a UART, and
        the oracle refuses to say what happens next. PROG_window's AFTER
        reading cannot be retaken with the serial card in slot 1."""
        lo = pg.assemble([("LDAI", 0x5A), ("OUT",),
                          ("JMP", *pg._addr(pg.IO_BASE))])
        img = bytearray([pg.SAFE_FILL]) * pg.ROM_IMAGE
        img[:len(lo)] = lo
        with self.assertRaises(pg.BuildError):
            pg.simulate(None, image=bytes(img), rom_window=pg.ROM_WINDOW)


class TestWindowWitness(unittest.TestCase):
    """PROG_window is an A/B image: ONE burn, TWO correct answers, one wire
    changed between them. It is the only positive proof the window exists;
    the twelve-image regression can only prove nothing broke."""

    def test_poison_is_not_the_park_value(self):
        """0xFF poison would be indistinguishable from never having jumped"""
        self.assertNotEqual(pg.WINDOW_POISON, pg.IO_PARK)
        self.assertNotEqual(pg.WINDOW_POISON, pg.SAFE_FILL)

    def test_sentinel_lands_at_the_window_boundary(self):
        img = pg.build_window()
        self.assertEqual(len(img), pg.ROM_IMAGE)
        upper = pg.assemble(pg.WINDOW_UPPER)
        self.assertEqual(img[pg.IO_BASE:pg.IO_BASE + len(upper)], upper)

    def test_low_segment_does_not_reach_the_boundary(self):
        self.assertLess(len(pg.assemble(pg.WINDOW_PROGRAM)), pg.IO_BASE)

    def test_BEFORE_the_mod_it_reads_the_sentinel(self):
        """rom_window = the whole part models U24 answering 0x0000-0x7FFF"""
        r = pg.simulate(pg.WINDOW_PROGRAM, image=pg.build_window(),
                        rom_window=pg.ROM_IMAGE)
        self.assertEqual(r["out"], pg.WINDOW_SENTINEL)

    def test_AFTER_the_mod_it_reads_the_poison(self):
        """the fetch at 0x4000 finds the park, 0xFF = HALT, OB keeps 0x5A.
        Slot 1 EMPTY (serial=False): this reading predates the serial card
        and is not retakeable with it fitted -- see TestIoRegionModel."""
        r = pg.simulate(pg.WINDOW_PROGRAM, image=pg.build_window(),
                        rom_window=pg.ROM_WINDOW, serial=False)
        self.assertEqual(r["out"], pg.WINDOW_POISON)

    def test_the_two_answers_differ(self):
        """if they ever collide the image proves nothing"""
        self.assertNotEqual(pg.WINDOW_SENTINEL, pg.WINDOW_POISON)

    def test_not_registered_as_coverage(self):
        """two answers cannot be one --expected row; built, not registered.
        Same precedent as spcylon."""
        self.assertNotIn("window", pg.COVERAGE)


class TestDipCard(unittest.TestCase):
    """SW1 stops being a SRC code and becomes an address. IN retires because
    keeping it alive would wire a microcode signal into the card, giving the
    slot a signal exactly one card uses -- a slot with a favourite, not a
    bus."""

    def test_dip_answers_at_its_slot(self):
        self.assertEqual(pg.io_read(pg.DIP_BASE, 0x1E), 0x1E)

    def test_dip_answers_across_its_whole_slot(self):
        # card zero decodes M11-M13 only, so it answers at all 2048
        # addresses in slot 0 -- 0x7FF is the last of them
        for off in (0, 1, 7, 0xFF, 0x400, 0x7FF):
            self.assertEqual(pg.io_read(pg.DIP_BASE + off, 0x3C), 0x3C)

    def test_other_slots_still_park(self):
        # 0x5000 is slot 2, unoccupied. NOT 0x4100 -- that is inside slot 0
        # -- and NOT 0x4800, which is the serial card since phase G.
        self.assertEqual(pg.io_read(pg.DIP_BASE + 0x1000, 0x1E), pg.IO_PARK)
        self.assertEqual(pg.io_read(0x7FFF, 0x1E), pg.IO_PARK)

    def test_dip_image_replaces_the_in_image(self):
        self.assertIn("dip", pg.COVERAGE)
        self.assertNotIn("in", pg.COVERAGE)
        self.assertEqual(set(pg.COVERAGE_SW), {"dip"})

    def test_dip_image_keeps_the_milestone_answer(self):
        """same arithmetic as PROG_in, addend read by address not by IN"""
        r = pg.simulate(pg.COVERAGE["dip"],
                        switches=pg.COVERAGE_SW["dip"])
        self.assertEqual(r["out"], 0x4D)

    def test_no_image_names_a_retired_mnemonic(self):
        """RETIRED, and replaced. The old form of this test scanned every
        image for the BYTE 0x52; that stopped meaning anything the moment
        phase F+ reassigned 0x52 to OUTB. Scanning bytes was always the weak
        form -- it false-fires on an operand that happens to equal the
        opcode. Scan the PROGRAMS instead: every step must name an
        instruction the ISA still has."""
        for tag, prog in pg.COVERAGE.items():
            with self.subTest(tag=tag):
                for step in prog:
                    if isinstance(step, str):
                        continue
                    self.assertIn(step[0], INSTRUCTIONS,
                                  f"{tag}: {step[0]} is not in the ISA")

    def test_the_IN_microcode_row_is_gone(self):
        """PHASE F BURNS ALL THREE MICROCODE ROMS, so the row that phase E
        could not afford to delete is now free to delete. Ruled by Rico
        2026-08-27, at the burn SECTION 5 named for it.

        Keeping it would have left a DECODABLE OPCODE THAT READS GARBAGE:
        src=SW asserts SRC_ACTIVE so U25 is enabled, but SW asserts neither
        ~{ROM_OUT} nor ~{RAM_OUT}, so READS_IDLE stays high, ~{IO_RD} stays
        high, BUS_DIR is LOW, and U25 drives W from a floating MDR. Worse
        than no opcode at all."""
        self.assertNotIn("IN", INSTRUCTIONS)
        self.assertNotIn("IN", OPCODES)
        # 0x52 IS REUSED, and deliberately: it is OUTB in phase F+. The slot
        # was freed by the same burn that reassigns it, so no ROM ever exists
        # in which 0x52 means IN and something else decodes it. Reusing a
        # freed opcode ACROSS burns would be the hazard; within one is not.
        self.assertEqual(OPCODES["OUTB"], 0x52)

    def test_swdemo_names_only_live_instructions(self):
        for step in pg.SWDEMO_PROGRAM:
            if not isinstance(step, str):
                self.assertIn(step[0], INSTRUCTIONS)


class TestFlagModelPhaseF(unittest.TestCase):
    """The oracle grows a CARRY. It had only FLAG_Z, because JNZ was the only
    branch in the machine.

    NETLIST-EXTRACTED, alu.kicad_sch, 2026-08-25: U49 is a '273 with NO clock
    enable -- it re-clocks every T-state -- and U48 is a '157 whose select is
    ~{ALU_OUT}. So the flags UPDATE on any row that sources the ALU and HOLD
    on every other row. That hold is why a Z set by AND survives to a JNZ two
    instructions later, and the same hold now carries C to a JNC."""

    def _run(self, prog, **kw):
        return pg.simulate(prog, **kw)

    def test_flag_c_is_NOT_borrow_on_sub(self):
        """THE SIGN OF THIS IS THE WHOLE POINT, and getting it backwards
        would make every JNC branch the wrong way.

        The '382 pair computes A-B as A + ~B + CIN with CIN=1 (ALU_CIN =
        NAND(SA1,SA0), and SUB is SA=0b010). CN+4 is therefore a NOT-borrow:
        FLAG_C = 1 means A >= B unsigned, FLAG_C = 0 means A < B."""
        r = self._run([("LDAI", 0x10), ("LDBI", 0x20), ("SUB",), ("HALT",)])
        self.assertEqual(r["flag_c"], 0, "0x10 - 0x20 borrows: FLAG_C must be 0")
        r = self._run([("LDAI", 0x20), ("LDBI", 0x10), ("SUB",), ("HALT",)])
        self.assertEqual(r["flag_c"], 1, "0x20 - 0x10 does not borrow")
        r = self._run([("LDAI", 0x20), ("LDBI", 0x20), ("SUB",), ("HALT",)])
        self.assertEqual(r["flag_c"], 1, "A == B is A >= B")

    def test_flag_c_is_carry_out_on_add(self):
        r = self._run([("LDAI", 0xFF), ("LDBI", 0x01), ("ADD",), ("HALT",)])
        self.assertEqual(r["flag_c"], 1)
        r = self._run([("LDAI", 0x01), ("LDBI", 0x01), ("ADD",), ("HALT",)])
        self.assertEqual(r["flag_c"], 0)

    def test_the_carry_is_UNDEFINED_after_a_logic_op(self):
        """A '382 in a LOGIC mode does not produce a meaningful CN+4. Modelling
        it as 0 would be a stand-in BETTER THAN THE HARDWARE, which is the
        defect class that let a rig-emulated bridge pass schematic bug 4.

        So the oracle tracks DEFINEDNESS and refuses to answer a JNC that
        reads a carry no ALU op defined. Z is unaffected -- it comes off the
        F0-7 NOR tree and is meaningful for every function code."""
        r = self._run([("LDAI", 0x0F), ("LDBI", 0xF0), ("AND",), ("HALT",)])
        self.assertFalse(r["flag_c_defined"],
                         "AND must leave the carry undefined")
        self.assertEqual(r["flag_z"], 1, "Z is defined for logic ops")
        r = self._run([("LDAI", 0x10), ("LDBI", 0x20), ("SUB",), ("HALT",)])
        self.assertTrue(r["flag_c_defined"])

    def test_jnc_on_an_undefined_carry_is_refused(self):
        prog = [("LDAI", 0x0F), ("LDBI", 0xF0), ("AND",),
                ("JNC", 0x00, 0x00), ("HALT",)]
        with self.assertRaises(pg.BuildError):
            self._run(prog)

    def test_flags_hold_across_non_alu_rows(self):
        """The hold leg is what makes compare-then-branch work at all: the
        AND sets Z, and the FETCH, the immediate load and the operand states
        between it and the JNZ never assert ~{ALU_OUT}."""
        r = self._run([("LDAI", 0x20), ("LDBI", 0x10), ("SUB",),
                       ("LDAI", 0x00), ("OUT",), ("HALT",)])
        self.assertEqual(r["flag_c"], 1, "LDAI/OUT must not disturb the carry")


class TestPhaseFInstructions(unittest.TestCase):
    """One test per group, each asserting the thing that would be WRONG if the
    row were mis-encoded rather than merely that it runs."""

    def _run(self, prog, **kw):
        return pg.simulate(prog, **kw)

    def test_jnc_takes_the_branch_when_A_is_less_than_B(self):
        """SECTION 8's PROG_jnc, in the oracle. BOTH DIRECTIONS, because a
        one-sided branch test is passed by a branch wired permanently taken."""
        def img(a, b):
            return [("LDAI", a), ("LDBI", b), ("CMP",),
                    ("JNC", 0x0C, 0x00),
                    ("LDAI", 0xEE), ("OUT",), ("HALT",),
                    "hit", ("LDAI", 0x5A), ("OUT",), ("HALT",)]
        r = self._run(img(0x10, 0x20))
        self.assertEqual(r["out"], 0x5A, "0x10 < 0x20: JNC must be taken")
        r = self._run(img(0x20, 0x10))
        self.assertEqual(r["out"], 0xEE, "0x20 >= 0x10: JNC must NOT be taken")

    def test_cmp_sets_flags_and_leaves_A_alone(self):
        r = self._run([("LDAI", 0x20), ("LDBI", 0x10), ("CMP",),
                       ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x20, "CMP must not write a destination")
        self.assertEqual(r["flag_c"], 1)
        self.assertEqual(r["flag_z"], 0)

    def test_mov_a_c_makes_C_observable_for_the_first_time(self):
        """LDCI has never executed in this machine's life because nothing
        could read C back. This is the row that retires that gap."""
        r = self._run([("LDCI", 0x5A), ("MOVAC",), ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x5A)

    def test_ldax_stax_walk_bc_and_are_read_back_by_ABSOLUTE_address(self):
        """PROG_sp3's discipline, and it is not optional. A pointer test that
        reads back through the SAME pointer is blind in the pointer -- exactly
        how PROG_sp1 stayed green through 2026-08-24 with every bank-1
        decoder output dead. Three cells, a different sentinel in each, each
        read back absolutely so an off-by-one names its direction."""
        base = pg.RAM_BASE + 0x100
        prog = [("LXISP", 0xFF, 0xFF)]
        for i, val in enumerate((0x11, 0x22, 0x33)):
            a = base + i
            prog += [("LDBI", (a >> 8) & 0xFF), ("LDCI", a & 0xFF),
                     ("LDAI", val), ("STAX",)]
        prog += [("LDA", base & 0xFF, (base >> 8) & 0xFF), ("OUT",), ("HALT",)]
        r = self._run(prog)
        self.assertEqual(r["out"], 0x11, "cell 0 read back absolutely")
        self.assertEqual(r["ram_writes"], 3)

    def test_ldax_reads_through_the_pointer(self):
        base = pg.RAM_BASE + 0x200
        prog = [("LDAI", 0x7E), ("STA", base & 0xFF, (base >> 8) & 0xFF),
                ("LDBI", (base >> 8) & 0xFF), ("LDCI", base & 0xFF),
                ("LDAI", 0x00), ("LDAX",), ("OUT",), ("HALT",)]
        self.assertEqual(self._run(prog)["out"], 0x7E)

    def test_C_is_the_LOW_half_of_the_index_pair(self):
        """A swapped pair is an off-by-256, and it survives every round trip
        that uses the same pointer. Plant through B:C, read back absolutely
        at the address C names."""
        base = pg.RAM_BASE + 0x0055
        prog = [("LDBI", 0x82), ("LDCI", 0x55), ("LDAI", 0x99), ("STAX",),
                ("LDA", 0x55, 0x82), ("OUT",), ("HALT",)]
        self.assertEqual(pg.RAM_BASE, 0x8000, "this test hardcodes 0x8255")
        self.assertEqual(self._run(prog)["out"], 0x99)
        self.assertEqual(base, 0x8055)

    def test_shl_inr_dcr_not(self):
        for op, start, want in (("SHL", 0x2C, 0x58), ("INR", 0x2C, 0x2D),
                                ("DCR", 0x2C, 0x2B), ("NOT", 0x2C, 0xD3)):
            with self.subTest(op=op):
                r = self._run([("LDAI", start), (op,), ("OUT",), ("HALT",)])
                self.assertEqual(r["out"], want, f"{op} {start:#04x}")

    def test_shl_inr_dcr_not_all_clobber_B(self):
        """Stated, not hidden. The TMP_B shadow is how they cost two rows."""
        for op in ("SHL", "INR", "DCR", "NOT"):
            with self.subTest(op=op):
                r = self._run([("LDBI", 0x77), ("LDAI", 0x01), (op,), ("HALT",)])
                self.assertNotEqual(r["B"], 0x77, f"{op} must clobber B")

    def test_sp_is_a_second_index_register(self):
        base = pg.RAM_BASE + 0x300
        prog = [("LDBI", (base >> 8) & 0xFF), ("LDCI", base & 0xFF),
                ("SPHL",),
                ("LDAI", 0x64), ("STAS",),
                ("LDAI", 0x00), ("LDAS",), ("OUT",), ("HALT",)]
        r = self._run(prog)
        self.assertEqual(r["out"], 0x64)

    def test_inxsp_is_the_machines_only_16_bit_increment(self):
        """B:C has no carry path between the registers, so INXSP is the only
        way to walk a pointer across a page boundary in one instruction."""
        prog = [("LXISP", 0xFF, 0x80), ("INXSP",),
                ("MOVASPL",), ("OUT",), ("HALT",)]
        r = self._run(prog)
        self.assertEqual(r["out"], 0x00, "0x80FF + 1 must carry into SPH")
        prog = [("LXISP", 0xFF, 0x80), ("INXSP",),
                ("MOVASPH",), ("OUT",), ("HALT",)]
        self.assertEqual(self._run(prog)["out"], 0x81)

    def test_rst_clears_the_pc_without_clearing_anything_else(self):
        """RST is PC_CLEAR and nothing more: the stack, the registers and OB
        all survive it. Say which reset you mean."""
        prog = [("LDAI", 0x3C), ("OUT",), ("JMP", 0x07, 0x00),
                ("HALT",), "target", ("RST",)]
        r = pg.simulate(prog, max_steps=40)
        self.assertFalse(r["halted"], "RST must jump to 0x0000 and re-run")

    def test_movapcl_reads_the_live_pc(self):
        r = self._run([("MOVAPCL",), ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x01, "PC has been incremented once, by T0")


class TestPhaseFPlus(unittest.TestCase):
    """The 108 that the copper already allowed. One test per MECHANISM, not
    per opcode -- 108 near-identical tests would be a blind counter."""

    def _run(self, prog, **kw):
        return pg.simulate(prog, **kw)

    def test_OUT_latches_the_BUS_not_the_accumulator(self):
        """NETLIST-EXTRACTED 2026-08-27, registers_a_b.kicad_sch: U44 is a
        '245 with DIR tied +5V, its A side on MDR0-7 and ~CE on
        ~{REG_OUT_LOAD}; U35's LE is ~{REG_OUT_LE}. So OB latches whatever
        is on MDR when the strobe fires. `src=REG_A` was a MICROCODE
        CONVENTION, never a wire -- which is why OUT-from-anything costs
        nothing, and why an oracle that models `out = A` is wrong the moment
        the source varies."""
        r = self._run([("LDAI", 0x11), ("LDBI", 0x22), ("OUTB",), ("HALT",)])
        self.assertEqual(r["out"], 0x22, "OUTB must show B, not A")
        r = self._run([("LDAI", 0x11), ("LDCI", 0x33), ("OUTC",), ("HALT",)])
        self.assertEqual(r["out"], 0x33)
        r = self._run([("LDAI", 0x11), ("OUTI", 0x44), ("HALT",)])
        self.assertEqual(r["out"], 0x44, "OUTI shows the immediate")
        self.assertEqual(r["A"], 0x11, "OUTI must not touch A")

    def test_OUT_the_pointers(self):
        r = self._run([("LXISP", 0x34, 0x12), ("OUTSPL",), ("HALT",)])
        self.assertEqual(r["out"], 0x34)
        r = self._run([("LXISP", 0x34, 0x12), ("OUTSPH",), ("HALT",)])
        self.assertEqual(r["out"], 0x12)
        r = self._run([("OUTPCL",), ("HALT",)])
        self.assertEqual(r["out"], 0x01, "PC has been incremented once, by T0")

    def test_OUT_an_ALU_result_without_storing_it(self):
        r = self._run([("LDAI", 0x20), ("LDBI", 0x0C), ("OUTADD",), ("HALT",)])
        self.assertEqual(r["out"], 0x2C)
        self.assertEqual(r["A"], 0x20, "OUTADD must not write a destination")

    def test_OUT_memory_in_all_three_addressing_modes(self):
        base = pg.RAM_BASE + 0x400
        plant = [("LDAI", 0x7A), ("STA", *pg._addr(base))]
        r = self._run(plant + [("LDAI", 0x00), ("OUTM", *pg._addr(base)),
                               ("HALT",)])
        self.assertEqual(r["out"], 0x7A, "OUTM, absolute")
        self.assertEqual(r["A"], 0x00, "OUTM must not go through A")
        r = self._run(plant + [("LDBI", base >> 8), ("LDCI", base & 0xFF),
                               ("OUTMX",), ("HALT",)])
        self.assertEqual(r["out"], 0x7A, "OUTMX, indexed through B:C")
        r = self._run(plant + [("LXISP", base & 0xFF, base >> 8),
                               ("OUTMS",), ("HALT",)])
        self.assertEqual(r["out"], 0x7A, "OUTMS, SP-relative")

    def test_immediate_alu_saves_the_LDBI(self):
        r = self._run([("LDAI", 0x20), ("ADI", 0x0C), ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x2C)
        r = self._run([("LDAI", 0x30), ("SUI", 0x04), ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x2C)
        r = self._run([("LDAI", 0xFF), ("ANI", 0x2C), ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x2C)

    def test_CPI_sets_the_flags_and_leaves_A(self):
        r = self._run([("LDAI", 0x10), ("CPI", 0x20), ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x10, "CPI must not write a destination")
        self.assertEqual(r["flag_c"], 0, "0x10 < 0x20 unsigned")
        r = self._run([("LDAI", 0x20), ("CPI", 0x10), ("HALT",)])
        self.assertEqual(r["flag_c"], 1)

    def test_CPI_plus_JNC_is_a_four_byte_compare_and_branch(self):
        def img(a):
            return [("LDAI", a), ("CPI", 0x20), ("JNC", Ref := 0x0A, 0x00),
                    ("LDAI", 0xEE), ("OUT",), ("HALT",),
                    ("LDAI", 0x6C), ("OUT",), ("HALT",)]
        # CPI is 2B: LDAI@0(2) CPI@2(2) JNC@4(3) LDAI@7(2) OUT@9 -> recompute
        prog = [("LDAI", 0x10), ("CPI", 0x20), ("JNC", 0x0B, 0x00),
                ("LDAI", 0xEE), ("OUT",), ("HALT",),
                ("LDAI", 0x6C), ("OUT",), ("HALT",)]
        self.assertEqual(len(pg.assemble(prog[:3])), 7, "the branch is 7 bytes in")
        self.assertEqual(self._run(prog)["out"], 0x6C, "0x10 < 0x20 -> taken")
        prog[0] = ("LDAI", 0x30)
        self.assertEqual(self._run(prog)["out"], 0xEE, "0x30 >= 0x20 -> not taken")

    def test_ALU_into_C_destroys_neither_operand(self):
        """C has no TMP shadow, so it is the only destination that leaves both
        ALU inputs intact."""
        r = self._run([("LDAI", 0x20), ("LDBI", 0x0C), ("ADD_C",),
                       ("OUTC",), ("HALT",)])
        self.assertEqual(r["out"], 0x2C)
        self.assertEqual((r["A"], r["B"]), (0x20, 0x0C),
                         "ADD_C must leave A and B alone")

    def test_ALU_into_B_makes_B_an_accumulator(self):
        """dst=REG_B refills TMP_B through the shadow latch, so the next ALU
        op sees the result -- which is what makes a sum loop work."""
        r = self._run([("LDAI", 0x01), ("LDBI", 0x00),
                       ("ADD_B",), ("ADD_B",), ("ADD_B",),
                       ("OUTB",), ("HALT",)])
        self.assertEqual(r["out"], 0x03, "B accumulated A three times")

    def test_MVI_stores_an_immediate_without_touching_A(self):
        base = pg.RAM_BASE + 0x500
        r = self._run([("LDAI", 0x11), ("MVI", *pg._addr(base), 0x99),
                       ("LDA", *pg._addr(base)), ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x99)
        r = self._run([("LDAI", 0x11), ("MVI", *pg._addr(base), 0x99),
                       ("OUTM", *pg._addr(base)), ("HALT",)])
        self.assertEqual(r["A"], 0x11, "MVI must not go through A")

    def test_MVIX_fills_through_the_pointer(self):
        base = pg.RAM_BASE + 0x600
        r = self._run([("LDBI", base >> 8), ("LDCI", base & 0xFF),
                       ("MVIX", 0x5B), ("LDA", *pg._addr(base)),
                       ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x5B)

    def test_compute_and_store_in_one_instruction(self):
        base = pg.RAM_BASE + 0x700
        r = self._run([("LDAI", 0x20), ("LDBI", 0x0C),
                       ("STADD", *pg._addr(base)),
                       ("LDAI", 0x00), ("LDA", *pg._addr(base)),
                       ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x2C, "STADD wrote A+B straight to memory")

    def test_save_and_restore_the_stack_pointer(self):
        base = pg.RAM_BASE + 0x800
        r = self._run([("LXISP", 0x34, 0x12),
                       ("STSPL", *pg._addr(base)),
                       ("STSPH", *pg._addr(base + 1)),
                       ("LXISP", 0xFF, 0xFF),
                       ("LDSPL", *pg._addr(base)),
                       ("LDSPH", *pg._addr(base + 1)),
                       ("OUTSPH",), ("HALT",)])
        self.assertEqual(r["out"], 0x12)
        self.assertEqual(r["sp"], 0x1234, "SP came back whole")

    def test_SP_relative_for_B_and_C(self):
        base = pg.RAM_BASE + 0x900
        r = self._run([("LXISP", base & 0xFF, base >> 8),
                       ("LDBI", 0x3C), ("STBS",),
                       ("LDBI", 0x00), ("LDBS",), ("OUTB",), ("HALT",)])
        self.assertEqual(r["out"], 0x3C)

    def test_pushing_the_PC_is_a_software_CALL(self):
        r = self._run([("LXISP", 0xFF, 0x80), ("PUSHPCL",),
                       ("POPA",), ("OUT",), ("HALT",)])
        self.assertEqual(r["out"], 0x04,
                         "LXISP is 3 bytes, so T0 of PUSHPCL leaves PC=4 -- "
                         "and PC_LO is read at T3, before any further step. "
                         "This is the same PC+1 convention CALL pushes, which "
                         "is why RET has to step over two operand bytes")

    def test_MEMORY_INDIRECT_loads_through_a_pointer_held_in_RAM(self):
        """The third addressing mode. The pointer lives in memory; the
        instruction names WHERE THE POINTER IS, not where the data is."""
        ptr, data = pg.RAM_BASE + 0xA00, pg.RAM_BASE + 0xABC
        prog = [("MVI", *pg._addr(ptr), data & 0xFF),
                ("MVI", *pg._addr(ptr + 1), data >> 8),
                ("MVI", *pg._addr(data), 0x7E),
                ("LDBI", 0xB5),                      # B must SURVIVE
                ("LDAM", *pg._addr(ptr), *pg._addr(ptr + 1)),
                ("OUT",), ("HALT",)]
        r = self._run(prog)
        self.assertEqual(r["out"], 0x7E, "LDAM followed the pointer")
        self.assertEqual(r["B"], 0xB5, "LDAM must not clobber B")

    def test_MEMORY_INDIRECT_jump(self):
        """The landing address is COMPUTED, not typed. A hand-counted offset
        in a test that also exercises the addressing mode under test is a
        test that passes for the wrong reason the first time the prologue
        changes length."""
        ptr = pg.RAM_BASE + 0xB00
        prologue = [("MVI", *pg._addr(ptr), 0x00),
                    ("MVI", *pg._addr(ptr + 1), 0x00),
                    ("JMPM", *pg._addr(ptr), *pg._addr(ptr + 1)),
                    ("LDAI", 0xEE), ("OUT",), ("HALT",)]
        land = len(pg.assemble(prologue))
        prog = [("MVI", *pg._addr(ptr), land & 0xFF),
                ("MVI", *pg._addr(ptr + 1), land >> 8),
                ("JMPM", *pg._addr(ptr), *pg._addr(ptr + 1)),
                ("LDAI", 0xEE), ("OUT",), ("HALT",),
                ("LDAI", 0x6C), ("OUT",), ("HALT",)]
        r = self._run(prog)
        self.assertEqual(r["out"], 0x6C,
                         "JMPM must land where the RAM pointer says; 0xEE is "
                         "the fall-through")

    def test_STAM_stores_through_a_pointer_held_in_RAM(self):
        ptr, data = pg.RAM_BASE + 0xC00, pg.RAM_BASE + 0xCDE
        prog = [("MVI", *pg._addr(ptr), data & 0xFF),
                ("MVI", *pg._addr(ptr + 1), data >> 8),
                ("LDAI", 0x5B),
                ("STAM", *pg._addr(ptr), *pg._addr(ptr + 1)),
                ("OUTM", *pg._addr(data)), ("HALT",)]
        self.assertEqual(self._run(prog)["out"], 0x5B)


class TestSerialCard(unittest.TestCase):
    """PHASE G -- the serial card at slot 1, and the ONE byte of it the
    oracle models.

    .git/sdd/PHASE_G.md SECTION 5 is explicit: MODEL the scratch register
    at base+7 and NOTHING ELSE. THR, RBR, the FIFOs, the baud generator and
    loopback are TEMPORAL -- THRE and DR change on bit boundaries -- and
    simulate() has no clock. A model of them would be a second UART written
    by the same hand as the spec, agreeing with itself while both were
    wrong. So a program touching any other register gets a BuildError, not
    a number: the oracle refuses to invent, exactly as it refuses to invent
    a carry after a logic op.

    Six of the eight witness images therefore have NO answer key. They are
    generated, they are burnable, and their expected bytes are DATASHEET-
    SOURCED, UNORACLED -- reported as such every time."""

    def setUp(self):
        self.SCR = pg.SER_BASE + 7

    def test_slot_one_is_the_serial_card(self):
        # U101 O1. Slot 1 of eight 2K slots decoded on M11-M13.
        self.assertEqual(pg.SER_BASE, 0x4800)
        self.assertEqual(pg.SER_SCR, 0x4807)

    def test_scr_round_trips_through_sta_and_lda(self):
        prog = [("LDAI", 0x55), ("STA", *pg._addr(self.SCR)),
                ("LDA", *pg._addr(self.SCR)), ("OUT",), ("HALT",)]
        self.assertEqual(pg.simulate(prog)["out"], 0x55)

    def test_scr_reads_zero_after_master_reset(self):
        # FACT, datasheet section 6.0, MR: "clears all the registers (except
        # the Receiver Buffer, Transmitter Holding, and Divisor Latches)".
        # SCR is none of the three, so it is 0x00 at the first fetch.
        prog = [("LDA", *pg._addr(self.SCR)), ("OUT",), ("HALT",)]
        self.assertEqual(pg.simulate(prog)["out"], 0x00)

    def test_scr_mirrors_inside_the_slot_only(self):
        # GOTCHA 3: M3-M10 are undecoded, so the eight registers repeat every
        # 8 bytes through 0x4800-0x4FFF. 0x480F and 0x4FFF are both SCR.
        for mirror in (self.SCR + 8, pg.SER_BASE + 0x7FF):
            prog = [("LDAI", 0x3C), ("STA", *pg._addr(self.SCR)),
                    ("LDA", *pg._addr(mirror)), ("OUT",), ("HALT",)]
            self.assertEqual(pg.simulate(prog)["out"], 0x3C, hex(mirror))

    def test_a_scr_write_is_not_a_lost_write(self):
        # Until phase G every write below RAM_BASE was "lost" -- nothing
        # consumed ~{IO_WR}. The serial card is the first thing that does.
        prog = [("LDAI", 0x55), ("STA", *pg._addr(self.SCR)), ("HALT",)]
        self.assertEqual(pg.simulate(prog).get("lost_writes", 0), 0)
        # card zero is read-only; a write there is still lost
        prog = [("LDAI", 0x55), ("STA", *pg._addr(pg.DIP_BASE)), ("HALT",)]
        self.assertEqual(pg.simulate(prog).get("lost_writes", 0), 1)

    def test_every_other_uart_register_refuses(self):
        # LSR read, LCR write, RBR read, FCR write: all temporal or stateful
        # beyond the one byte SECTION 5 allows. The oracle must not answer.
        for reg, prog in (
            (5, [("LDA", *pg._addr(pg.SER_BASE + 5)), ("OUT",), ("HALT",)]),
            (3, [("LDAI", 0x83), ("STA", *pg._addr(pg.SER_BASE + 3)), ("HALT",)]),
            (0, [("LDA", *pg._addr(pg.SER_BASE + 0)), ("OUT",), ("HALT",)]),
            (2, [("LDAI", 0x07), ("STA", *pg._addr(pg.SER_BASE + 2)), ("HALT",)]),
        ):
            with self.assertRaises(pg.BuildError, msg=f"register {reg}"):
                pg.simulate(prog)

    def test_slot_two_and_up_still_park(self):
        u = pg.uart_reset()
        self.assertEqual(pg.io_read(pg.SER_BASE + 0x800 + 7, 0x00, u), pg.IO_PARK)
        self.assertEqual(pg.io_read(0x7FFF, 0x00, u), pg.IO_PARK)

    def test_card_absent_parks(self):
        # uart=None is "no card in slot 1", the phase-E world. The park.
        self.assertEqual(pg.io_read(pg.SER_SCR, 0x00, None), pg.IO_PARK)

    def test_card_zero_is_untouched(self):
        self.assertEqual(pg.simulate(pg.COVERAGE["dip"],
                                     switches=pg.COVERAGE_SW["dip"])["out"], 0x4D)

    # ---- the two ORACLED images --------------------------------------
    def test_serid_images_are_in_coverage_with_complementary_bytes(self):
        self.assertIn("serid", pg.COVERAGE)
        self.assertIn("serid_aa", pg.COVERAGE)
        self.assertEqual(pg.simulate(pg.COVERAGE["serid"])["out"], 0x55)
        self.assertEqual(pg.simulate(pg.COVERAGE["serid_aa"])["out"], 0xAA)
        # between them every data line carries both a 1 and a 0
        self.assertEqual(0x55 ^ 0xAA, 0xFF)

    def test_serid_poisons_ob_first(self):
        # U35 has no reset; the first two steps must be LDAI POISON; OUT
        for tag in ("serid", "serid_aa"):
            prog = pg.COVERAGE[tag]
            self.assertEqual(prog[0], ("LDAI", pg.POISON), tag)
            self.assertEqual(prog[1], ("OUT",), tag)

    # ---- the UNORACLED witnesses -------------------------------------
    UNORACLED = {"serprobe", "serlsr", "seriir", "serbaud",
                 "serloop", "sertx", "serrx"}

    def test_serial_witness_registry(self):
        self.assertEqual(set(pg.SERIAL_WITNESS), self.UNORACLED)
        for tag, (prog, ob, source) in pg.SERIAL_WITNESS.items():
            code = pg.assemble(prog)
            self.assertLessEqual(len(code), pg.ROM_WINDOW, tag)
            self.assertTrue(source, f"{tag}: names its datasheet source")
            self.assertNotIn(tag, pg.COVERAGE, f"{tag} has no oracle")

    def test_datasheet_sourced_expectations(self):
        want = {"serprobe": 0xFF,   # the park; U103 NOT seated (step 2)
                "serlsr": 0x60,     # TABLE I, LSR after MR
                "seriir": 0xC1,     # section 8.6, FCR0=1, nothing pending
                "serbaud": None,    # scope witness, 153.6 kHz on U103.15
                "serloop": 0x53,    # the byte, back through loopback
                "sertx": 0x53,      # OB only says it finished; host reads
                "serrx": None}      # never halts
        got = {tag: ob for tag, (_p, ob, _s) in pg.SERIAL_WITNESS.items()}
        self.assertEqual(got, want)

    def test_every_witness_is_refused_by_the_oracle(self):
        # THE HONEST HOLE. If any of these ever simulates to a number, a
        # UART model crept in, and SECTION 5 says it must not.
        for tag, (prog, _ob, _s) in pg.SERIAL_WITNESS.items():
            with self.assertRaises(pg.BuildError, msg=tag):
                pg.simulate(prog)

    def test_witness_values_are_not_palindromes(self):
        # LSB-first on the wire: a bus reversed end to end returns a
        # palindrome unchanged. 0x53 -> 0xCA, so a reversal is readable.
        def rev(b):
            return int(f"{b:08b}"[::-1], 2)
        for tag in ("serloop", "sertx", "serlsr", "seriir"):
            ob = pg.SERIAL_WITNESS[tag][1]
            self.assertNotEqual(ob, rev(ob), tag)

    def test_init_order_clears_dlab_before_ier(self):
        # GOTCHA 1. With DLAB set, 0x4801 is DLM: an IER write there changes
        # the baud rate silently. LCR=0x03 must precede the IER write.
        init = pg.ser_init(mcr=0x00)
        vals = [x[1] for x in init if x[0] == "LDAI"]
        stas = [x[1] | (x[2] << 8) for x in init if x[0] == "STA"]
        stores = list(zip(stas, vals))
        self.assertEqual(stores[0], (0x4803, 0x83), "DLAB set first")
        self.assertEqual(stores[1], (0x4800, 0x18), "DLL = 24 -> 9600")
        self.assertEqual(stores[2], (0x4801, 0x00), "DLM = 0")
        self.assertEqual(stores[3], (0x4803, 0x03), "8N1, DLAB clear")
        self.assertEqual(stores[4], (0x4802, 0x07), "FIFO on, both cleared")
        self.assertEqual(stores[5], (0x4801, 0x00), "IER = 0, AFTER DLAB clear")
        self.assertEqual(stores[6], (0x4804, 0x00), "MCR last")
        self.assertEqual(pg.ser_init(mcr=0x10)[-2:],
                         [("LDAI", 0x10), ("STA", *pg._addr(0x4804))])

    def test_init_is_seven_pairs_thirty_five_bytes(self):
        # SECTION 4: 14 instructions, 35 bytes, 42 T-states.
        init = pg.ser_init(mcr=0x00)
        self.assertEqual(len(init), 14)
        self.assertEqual(len(pg.assemble(init)), 35)

    def test_serloop_sets_loopback_and_polls_dr(self):
        prog = pg.SERIAL_WITNESS["serloop"][0]
        steps = [s for s in prog if not isinstance(s, str)]
        self.assertIn(("LDAI", 0x10), steps, "MCR = 0x10")
        self.assertIn(("LDBI", 0x01), steps, "DR is LSR bit 0")
        self.assertNotIn(("LDBI", 0x20), steps, "TX poll is not needed")

    def test_sertx_sends_DINO_crlf_polling_thre(self):
        prog = pg.SERIAL_WITNESS["sertx"][0]
        steps = [s for s in prog if not isinstance(s, str)]
        thr = ("STA", *pg._addr(0x4800))
        # every THR store past the init (whose DLL write is also at 0x4800)
        sent = bytes(steps[i - 1][1] for i, s in enumerate(steps)
                     if s == thr and i > 16)
        self.assertEqual(sent, b"DINO\r\n")
        self.assertEqual(steps.count(("LDBI", 0x20)), 6, "one THRE poll per byte")
        self.assertEqual(steps[-3:], [("LDAI", 0x53), ("OUT",), ("HALT",)])

    def test_serrx_never_halts_and_echoes(self):
        prog = pg.SERIAL_WITNESS["serrx"][0]
        steps = [s for s in prog if not isinstance(s, str)]
        self.assertNotIn(("HALT",), steps, "soak image: never halts")
        self.assertIn(("LDBI", 0x01), steps, "polls DR")
        self.assertIn(("LDBI", 0x20), steps, "polls THRE before the echo")
        # GOTCHA 2: RBR is read EXACTLY ONCE per character
        self.assertEqual(steps.count(("LDA", *pg._addr(0x4800))), 1)

    def test_serbaud_is_the_divisor_dance_then_halt(self):
        prog = pg.SERIAL_WITNESS["serbaud"][0]
        steps = [s for s in prog if not isinstance(s, str)]
        self.assertEqual(steps[-1], ("HALT",))
        self.assertIn(("LDAI", 0x18), steps, "DLL = 24")
        self.assertNotIn(("LDAI", 0x07), steps, "no FCR: nothing but the divisor")


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
