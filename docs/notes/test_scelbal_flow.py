#!/usr/bin/env python3
"""Host tests for scelbal_flow.py -- control flow and flag analysis of 8008 code.

PHASE_BASIC step 4a. The translator picks a cheap DINO macro only where
an 8008 flag is DEAD, and picks a branch sense from the carry's POLARITY:

    8008  SU/SB/CP set C on BORROW         DINO  SUB sets C on NOT-borrow
    8008  ND/XR/OR clear C                 DINO  logic leaves C UNDEFINED
    8008  INr/DCr leave C alone            DINO  INR/DCR clobber C

so both analyses must be right, or a branch goes the wrong way on a path
the tests never ran. The 8008's stack is not addressable, so a CAL always
returns to the instruction after it: the call graph is exact.

Run: python3 test_scelbal_flow.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as8                                                    # noqa: E402
import scelbal_flow as flow                                   # noqa: E402

UP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                  "asm", "scelbal", "upstream", "sc1fast.asm")


def prog(src):
    text = "\tORG 002#000\n" + src + "\n"
    items = as8.parse(text)
    return flow.Flow(items, as8.parse.symbols, entries=["START"])


def at(f, label):
    return f.sym[label]


def test_liveness_straight_line():
    f = prog("START: CPI 001\nX: LAI 005\n\tJTZ START\n\tHLT")
    assert "Z" in f.live_out[at(f, "START")]
    assert "C" not in f.live_out[at(f, "START")]


def test_liveness_killed_by_alu():
    f = prog("START: CPI 001\nX: NDA\n\tJTZ START\n\tHLT")
    assert "Z" not in f.live_out[at(f, "START")]


def test_liveness_flows_through_ret_to_caller():
    f = prog("START: CAL SUB\nAFT: JTC START\n\tHLT\nSUB: CPI 003\nR: RET")
    assert "C" in f.live_out[at(f, "SUB")]          # the CPI's carry
    assert "C" in f.live_out[at(f, "R")]


def test_ret_only_feeds_its_own_callers():
    f = prog("START: CAL S1\n\tCAL S2\n\tJTZ START\n\tHLT\n"
             "S1: CPI 003\nR1: RET\nS2: CPI 004\nR2: RET")
    assert "Z" in f.live_out[at(f, "R2")]
    assert "Z" not in f.live_out[at(f, "R1")]       # S2 kills it first


def test_inr_does_not_kill_carry():
    f = prog("START: CPI 001\nI: INL\n\tJTC START\n\tHLT")
    assert "C" in f.live_out[at(f, "I")]
    assert "C" in f.live_out[at(f, "START")]


def test_polarity_sub_is_inverted_add_is_true():
    f = prog("START: SUI 001\nA: JTC START\n\tADI 001\nB: JTC START\n\tHLT")
    assert f.c_pol_in[at(f, "A")] == {"I"}
    assert f.c_pol_in[at(f, "B")] == {"T"}


def test_logic_carry_normalized_to_what_readers_need():
    """ADDER: NDA / ADDMOR: ACM and SUBBER: NDA / SUBTRA: SBM -- the
    8008's cleared carry must arrive as DINO 0 for ADC, DINO 1 for SBB."""
    f = prog("START: NDA\nA: ACI 000\n\tNDA\nS: SBI 000\n\tHLT")
    assert f.c_norm[at(f, "START")] == "T"
    assert f.c_pol_in[at(f, "A")] == {"T"}
    assert f.c_pol_in[at(f, "S")] == {"I"}


def test_logic_carry_unread_stays_zero():
    f = prog("START: NDA\nA: LAB\n\tHLT")
    assert at(f, "START") not in f.c_norm
    assert f.c_pol_in[at(f, "A")] == {"Z0"}


def test_polarity_survives_inr_and_joins():
    f = prog("START: SUI 001\n\tJTZ M\n\tADI 001\nM: INB\nA: JTC START\n\tHLT")
    assert f.c_pol_in[at(f, "A")] == {"I", "T"}


def test_polarity_through_call():
    f = prog("START: CAL S\nA: JFC START\n\tHLT\nS: CPI 004\n\tRET")
    assert f.c_pol_in[at(f, "A")] == {"I"}


def test_transparent_callee_passes_callers_state():
    """SWAP touches no flag, so each caller keeps its own carry across it;
    a context-insensitive join would hand every caller every carry."""
    f = prog("START: SUI 001\n\tCAL SWAP\nA: JTC START\n"
             "\tADI 001\n\tCAL SWAP\nB: JTC START\n\tHLT\n"
             "SWAP: LAB\n\tRET")
    assert f.c_pol_in[at(f, "A")] == {"I"}
    assert f.c_pol_in[at(f, "B")] == {"T"}


def test_transparent_callee_liveness_is_per_call_site():
    f = prog("START: CPI 001\nC1: CAL SWAP\n\tJTC START\n"
             "\tNDA\nC2: CAL SWAP\n\tNDA\n\tHLT\n"
             "SWAP: LAB\nR: RET")
    assert "C" in f.live_out[at(f, "START")]
    assert "C" not in f.live_in[at(f, "C2")]


def test_h_l_constants_through_transparent_call():
    f = prog("START: LHI 026\n\tLLI 005\n\tCAL SWAP\nA: LAM\n\tINL\n"
             "B: LAM\n\tHLT\nSWAP: LAB\n\tRET")
    assert f.consts[at(f, "A")] == {"H": 0o26, "L": 5}
    assert f.consts[at(f, "B")] == {"H": 0o26, "L": 6}


def test_constants_join_to_unknown():
    f = prog("START: LLI 001\n\tJTZ M\n\tLLI 002\nM: LAM\n\tHLT")
    assert f.consts[at(f, "M")]["L"] is None


def test_constants_killed_by_callee_that_writes():
    f = prog("START: LLI 001\n\tLHI 002\n\tCAL W\nA: LAM\n\tHLT\n"
             "W: LLI 007\n\tJTZ W2\n\tLLI 010\nW2: RET")
    assert f.consts[at(f, "A")] == {"H": 2, "L": None}


def test_constants_through_register_moves():
    f = prog("START: LDI 027\n\tLHD\nA: LAM\n\tHLT")
    assert f.consts[at(f, "A")]["H"] == 0o27


def test_cell_dead_when_fused_access_is_the_only_reader():
    """LHI/LLI both known at LAM -> LAM is an absolute LDA, reads no cell,
    so the stores are dead; VH is never read at all."""
    f = prog("START: LHI 026\n\tLLI 005\nA: LAM\n\tLLI 007\n\tHLT")
    assert "VL" not in f.cell_live_out[at(f, "START") + 2]
    assert "PH" not in f.cell_live_out[at(f, "START")]
    assert "VH" not in f.cell_live_out[at(f, "START")]


def test_cell_live_for_unfused_and_register_reads():
    f = prog("START: LLI 005\n\tJTZ M\n\tLLI 006\nM: LAM\n\tLAH\n\tHLT")
    assert "VL" in f.cell_live_out[at(f, "START")]      # L unknown at M
    assert "PH" in f.cell_live_in[at(f, "M")]
    assert "VH" in f.cell_live_in[at(f, "M")]           # LAH reads H


def test_cell_live_across_transparent_call_per_site():
    f = prog("START: LBI 001\n\tCAL S\n\tLAB\n\tLBI 002\n\tCAL S\n"
             "\tHLT\nS: LAC\n\tRET")
    assert "VB" in f.cell_live_out[at(f, "START")]
    b2 = at(f, "START") + 6                         # the second LBI
    assert "VB" not in f.cell_live_out[b2]


def test_redundant_load_is_not_a_write():
    """The translator emits NOTHING for LHI/LLI of the value already held,
    so liveness must not count it as a store -- or the FIRST store looks
    dead, is dropped too, and the cell is never written (2026-10-06: LIST
    printed program lines as zeros)."""
    f = prog("START: LHI 026\n\tLLI 005\n\tJTZ M\n\tLLI 006\n"
             "M: LHI 026\nB: LAM\n\tHLT")
    assert "PH" in f.cell_live_out[at(f, "START")]
    assert f.cell_du(at(f, "M"))[0] == frozenset()


def test_cell_used_inside_callee():
    f = prog("START: LBI 001\n\tCAL S\n\tHLT\nS: LAB\n\tRET")
    assert "VB" in f.cell_live_out[at(f, "START")]


def test_peek_poke_ports_read_d_and_e():
    """Dead-store removal must not drop the address POKE/PEEK use."""
    f = prog("START: LDI 360\n\tLEI 001\n\tOUT 011\n\tLDI 361\n"
             "\tINP 1\n\tHLT")
    assert {"VD", "VE"} <= f.cell_live_out[at(f, "START") + 2]
    assert "VD" in f.cell_live_out[at(f, "START")]


def test_whole_scelbal_is_analysable():
    items = as8.parse(open(UP).read())
    f = flow.Flow(items, as8.parse.symbols, entries=["EXEC"],
                  native=["CINP", "CPRINT"])
    assert len(f.reached) > 3000
    assert f.sym["EXEC"] in f.reached


# ---- runner: ENUMERATED (test_suite_reachability.py) -------------------
if __name__ == "__main__":
    _failed = []
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        try:
            _fn()
            print(f"  ok   {_name}")
        except Exception as _e:                   # noqa: BLE001
            _failed.append((_name, _e))
            print(f"  FAIL {_name}: {type(_e).__name__}: {_e}")
    if _failed:
        print(f"\n{len(_failed)} FAILED")
        sys.exit(1)
    print("OK test_scelbal_flow")
