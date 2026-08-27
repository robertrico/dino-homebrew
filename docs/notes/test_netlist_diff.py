#!/usr/bin/env python3
"""Host test for kicad_contracts.pin_net_diff().
Run: python3 test_netlist_diff.py

WHAT THIS IS FOR. `--continuity <new refs>` filters to nets touching the NEW
designators, so it structurally cannot show you an EXISTING pin whose net
changed underneath it. In the stack commit that blind spot hid two wires:

    U28.6 E3   +5V -> CW17/~{SRC_BANK}     lift the strap
    U30.6 E3   +5V -> CW18/~{DST_BANK}     lift the strap

Two wires, but they are decoder ENABLES on a working board -- the worst class
under the block law. They were found by diffing HEAD by hand, which is not a
procedure, it is a person remembering.

NO BASELINE IS STORED. `git show <rev>:<path>` is the old sheet and
build_report takes a path, so the diff is old-parse vs new-parse. Git is the
store. A checked-in baseline would be one more generated artifact that drifts.

CLASSIFICATION IS THE POINT, not the raw diff. Of the 48 pin->net changes in
the stack commit, 44 were annotation -- U9/U15/U16/U17 gaining MCA0-11 labels
on wires that were already landed years earlier. An unclassified diff hands
you a 48-line scare sheet; a classified one hands you a 4-line work list.

Four buckets, and every rule below is forced by a real case in this repo's
history rather than invented:

    NEW_PIN    the pin did not exist at <rev>              U23.12
    NEW_WIRE   was anonymous with NOTHING else on the net  U29.7 (O7, was NC)
                 -> real new copper to land
    ANNOTATE   was anonymous but the net ALREADY had other U9.3 (already tied
                 pins -> the wire existed, a label was       to U15.3/U16.12)
                 added. No copper.
    ANNOTATE   old label set is a SUBSET of the new one    U24.20 ROM_EN ->
                 -> an alias was added, same net. No copper.  M15/ROM_EN
    COPPER     anything else: the pin genuinely moved      U28.6 +5V -> CW17

The U29.7-vs-U9.3 split is why the anonymous case cannot be one rule. Both
read `N$anon -> LABEL`; one is a wire to land and the other is ink.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kicad_contracts

ROOT = os.path.normpath(os.path.join(HERE, "..", "..",
                                     "dino_v0_0_2", "dino_v0_0_2.kicad_sch"))

# The stack commit. Pinned as a literal SHA, not HEAD~n, so the expectations
# below stay true as history grows.
STACK_COMMIT = "2fe4d7c"


def _by_pin(entries):
    return {(e[0], e[1]): e for e in entries}


def test_lifted_strap_is_classified_as_copper():
    """U28.6/U30.6 went +5V -> a real signal. That is a wire to move on a
    board that already works, and it is the whole reason this tool exists."""
    d = kicad_contracts.pin_net_diff(ROOT, f"{STACK_COMMIT}^")
    copper = _by_pin(d["copper"])

    assert ("U28", 6) in copper, (
        "U28.6 E3 went from a +5V strap to CW17/~{SRC_BANK} and must be "
        f"reported as COPPER. Got copper={sorted(copper)}")
    _ref, _pin, old, new = copper[("U28", 6)]
    assert old == "+5V" and "CW17" in new, f"U28.6: {old} -> {new}"

    assert ("U30", 6) in copper, "U30.6 E3 is the same lift and is missing"


def test_label_added_to_an_existing_wire_is_not_copper():
    """U9.3 was N$anon but already tied to U15.3 and U16.12 -- the wire was
    landed. The stack commit only added the MCA7 label. Reporting that as
    copper would bury the two real wires in 44 lines of noise."""
    d = kicad_contracts.pin_net_diff(ROOT, f"{STACK_COMMIT}^")
    annotate = _by_pin(d["annotate"])
    copper = _by_pin(d["copper"])

    assert ("U9", 3) in annotate, (
        "U9.3 N$anon -> MCA7 is a label on an already-landed wire")
    assert ("U9", 3) not in copper, "U9.3 must not be reported as copper"


def test_newly_driven_dead_pin_is_new_wire_not_annotation():
    """U29.7 was also N$anon -- but with NOTHING else on the net. That is a
    real wire to land, and it must not be filed with U9.3."""
    d = kicad_contracts.pin_net_diff(ROOT, f"{STACK_COMMIT}^")
    new_wire = _by_pin(d["new_wire"])
    annotate = _by_pin(d["annotate"])

    assert ("U29", 7) in new_wire, (
        "U29.7 O7 was an unconnected decoder output and now drives "
        f"~{{SP_DOWN}} — real new copper. Got new_wire={sorted(new_wire)}")
    assert ("U29", 7) not in annotate, (
        "U29.7 must not be filed as annotation — both it and U9.3 read "
        "'N$anon -> LABEL', and only the pin count on the old net tells "
        "them apart")


def test_adding_an_alias_to_a_net_is_not_copper():
    """U23.12 went CW17 -> CW17/~{SRC_BANK} in 8127bbb. The label set grew;
    the net did not move, so it is ANNOTATE and not copper.

    U24.20 was this test's other exemplar and IS NO LONGER ONE. Phase E step
    A moved the ROM's ~CE off M15/ROM_EN onto ~{ROM_SEL} -- a real wire, real
    copper -- so against STACK_COMMIT that pin now reports COPPER, correctly.
    It is asserted here from the OTHER side, which guards the same
    distinction: a pin that genuinely moved must never be filed as
    annotation. Corrected 2026-08-26; red since step A landed."""
    d = kicad_contracts.pin_net_diff(ROOT, STACK_COMMIT)
    annotate = _by_pin(d["annotate"])
    copper = _by_pin(d["copper"])

    assert ("U23", 12) in annotate, "U23.12 CW17 -> CW17/~{SRC_BANK}"
    assert ("U23", 12) not in copper

    assert ("U24", 20) in copper, (
        "U24.20 ROM_EN -> ~{ROM_SEL} is phase E step A's real move")
    assert ("U24", 20) not in annotate, (
        "a pin that MOVED must not be filed as an alias growth")


def test_a_pin_that_did_not_exist_is_new_pin_not_copper():
    """U23 itself arrived in the stack commit. Its pins have no prior net, so
    they are NEW_PIN — they belong on the landing list, but they are not a
    change to something that already worked."""
    d = kicad_contracts.pin_net_diff(ROOT, f"{STACK_COMMIT}^")
    new_pin = _by_pin(d["new_pin"])
    copper = _by_pin(d["copper"])

    assert ("U23", 12) in new_pin, "U23 did not exist before the stack commit"
    assert ("U23", 12) not in copper


def test_no_change_against_the_current_head_is_empty():
    """Sanity: diffing the working tree against HEAD with a clean tree must
    report nothing in any bucket. A tool that always finds something is a
    tool nobody reads."""
    d = kicad_contracts.pin_net_diff(ROOT, "HEAD")
    assert not any(d[k] for k in ("copper", "new_wire", "new_pin", "annotate")), \
        f"clean tree vs HEAD should be empty, got { {k: len(v) for k, v in d.items()} }"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
