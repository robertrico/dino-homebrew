import glob
import json
import os
import re
import shutil
import subprocess

import pytest

# Task-13 synthesis rework, item 5 (synth-rework-brief.md): "the missing
# gate that would have caught the whole thing on day one." Task 13's
# original CRITICAL FINDING was exactly this class of failure --
# ghdl-yosys-plugin silently SEVERS internal nets that touch a
# sub-instance `inout` port at synthesis import (fine in simulation,
# broken on the import path): 65 nets were dropped (mdr bus stubs,
# mar0-15, pc0-15, ROM/RAM data connections), and NOTHING in the sim-side
# test suite could ever catch it, because the bug is specific to the
# GHDL-as-synthesis-frontend import path, which no cocotb test exercises.
#
# Two checks, both against the REAL toolchain (oss-cad-suite), skipped
# outright if that toolchain isn't installed on this machine (matching
# CLAUDE.md's "Tools ~/oss-cad-suite/bin only" rule -- this test never
# falls back to a different ghdl/yosys):
#
#   1. dropcheck (prototyped in this task's own investigation): import
#      dino_core through `ghdl` (RAW -- write_rtlil immediately after
#      `hierarchy`, before ANY yosys optimization pass has run) and
#      assert every `signal ... : ...;` declared in each fpga/gen/*.vhd
#      sheet's architecture is present as a real wire in the imported
#      RTLIL for that module. Pre-optimization, there is no legitimate
#      reason for a declared signal to be missing -- opt_clean hasn't run
#      yet, so "missing" can only mean "severed at import."
#   2. memrd census: after synth_ecp5's own `coarse` stage (flatten +
#      tribuf -logic + opt_expr + opt_clean -- the exact point Task 13's
#      CRITICAL FINDING traced the drop to), `select -count t:$memrd_v2`
#      must read exactly 4 -- the two microcode ROMs (U9/U15) plus the
#      program ROM (U24) and RAM (U26). Fewer than 4 means dead-code
#      elimination ate a real memory, the Task-13 failure mode, byte for
#      byte; more than 4 would mean an unexpected extra inferred memory.
#
# Both checks run against fpga/gen/*.vhd + fpga/ttl/*.vhd directly (NOT
# top/versa_top.vhd) -- dino_core is the composed machine gate; the board
# shell is a separate, later concern (top-level port count, LPF, PLL).

HERE = os.path.dirname(os.path.abspath(__file__))
FPGA_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "fpga"))
GEN_DIR = os.path.join(FPGA_DIR, "gen")
TTL_DIR = os.path.join(FPGA_DIR, "ttl")

TOOLS = os.path.expanduser("~/oss-cad-suite/bin")
YOSYS = os.path.join(TOOLS, "yosys")
GHDL_PREFIX = os.path.normpath(os.path.join(TOOLS, "..", "lib", "ghdl"))

# The nine sheet entities (fpga/gen/<name>.vhd) -- dino_core.vhd's own
# analysis-order dependency (it instantiates all nine, must be analyzed
# last) mirrors fpga/Makefile's SYNTH_VHDL_SOURCES / fpga/sim/Makefile's
# MODULE_UNDER_TEST=dino_core GEN_SHEETS, not reinvented here.
GEN_SHEETS = ["alu", "control_word", "input_output", "mar", "mdr",
              "memory", "microcode", "program_counter", "registers_a_b"]

pytestmark = pytest.mark.skipif(
    not os.path.exists(YOSYS),
    reason="oss-cad-suite not installed at ~/oss-cad-suite -- CLAUDE.md's "
           "'Tools ~/oss-cad-suite/bin only' rule means this gate has no "
           "fallback toolchain to run against")


def _vhdl_sources():
    ttl = sorted(glob.glob(os.path.join(TTL_DIR, "*.vhd")))
    gen = [os.path.join(GEN_DIR, f"{s}.vhd") for s in GEN_SHEETS]
    gen.append(os.path.join(GEN_DIR, "dino_core.vhd"))
    return ttl + gen


def _run_yosys(script_text, timeout=180):
    env = dict(os.environ)
    env["GHDL_PREFIX"] = GHDL_PREFIX
    env["PATH"] = TOOLS + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [YOSYS, "-m", "ghdl", "-p", script_text],
        cwd=FPGA_DIR, capture_output=True, text=True, env=env, timeout=timeout)


def _declared_signals(vhdl_path):
    """Every `signal <name> : ...;` declared in this file's architecture
    body AND actually carrying information (driven AND read somewhere
    else in the same file) -- the ground truth for "what nets THIS
    sheet's generator meant to exist as real information flow,"
    independent of what yosys's import happens to keep.

    Excludes signals referenced only by their own declaration plus a
    single further occurrence (one write, zero reads) -- e.g.
    dino_core.vhd's `to0`..`to15` (two spare '138 decoder-output banks
    tied to declared-but-never-read signals, pre-existing and unrelated
    to any inout wiring). GHDL's OWN frontend already elides a
    zero-fanout signal like that before any yosys optimization pass ever
    runs, so treating it as "severed" would be a false positive this
    gate cannot distinguish from Task 13's real bug (which only ever
    drops nets that DO carry information downstream)."""
    text = open(vhdl_path).read()
    arch = text[text.index("architecture"):] if "architecture" in text else text
    declared = re.findall(r"^\s*signal\s+(\w+)\s*:", arch, re.M)
    used = []
    for name in declared:
        occurrences = len(re.findall(rf"\b{re.escape(name)}\b", arch))
        if occurrences >= 3:   # declaration + >=1 driver + >=1 reader
            used.append(name)
    return used


def _rtlil_module_wires(rtlil_text):
    """{module_name: {wire_name, ...}} parsed straight out of RTLIL text
    -- mirrors this task's own dropcheck.py prototype exactly (module ..
    end / wire \\name lines), no yosys `select` JSON round-trip needed
    for this simple a query."""
    mods = {}
    cur = None
    for line in rtlil_text.splitlines():
        m = re.match(r"^module \\(\S+)", line)
        if m:
            cur = m.group(1)
            mods[cur] = set()
            continue
        if line.startswith("end") and cur:
            cur = None
            continue
        if cur:
            m = re.match(r"^  wire .*?\\(\S+)\s*$", line)
            if m:
                mods[cur].add(m.group(1))
    return mods


def test_ghdl_import_severs_no_declared_signal(tmp_path):
    """Task-13 rework item 5: the netlist-integrity regression gate.
    Zero severed nets after GHDL import -- restated synthesis gate 1."""
    sources = _vhdl_sources()
    il_path = tmp_path / "dino_core_raw.il"
    script = (
        "ghdl --std=08 " + " ".join(sources) + " -e dino_core\n"
        f"write_rtlil {il_path}\n"
    )
    proc = _run_yosys(script)
    assert proc.returncode == 0, (
        f"ghdl import of dino_core failed (exit {proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}")

    mods = _rtlil_module_wires(il_path.read_text())

    total_missing = 0
    details = []
    for sheet in GEN_SHEETS + ["dino_core"]:
        vhdl_path = os.path.join(GEN_DIR, f"{sheet}.vhd")
        ent = re.search(r"entity (\w+) is", open(vhdl_path).read()).group(1)
        declared = _declared_signals(vhdl_path)
        have = set()
        for mod_name, wires in mods.items():
            # ghdl-yosys-plugin suffixes a generated variant module name
            # "<entity>_Brtl[...]" per distinct generic-map instantiation
            # (e.g. addr_bits=13 vs 15) -- collect wires from every
            # variant, same as dropcheck.py's own module-name matching.
            if mod_name == ent or mod_name.startswith(ent + "_Brtl"):
                have |= wires
        missing = [s for s in declared if s not in have]
        if missing:
            details.append(f"{sheet}: declared={len(declared)} "
                            f"missing={missing}")
        total_missing += len(missing)

    assert total_missing == 0, (
        f"{total_missing} architecture-declared signal(s) severed at GHDL "
        f"import (ghdl-yosys-plugin's inout-import bug, or a regression "
        f"of the same class):\n" + "\n".join(details))


def _multiply_driven(stdout):
    """Every `check`-reported multiply-driven net, as (net, drivers-blurb)."""
    hits = []
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^Warning: multiple conflicting drivers for (.*):$", line)
        if m:
            drivers = [l.strip() for l in lines[i + 1:i + 3]
                       if l.startswith("    port") or l.startswith("    module")]
            hits.append((m.group(1), "; ".join(drivers)))
    return hits


def test_bus_resolve_leaves_no_multiply_driven_net():
    """The gate for fpga/synth/bus_resolve.ys -- restated synthesis gate 1,
    third leg. synth_ecp5's own coarse stage (`flatten; tribuf -logic`) does
    NOT resolve this design's shared tri-state buses: it leaves 24
    multiply-driven nets (the 16-bit M bus at mar U54/U59 and the 8-bit MDR
    bus at mdr U18), and nextpnr-ecp5 aborts at placement with "Net
    'dino_core_i.m[0]' is multiply driven by cell ports". Two mechanisms,
    both explained in bus_resolve.ys itself: `tribuf` groups tri-state
    drivers by whole-SigSpec Y (so a vector-wide $tribuf never merges with
    the bit-wide ones sharing its bits), and it cannot see a non-tri-state
    driver at all ('193 counter Q, registered ROM data).

    This test asserts BOTH directions so it can never pass vacuously:
    stock coarse must still show the failure, and the pre-pass must clear
    it to zero."""
    sources = _vhdl_sources()
    preamble = ("ghdl --std=08 " + " ".join(sources) + " -e dino_core\n"
                "hierarchy -check -top dino_core\n"
                "proc -latches warn\n")

    stock = _run_yosys(preamble + "flatten\ntribuf -logic\ncheck\n")
    assert stock.returncode == 0, (
        f"stock coarse run failed (exit {stock.returncode}):\n"
        f"{stock.stdout}\n{stock.stderr}")
    stock_hits = _multiply_driven(stock.stdout)
    assert stock_hits, (
        "synth_ecp5's stock `flatten; tribuf -logic` no longer produces any "
        "multiply-driven net -- either the toolchain changed or the models "
        "did. If this is a real improvement, RE-DERIVE whether "
        "fpga/synth/bus_resolve.ys is still needed rather than deleting "
        "this assertion; it is what keeps the gate below from passing "
        "vacuously.")

    fixed = _run_yosys(preamble + "script synth/bus_resolve.ys\n")
    assert fixed.returncode == 0, (
        f"bus_resolve.ys failed (exit {fixed.returncode}):\n"
        f"{fixed.stdout}\n{fixed.stderr}")
    fixed_hits = _multiply_driven(fixed.stdout)
    assert not fixed_hits, (
        f"{len(fixed_hits)} multiply-driven net(s) survive "
        f"fpga/synth/bus_resolve.ys (stock coarse leaves "
        f"{len(stock_hits)}). nextpnr-ecp5 will refuse to place this "
        f"netlist:\n" + "\n".join(f"  {n}: {d}" for n, d in fixed_hits[:12]))


# The PRODUCTION synthesis sequence, character for character what
# fpga/Makefile's `bit` rule runs between the GHDL import and the final
# `synth_ecp5 -run coarse:`. Both memory tests below drive THIS, not a
# hand-rolled approximation of it: a gate that exercises stock
# `flatten; tribuf -logic` proves nothing about the netlist the
# bitstreams are actually built from.
_PRODUCTION_PRELUDE = (
    "synth_ecp5 -top dino_core -run begin:coarse\n"
    "proc -latches warn\n"
    "script synth/bus_resolve.ys\n"
)


def test_synth_coarse_preserves_all_four_memories():
    """Task-13 rework item 5 continued: 4 memories still present at the END
    of the coarse stage -- restated synthesis gate 1's second half. Task
    13's CRITICAL FINDING lived right here (4 memory cells present after
    opt_expr, only the two microcode ROMs surviving the immediately
    following opt_clean).

    Runs the PRODUCTION sequence (fpga/synth/bus_resolve.ys), not stock
    coarse, so it covers what `make -C fpga bit` actually builds.

    Counts `$mem_v2`, not `$memrd_v2`: coarse ENDS with `memory -nomap`,
    whose `memory_collect` folds each memory's separate `$memrd_v2` read
    ports back into one whole-memory `$mem_v2` cell. Asserting on
    `$memrd_v2` here would silently read 0 and only pass because the
    earlier version of this test stopped short of that pass."""
    sources = _vhdl_sources()
    script = (
        "ghdl --std=08 " + " ".join(sources) + " -e dino_core\n"
        + _PRODUCTION_PRELUDE +
        "synth_ecp5 -top dino_core -run coarse:map_ram\n"
        "select -count t:$mem_v2\n"
    )
    proc = _run_yosys(script)
    assert proc.returncode == 0, (
        f"production coarse stage failed (exit {proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}")
    m = re.findall(r"^(\d+) objects\.$", proc.stdout, re.M)
    assert m, f"no 'select -count' result found in yosys output:\n{proc.stdout}"
    count = int(m[-1])
    assert count == 4, (
        f"$mem_v2 count at the end of the production coarse stage: {count}, "
        f"want 4 (microcode U9/U15 + program ROM U24 + RAM U26) -- fewer "
        f"means dead-code elimination ate a real memory (Task 13's original "
        f"failure mode); more means an unexpected extra inferred memory.\n"
        f"{proc.stdout}")


def test_full_synth_maps_all_four_memories_to_block_ram():
    """Restated synthesis gate 1's ACTUAL wording -- "4 memories at end of
    synth_ecp5 (not just coarse)" -- and gate 3's fit half, neither of
    which had a test. Task 13's CRITICAL FINDING was a memory that
    survived one pass and was eliminated by the next, so "still there at
    the coarse stage" is exactly the claim that is not sufficient.

    Runs the FULL production pipeline to completion and parses yosys's own
    memory_libmap/techmap log: exactly four `mapping memory ... via
    $__DP16KD_` events, one per real memory, and ZERO `using FF mapping`
    fallbacks (a 32K byte ROM silently mapped to flip-flops would blow the
    device up rather than fit, so the absence of that line is load-bearing,
    not cosmetic)."""
    sources = _vhdl_sources()
    script = (
        "ghdl --std=08 " + " ".join(sources) + " -e dino_core\n"
        + _PRODUCTION_PRELUDE +
        "synth_ecp5 -top dino_core -run coarse:\n"
    )
    proc = _run_yosys(script, timeout=600)
    assert proc.returncode == 0, (
        f"full synth_ecp5 failed (exit {proc.returncode}):\n"
        f"{proc.stdout[-6000:]}\n{proc.stderr[-2000:]}")

    mapped = re.findall(r"^mapping memory (\S+) via \$__DP16KD_", proc.stdout,
                        re.M)
    assert len(mapped) == 4, (
        f"{len(mapped)} memories mapped to DP16KD block RAM at the END of "
        f"synth_ecp5, want 4 (microcode U9/U15 + program ROM U24 + RAM "
        f"U26). Mapped: {mapped}")

    ff_mapped = [ln for ln in proc.stdout.splitlines()
                 if "using FF mapping" in ln]
    assert not ff_mapped, (
        f"{len(ff_mapped)} memor(ies) fell back to flip-flop mapping "
        f"instead of DP16KD block RAM -- this design's memories are 8K and "
        f"32K bytes, so an FF fallback is a fit failure, not a style "
        f"choice:\n" + "\n".join(ff_mapped))
