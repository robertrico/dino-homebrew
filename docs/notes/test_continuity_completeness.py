#!/usr/bin/env python3
"""Host test for kicad_contracts.continuity_checklist().
Run: python3 test_continuity_completeness.py

The continuity checklist is the ONLY coverage the netlist->copper step has.
A wire missing from it is driven by no test and sampled by no test — that is
the MAR-lo post-mortem in one sentence. So the checklist's completeness is
itself worth a test.

M15/ROM_EN is the case that proves it: one physical board-to-board wire, the
ROM chip-enable, carried under two names. Every sheet that touches it must
declare the SAME label set, or build_report keys the ends differently, the
cross-sheet filter sees singletons, and the whole net drops off the list.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kicad_contracts import continuity_checklist

ROOT = os.path.normpath(os.path.join(HERE, "..", "..",
                                     "dino_v0_0_2", "dino_v0_0_2.kicad_sch"))

# Netlist-extracted 2026-08-11, not read off the schematic:
#   mar              U59.11 B7 (MAR15 buffered out), U60.8/9 ('02 in -> ~{RAM_EN})
#   memory           U24.20 ~{CE}   (the ROM's chip enable)
#   program_counter  U12.9, U14.9   (A7 of the high '245 pair)
M15_PINS = {("U12", 9), ("U14", 9), ("U24", 20),
            ("U59", 11), ("U60", 8), ("U60", 9)}


# A pytest FUNCTION, not a module-level assert. The other test_*.py here assert
# at import time, which is fine while they pass -- but a RED one aborts pytest
# COLLECTION, and a collection error takes the whole `make -C fpga verify` host
# suite with it. A red test must report itself without hiding the other 147.
def test_m15_rom_en_is_one_complete_checklist_row():
    rows = continuity_checklist(ROOT)
    hits = [(net, new, old) for net, new, old in rows
            if "M15" in net or "ROM_EN" in net]

    assert hits, (
        "M15/ROM_EN is absent from the continuity checklist entirely. "
        "It is a board-to-board wire (mar -> memory, mar -> program_counter) "
        "and the checklist is the only artifact that would tell you to land it.")

    assert len(hits) == 1, (
        f"M15/ROM_EN split across {len(hits)} checklist rows "
        f"({', '.join(net for net, _, _ in hits)}) — one wire must be one row, "
        "or beeping the list leaves an end unwalked.")

    net, new, old = hits[0]
    found = set(new) | set(old)
    missing = M15_PINS - found
    extra = found - M15_PINS
    assert not missing, f"{net}: checklist omits {sorted(missing)}"
    assert not extra, f"{net}: checklist claims pins not on the net: {sorted(extra)}"


# The two bank-select bits, same disease as M15. U23 is the third microcode
# EEPROM; CW17/CW18 are its ONLY wired outputs and the entire bank-1 feature
# rides on them. The microcode side labels the net bare (CW17); control_word
# labels it CW17 + ~{SRC_BANK}. Different label sets -> different keys -> both
# ends look single-sheet -> the checklist drops the one wire that turns the
# expansion decoders on.
#
# Netlist-extracted 2026-08-11:
#   microcode      U23.12 I/O1 -> CW17        U23.13 I/O2 -> CW18
#   control_word   U28.6  E3   (active HIGH, enables the bank-0 decoder)
#                  U70.4  E1   (active LOW,  enables the bank-1 decoder)
# One signal, opposite-polarity enables — which is exactly why landing it on
# the wrong pin fires both decoders at once, and why it must be on the list.
BANK_SELECTS = {
    "CW17": {("U23", 12), ("U28", 6), ("U70", 4)},   # ~{SRC_BANK}
    "CW18": {("U23", 13), ("U30", 6), ("U71", 4)},   # ~{DST_BANK}
}


def _one_complete_row(bit, expected):
    rows = continuity_checklist(ROOT)
    hits = [(net, new, old) for net, new, old in rows if bit in net]

    assert hits, (
        f"{bit} is absent from the continuity checklist entirely. It is the "
        f"board-to-board wire from U23 (third microcode EEPROM) to the "
        f"control_word decoders — miss it and both bank decoders lose their "
        f"enable, which reads at the bench like a bad three-ROM burn.")

    assert len(hits) == 1, (
        f"{bit} split across {len(hits)} checklist rows "
        f"({', '.join(net for net, _, _ in hits)}) — one wire must be one row.")

    net, new, old = hits[0]
    found = set(new) | set(old)
    missing = expected - found
    extra = found - expected
    assert not missing, f"{net}: checklist omits {sorted(missing)}"
    assert not extra, f"{net}: checklist claims pins not on the net: {sorted(extra)}"


def test_cw17_src_bank_is_one_complete_checklist_row():
    _one_complete_row("CW17", BANK_SELECTS["CW17"])


def test_cw18_dst_bank_is_one_complete_checklist_row():
    _one_complete_row("CW18", BANK_SELECTS["CW18"])


if __name__ == "__main__":
    test_m15_rom_en_is_one_complete_checklist_row()
    print(f"ok  M15/ROM_EN: all {len(M15_PINS)} pins on one checklist row")
    for _bit, _pins in BANK_SELECTS.items():
        _one_complete_row(_bit, _pins)
        print(f"ok  {_bit}: all {len(_pins)} pins on one checklist row")
