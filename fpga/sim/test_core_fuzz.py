"""Differential fuzz harness (verification plan Task 2) -- random legal
DINO programs (docs/notes/fuzz_gen.py, Task 1) run against the SAME
dino_core elaboration test_core_milestone.py/test_core_coverage.py
already build, oracle-checked against docs/notes/progrom_gen.py's own
simulate() -- no hand-typed expectations, the same discipline every
other whole-core test in this directory holds.

TWO-HEADED FILE, and here is why: ROM content is a GHDL generic, fixed
at elaboration (conftest_helpers.run_program()'s own docstring) -- one
simulation process can only ever execute ONE program. test_core_
milestone.py/test_core_coverage.py get away with "one `make` per named
tag" because there are only a handful of tags. A fuzz run needs one
elaboration PER SEED, and DINO_FUZZ_N can be in the hundreds, so this
file is both:

  - `@cocotb.test() fuzz_one_seed(dut)`: runs UNDER `ghdl -r`/cocotb, one
    seed per elaboration. The seed comes from the DINO_FUZZ_SEED
    environment variable, NOT from DINO_PROG_HEX (conftest_helpers.
    run_program()'s own docstring: that argument is a LABEL for logging,
    never a selector -- the ROM was already fixed before this Python code
    ran). Confirmed empirically, not assumed, that a `make VAR=val`
    command-line assignment reaches this coroutine's os.environ: GNU Make
    auto-exports command-line variable assignments into recipe
    subprocess environments -- this task's own scratch probe
    (test_core_fuzz_probe.py, since deleted) round-tripped
    DINO_FUZZ_SEED=42 through a live `make ... DINO_FUZZ_SEED=42` run and
    read it back inside a @cocotb.test() coroutine.
  - `run_fuzz_seeds(seeds)`: the HOST-side orchestrator -- run this file
    directly (`~/.venvs/dino-fpga/bin/python3 test_core_fuzz.py`, or
    `DINO_FUZZ_N=500 ~/.venvs/dino-fpga/bin/python3 test_core_fuzz.py`
    for a soak). It writes each seed's ROM image
    (write_fuzz_hex()/fpga_gen.bin2hex(), never hand-encoded bytes) into
    sim/hex/fuzz_<seed>.hex (gitignored -- these are not something Rico
    burns, CLAUDE.md rule 4), then runs it. The FIRST seed goes through a
    full `make MODULE_UNDER_TEST=dino_core MODULE=test_core_fuzz
    TESTCASE=fuzz_one_seed` invocation -- the same analyze+elaborate+
    prepare_roms+run recipe test_core_milestone.py/test_core_coverage.py
    already use, which builds fpga/sim/sim_build/ fresh. Every LATER seed
    reuses that already-elaborated sim_build/ via a direct `ghdl -r`
    invocation with only the u24_init_file generic changed -- measured
    (this task's own probe, same one that confirmed the env-var path)
    at ~0.4s vs ~3s for a full `make`, ~7x faster, because swapping ROM
    CONTENT is a runtime file read (ttl_at28c256.vhd's own impure
    `load_mem` function), not something GHDL's elaboration pass needs to
    resolve -- `addr_bits`, not `init_file`, is what sizes the memory
    array statically. Both paths write the identical results.xml/
    NUMERIC_STD-warning-bearing stdout, so pass/fail
    (cocotb_tools.check_results, never hand-parsed XML) and metavalue
    counting are the same either way.

Compares THREE observables against progrom_gen.simulate()'s own oracle,
none hand-typed:
  - final OB, the datapath's only externally observable pin
    (CLAUDE.md/test_core_coverage.py's own doctrine);
  - ram_writes: a sim-only VPI read of n_ram_write_en (memory.vhd's own
    signal, wired straight to U26.we_n -- NAND(write_dir, n_clk),
    CLAUDE.md's own "RAM write via NAND(WRITE_DIR, ~CLK)" formula), one
    falling edge per committed RAM write;
  - branches_taken: a sim-only VPI read of control_word.vhd's own
    `cond_taken` (U62's NOR(n_cond, flag_z)), one rising edge per
    COND-row-with-flag_z=0 T-state -- exactly progrom_gen.simulate()'s
    own `misc=="COND" and not flag_z` condition (progrom_gen.py's own
    branches_taken increment).
Both taps are reused/derived the SAME way this file (and every other
whole-core test) already reads internal simulation state -- `_track_commits()`
below reuses conftest_helpers.resolve_gated_clock_handles() for the RAM tap
(the identical handle invariant_monitor already resolves and checks every
run) and a plain hierarchical read (`dut.control_word_i.cond_taken`) for
the branch tap, the same access class as `_read_pc()`/`invariant_monitor`
itself. Empirically cross-checked against five progrom_gen.COVERAGE
images before being trusted here (loop: 8 ram_writes/2 branches_taken,
mem: 1/0, mardisc: 2/0, alu: 0/0, flow: 0/0 -- flow specifically exercises
a JNZ NOT taken, confirming `cond_taken` does not fire when flag_z=1); see
task-2-report.md's fix-round section for the probe log.

"halted" is checked via run_program()'s wait_halt(), whose timeout is
DERIVED from the oracle's own dynamic step count (max_us_for(), same
derivation as test_core_coverage._max_us_for(), ported to take a program
directly instead of a COVERAGE tag) -- a real program requiring MORE
steps than the oracle predicts times out loudly, which IS a halted-vs-not
comparison, just an asymmetric one (it can only ever fail in the
"hardware needed longer" direction, never silently pass a hardware run
that halted too EARLY, since OB/ram_writes/branches_taken are all also
checked).

Every failure names its seed and prints fuzz_gen.gen(seed)'s own
disassembled listing (`meta["text"]`); reproduce with
`fuzz_gen.gen(seed)`, shrink with `limit=`.

CALIBRATION (2026-08-09, this task's own 500-seed soak -- full log in
task-2-report.md, scratchpad/soak_500_retry.log): `DINO_FUZZ_N=500
~/.venvs/dino-fpga/bin/python3 test_core_fuzz.py` -> 500/500 PASS, 275.6s
wall (0.55s/seed average, first-seed `make` bootstrap + 499 fast `ghdl -r`
reruns), 2500 metavalue warnings total -- every single seed printed
exactly 5 (never more, never fewer), matching METAVALUE_PER_PROGRAM_BOUND
below being pinned above that measured floor. The 20-seed default
(`DINO_FUZZ_N` unset) separately ran 20/20 PASS in 16.9s (0.85s/seed,
heavier per-seed average since one bootstrap `make` amortizes over fewer
runs). Zero oracle divergence across all 520 sampled seeds combined.
"""
import math
import os
import subprocess
import sys
import tempfile
import time

import cocotb
from cocotb.triggers import RisingEdge

HERE = os.path.dirname(os.path.abspath(__file__))
HEX_DIR = os.path.join(HERE, "hex")
DOCS_NOTES = os.path.normpath(os.path.join(HERE, "..", "..", "docs", "notes"))
sys.path.insert(0, HERE)
sys.path.insert(0, DOCS_NOTES)

import fuzz_gen                          # noqa: E402
import progrom_gen                       # noqa: E402
from fpga_gen import bin2hex             # noqa: E402
from microcode_gen import INSTRUCTIONS   # noqa: E402

from conftest_helpers import (           # noqa: E402
    CLK_SYS_PERIOD_NS, Y1_DIVIDE, _track_ob, invariant_monitor, run_program,
    resolve_gated_clock_handles,
)

# FUZZ_SEEDS: the seed range a single run_fuzz_seeds() / fuzz_one_seed
# collection call covers. DINO_FUZZ_N=500 for the calibration soak
# (Task 2 Step 3); a bare run defaults to 20 (Task 2 Step 2).
FUZZ_SEEDS = range(int(os.environ.get("DINO_FUZZ_N", "20")))


# ---- oracle -------------------------------------------------------------
def oracle(prog, switches=0x00):
    """progrom_gen.simulate() wrapper. Returns simulate()'s own `st` dict
    (out/halted/ram_writes/branches_taken/steps/...) unmodified -- no
    second table restating its keys. `ram_writes`/`branches_taken` are
    cross-checked against sim-only VPI taps in fuzz_one_seed() (see
    `_track_commits()` and this file's own header for the exact signals
    and the empirical validation against five COVERAGE images).

    An earlier version of this file kept these two oracle-only, citing
    CLAUDE.md's block law ("a wrong SAMPLED wire is a false FAIL") as the
    reason not to add a hardware-side probe. That citation was a
    misapplication, caught in review: the block law is about a PHYSICAL
    bench rig wire that can electrically FIGHT a real driver -- the risk
    named is a wrong DRIVEN wire, and even a wrong SAMPLED rig wire is
    about a soldered probe reading a real, noisy signal. A cocotb VPI
    read of an internal simulation signal has neither failure mode: it
    cannot fight anything (read-only, no rig, no copper), and this file
    already does the identical class of read for dut.t, _read_pc()'s
    per-bit signals, and invariant_monitor's own gated-clock nets, all
    without incident. The real reason to keep a check narrow is a
    concrete, demonstrated gap it would miss without one -- fuzz_gen
    picks STA/LDA addresses independently, so a wrong-address STA that is
    never read back before HALT changes NO register/RAM cell any later
    instruction reads, and so changes no final OB -- the exact
    MAR-as-a-latch blind spot progrom_gen.py's own mem/mardisc images
    exist to name. OB-only would silently pass that class of bug."""
    st = progrom_gen.simulate(prog, switches=switches)
    assert st["halted"], (
        "oracle: program did not halt within simulate()'s max_steps -- a "
        "fuzz_gen.py structural-guarantee regression (its own forward-"
        "only-jump proof is what makes every generated program terminate "
        "by construction), not a hardware question")
    return st


# ---- ROM image -> committed hex format -----------------------------------
def write_fuzz_hex(seed, prog):
    """build_image() + fpga_gen.bin2hex() -- the SAME conversion path
    conftest_helpers.prepare_roms() uses for every committed coverage
    image, routed through a throwaway tempfile (never a tracked
    roms/*.bin -- fuzz images are not something Rico burns, CLAUDE.md
    rule 4) so bin2hex's own file-in/file-out contract needs no bespoke
    bytes-to-hex reimplementation here. Writes sim/hex/fuzz_<seed>.hex
    (gitignored, see .gitignore's own fpga/sim/hex/fuzz_*.hex entry) and
    returns its path."""
    image = progrom_gen.build_image(prog)
    os.makedirs(HEX_DIR, exist_ok=True)
    hex_path = os.path.join(HEX_DIR, f"fuzz_{seed}.hex")
    fd, tmp_bin = tempfile.mkstemp(suffix=".bin", dir=HEX_DIR)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(image)
        bin2hex(tmp_bin, hex_path)
    finally:
        os.remove(tmp_bin)
    return hex_path


# ---- max_us: derived from THIS program's own oracle step count ---------
# Same derivation as test_core_coverage.py's _max_us_for() (that file's
# own header comment has the full clk4m_y1->U20->U27 divider-chain
# derivation and its cross-check against Task 11's recorded milestone
# run) -- ported to take an assembled program directly instead of a
# progrom_gen.COVERAGE tag, since fuzz programs aren't COVERAGE members.
CLK_PERIOD_NS = 4 * Y1_DIVIDE * CLK_SYS_PERIOD_NS      # 4*25*10 = 1000ns
MAX_ROWS_PER_INSTR = max(len(rows) for _len, rows in INSTRUCTIONS.values())
RESET_OVERHEAD_NS = 2000
SAFETY_FACTOR = 3


def max_us_for(prog, switches=0x00):
    steps = progrom_gen.simulate(prog, switches=switches)["steps"]
    t_states = steps * (1 + MAX_ROWS_PER_INSTR)
    ns = RESET_OVERHEAD_NS + t_states * CLK_PERIOD_NS
    return int(math.ceil(ns * SAFETY_FACTOR / 1000))


# ---- monitor/OB-trace/liveness reporting --------------------------------
# Verbatim from test_core_coverage.py (itself verbatim from
# test_core_milestone.py) -- Task 11's own interface note says every
# whole-core test reuses this pattern; kept as each file's own private
# copy, matching the precedent those two files already set, rather than
# introducing a new shared module for three call sites.
def _report_monitor():
    cov = getattr(invariant_monitor, "coverage", [])
    excluded = getattr(invariant_monitor, "excluded", [])
    gaps = getattr(invariant_monitor, "gaps", [])
    cocotb.log.info(
        f"invariant monitor: {len(cov)} nets checked, {len(excluded)} "
        f"resolved-but-excluded, {len(gaps)} gap(s)")
    for name in cov:
        cocotb.log.info(f"  checked: {name}")
    for name in excluded:
        cocotb.log.info(f"  excluded (netlist-verified, see "
                         f"conftest_helpers.MONITOR_EXCLUDE): {name}")
    for name, why in gaps:
        cocotb.log.warning(f"  GAP: {name} -- {why}")
    assert not gaps, (
        f"invariant monitor has {len(gaps)} unresolved gated-clock "
        f"identifier(s) from fpga/gen/gated_clocks.txt: "
        f"{[name for name, _ in gaps]} -- a gap means the monitor never "
        f"checked that net this run, so a clean violations list would be "
        f"silently incomplete, not a real pass")


def _report_ob_trace():
    trace = getattr(_track_ob, "trace", [])
    for t_ns, v in trace:
        cocotb.log.info(f"  OB trace: t={t_ns}ns OB=0x{v:02X}")


def _assert_no_violations():
    qualifying = getattr(invariant_monitor, "qualifying_samples", 0)
    assert qualifying > 0, (
        "invariant monitor never saw a single qualifying CLK-high sample "
        "(clk_prev==1 and clk_now==1) this run -- '0 violations' below "
        "would be vacuous, not a real pass")
    cocotb.log.info(f"invariant monitor: {qualifying} qualifying CLK-high "
                     f"samples checked")
    violations = getattr(invariant_monitor, "violations", [])
    assert not violations, (
        f"{len(violations)} standing-invariant violation(s):\n" +
        "\n".join(violations))


def _bit(handle):
    """Same resolved-or-None read invariant_monitor's own `_bit()` uses
    (conftest_helpers.py) -- duplicated here rather than imported since
    conftest_helpers doesn't export it (leading underscore, module-
    private by that file's own convention)."""
    v = handle.value
    s = str(v)
    return int(v) if len(s) > 0 and all(c in "01" for c in s) else None


async def _track_commits(dut):
    """Sim-only commit counters -- RAM-write and JNZ-taken pulses, cross-
    checked in fuzz_one_seed() against progrom_gen.simulate()'s own
    `ram_writes`/`branches_taken`. See this file's own header for what
    each tap is wired to and the empirical cross-check against five
    progrom_gen.COVERAGE images (loop/mem/mardisc/alu/flow) that
    validated this BEFORE it was trusted here.

    n_ram_write_en: reused via conftest_helpers.resolve_gated_clock_
    handles() -- the SAME handle invariant_monitor already resolves and
    checks every run, not a second hand-rolled hierarchy lookup. Falls
    (1->0) exactly once per committed RAM write (dst=="RAM" microcode
    row, progrom_gen.py's own `ram_writes` increment site).

    cond_taken: a direct hierarchical read of control_word.vhd's own
    internal signal (dut.control_word_i.cond_taken -- control_word_i is
    already one of conftest_helpers.SHEET_INSTANCES, the same access
    class as every other sheet-local signal this codebase's whole-core
    tests already read). High for exactly the T-state whose CURRENT
    microcode row decodes MISC=COND (n_cond=0) with flag_z=0 --
    literally progrom_gen.py's own `misc=="COND" and not flag_z` test,
    read off control_word.vhd's own U62 NOR gate, not re-derived by eye.
    Rising edges (0->1) are counted once per branch-taken event; a T0
    FETCH row -- whose own MISC field is one of U29's two unassigned
    (`open`) codes, forcing n_cond high -- always intervenes between any
    two COND-decoding rows (every instruction starts there), so
    cond_taken provably returns to 0 between any two counted events, and
    two back-to-back taken branches cannot merge into one count.

    Both are plain VPI reads of internal simulation signals -- read-only,
    no rig, nothing to fight -- the same access class this file's
    invariant-monitor reporting and _read_pc() already use throughout
    this codebase's whole-core tests.
    """
    handles, _gaps = resolve_gated_clock_handles(dut)
    ram_we = handles["n_ram_write_en"]
    cond = dut.control_word_i.cond_taken
    _track_commits.ram_writes = 0
    _track_commits.branches_taken = 0
    await RisingEdge(dut.clk_sys)
    prev_we = _bit(ram_we)
    prev_cond = _bit(cond)
    while True:
        await RisingEdge(dut.clk_sys)
        cur_we = _bit(ram_we)
        cur_cond = _bit(cond)
        if prev_we == 1 and cur_we == 0:
            _track_commits.ram_writes += 1
        if prev_cond == 0 and cur_cond == 1:
            _track_commits.branches_taken += 1
        if cur_we is not None:
            prev_we = cur_we
        if cur_cond is not None:
            prev_cond = cur_cond


# ---- the cocotb test: ONE seed, ONE elaboration -------------------------
@cocotb.test()
async def fuzz_one_seed(dut):
    """One fuzz seed against the already-elaborated ROM image. The seed
    comes from DINO_FUZZ_SEED (see this file's own header for why not
    DINO_PROG_HEX). Compares OB, ram_writes, and branches_taken against
    progrom_gen.simulate()'s oracle (see this file's own header for what
    each tap reads and how it was validated); a HALT that takes longer
    than max_us_for()'s oracle-derived timeout fails loudly via
    wait_halt()'s own diagnostic (OB/T/PC at time of timeout), which is
    this test's 'did it halt' check. Every failure prints the seed and
    fuzz_gen.gen(seed)'s own disassembled listing -- reproduce with
    `fuzz_gen.gen(seed)`, shrink with `limit=`.

    fuzz_gen.gen() (Task 1) does not guarantee a program executes OUT --
    unlike every curated progrom_gen.COVERAGE image, which always ends
    OUT; HALT by hand-written construction, a random legal stream can
    reach HALT having never loaded the OB register (simulate()'s own
    `out` stays its None sentinel; empirically ~29% of seeds at
    main_len=24, from JMP-straight-to-HALT short-circuits and the OUT/IN
    weight both being low -- see fuzz_gen.py's own weight table). OB has
    NO RESET on real hardware (CLAUDE.md: "OB always already holds the
    previous answer"), so a fresh cocotb elaboration's own OB is simply
    whatever the register model's own un-driven reset state is -- not
    something progrom_gen.simulate()'s `out=None` models or could be
    compared against without inventing a value neither side actually
    computed. When exp['out'] is None, this test skips ONLY the OB
    equality (still logged, not silently dropped) -- ram_writes/
    branches_taken are unaffected by this (simulate() always returns
    them, OUT or not) and are checked on EVERY seed regardless.
    """
    seed = int(os.environ["DINO_FUZZ_SEED"])
    prog, meta = fuzz_gen.gen(seed)
    sw = meta["switches"] if meta["uses_in"] else 0x00
    if meta["uses_in"]:
        cocotb.log.info(f"seed {seed}: uses IN, switches={sw:#04x} "
                         f"(fuzz_gen.gen()'s own seed-derived draw)")
    exp = oracle(prog, switches=sw)
    hexp = os.path.join(HEX_DIR, f"fuzz_{seed}.hex")
    assert os.path.exists(hexp), (
        f"fuzz_one_seed: {hexp!r} does not exist -- write_fuzz_hex(seed, "
        f"prog) (run_fuzz_seeds()'s own per-seed step) did not run before "
        f"this elaboration, or DINO_FUZZ_SEED={seed} names a seed whose "
        f"hex was never written")
    cocotb.start_soon(_track_commits(dut))
    ob = await run_program(dut, hexp, switches=sw, max_us=max_us_for(prog, sw))
    _report_monitor()
    _report_ob_trace()
    _assert_no_violations()
    got_rw = _track_commits.ram_writes
    got_bt = _track_commits.branches_taken
    cocotb.log.info(
        f"seed {seed}: commit taps -- ram_writes={got_rw} "
        f"(want {exp['ram_writes']}) branches_taken={got_bt} "
        f"(want {exp['branches_taken']})")
    listing = "\n".join(meta["text"])
    assert got_rw == exp["ram_writes"], (
        f"seed {seed}: n_ram_write_en committed {got_rw} time(s), want "
        f"{exp['ram_writes']} (progrom_gen.simulate(), never hand-typed) "
        f"-- OB={ob:#04x} steps={exp['steps']}\n{listing}")
    assert got_bt == exp["branches_taken"], (
        f"seed {seed}: cond_taken committed {got_bt} time(s), want "
        f"{exp['branches_taken']} (progrom_gen.simulate(), never "
        f"hand-typed) -- OB={ob:#04x} steps={exp['steps']}\n{listing}")
    if exp["out"] is None:
        cocotb.log.info(
            f"seed {seed}: oracle never executed OUT (out=None) -- OB "
            f"comparison skipped, ram_writes/branches_taken/HALT-"
            f"reachability/invariant checks still ran full (see "
            f"fuzz_one_seed's own docstring)")
        return
    assert ob == exp["out"], (
        f"seed {seed}: OB={ob:#04x} at HALT, want {exp['out']:#04x} "
        f"(progrom_gen.simulate(), never hand-typed) -- steps="
        f"{exp['steps']} ram_writes={exp['ram_writes']} branches_taken="
        f"{exp['branches_taken']}\n{listing}")


# ---- host-side orchestrator ----------------------------------------------
# Everything below runs OUTSIDE cocotb/ghdl -- plain Python driving `make`/
# `ghdl` as subprocesses, one elaboration per seed (see this file's own
# header for why one @cocotb.test() cannot loop over seeds itself).
VENV_BIN = os.path.expanduser("~/.venvs/dino-fpga/bin")
TOOLS_BIN = os.path.expanduser("~/oss-cad-suite/bin")

# Calibrated per-program metavalue bound -- measured 2026-08-09, this
# task's own 500-seed soak (`DINO_FUZZ_N=500`, see this file's own header
# CALIBRATION note, task-2-report.md, and
# scratchpad/soak_500_retry.log's own tail: "500 seeds in 275.6s wall
# (0.55s/seed), 2500 metavalue warnings ... ALL GREEN" -- 2500/500 = 5.0
# metavalue lines per seed, EXACTLY, no variance across all 500 runs).
# The 20-seed default run showed the identical 5/seed (100 total). Every
# fuzz seed prints the SAME 5 "NUMERIC_STD.TO_INTEGER: metavalue
# detected" lines (3 @0ms + 2 @10ns) test_core_milestone.py's milestone/
# IN runs already show -- traced (test_module_control_word.py's own
# header) to control_word.vhd's literal-constant E1/E2/E3 port maps being
# resolved once, at VHDL's mandatory t=0 initialization pass, before any
# stimulus can run -- independent of PROGRAM CONTENT, dependent only on a
# fresh elaboration happening at all. Pinned above the observed 5 with
# headroom, not at the bare minimum, so a future generator change that
# adds real per-instruction metavalue variability (e.g. a wider opcode
# menu touching a sheet control_word doesn't) does not need instant
# retuning to stay green; still tight enough that a NEW class of warning
# (a real modeling gap, not this known-benign elaboration artifact) trips
# the assertion.
METAVALUE_PER_PROGRAM_BOUND = 8


def _tool_env(extra=None):
    env = dict(os.environ)
    env["PATH"] = f"{VENV_BIN}:{TOOLS_BIN}:" + env.get("PATH", "")
    if extra:
        env.update(extra)
    return env


def _cocotb_cfg(*args):
    out = subprocess.run(
        [os.path.join(VENV_BIN, "python3"), "-m", "cocotb_tools.config", *args],
        capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _make_seed(seed):
    """Full `make` invocation -- analyze+elaborate+prepare_roms+run, the
    SAME recipe test_core_milestone.py/test_core_coverage.py use. Only
    called for the first seed of a run (bootstraps sim_build/); later
    seeds reuse it via _ghdl_run_seed()."""
    hexrel = os.path.join("hex", f"fuzz_{seed}.hex")
    env = _tool_env({"DINO_FUZZ_SEED": str(seed)})
    cmd = ["make", "MODULE_UNDER_TEST=dino_core", "MODULE=test_core_fuzz",
           "TESTCASE=fuzz_one_seed", f"DINO_PROG_HEX={hexrel}"]
    return subprocess.run(cmd, cwd=HERE, env=env, capture_output=True, text=True)


def _ghdl_run_seed(seed):
    """Reuse the sim_build/ a prior _make_seed() call already produced --
    ~7x faster than a full `make` (measured, this task's own probe: 0.4s
    vs ~3s), because swapping u24_init_file is a RUNTIME generic (see
    this file's own header for why elaboration doesn't need to repeat).
    Every env var/generic here mirrors fpga/sim/Makefile's own dino_core
    branch + cocotb's Makefile.ghdl recipe line, with the VPI/libpython
    paths resolved via `cocotb_tools.config` (the same tool Makefile.inc
    itself shells out to), never hand-guessed or hard-coded to one
    machine's install layout."""
    hexrel = os.path.join("hex", f"fuzz_{seed}.hex")
    env = _tool_env({
        "DINO_FUZZ_SEED": str(seed),
        "COCOTB_TEST_MODULES": "test_core_fuzz",
        "COCOTB_TEST_FILTER": "fuzz_one_seed",
        "COCOTB_TOPLEVEL": "dino_core",
        "TOPLEVEL_LANG": "vhdl",
    })
    env["PYGPI_PYTHON_BIN"] = _cocotb_cfg("--python-bin")
    env["LIBPYTHON_LOC"] = _cocotb_cfg("--libpython")
    vpi = _cocotb_cfg("--lib-name-path", "vpi", "ghdl")
    cmd = ["ghdl", "-r", "--std=08", "--workdir=sim_build", "-Psim_build",
           "--work=work", "dino_core", f"--vpi={vpi}",
           f"-gu9_init_file={os.path.join(HERE, 'hex', 'U9.hex')}",
           f"-gu15_init_file={os.path.join(HERE, 'hex', 'U15.hex')}",
           # U23, the third microcode EEPROM (2026-08-10). Its generic has no
           # default -- ttl_at28c64b's init_file is `string;` with no value --
           # so omitting this is an ELABORATION error ("cannot open file
           # sim/hex/U23.hex"), not a wrong-content one.
           f"-gu23_init_file={os.path.join(HERE, 'hex', 'U23.hex')}",
           f"-gu24_init_file={os.path.join(HERE, hexrel)}",
           f"-gu26_init_file={os.path.join(HERE, 'hex', 'RAM.hex')}",
           "--max-stack-alloc=1024"]
    return subprocess.run(cmd, cwd=HERE, env=env, capture_output=True, text=True)


def _count_metavalue(text):
    return text.count("NUMERIC_STD.TO_INTEGER: metavalue detected")


def _passed():
    results = os.path.join(HERE, "results.xml")
    if not os.path.exists(results):
        return False
    r = subprocess.run(
        [os.path.join(VENV_BIN, "python3"), "-m", "cocotb_tools.check_results",
         results], capture_output=True, text=True)
    return r.returncode == 0


def run_one_seed(seed, bootstrap=False):
    """write_fuzz_hex() then run (make on the first/bootstrap seed of a
    batch, direct ghdl -r otherwise). Returns (passed, metavalue_count,
    combined stdout+stderr, meta)."""
    prog, meta = fuzz_gen.gen(seed)
    write_fuzz_hex(seed, prog)
    result = _make_seed(seed) if bootstrap else _ghdl_run_seed(seed)
    out = result.stdout + result.stderr
    ok = result.returncode == 0 and _passed()
    return ok, _count_metavalue(out), out, meta


def run_fuzz_seeds(seeds):
    """The orchestrator: run every seed, print a one-line-per-seed
    progress log, then a summary (wall time, metavalue total vs budget).
    Raises (does not just print) on any oracle divergence or budget
    overrun, so this doubles as the soak's own pass/fail gate when driven
    from a shell (`python3 test_core_fuzz.py; echo $?`)."""
    seeds = list(seeds)
    failures = []
    total_mv = 0
    t0 = time.time()
    for i, seed in enumerate(seeds):
        ok, mv, out, meta = run_one_seed(seed, bootstrap=(i == 0))
        total_mv += mv
        sw_s = f" switches={meta['switches']:#04x}" if meta["uses_in"] else ""
        print(f"seed {seed}: {'PASS' if ok else 'FAIL'}  metavalue={mv}{sw_s}")
        if not ok:
            failures.append((seed, meta, out))
    elapsed = time.time() - t0
    budget = METAVALUE_PER_PROGRAM_BOUND * len(seeds)
    per_seed = elapsed / len(seeds) if seeds else 0.0
    print(f"\n{len(seeds)} seeds in {elapsed:.1f}s wall "
          f"({per_seed:.2f}s/seed), {total_mv} metavalue warnings "
          f"(budget {budget} = {METAVALUE_PER_PROGRAM_BOUND}/program x "
          f"{len(seeds)})")
    if failures:
        for seed, meta, out in failures:
            print(f"\n--- seed {seed} FAILED ---")
            print("\n".join(meta["text"]))
            tail = out[-4000:]
            print(tail)
        raise SystemExit(
            f"{len(failures)}/{len(seeds)} seeds diverged from the oracle "
            f"-- see per-seed listings above")
    if total_mv > budget:
        raise SystemExit(
            f"metavalue budget exceeded: {total_mv} > {budget} "
            f"({METAVALUE_PER_PROGRAM_BOUND}/program x {len(seeds)} seeds)")
    print("ALL GREEN")
    return elapsed, total_mv


if __name__ == "__main__":
    run_fuzz_seeds(FUZZ_SEEDS)
