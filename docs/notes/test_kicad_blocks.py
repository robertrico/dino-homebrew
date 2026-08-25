#!/usr/bin/env python3
"""Host tests for the BLOCK surface derivation in kicad_contracts.py.

A block is an integration step: several bench-proven modules wired to each
other, with the rig touching only what the combination newly determines.
THE BLOCK LAW (BRINGUP.md): sample a signal at block level only if its
value depends on more than one member. Everything else is copper, strapped,
or already retired by a module test or an earlier block.

These tests are the RED half of that work. They assert the derivation, the
retirement cascade, and — most importantly — that the classifier HARD-ERRORS
rather than silently guessing, because a silently-misclassified input is how
a floating WRITE_DIR fires real RAM writes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_contracts as kc

try:
    import pytest
except ImportError:            # pragma: no cover -- plain `python3
    pytest = None               # docs/notes/test_kicad_blocks.py` has no
                                 # pytest dependency; keep it that way.

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", "dino_v0_0_2", "dino_v0_0_2.kicad_sch"))

FAILS = []


def check(cond, label):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILS.append(label)


def check_eq(got, want, label):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        print(f"         got  {sorted(got) if isinstance(got, (set, frozenset)) else got}")
        print(f"         want {sorted(want) if isinstance(want, (set, frozenset)) else want}")
        FAILS.append(label)


def check_raises(fn, needle, label):
    try:
        fn()
    except SystemExit as e:
        if needle in str(e):
            print(f"  ok   {label}")
            return
        print(f"  FAIL {label} — wrong message: {e}")
        FAILS.append(label)
        return
    except Exception as e:                       # noqa: BLE001
        print(f"  FAIL {label} — wrong exception type: {type(e).__name__}: {e}")
        FAILS.append(label)
        return
    print(f"  FAIL {label} — no error raised")
    FAILS.append(label)


CONTRACTS = kc.build_contracts(ROOT)
SURF = kc.build_blocks(CONTRACTS)

IRB = {f"IRB{i}" for i in range(8)}
MDR = {f"MDR{i}" for i in range(8)}
OB = {f"OB{i}" for i in range(8)}
T03 = {f"T{i}" for i in range(4)}
CW08 = {f"CW{i}" for i in range(9)}
DST7 = {"~{REG_A_LOAD}", "~{REG_B_LOAD}", "~{REG_C_LOAD}", "~{MAR_LO_LOAD}",
        "~{MAR_HI_LOAD}", "~{IR_LOAD}", "~{RAM_LOAD}"}
SRC8 = {"SRC_ACTIVE", "~{ROM_OUT}", "~{RAM_OUT}", "~{REG_A_OUT}", "~{REG_B_OUT}",
        "~{REG_C_OUT}", "~{ALU_OUT}", "~{SW_OUT}"}
JMP4 = {"~{PC_CLEAR}", "~{MDR_OUT}", "~{REG_OUT_LOAD}", "~{PC_LOAD}"}
SA3 = {"CW9=SA2", "CW10=SA1", "CW11=SA0"}
PCBITS = {"CW13=PC_UP", "CW14=PC_MAR_MUX"}
ENDHALT = {"CW12=END", "CW15=HALT"}
# 2026-08-10: control_word's eight new outputs, all consumed by the stack
# pointer sheet. Four bank-1 SRC decodes (U70), two bank-1 DST decodes (U71),
# and the two MISC codes that were U29's last free slots.
SPCTL8 = {"~{SP_LO_OUT}", "~{SP_HI_OUT}", "~{PC_LO_OUT}", "~{PC_HI_OUT}",
          "~{SP_LO_LOAD}", "~{SP_HI_LOAD}", "~{SP_UP}", "~{SP_DOWN}"}
# 2026-08-10: PC0-15 leave the pc sheet for the first time -- U72/U73 tap the
# '193 Q outputs into MDR so CALL can push a return address. Sixteen new
# board-to-board wires, the largest single crossing added since the MAR-lo
# post-mortem named that category.
PCBUS16 = {f"PC{i}" for i in range(16)}
# CLK is sampled in every block as a CAPTURE QUALIFIER, never as an assertion:
# the ROM outputs are invalid for one access time after T changes, and a blind
# sampler splits one T-state into several frames. Gating on CLK low samples
# after the ROM has settled. root.clock still owns CLK as an assertion.
QUAL = {"CLK"}
# T0-3 joins CLK as a block1 SAMPLE LABEL, not an assertion: root.tstates still
# owns the counter. Reading T means every sample carries the T-state that
# produced it, so the rig never infers t from position in a captured sequence.
# That inference required the fetch frame to be unique — and in the SRC pass it
# is not, since LDA's T0/T1/T2 are all mux_pc+pc_up+src=ROM and differ only in
# DST. Block1 only: block2 fills PF with MDR0-7, and blocks 2-6 do not decode
# per-T.
QUAL1 = QUAL | T03
# CLK + T0-3 are the STANDING TIMING SET: sampled in every block, in the same
# holes throughout, exactly as END/HALT are. Neither is an assertion —
# root.clock and root.tstates own them. They are what makes a sample
# INTERPRETABLE: CLK says the ROM has settled, T says which microcode row the
# sample belongs to.
TIMING = QUAL | T03


def test_block_names_and_order():
    print("block ladder shape")
    names = list(SURF)
    check_eq(names, ["block1", "block2", "block3", "block4", "block5"],
             "five blocks, in ladder order")
    check_eq(SURF["block1"]["members"], ["root", "microcode", "control_word"],
             "block1 members")
    check_eq(len(SURF["block5"]["members"]), 11,
             "block5 is all eleven modules — the ladder ENDS here")
    check("stack_pointer" in SURF["block5"]["members"],
          "stack_pointer is in the final block")
    check("stack_pointer" not in SURF["block3"]["members"],
          "stack_pointer arrives with the datapath, not before it")


def test_driven_gate():
    """The gate: driven-wire count may never rise."""
    print("driven-wire gate")
    counts = [len(SURF[b]["drive"]) for b in SURF]
    check_eq(counts, [8, 8, 0, 0, 0], "driven ladder 8,8,0,0,0")
    check(all(b <= a for a, b in zip(counts, counts[1:])),
          "driven count never rises between consecutive blocks")
    check_eq(set(SURF["block1"]["drive"]), IRB, "block1 drives exactly IRB0-7")
    check_eq(set(SURF["block2"]["drive"]), IRB, "block2 drives exactly IRB0-7")
    for b in ("block3", "block4", "block5"):
        check_eq(set(SURF[b]["drive"]), set(), f"{b} drives nothing")


def test_sample_counts():
    print("sample ladder")
    counts = [len(SURF[b]["sample"]) for b in SURF]
    check_eq(counts, [39, 31, 15, 15, 15],
             "sampled ladder 39,31,15,15,15 (CLK+T0-3 in every block)")
    for b in SURF:
        check_eq(SURF[b]["qualify"], ["CLK", "T0", "T1", "T2", "T3"],
                 f"{b} carries the standing timing set")


def test_block1_surface():
    print("block1 — control")
    s = SURF["block1"]
    want = DST7 | SRC8 | JMP4 | SA3 | PCBITS | ENDHALT | QUAL1 | SPCTL8
    check_eq(set(s["sample"]), want,
             "block1 samples the 34 + CLK + T0-3 as sample labels")
    check(T03 <= set(s["copper"]), "T0-3 is copper")
    check(CW08 <= set(s["copper"]), "CW0-8 is copper")
    check(ENDHALT <= set(s["copper"]), "END/HALT are copper as well as sampled")
    for sig in CW08:
        check(sig not in s["sample"] and sig not in s["drive"],
              f"copper {sig} is in neither drive nor sample")
    check(T03 <= set(s["copper"]), "T0-3 is still copper — sampled as a LABEL")
    for sig in T03:
        check(sig not in s["drive"], f"{sig} is sampled, never driven")
    check_eq(set(s["strap"]), {"FLAG_Z"}, "block1 straps exactly FLAG_Z")
    check_eq(s["strap"]["FLAG_Z"][0], "HIGH", "FLAG_Z strapped HIGH")
    check_eq(set(s["floats"]), set(), "block1 has no unclassified floating input")
    for sig in ("CLK", "~{CLK}", "RESET", "~{RESET}"):
        check(sig in s["retired"], f"{sig} retired at block1")
        if sig != "CLK":
            check(sig not in s["sample"], f"{sig} not sampled at block1")


def test_block2_surface():
    print("block2 — + pc + mar + memory")
    s = SURF["block2"]
    check_eq(set(s["sample"]), MDR | ENDHALT | TIMING | PCBUS16,
             "block2 samples MDR0-7 + PC0-15 + END/HALT + CLK + T0-3")
    check(all(f"M{i}" in s["copper"] for i in range(15)), "M0-14 are copper")
    # PHASE E, 2026-08-25: the ROM_EN alias was deleted. Once U24.20 moved to
    # ~{ROM_SEL} the name described a function that had left the net.
    check("M15" in s["copper"], "M15 is copper")
    # PHASE D, 2026-08-24: ~{ROM_BUF_EN} and ~{RAM_OE_G} joined the strap set
    # when the ROM-buffer and RAM-OE enables moved onto the MDR board, which
    # does not join the ladder until block3. Both values are forced --
    # ~{RAM_OE_G} LOW would leave U19 and U21 both driving MDR0-7. The cost is
    # that block2 no longer reads RAM under microcode control; that path is now
    # covered only by the memory module test.
    #
    # PHASE E, 2026-08-25: ~{RAM_OE_G} LEFT the strap set -- U74 g3 generates
    # it INSIDE block2 now. Its two upstream terms cross in from the MDR board
    # instead, and the forced electrical state is unchanged: RAM_OE_ON LOW
    # makes ~{RAM_OE_G} = NAND(LOW, M15) = HIGH, exactly what phase D strapped
    # by hand. READS_IDLE HIGH keeps the published card read strobe deasserted;
    # there is no card in the ladder to read.
    check_eq(set(s["strap"]),
             {"FLAG_Z", "WRITE_DIR", "~{ROM_BUF_EN}",
              "RAM_OE_ON", "READS_IDLE"}
             | {f"W{i}" for i in range(8)},
             "block2 straps FLAG_Z + WRITE_DIR + ROM_BUF_EN + RAM_OE_ON + "
             "READS_IDLE + W0-7")
    check_eq(s["strap"]["RAM_OE_ON"][0], "LOW",
             "RAM_OE_ON strapped LOW -- forces ~{RAM_OE_G} HIGH, so U19 and "
             "U21 cannot both drive MDR0-7")
    check_eq(s["strap"]["READS_IDLE"][0], "HIGH",
             "READS_IDLE strapped HIGH -- ~{IO_RD} never asserts in block2")
    check_eq(s["strap"]["~{ROM_BUF_EN}"][0], "LOW",
             "~{ROM_BUF_EN} strapped LOW -- block2's primary is fetch")
    check_eq(s["strap"]["WRITE_DIR"][0], "LOW", "WRITE_DIR strapped LOW")
    check_eq(set(s["floats"]), set(), "block2 has no unclassified floating input")
    # the retirement cascade: everything block1 sampled is gone here
    for sig in DST7 | SRC8 | SA3:
        check(sig not in s["sample"], f"{sig} retired by block1, not resampled")
    check_eq(s["retired_by"].get("SRC_ACTIVE"), "block1.decode",
             "block1 retirements are cited to the block, not a module")
    check_eq(s["retired_by"].get("~{RESET}"), "root.reset",
             "module retirements keep their module citation")


def test_block3_surface():
    print("block3 — + mdr")
    s = SURF["block3"]
    check_eq(set(s["sample"]), IRB | ENDHALT | TIMING,
             "block3 samples IRB0-7 + END/HALT + CLK + T0-3")
    check(IRB <= set(s["copper"]), "IRB is copper now — the IR is real")
    check(all(f"W{i}" in s["copper"] for i in range(8)), "W0-7 is copper now")
    check("WRITE_DIR" in s["copper"], "WRITE_DIR is copper now")
    check_eq(set(s["strap"]), {"FLAG_Z"}, "only FLAG_Z still strapped at block3")
    check(all(m not in s["sample"] for m in MDR), "MDR retired by block2")


def test_block4_surface():
    print("block4 — + registers + alu")
    s = SURF["block4"]
    check_eq(set(s["sample"]), OB | ENDHALT | TIMING,
             "block4 samples OB0-7 + END/HALT + CLK + T0-3")
    check("FLAG_Z" in s["copper"], "FLAG_Z is copper now — real flags")
    check_eq(set(s["strap"]), set(), "block4 straps nothing")
    check(all(i not in s["sample"] for i in IRB), "IRB retired by block3")


def test_block5_is_the_last_rung():
    """Block 5 is the end of the ladder. There WAS a block 6 — the same ten
    boards again, END unjumpered, ten resets for ten sums. It was dropped
    (2026-08-02): it added no board and no coverage, only repetition, and
    running the machine INTERACTIVELY off the switches via IN is a stronger
    acceptance than running the same fixed program ten more times."""
    print("block5 — the last rung")
    s5 = SURF["block5"]
    check_eq(set(s5["sample"]), OB | ENDHALT | TIMING,
             "block5 samples OB0-7 + END/HALT + CLK + T0-3")
    check(OB <= set(s5["copper"]), "OB is copper at block5 — io is present")
    check_eq(set(s5["strap"]), set(),
             "block5 straps nothing — IS0-7 never crosses a sheet, so SW1=0xF7 "
             "is a bench setting, not a contract strap")
    check_eq(len(s5["sample"]), 15, "block5 is fifteen sampled wires")
    check_eq(len(SURF), 5, "the ladder has no sixth rung")


def test_every_unfed_input_is_classified():
    """The WRITE_DIR lesson: an input with no driver is a hazard until named."""
    print("no silent floats anywhere on the ladder")
    for name, s in SURF.items():
        check_eq(set(s["floats"]), set(), f"{name}: every unfed input is drive or strap")


def test_hard_errors():
    print("hard errors, never last-writer-wins")
    good = kc.BLOCKS["block1"]

    def bad_retire():
        kc.block_surface(CONTRACTS, "x", dict(good, retire={"NO_SUCH_SIGNAL": "t"}))
    check_raises(bad_retire, "NO_SUCH_SIGNAL", "retire naming an absent signal raises")

    def bad_strap():
        kc.block_surface(CONTRACTS, "x", dict(good, strap={"NOPE": ("LOW", "t")}))
    check_raises(bad_strap, "NOPE", "strap naming an absent signal raises")

    def bad_anyway():
        kc.block_surface(CONTRACTS, "x", dict(good, sample_anyway=["~{PC_LOAD}"]))
    check_raises(bad_anyway, "~{PC_LOAD}", "sample_anyway on a non-copper signal raises")

    def bad_drive():
        kc.block_surface(CONTRACTS, "x", dict(good, drive=["T0"]))
    check_raises(bad_drive, "T0", "driving a copper signal raises")

    def unclassified():
        kc.block_surface(CONTRACTS, "x", dict(good, strap={}))
    check_raises(unclassified, "FLAG_Z", "an unfed input left unclassified raises")

    def bad_member():
        kc.block_surface(CONTRACTS, "x", dict(good, members=["root", "nosuchmod"]))
    check_raises(bad_member, "nosuchmod", "unknown member module raises")


def test_pinmap_has_block_bundles():
    """Blocks ride the existing MODMAPS machinery — no parallel code path."""
    print("pinmap integration")
    import io
    import re
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".blocks_test.h")
    try:
        kc.emit_pinmap(CONTRACTS, tmp)
        text = open(tmp).read()
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    for b in SURF:
        check(f"sig_{b}[]" in text, f"{b} emits a bundle into pinmap_gen.h")
    # every block bundle must carry exactly its drive+sample rows
    for b, s in SURF.items():
        m = re.search(r"static const sigpin_t sig_%s\[\] PROGMEM = \{(.*?)\n\};" % b,
                      text, re.S)
        check(m is not None, f"{b} bundle parses")
        if m:
            rows = m.group(1).count("{")
            # step_drive rides in the bundle so `pins <block>` shows it, but it
            # is NOT part of the acceptance DRIVE set — the driven-wire gate
            # governs the acceptance harness, and stepping is an instrument
            # like the LA and the scope.
            check_eq(rows,
                     len(s["drive"]) + len(s["sample"]) + len(s.get("step_drive", {})),
                     f"{b} bundle row count == drive + sample + step_drive")


def test_block1_port_alignment():
    """capture_burst() reads whole ports; a group split across two cannot be
    read coherently. The SRC group in particular decides control.onehot."""
    print("block1 port alignment")
    pins = {s: p for s, p, _d, _o in kc.block_pins(CONTRACTS, "block1")}

    def port_of(sig):
        return pins[sig].split("/")[0][:2]
    check_eq(pins["CLK"], "PL0/D49",
             "CLK on PL0 — the qualifier arrives in the SAME READ as its frame")
    for i, pin in enumerate(("PF4/A4", "PF5/A5", "PF6/A6", "PF7/A7")):
        check_eq(pins[f"T{i}"], pin,
                 f"T{i} on {pin} — one PF read gives jmp strobes AND the T label")
    for grp, label in ((SRC8, "SRC"), (DST7, "DST"), (JMP4, "JMP"),
                       (SA3 | PCBITS | ENDHALT | QUAL, "anchor"),
                       (T03, "T label")):
        ports = {port_of(s) for s in grp}
        check_eq(len(ports), 1, f"{label} group sits in exactly one port")
    check_eq(port_of("SRC_ACTIVE"), "PC", "SRC group on PORTC")
    check_eq(port_of("~{REG_A_LOAD}"), "PA", "DST group on PORTA")
    check_eq(port_of("CW12=END"), "PL", "anchor group on PORTL")
    check_eq(pins["CW12=END"], "PL4/D45", "END on D45, all six blocks")
    check_eq(pins["CW15=HALT"], "PL7/D42", "HALT on D42, all six blocks")


def test_owner_board_is_where_the_wire_lands():
    """`pins <block>` has to say WHICH BOARD, because a block is three-plus
    boards on the bench. The owner is NOT always the producer: a far-end tap
    lands on the consumer, and that is deliberate (strike-7)."""
    print("owner board resolution")

    def owners(b):
        return {s: o for s, _p, _d, o in kc.block_pins(CONTRACTS, b)}

    o1 = owners("block1")
    for s in DST7 | SRC8 | JMP4:
        check_eq(o1[s], "control_word", f"block1 {s} lands on control_word")
    for s in SA3 | PCBITS:
        check_eq(o1[s], "microcode", f"block1 {s} lands on microcode")
    check_eq(o1["CLK"], "root", "block1 CLK qualifier lands on root's U27")
    for i in range(4):
        check_eq(o1[f"T{i}"], "root", f"block1 T{i} label lands on root's U6")
    for s in ENDHALT:
        check_eq(o1[s], "root",
                 f"block1 {s} lands on ROOT (U61, the consumer end) not microcode")
    for s in IRB:
        check_eq(o1[s], "microcode", f"block1 {s} driven into microcode's U16")

    # block3: IRB is copper now, produced by mdr, but tapped at the CONSUMER
    # end (U16) because that is what makes it the U25 bridge mirror-witness
    o3 = owners("block3")
    for s in IRB:
        check_eq(o3[s], "microcode",
                 f"block3 {s} sampled at microcode's U16, not at mdr")

    # block4 has no io board, so OB is sampled at its producer (U35)
    o4 = owners("block4")
    for s in OB:
        check_eq(o4[s], "registers", f"block4 {s} sampled at registers' U35")

    # block5 adds io, so the tap moves to the far end
    o5 = owners("block5")
    for s in OB:
        check_eq(o5[s], "io", f"block5 {s} moves to the io end")


def test_step_drive_is_not_in_the_acceptance_gate():
    """CLKIN appears in block3's bundle so the hookup table shows it, but the
    ladder's driven count must stay 8/8/0/0/0. Stepping drives one wire, and
    a stepped run is 1 driven where acceptance is 0 — the gate governs
    acceptance, exactly as it does for the LA and the scope."""
    print("step_drive stays out of the acceptance gate")
    check_eq([len(SURF[b]["drive"]) for b in SURF], [8, 8, 0, 0, 0],
             "driven ladder unchanged by adding a step wire")
    # Blocks 3, 4 and 5 are steppable. Block 4 needs it most: the milestone is
    # ten T-states, ~10us, and NO POLLING TRIGGER CAN WIN THAT RACE — with the
    # rig owning the clock the machine is frozen between pulses instead.
    for b in ("block3", "block4", "block5"):
        check_eq(set(SURF[b]["step_drive"]), {"CLKIN"},
                 f"{b} declares CLKIN as a step-only drive")
    for b in ("block1", "block2"):
        check_eq(SURF[b].get("step_drive", {}), {}, f"{b} declares no step drive")
    for b in ("block3", "block4", "block5"):
        pins = {s: p for s, p, _d, _o in kc.block_pins(CONTRACTS, b)}
        check_eq(pins.get("CLKIN"), "PF0/A0",
                 f"{b}: CLKIN on A0 — same port read as T, and PF0-3 is free")


def test_timing_set_never_moves():
    """CLK and T0-3 must be in the SAME HOLES in every block. Five wires that
    never move are five wires that cannot be re-landed wrong — the same reason
    END/HALT are pinned."""
    print("the timing set never moves")
    want = {"CLK": "PL0/D49", "T0": "PF4/A4", "T1": "PF5/A5",
            "T2": "PF6/A6", "T3": "PF7/A7"}
    for b in SURF:
        pins = {s: p for s, p, _d, _o in kc.block_pins(CONTRACTS, b)}
        for sig, pin in want.items():
            check_eq(pins.get(sig), pin, f"{b}: {sig} on {pin}")
        for sig in want:
            check_eq({o for s, _p, _d, o in kc.block_pins(CONTRACTS, b)
                      if s == sig}, {"root"}, f"{b}: {sig} lands on root")


def test_end_halt_never_move():
    print("END/HALT never move")
    for b in SURF:
        pins = {s: p for s, p, _d, _o in kc.block_pins(CONTRACTS, b)}
        if "CW12=END" in pins:
            check_eq(pins["CW12=END"], "PL4/D45", f"{b}: END on D45")
        check_eq(pins["CW15=HALT"], "PL7/D42", f"{b}: HALT on D42")


# ---- pytest bridge (Task 8 VPLAN audit, fix round 2) ---------------------
# Same hollowness-under-pytest fix as
# docs/notes/test_progrom_coverage.py's own copy of this block --
# check()/check_eq()/check_raises() only APPEND to FAILS, never raise, so
# pytest would otherwise report every test_* function here as PASS
# regardless of content. Wraps every test_* function so a run UNDER
# PYTEST raises (inside the wrapped call itself, so pytest reports a
# clean FAILED, never a passed-plus-teardown-error split) if its OWN
# execution added anything to FAILS. Guarded by `__name__ != "__main__"`
# so the direct-invocation path below keeps calling the UNWRAPPED
# originals and its own collect-everything-then-report-once behavior is
# untouched.
if pytest is not None and __name__ != "__main__":
    def _wrap_for_pytest(fn):
        def _wrapped():
            start = len(FAILS)
            result = fn()
            new = FAILS[start:]
            if new:
                raise AssertionError(
                    f"{len(new)} check() failure(s) in {fn.__name__}:\n"
                    + "\n".join(f"  - {f}" for f in new))
            return result
        _wrapped.__name__ = fn.__name__
        _wrapped.__doc__ = fn.__doc__
        return _wrapped

    for _tname, _tobj in list(globals().items()):
        if _tname.startswith("test_") and callable(_tobj):
            globals()[_tname] = _wrap_for_pytest(_tobj)


if __name__ == "__main__":
    for fn in (test_block_names_and_order, test_driven_gate, test_sample_counts,
               test_block1_surface, test_block2_surface, test_block3_surface,
               test_block4_surface, test_block5_is_the_last_rung,
               test_every_unfed_input_is_classified, test_hard_errors,
               test_pinmap_has_block_bundles, test_block1_port_alignment,
               test_owner_board_is_where_the_wire_lands,
               test_step_drive_is_not_in_the_acceptance_gate,
               test_timing_set_never_moves,
               test_end_halt_never_move):
        fn()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print("\nblock surface: OK")
