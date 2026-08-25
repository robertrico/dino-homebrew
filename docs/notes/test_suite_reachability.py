#!/usr/bin/env python3
"""Every test function in this directory must be REACHED by something.

THE BUG THIS EXISTS FOR (2026-08-25): `test_microcode_gen.py` defined
`test_sa_field_reaches_the_382_uninverted()` -- the only check in the whole
project that compares the microcode's SA ENCODING against the '382's actual
WIRING, written after three bench images agreed on a wrong answer because
`ADD` (011) was executing as `AND` (110).

It had never run. Not once.

Three things stacked to hide it, and any one alone would have been caught:

  1. The module's self-check is module-level asserts plus a closing
     `print("OK test_microcode_gen")`. It never called its own test_ fns.
  2. `unittest` collects nothing from it -- the functions are bare, not
     methods on a TestCase.
  3. `pytest`, the only runner that WOULD have collected them, is not
     installed on this machine.

So the module printed OK, exited 0, and asserted nothing.

THE HOUSE PATTERN IS THE HAZARD. Most test modules here run themselves with
an explicit hand-written list:

    if __name__ == "__main__":
        for fn in (test_a, test_b, test_c):
            fn()

Adding a function to that tuple is a step a person has to remember. This file
is the check that nobody forgot -- and the fix, where a module needs one, is
to ENUMERATE rather than list, so the tuple cannot drift from the definitions.

This is the same rule as `alias_splits()` and the continuity checklist: a
tool's silence is not coverage.
"""
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Modules exempted from the reachability rule. EVERY ENTRY NAMES WHAT RETIRED
# IT -- an unexplained exemption is how the hole reopens.
EXEMPT = {
    "test_fpga_gen.py":
        "DEAD with the FPGA twin, retired 2026-08-24. CLAUDE.md: do not "
        "repair it, do not read a green badge into it.",
    "test_vplan.py":
        "DEAD with the FPGA twin -- dino_fpga_vplan.md is the twin's "
        "coverage map, retired 2026-08-24.",
    "test_netlist_integrity.py":
        "DEAD with the FPGA twin: it synthesises fpga/gen/*.vhd through "
        "ghdl-yosys-plugin. oss-cad-suite IS installed, so this gate would "
        "run -- but the artifact it gates is retired.",
    "test_kicad_contracts_pinmap.py":
        "PERMANENTLY RED with the ATmega rig, retired 2026-08-24. --pinmap "
        "throws IndexError: the MDR sheet needs 21 rig pins and POOL has 19. "
        "CLAUDE.md: do NOT extend POOL, that would commit a hookup table for "
        "retired hardware.",
    "test_suite_reachability.py":
        "this file; it is its own runner.",
}

# An enumerating runner reaches every test_ function by construction, so a
# module using one of these idioms does not need name-by-name checking.
ENUMERATING = ("globals()", "getmembers", "vars()", "dir()")

FAILS = []


def _main_block_source(tree, src):
    """Source text of the `if __name__ == '__main__':` block, or None."""
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        t = node.test
        if (isinstance(t, ast.Compare)
                and isinstance(t.left, ast.Name) and t.left.id == "__name__"):
            lines = src.splitlines()
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return None


def _all_referenced_names(tree):
    """Every name MENTIONED anywhere in the module, not just called.

    Call sites are not enough. The house dispatch pattern is

        for fn in (test_a, test_b, test_c):
            fn()

    where the test functions appear as bare NAMES in a tuple and the only
    Call is `fn()`. Looking for calls alone reports every one of them
    unreachable -- which is how the first draft of this file cried wolf on
    39 functions that were fine.

    Mentioned-anywhere is deliberately an UNDER-approximation: it never
    produces a false FAIL, and a false FAIL here would train people to
    ignore the one check that catches silent tests. It can miss a function
    referenced only from another unreachable function; that is the right
    way to be wrong.
    """
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def test_every_test_function_is_reachable():
    print("every test_ function is reached by its module's runner")
    for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
        name = os.path.basename(path)
        if name in EXEMPT:
            print(f"  skip {name}  ({EXEMPT[name].split('.')[0]})")
            continue
        src = open(path).read()
        tree = ast.parse(src)

        defined = [n.name for n in tree.body
                   if isinstance(n, ast.FunctionDef)
                   and n.name.startswith("test_")]
        # unittest.TestCase methods are reached by unittest discovery
        has_testcase = any(
            isinstance(n, ast.ClassDef)
            and any(getattr(b, "attr", getattr(b, "id", "")) == "TestCase"
                    for b in n.bases)
            for n in tree.body)
        if not defined:
            print(f"  ok   {name}  ({'TestCase' if has_testcase else 'no bare test_ fns'})")
            continue

        block = _main_block_source(tree, src)
        called = _all_referenced_names(tree)

        if block and any(idiom in block for idiom in ENUMERATING):
            print(f"  ok   {name}  ({len(defined)} fns, enumerating runner)")
            continue

        unreached = [d for d in defined if d not in called]
        if unreached:
            FAILS.append(f"{name}: {len(unreached)} unreachable")
            print(f"  FAIL {name}  {len(unreached)} of {len(defined)} "
                  f"test_ functions are never called:")
            for d in unreached:
                print(f"         {d}")
            if block is None:
                print("         (module has no __main__ runner at all)")
        else:
            print(f"  ok   {name}  ({len(defined)} fns, all listed)")


def test_exemptions_all_name_a_reason():
    """An exemption without a stated reason is how the hole reopens."""
    print("every exemption names what retired it")
    for name, reason in sorted(EXEMPT.items()):
        if len(reason) < 20:
            FAILS.append(f"{name}: exemption reason too thin")
            print(f"  FAIL {name}: reason is not a reason")
        else:
            print(f"  ok   {name}")


def test_no_exemption_is_stale():
    """An exemption for a file that no longer exists is dead weight."""
    print("every exemption points at a file that exists")
    for name in sorted(EXEMPT):
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            print(f"  ok   {name}")
        else:
            FAILS.append(f"{name}: exempted but missing")
            print(f"  FAIL {name}: exempted but the file is gone")


if __name__ == "__main__":
    for fn in sorted(
            (v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)),
            key=lambda f: f.__name__):
        fn()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("\nsuite reachability: OK")
