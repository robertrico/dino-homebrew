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
import kicad_contracts
from kicad_contracts import continuity_checklist

ROOT = os.path.normpath(os.path.join(HERE, "..", "..",
                                     "dino_v0_0_2", "dino_v0_0_2.kicad_sch"))

# Netlist-extracted 2026-08-11, not read off the schematic:
#   mar              U59.11 B7 (MAR15 buffered out), U60.8/9 ('02 in -> ~{RAM_EN})
#   memory           U24.20 ~{CE}   (the ROM's chip enable)
#   program_counter  U12.9, U14.9   (A7 of the high '245 pair)
#
# UPDATED 2026-08-25, PHASE E. Two changes, both deliberate:
#
#   U24.20 LEFT THIS NET. The ROM's chip enable is now ~{ROM_SEL} = NAND(
#   ~{RAM_EN}, ~{M14}), so the ROM answers 0x0000-0x3FFF and 0x4000-0x7FFF
#   is an I/O window. M15 keeps its five ADDRESS consumers and gains U74.10,
#   which is the M15 term of ~{RAM_OE_G} = NAND(RAM_OE_ON, M15).
#
#   THE `ROM_EN` ALIAS WAS DELETED. Once U24.20 moved, `ROM_EN` named a net
#   with no ROM consumer at all -- a label describing a function that had
#   moved to ~{ROM_SEL}. This is the exact net whose alias split cost every
#   continuity checklist this project ever generated, so a stale name on it
#   re-arms that hazard under a name that now also lies.
M15_PINS = {("U12", 9), ("U14", 9), ("U74", 10),
            ("U59", 11), ("U60", 8), ("U60", 9)}


# A pytest FUNCTION, not a module-level assert. The other test_*.py here assert
# at import time, which is fine while they pass -- but a RED one aborts pytest
# COLLECTION, and a collection error takes the whole `make -C fpga verify` host
# suite with it. A red test must report itself without hiding the other 147.
def test_m15_is_one_complete_checklist_row():
    rows = continuity_checklist(ROOT)
    hits = [(net, new, old) for net, new, old in rows
            if "M15" in net or "ROM_EN" in net]

    assert hits, (
        "M15 is absent from the continuity checklist entirely. "
        "It is a board-to-board wire (mar -> memory, mar -> program_counter) "
        "and the checklist is the only artifact that would tell you to land it.")

    assert len(hits) == 1, (
        f"M15 split across {len(hits)} checklist rows "
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


# --- the guard: no wire may go missing THIS WAY again --------------------
#
# M15/ROM_EN and CW17/CW18 were all one failure: a net whose label set differs
# between sheets gets a different key per sheet, every key looks single-sheet,
# and the cross-sheet filter drops the whole wire. Silent — a copper wire is
# driven by no test and sampled by no test, which is why M15 sat that way while
# the machine booted from ROM every day.
#
# Those three are fixed in the schematic. Nothing stops the fourth. This guard
# is the thing that stops the fourth.
#
# alias_splits() is deliberately PURE (it takes the net->pins map, not a path)
# so it can be tested against a synthetic split. A guard written only against
# the live design would have passed on its first run and proved nothing.
#
# kicad_contracts is imported as a MODULE and the attribute is looked up inside
# each test, so a missing function is one test failure — not an ImportError at
# collection time, which would take the whole host suite down with it.


def test_alias_splits_flags_one_label_carried_under_two_net_keys():
    net_pins = {
        # the real CW17 shape: bare on microcode, aliased on control_word
        "CW17":             [("U23", 12, "microcode")],
        "CW17/~{SRC_BANK}": [("U28", 6, "control_word"), ("U70", 4, "control_word")],
        # a healthy cross-sheet net, must NOT be flagged
        "MDR0":             [("U19", 18, "memory"), ("U25", 18, "mdr")],
    }
    splits = kicad_contracts.alias_splits(net_pins)
    assert splits == {"CW17": ["CW17", "CW17/~{SRC_BANK}"]}, (
        f"expected CW17 flagged as split across two keys, got {splits!r}")


def test_alias_splits_is_quiet_when_every_sheet_agrees():
    net_pins = {
        "M15/ROM_EN": [("U59", 11, "mar"), ("U24", 20, "memory")],
        "MDR0":       [("U19", 18, "memory"), ("U25", 18, "mdr")],
    }
    assert kicad_contracts.alias_splits(net_pins) == {}


def test_no_alias_split_survives_anywhere_in_the_design():
    splits = kicad_contracts.alias_splits(kicad_contracts.net_pins(ROOT))
    assert not splits, (
        "a net is carried under two different label sets, so its ends key "
        "differently and the continuity checklist drops the wire:\n  " +
        "\n  ".join(f"{base}: {keys}" for base, keys in sorted(splits.items())))


# --- B: a new chip's OWN on-board wiring must be on the list -------------
#
# continuity_checklist drops any net confined to one sheet file. That is right
# for the DEFAULT report -- "which nets cross a board boundary" is what
# dino_sheet_contracts.md consumes. It is wrong once you pass `refs`, because
# then the question is "what do I land for these chips", and a new chip's own
# on-board wiring is most of that work.
#
# Measured 2026-08-11 for the twelve stack chips: 41 nets are on the list and
# 38 are invisible -- 62 pins, barely half the job. ~{TC1} is the one that
# justifies the change: drop U63.15 -> U64.10 and the SP counts correctly for
# 256 pushes before the low byte wraps, which PROG_stack passes clean.
#
# Single-pin nets are NOT work. CW16 and CW19-23 are U23 outputs to nothing;
# listing them as "land this" would be wrong, and CLAUDE.md warns specifically
# against reading unwired CW bits as a failure. They belong in a separate
# no-connect bucket -- accounted for, not silently absent.

def test_refs_list_includes_a_new_chips_own_on_board_wiring():
    rows = continuity_checklist(ROOT, ["U63", "U64"])
    hits = [(net, new, old) for net, new, old in rows if net == "~{TC1}"]
    assert hits, (
        "~{TC1} is absent: U63.15 -> U64.10 is the '169 ripple-carry chain and "
        "it lives entirely inside stack_pointer.kicad_sch, so the cross-sheet "
        "filter hides it. Unlanded, SP counts fine for 256 pushes before the "
        "low byte wraps — PROG_stack passes and the bench learns nothing.")
    net, new, old = hits[0]
    assert set(new) | set(old) == {("U63", 15), ("U64", 10)}, \
        f"{net}: expected U63.15 + U64.10, got new={new} old={old}"


def test_single_pin_stubs_are_bucketed_not_listed_as_work():
    rows = continuity_checklist(ROOT, ["U23"])
    listed = {net for net, _, _ in rows}
    assert "CW16/~{CIN_SEL}" not in listed, (
        "CW16 is a U23 output wired to nothing — it must not appear as a wire "
        "to land. Unwired CW bits are correct, not a failed label.")

    # RESERVE_BITS, not a second hand-written list. A tuple someone has to
    # remember to update is the failure test_suite_reachability.py exists for,
    # and this test drifted from the ledger once already when the aliases
    # landed on 2026-08-27.
    stubs = kicad_contracts.unlanded_stubs(ROOT, ["U23"])
    assert set(stubs) >= RESERVE_BITS, (
        f"the unwired U23 outputs must be reported as no-connects so they "
        f"are accounted for rather than silently missing; got {sorted(stubs)}")


def test_cw21_is_a_real_crossing_now_that_the_flag_mux_consumes_it():
    """PHASE F, 2026-08-27. U77.1 is CW21's first consumer in the machine's
    life, so it must appear as WORK TO LAND and not in the no-connect bucket.

    This is the regression for the fault the stub bucket caught on the day:
    the ALU sheet carried FLAG_SEL0 alone while U23.17 carried CW21 alone,
    which is two nets and a floating select input. A floating LS input reads
    HIGH, which is the value that makes the mux look correct and JNC dead."""
    rows = continuity_checklist(ROOT, ["U77"])
    listed = {net for net, _, _ in rows}
    assert "CW21/FLAG_SEL0" in listed, (
        "CW21 must be a crossing now — U77.1 consumes it. Got: "
        f"{sorted(listed)}")
    assert "CW21/FLAG_SEL0" not in set(kicad_contracts.unlanded_stubs(
        ROOT, ["U77"])), "CW21 has a consumer; it is not a stub any more"


def test_default_report_is_unchanged_by_the_refs_relaxation():
    # dino_sheet_contracts.md and every downstream consumer read this one.
    # Relaxing the filter must not touch it.
    rows = continuity_checklist(ROOT)
    nets = {net for net, _, _ in rows}
    assert "~{TC1}" not in nets, (
        "the no-refs report must stay board-to-board only — ~{TC1} is "
        "intra-sheet and must not leak into the default checklist")
    # Was "M15/ROM_EN" until phase E deleted the ROM_EN alias. The CROSSING
    # is unchanged -- mar -> memory, mar -> program_counter -- only its key
    # moved, because a net's key here is its full label set.
    assert "M15" in nets, "the default report lost a real crossing"



# --- C: the stub bucket is a LEDGER, not a dumping ground ---------------
#
# Found 2026-08-23. unlanded_stubs() reports single-pin nets so they are
# accounted for rather than silently absent -- but nothing asserted WHICH ones
# are allowed to be there. Twenty were, and only six were legitimate.
#
# Five were real alias splits of the CW9/SA2 shape: microcode labelled the net
# CWnn, the consumer sheet labelled it SA2/PC_UP/PC_MAR_MUX, the two names
# share no substring, and alias_splits() -- which keys on a shared BASE label
# -- is structurally unable to see it. Those five are now joined in the
# schematic (sheet_ops/2026-08-23_alias_*.json).
#
# The remaining eight are a DIFFERENT and larger gap, recorded here rather
# than fixed: net_pins() walks the ten child sheets and NOT the root sheet.
# Root carries U6 (T-counter), U7/U8 (T decoders), U20 (divider), U27
# (clock/reset), U56, U61, Y1, SW2 -- real parts on no child sheet. Their pins
# can never reach a continuity checklist, and any child-sheet net terminating
# on root is misreported as a no-connect. Whether net_pins() should scan root
# is a design decision: it would add real parts to every checklist, which is
# probably right, but it changes what --continuity prints for every module.
#
# Until then this test pins the exact set. A NEW stub fails immediately, which
# is the whole point -- a tool's silence is not coverage.

# RENAMED 2026-08-27, PHASE F. The five remaining reserve bits gained their
# function aliases on the microcode sheet when CW21 got FLAG_SEL0 -- the whole
# CW16-CW23 group was labelled in one pass rather than one at a time. Every
# alias sorts AFTER its CWnn (a leading "~{" or an F), so CWnn keeps the net
# name and stays on the CW[0..23] bus.
#
# CW21 LEFT THIS LEDGER the same day: U77.1 (the flag mux '157's S input) is
# its first consumer ever, so it is a genuine crossing now and appears on the
# checklist proper as CW21/FLAG_SEL0 against U23.17. That is what an alias
# binding for the first time looks like -- "an alias binds only when its
# consumer pin exists".
RESERVE_BITS = {"CW16/~{CIN_SEL}", "CW19/~{MISC_BANK}", "CW20/~{ADDR_SEL1}",
                "CW22/FLAG_SEL1", "CW23/FLAG_POL"}

# PHASE E, 2026-08-25. U75's three published strobes have no consumer in the
# CORE and are not supposed to have one: they are the bus DINO publishes, and
# their counterparts live on CARDS that do not exist yet. An unwired output is
# correct here, exactly as the no-connect bucket's own header says.
#
# ~{IO_WR} and ~{IO_RD_Q} retire when the first card lands on them. RESET_B is
# a BUFFER of RESET for the backplane and may stay a stub indefinitely -- that
# is what a published reset looks like with no card plugged in.
PUBLISHED_BUS = {
    "~{IO_WR}":    "OR(~{IO_SEL}, ~{RAM_WRITE_EN}) -> every card's ~WR",
    "RESET_B":     "OR(RESET, GND) -> the backplane's reset",
}
# ~{IO_RD_Q} LEFT THIS LEDGER 2026-08-26, PHASE E STEP B. It was a stub while
# U75.11 was its only pin; card zero's '138 (U76.4, E1) gave it a second and
# it is now a genuine crossing on the checklist proper. ~{IO_WR} and RESET_B
# stay -- no card uses them yet.

ROOT_CROSSING = {           # counterpart lives on the root sheet
    "CW12":     "END      -> root U61.3",
    "CW15":     "HALT     -> root U61.5/6",
    "T0":       "root T-counter U6/U7/U8",
    "T1":       "root T-counter U6/U7/U8",
    "T2":       "root T-counter U6/U7/U8",
    "T3":       "root T-counter U6/U7/U8",
    "~{RESET}": "root U27.8",
}
# RESET LEFT THIS LEDGER 2026-08-25, PHASE E. It was a stub because its only
# child-sheet pin was U10.6 (program_counter) and its driver U27.9 is on the
# ROOT sheet, which net_pins() does not walk. U75.9 gave it a SECOND child-
# sheet pin, so it is now a genuine cross-sheet crossing and appears on the
# checklist proper. ~{RESET} still has exactly one (alu U47) and stays.


def test_stub_bucket_contains_only_known_entries():
    stubs = set(kicad_contracts.unlanded_stubs(ROOT))
    allowed = RESERVE_BITS | set(ROOT_CROSSING) | set(PUBLISHED_BUS)
    unexpected = stubs - allowed
    assert not unexpected, (
        "new single-pin net(s) -- either a real alias split (the CW9/SA2 "
        "shape, which alias_splits cannot see because the two labels share no "
        "substring) or a wire that was never landed:\n  " +
        "\n  ".join(sorted(unexpected)))
    vanished = allowed - stubs
    assert not vanished, (
        "expected stub(s) are gone -- if that is a real fix, delete them from "
        "RESERVE_BITS/ROOT_CROSSING so the ledger stays honest:\n  " +
        "\n  ".join(sorted(vanished)))


def test_the_five_repaired_aliases_stay_joined():
    """Regression for 2026-08-23. Each of these was in the no-connect bucket
    while being a live wire on a working machine."""
    np = kicad_contracts.net_pins(ROOT)
    for key, sheets in (("CW9/SA2", {"microcode", "alu"}),
                        ("CW10/SA1", {"microcode", "alu"}),
                        ("CW11/SA0", {"microcode", "alu"}),
                        ("CW13/PC_UP", {"microcode", "program_counter"}),
                        ("CW14/PC_MAR_MUX", {"microcode", "mar"})):
        assert key in np, (
            f"{key} is split again -- both sheets must declare the SAME label "
            f"set or the checklist drops the wire")
        got = {s for _, _, s in np[key]}
        assert got == sheets, f"{key}: expected {sheets}, got {got}"


if __name__ == "__main__":
    # ENUMERATED, not a hand-written sequence. The block that used to live
    # here named six of this module's eleven test_ functions; five had never
    # run -- including both bank-select row checks and the refs-relaxation
    # regression. Guarded by test_suite_reachability.py.
    _failed = []
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        try:
            _fn()
            print(f"ok  {_name}")
        except AssertionError as _e:
            _failed.append(_name)
            print(f"FAIL {_name}: {_e}")
    for _bit, _pins in BANK_SELECTS.items():
        _one_complete_row(_bit, _pins)
        print(f"ok  {_bit}: all {len(_pins)} pins on one checklist row")
    if _failed:
        print(f"\n{len(_failed)} FAILED")
        sys.exit(1)
    print("\ncontinuity completeness: OK")
