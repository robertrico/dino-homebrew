#!/usr/bin/env python3
"""A probe header is not a consumer.

2026-10-29 the Rev 1.0 pre-order batch put J15 (the LA header: 16 signals,
16 GND) on the root sheet. Its pins are passive, and build_contracts read
every non-driving pin as an input, so root became an IN of ten signals it
only exposes to the analyser (WR_GATE, ~{IRQ}, FLAG_C, INJECT, ...). The
block classifier then refused to load: unfed inputs with no driver.

Instrument pins (J15, test points) and DNP pads (C95 on CLK_ALU) are left out of the direction
derivation. Everything else keeps its contract: a series resistor's
passive pin is still copper into a consumer (R2 on the SP board's CLK).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kicad_contracts as kc  # noqa: E402

ROOT = os.path.join(HERE, "..", "..", "dino_v0_0_2", "dino_v0_0_2.kicad_sch")
C = kc.build_contracts(ROOT)


def labels(sheet, kind):
    return {lab for lab, _ in C[sheet][kind]}


def sheet(name):
    return next(s for s in C if kc.short(s) == name)


class Probes(unittest.TestCase):
    def test_root_consumes_nothing_it_only_probes(self):
        probed = {"~{IRQ}", "FLAG_C", "WR_GATE", "~{IR_LOAD}", "~{PC_LOAD}",
                  "INJECT", "~{IO_RD_Q}", "~{IO_WR}", "CLK_ALU"}
        self.assertEqual(labels("/", "IN") & probed, set())

    def test_root_keeps_its_real_inputs(self):
        # U61.3 <- END_OR_ACCEPT, U61.5 <- HALT: chip pins, not the header
        self.assertTrue({"END_OR_ACCEPT", "CW15=HALT"} <= labels("/", "IN"))

    def test_probed_signals_do_not_list_root_as_a_destination(self):
        for lab in ("FLAG_C", "WR_GATE", "INJECT"):
            outs = [o for l, o in sum((C[s]["OUT"] for s in C), []) if l == lab]
            self.assertTrue(outs, lab)
            for o in outs:
                self.assertNotIn("/", o, lab)

    def test_series_resistor_still_carries_a_contract(self):
        # SP board's CLK arrives through R2 (passive): still an input there
        self.assertIn("CLK", labels(sheet("Stack Pointer"), "IN"))


if __name__ == "__main__":
    unittest.main()
