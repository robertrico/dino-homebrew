"""Whole-core cocotb helpers (Task 11): ROM-image prep, run_program(),
wait_halt(), and the standing gated-clock invariant monitor -- shared by
every whole-core test. test_core_milestone.py is the first consumer;
Task 12 reuses run_program()'s signature/behavior verbatim (this task's
own brief interface note), so its ROM-selection contract (see
run_program()'s own docstring) is deliberately generic, not milestone-
specific.

Run directory: fpga/sim/ (matches every fpga/sim/test_module_*.py and
fpga/sim/Makefile's own documented convention). HERE below resolves every
path from THIS file's own location, not the process CWD, so the ROM-prep
functions work both when this module is imported inside a running cocotb
simulation and when invoked standalone
(`python3 -c "from conftest_helpers import prepare_roms; prepare_roms()"`,
fpga/sim/Makefile's own CUSTOM_SIM_DEPS hook for MODULE_UNDER_TEST=dino_core).
"""
import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotb.utils import get_sim_time

HERE = os.path.dirname(os.path.abspath(__file__))
FPGA_DIR = os.path.normpath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
DOCS_NOTES = os.path.join(REPO_ROOT, "docs", "notes")
ROMS_DIR = os.path.join(REPO_ROOT, "roms")
HEX_DIR = os.path.join(HERE, "hex")
GATED_CLOCKS_TXT = os.path.join(FPGA_DIR, "gen", "gated_clocks.txt")

sys.path.insert(0, DOCS_NOTES)
import microcode_gen           # noqa: E402
import progrom_gen             # noqa: E402
from fpga_gen import bin2hex   # noqa: E402


# ---- ROM-image prep -------------------------------------------------------
# coverage tag -> roms/*.bin filename. "real" (the milestone image) is
# special-cased to PROG.bin -- progrom_gen.py's own main() never
# regenerates the milestone image under another name (block 6 must
# accept on exactly the image it was specified against) -- every other
# COVERAGE key follows PROG_<tag>.bin, the SAME rule progrom_gen.main()'s
# own build loop uses to name what it writes. Generalized (Task 12) from
# a 2-entry {"real": ..., "in": ...} literal table to this rule so a
# wider `tags` tuple (alu/mem/flow/loop/adda/addb, this task's own
# coverage ladder) needs no table edit here -- any key already present in
# progrom_gen.COVERAGE resolves correctly by construction.
def _prog_bin_name(tag):
    return "PROG.bin" if tag == "real" else f"PROG_{tag}.bin"


def _hex_name(tag):
    return "PROG.hex" if tag == "real" else f"PROG_{tag}.hex"


def _stale(srcs, outs):
    """True if any output is missing, or the newest source is younger
    than the process boundary -- i.e. any SOURCE postdates the OLDEST
    output. Mirrors a plain Makefile timestamp rule; never compares byte
    content (roms/*.bin is binary, generated, and the whole point is not
    re-deriving it by hand here)."""
    if any(not os.path.exists(o) for o in outs):
        return True
    existing_srcs = [s for s in srcs if os.path.exists(s)]
    if not existing_srcs:
        return False
    newest_src = max(os.path.getmtime(s) for s in existing_srcs)
    oldest_out = min(os.path.getmtime(o) for o in outs)
    return newest_src > oldest_out


def _assert_crc(path, expected_bytes, crc16_fn, label):
    """CRC guard (Task 8 VPLAN rider, port-phase follow-up #3). Asserts
    the on-disk ROM file's content matches a FRESH in-memory rebuild --
    every prepare_roms() call, not just when _stale()'s mtime heuristic
    decides a regeneration is due. mtime alone cannot catch a roms/*.bin
    that was hand-edited, bit-rotted, or checked out with a mtime that
    postdates its generator source without the CONTENT actually matching
    what that source would produce today -- exactly the gap this closes.

    Review fix (task-8 fix round 1): compares the BYTES directly (strictly
    stronger than a CRC-16 match -- a 16-bit CRC has real collisions,
    bytes cannot) at zero extra cost (both are already in memory); the
    CRC-16 stays in the failure message only as a short, human-legible
    fingerprint alongside the definitive byte-length/first-mismatch-offset
    report, not as the actual check.

    A MISSING file is its own labeled failure (not a bare, unlabeled
    FileNotFoundError) -- same "name the lying signal" doctrine as every
    other check in this repo (CLAUDE.md "NO BLIND COUNTERS")."""
    if not os.path.exists(path):
        raise AssertionError(
            f"prepare_roms CRC guard: {label} -- {path} does not exist "
            f"(expected {len(expected_bytes)} bytes, crc16=0x"
            f"{crc16_fn(expected_bytes):04X}) -- re-run its generator's "
            f"main() (never hand-patch a ROM byte, CLAUDE.md rule 4/5)")
    with open(path, "rb") as f:
        on_disk = f.read()
    if on_disk == expected_bytes:
        return
    got_crc = crc16_fn(on_disk)
    want_crc = crc16_fn(expected_bytes)
    first_diff = next((i for i, (a, b) in enumerate(zip(on_disk, expected_bytes))
                        if a != b), min(len(on_disk), len(expected_bytes)))
    raise AssertionError(
        f"prepare_roms CRC guard: {label} ({path}) content mismatch -- "
        f"on-disk {len(on_disk)} bytes (crc16=0x{got_crc:04X}) != "
        f"expected {len(expected_bytes)} bytes (crc16=0x{want_crc:04X}) "
        f"from the current generator source, first differing byte at "
        f"offset {first_diff} -- the file is stale or was hand-edited; "
        f"re-run its generator's main() (never hand-patch a ROM byte, "
        f"CLAUDE.md rule 4/5)")


def prepare_roms(tags=("real", "in")):
    """Regenerate roms/*.bin (via microcode_gen.main()/progrom_gen.main(),
    called IN-PROCESS -- both are idempotent, side-effect-only writers,
    the same contract docs/notes/fpga_gen.py's own _regenerate() already
    relies on for its microcode/memory hex) whenever either generator
    script is newer than its own output, then bin2hex()s every ROM this
    task's tests need into fpga/sim/hex/. Never hand-writes a ROM byte --
    roms/*.bin remains the single source of truth (CLAUDE.md rule 4/5);
    this function only keeps fpga/sim/hex/*.hex (GHDL's own load format)
    in sync with it.

    `tags` selects which PROG_<tag>.bin coverage images get converted,
    beyond the microcode pair (U9/U15) and the always-present milestone
    image -- Task 12's own coverage ladder (alu/mem/flow/loop/...) reuses
    this by passing a wider tags tuple, without needing its own copy of
    this staleness/conversion logic.

    CRC guard: after the staleness-driven regeneration (if any), every
    ROM this call is about to convert to hex is CRC-checked against a
    fresh in-memory rebuild (_assert_crc, above) -- closes the port-phase
    "prepare_roms CRC guard" follow-up (docs/notes/dino_fpga_vplan.md).
    """
    mc_outs = [os.path.join(ROMS_DIR, "U9.bin"), os.path.join(ROMS_DIR, "U15.bin")]
    if _stale([os.path.join(DOCS_NOTES, "microcode_gen.py")], mc_outs):
        microcode_gen.main()

    pr_outs = [os.path.join(ROMS_DIR, _prog_bin_name(t)) for t in tags
               if t in progrom_gen.COVERAGE]
    pr_srcs = [os.path.join(DOCS_NOTES, "microcode_gen.py"),
               os.path.join(DOCS_NOTES, "progrom_gen.py")]
    if _stale(pr_srcs, pr_outs):
        progrom_gen.main()

    # roms/U9.bin and U15.bin are the A12-GROUNDED chips: main() writes
    # each 4096-byte half MIRRORED (microcode_gen._mirror() = half+half,
    # 8192 bytes on disk), matching what the real AT28C64B reads with its
    # top address line tied low. Comparing against just the un-mirrored
    # half would CRC-mismatch every real committed file -- mirror the
    # freshly-rebuilt half the same way before comparing.
    mc_lo, mc_hi = microcode_gen.split(microcode_gen.build_real())
    _assert_crc(mc_outs[0], microcode_gen._mirror(mc_lo),
                microcode_gen.crc16, "U9 (microcode low byte, mirrored)")
    _assert_crc(mc_outs[1], microcode_gen._mirror(mc_hi),
                microcode_gen.crc16, "U15 (microcode high byte, mirrored)")
    for tag in tags:
        if tag not in progrom_gen.COVERAGE:
            continue
        out_path = os.path.join(ROMS_DIR, _prog_bin_name(tag))
        # build_image(COVERAGE[tag]) == build_real() when tag == "real"
        # (COVERAGE["real"] IS the PROGRAM build_real() assembles; the two
        # functions are byte-identical bodies over the same source) --
        # review fix round: collapsed the redundant tag=="real" branch
        # rather than keep two code paths that can never actually differ.
        expected = progrom_gen.build_image(progrom_gen.COVERAGE[tag])
        _assert_crc(out_path, expected, progrom_gen.crc16,
                    _prog_bin_name(tag))

    os.makedirs(HEX_DIR, exist_ok=True)
    bin2hex(os.path.join(ROMS_DIR, "U9.bin"), os.path.join(HEX_DIR, "U9.hex"))
    bin2hex(os.path.join(ROMS_DIR, "U15.bin"), os.path.join(HEX_DIR, "U15.hex"))
    for tag in tags:
        if tag not in progrom_gen.COVERAGE:
            continue
        bin2hex(os.path.join(ROMS_DIR, _prog_bin_name(tag)),
                os.path.join(HEX_DIR, _hex_name(tag)))
    ram_hex = os.path.join(HEX_DIR, "RAM.hex")
    if not os.path.exists(ram_hex):
        open(ram_hex, "w").close()   # blank -- the real board's RAM starts empty too


def oracle_final_ob(tag, switches=0x00):
    """The OB value docs/notes/progrom_gen.py's own simulate() predicts
    for COVERAGE[tag] -- IMPORTED, never hand-typed. Same oracle
    discipline test_module_memory.py/test_module_microcode.py already
    hold for ROM content and microcode rows, extended here to the whole
    machine's own datapath observable."""
    program = progrom_gen.COVERAGE[tag]
    result = progrom_gen.simulate(program, switches=switches)
    assert result["halted"], (
        f"oracle_final_ob({tag!r}, switches=0x{switches:02X}): the "
        f"microcode-driven interpreter itself never reached HALT within "
        f"its max_steps -- fixture problem, not a hardware one")
    return result["out"]


# ---- clocking ---------------------------------------------------------
CLK_SYS_PERIOD_NS = 10                        # 100MHz simulation-sampling clock
Y1_DIVIDE = 25                                 # 100MHz / 25 = 4MHz (this task's own math)
Y1_LOW_CYCLES = 13
Y1_HIGH_CYCLES = Y1_DIVIDE - Y1_LOW_CYCLES     # 12 -- asymmetric duty cycle is fine,
                                                # only EDGES matter to the '163 CP
                                                # input this feeds (dino_core's U20);
                                                # every edge lands exactly on a
                                                # clk_sys edge (phase-locked divider,
                                                # not an independent free-running
                                                # Clock()), so the clk_sys-edge-
                                                # sampling TTL models can never miss one.


async def _drive_clk4m_y1(dut):
    """clk4m_y1 (dino_core's own port, the Y1 4MHz-oscillator stand-in)
    toggled by a clk_sys-locked divider coroutine, not an independent
    cocotb Clock() -- keeps its phase honest relative to clk_sys, per
    this task's own interface note."""
    dut.clk4m_y1.value = 0
    while True:
        await ClockCycles(dut.clk_sys, Y1_LOW_CYCLES)
        dut.clk4m_y1.value = 1
        await ClockCycles(dut.clk_sys, Y1_HIGH_CYCLES)
        dut.clk4m_y1.value = 0


RESET_ESCAPE_CYCLES = 400   # generous margin re: the note below (>= 4 full
                            # machine-clk periods at the slowest observed
                            # ~1000ns period, well past the one qualifying
                            # edge this actually needs)


async def _arm_reset(dut, reset_ns=500):
    """ARM (hold btn_reset_n asserted -- the machine's only reset path)
    and release. CLAUDE.md's own doctrine: 'reset is the button on an ARM
    prompt, and no press has to be fast' -- this machine is fully static,
    so there is no minimum HOLD time to get right here; reset_ns is
    generous, not tuned.

    What DOES need to be got right: `reset` (dino_core's internal signal,
    U27 FF2's Q2, asynchronously PRESET while btn_reset_n=0) only FALLS
    back to 0 on the first `clk` (the slow, ~us-scale internal machine
    clock -- not clk_sys) rising edge AFTER btn_reset_n releases, not the
    instant it releases -- releasing the button is not the same event as
    the machine actually leaving reset. The T-counter's own synchronous
    clear (mr_n, gated by `reset OR END`) is sampled on that SAME clk
    edge, so this is also the event that lets a HALTed machine
    (T frozen, per CLAUDE.md's own 'park' description) escape: T cannot
    return to 0 -- and cw15_eq_halt/`halt` cannot drop -- until this
    exact edge has come and gone. A caller that returns from `_arm_reset`
    on a fixed short delay (this function's own first-draft bug, found
    empirically: in_tracks_switches's SECOND run returned a stale OB
    from the FIRST run because wait_halt's very first sample still read
    `halt`=1, left over, and returned instantly) races that edge. Poll
    for `dut.halt` to actually read '0' before calling the re-arm done,
    with its own timeout (CLAUDE.md's NO BLIND COUNTERS rule) -- on a
    fresh power_on() this is typically already true and returns at once;
    it only actually waits when escaping a prior HALT."""
    dut.btn_reset_n.value = 0          # ARM: button held (active low)
    await Timer(reset_ns, unit="ns")
    dut.btn_reset_n.value = 1          # release -- `reset` itself falls
                                        # on the NEXT clk edge, not now
    for _ in range(RESET_ESCAPE_CYCLES):
        await RisingEdge(dut.clk_sys)
        if str(dut.halt.value) == "0":
            return
    raise AssertionError(
        f"_arm_reset: dut.halt never read '0' within "
        f"{RESET_ESCAPE_CYCLES} clk_sys cycles of releasing btn_reset_n "
        f"-- the machine did not leave HALT (halt={dut.halt.value})")


async def _track_ob(dut):
    """Record every OB value change (time, byte) into `_track_ob.trace`
    -- diagnostic only (this task's own report wants the observed OB
    TRAJECTORY, e.g. the POISON byte 0xFF showing up before the real
    answer, not just the final value; CLAUDE.md's own point of the
    leading LDAI 0xFF; OUT is exactly that this trajectory is the
    evidence a run actually reached the second OUT, not a stale
    left-over)."""
    _track_ob.trace = []
    prev = None
    while True:
        await RisingEdge(dut.clk_sys)
        v = _resolved_int(dut.ob_led.value)
        if v is not None and v != prev:
            _track_ob.trace.append((get_sim_time(unit="ns"), v))
            prev = v


async def power_on(dut, reset_ns=500):
    """Start clk_sys (100MHz), the clk4m_y1 Y1-stand-in divider, the
    standing invariant monitor, and the OB trajectory tracker; then ARM
    and release (_arm_reset()).

    Returns the invariant-monitor Task handle so callers/tests can read
    its `.coverage`/`.gaps` attributes (set once, at monitor start) for
    reporting."""
    dut.dip_sw.value = 0
    dut.btn_reset_n.value = 0
    dut.clk4m_y1.value = 0
    cocotb.start_soon(Clock(dut.clk_sys, CLK_SYS_PERIOD_NS, unit="ns").start())
    await Timer(CLK_SYS_PERIOD_NS, unit="ns")   # let clk_sys tick at least once first
    cocotb.start_soon(_drive_clk4m_y1(dut))
    monitor = cocotb.start_soon(invariant_monitor(dut))
    cocotb.start_soon(_track_ob(dut))
    await _arm_reset(dut, reset_ns)
    return monitor


async def rerun(dut, switches=0x00, max_us=500, reset_ns=500):
    """Re-arm and run again against the SAME already-elaborated ROM image,
    WITHOUT restarting clk_sys/clk4m_y1/the invariant monitor -- for a
    test that exercises more than one switch setting against ONE ROM
    within a single @cocotb.test() (dip_sw/registers/PC reset; the ROM
    content itself is fixed for the whole elaboration, per run_program()'s
    own docstring). Must only be called after power_on()/run_program()
    already started the clocks on this `dut`."""
    dut.dip_sw.value = switches
    await _arm_reset(dut, reset_ns)
    await wait_halt(dut, timeout_us=max_us)
    ob = int(dut.ob_led.value)
    cocotb.log.info(f"rerun(switches=0x{switches:02X}) -> OB=0x{ob:02X}")
    return ob


def _read_pc(dut):
    """16-bit PC value, decoded from program_counter_i's own per-bit
    signals (pc0..pc15 -- there is no single 'pc' bus signal on this
    sheet, see fpga/gen/program_counter.vhd). Diagnostic-only."""
    val = 0
    for i in range(16):
        bit = getattr(dut.program_counter_i, f"pc{i}").value
        if str(bit) in ("0", "1"):
            val |= (int(bit) & 1) << i
    return val


async def wait_halt(dut, timeout_us=500):
    """Wait for dut.halt (CW15=HALT, tapped at U61.3/U61.5 per CLAUDE.md
    -- the same two wires sampled in every bench block) to read high.
    Raises with enough decoded state to name what the machine was doing
    instead of a blind timeout (CLAUDE.md's NO BLIND COUNTERS rule)."""
    max_cycles = int(timeout_us * 1000 / CLK_SYS_PERIOD_NS)
    for _ in range(max_cycles):
        await RisingEdge(dut.clk_sys)
        if str(dut.halt.value) == "1":
            return
    ob = _resolved_int(dut.ob_led.value)
    t = _resolved_int(dut.t.value)
    pc = _read_pc(dut)
    ob_str = f"0x{ob:02X}" if ob is not None else str(dut.ob_led.value)
    t_str = f"0x{t:X}" if t is not None else str(dut.t.value)
    raise AssertionError(
        f"wait_halt: no HALT within {timeout_us}us ({max_cycles} clk_sys "
        f"cycles) -- OB={ob_str} T={t_str} PC=0x{pc:04X} halt={dut.halt.value}")


def _resolved_int(value):
    return int(value) if _resolvable(value) else None


async def run_program(dut, prog_hex, switches=0x00, max_us=500):
    """Power on, drive dip_sw, wait for HALT, return the final OB byte.
    Task 12's own reuse target (this task's brief interface note).

    ROM SELECTION itself happens OUTSIDE this coroutine: dino_core's
    ROM/RAM content is a GHDL generic (u24_init_file), resolved once at
    elaboration -- a VHDL generic string cannot change mid-simulation, so
    swapping ROMs means a fresh `make` invocation (fpga/sim/Makefile's
    DINO_PROG_HEX override), not a runtime call here. `prog_hex` is
    therefore the CALLER's declaration of which image THIS run's
    elaboration was already built against: asserted to exist on disk (a
    ROM-prep failure fails loud, here, rather than silently reading a
    stale/wrong image) and folded into the diagnostic log line below, so
    a wrong cross-check is traceable to the exact hex path that produced
    it.
    """
    assert os.path.exists(prog_hex), (
        f"run_program: {prog_hex!r} does not exist -- ROM prep "
        f"(conftest_helpers.prepare_roms(), fpga/sim/Makefile's "
        f"prepare_roms CUSTOM_SIM_DEPS target) did not run, or ran "
        f"against the wrong tag")
    await power_on(dut)
    dut.dip_sw.value = switches
    await wait_halt(dut, timeout_us=max_us)
    ob = int(dut.ob_led.value)
    cocotb.log.info(
        f"run_program({prog_hex!r}, switches=0x{switches:02X}) -> "
        f"OB=0x{ob:02X}")
    return ob


# ---- standing invariant monitor -------------------------------------------
# dino_core instantiates the nine sheet entities under these labels (see
# fpga/gen/dino_core.vhd's own port-map blocks) -- the only place a
# gated-clocks.txt identifier that isn't a dino_core-level root
# signal/port can live, since Task 8's emit() collects `gated` names at
# EACH sheet's own local scope (fpga_gen.py's _instance_block: `expr` is
# the sheet-local VHDL identifier, never sheet-qualified).
SHEET_INSTANCES = [
    "program_counter_i", "microcode_i", "control_word_i", "mdr_i",
    "registers_a_b_i", "mar_i", "memory_i", "alu_i", "input_output_i",
]

# Two identifiers in gated_clocks.txt are the CLOCK-GENERATION chain
# itself, not a "commits on CLK low" state-commit signal: clk4m_y1 (the
# Y1 oscillator, dino_core's own port -- feeds U20.cp) and net_u20_q0
# (U20's own Q0 output, feeding U27's toggle-FF clk1 input -- the stage
# that PRODUCES `clk`). CLAUDE.md's invariant is about things that
# COMMIT while clk is high; these two are strictly UPSTREAM of clk, so
# "does the oscillator/its first divider tick while its own great-
# grandchild signal reads high" is a category error, not a finding --
# they tick constantly, by design, throughout every phase. Excluded from
# the RISE check (still counted in monitor coverage below, just not
# checked), first found empirically (dozens of same-run violations,
# confirmed structural rather than a one-off race by their strict
# periodicity) then confirmed by their own gate ancestry.
_CLOCK_CHAIN_NAMES = {"clk4m_y1", "net_u20_q0"}

# le_mdr (mdr.vhd's MDR-staging '373's LE) is netlist-verified (kicad_
# netlist.build_report('dino_v0_0_2/mdr.kicad_sch'), U39 pin 6 = LE_MDR)
# to be driven by NAND(~RAM_LOAD, READS_IDLE) -- ZERO clk/n_clk input
# anywhere in its combinational cone on this sheet, on the REAL board,
# not just in the generated VHDL. CLAUDE.md's own machine-invariant
# section enumerates every clock-qualified commit point BY NAME
# (register/IR/MAR/ALU loads, RAM write, PC load/clear/count, T-state
# clear) and MDR is not among them -- by design, MDR is a data-STAGING
# latch on the bus<->ROM/RAM path, not an architectural register; the
# actual downstream commit points it feeds (le_ir, confirmed here as
# NOR(n_ir_load, clk) -- exactly CLAUDE.md's own formula; also
# le_tmp_a/le_tmp_b, n_reg_*_le) are each independently, correctly
# clk-gated and never violate. Excluded from the RISE check for the
# same reason as the clock-chain names: this is a netlist-verified
# "wrong invariant for this net", not a hardware defect (this task's
# report documents the derivation in full -- see there before trusting
# this comment alone).
_STAGING_LATCH_NAMES = {"le_mdr"}

MONITOR_EXCLUDE = _CLOCK_CHAIN_NAMES | _STAGING_LATCH_NAMES


def _load_gated_names():
    with open(GATED_CLOCKS_TXT) as f:
        return [ln.strip() for ln in f if ln.strip()]


def resolve_gated_clock_handles(dut):
    """Map each fpga/gen/gated_clocks.txt identifier to a cocotb handle.

    Task 8's own known limitation (progress.md's note, flagged for this
    task's dispatch): the file holds SHEET-UNQUALIFIED sanitized names,
    so there is no name->sheet index anywhere else -- each name is tried
    first at dino_core's own scope (a root signal or port: clk4m_y1,
    n_clk, net_u20_q0 all live there) and then, failing that, inside each
    of the nine sheet instances in turn.

    A root-scope match wins outright without searching further: several
    names (n_clk among them) are BOTH a dino_core-level signal AND a
    same-named port threaded straight through to one or more sheets
    (electrically the identical net, just visible under more than one
    cocotb handle) -- preferring the root handle avoids reporting that
    as a false "ambiguous" gap. Only names with NO root match search the
    nine sheet instances, where true sheet-local signals (le_mdr,
    pc_up_stable, etc.) actually live.

    Returns (handles, gaps): `gaps` names every identifier this run could
    NOT resolve to exactly one handle, with the reason, so monitor
    coverage is reported honestly rather than silently claimed complete
    (this task's own self-review rule: partial coverage with a named-gap
    list beats a silent 100% claim)."""
    handles, gaps = {}, []
    for name in _load_gated_names():
        if hasattr(dut, name):
            handles[name] = getattr(dut, name)
            continue
        found = []
        for inst in SHEET_INSTANCES:
            scope = getattr(dut, inst, None)
            if scope is not None and hasattr(scope, name):
                found.append((inst, getattr(scope, name)))
        if len(found) == 1:
            handles[name] = found[0][1]
        elif len(found) == 0:
            gaps.append((name, "not found at dino_core's own scope or any "
                               "of the nine sheet instances -- likely "
                               "internal to a ttl_* sub-entity, unreachable "
                               "from dino_core's own handle tree"))
        else:
            locs = ", ".join(loc for loc, _ in found)
            gaps.append((name, f"ambiguous -- matched more than one sheet "
                                f"instance ({locs})"))
    return handles, gaps


def _resolvable(value):
    s = str(value)
    return len(s) > 0 and all(c in "01" for c in s)


def _bit(handle):
    v = handle.value
    return int(v) if _resolvable(v) else None


async def invariant_monitor(dut):
    """THE standing invariant this task's brief names: CLAUDE.md's
    machine invariant ('everything that changes state is clock-qualified
    and commits on CLK low') restated as a live monitor. Samples every
    RESOLVED, non-excluded (see MONITOR_EXCLUDE) gated-clock net each
    clk_sys edge and records a violation the instant one RISES (0->1)
    while the sampled machine CLK (dut.clk -- the internal CPU clock the
    '163 T-counter and every load-enable are qualified against, distinct
    from clk_sys, the simulation-only sampling clock) has ALREADY read
    high on the PREVIOUS clk_sys sample too -- not merely on the CURRENT
    one. That extra clause matters: a signal legitimately gated by
    NAND/NOR(x, ~clk) is combinationally forced to its CLK-high level in
    the SAME zero-delay delta as CLK's own rising edge (e.g.
    pc_up_stable = NAND(PC_UP, n_clk) is forced to 1 the instant n_clk
    falls, which is the SAME instant CLK rises) -- checking `clk_now==1`
    alone flags that expected, simultaneous deassertion as a false
    violation on EVERY correctly-gated signal, every single cycle.
    Requiring CLK to have already been sampled high on the PRIOR tick
    isolates a genuine mid-high-phase glitch (this task's own empirical
    finding process: pc_up_stable's periodic single-tick violations
    vanished under this fix; le_mdr's did not, because le_mdr's rise
    lands measurably later than CLK's edge, not in the same delta -- see
    MONITOR_EXCLUDE's own comment for why le_mdr is excluded anyway, on
    netlist grounds unrelated to this timing fix).

    KNOWN BLIND SPOT (self-review finding, not fixed -- named instead):
    this excludes not just the exact same-delta coincidence but the
    entire FIRST clk_sys sample of every CLK-high phase -- a genuine
    glitch that rose and (somehow) fell again within that single ~10ns
    clk_sys tick, and nowhere else during the high phase, would go
    undetected, every cycle, for every checked net. Given the machine
    clock period is two-plus orders of magnitude longer than clk_sys's
    10ns sampling period (~1us vs 10ns, per this task's own OB-trace
    timestamps), the exposure is one specific ~10ns window out of an
    ~500ns-high phase, not the whole phase -- but it is real, not zero.

    Runs forever (started once, in power_on(), for the WHOLE test) --
    does NOT raise from inside the background Task (a cocotb Task
    exception's propagation to the enclosing test is scheduler-version-
    dependent and not something to bet a hardware finding on). Instead it
    appends to `invariant_monitor.violations` (net name + T-state, per
    CLAUDE.md's NO BLIND COUNTERS rule) and logs each one at ERROR the
    instant it happens; the calling test asserts that list is empty
    AFTER wait_halt() returns, which is what actually fails the test.

    Also sets `invariant_monitor.coverage` (sorted resolved+CHECKED
    names), `invariant_monitor.excluded` (sorted resolved but not
    checked, i.e. MONITOR_EXCLUDE intersected with what actually
    resolved), `invariant_monitor.gaps` (see
    resolve_gated_clock_handles()), and
    `invariant_monitor.qualifying_samples` (see below) once/continuously,
    so the calling test can report monitor coverage/exclusions/named-gaps
    without re-deriving them.

    LIVENESS SELF-CHECK (self-review finding): "0 violations" is
    indistinguishable, by itself, from a monitor that never actually got
    to check anything -- e.g. `dut.clk` stuck unresolved, or the machine
    never actually reaching a CLK-high sample before HALT. A silent,
    perpetually-vacuous monitor would report the SAME "0 violations" as a
    monitor that genuinely watched thousands of qualifying samples and
    found nothing wrong. `qualifying_samples` counts every clk_sys tick
    where the violation check actually RAN (clk_prev==1 and clk_now==1 --
    the same condition the check itself requires); the calling test
    asserts this is non-zero, so a vacuous monitor fails LOUD instead of
    passing by accident. Task 12's four new coverage images reuse this
    verbatim, per its own interface note."""
    handles, gaps = resolve_gated_clock_handles(dut)
    checked = {n: h for n, h in handles.items() if n not in MONITOR_EXCLUDE}
    invariant_monitor.coverage = sorted(checked)
    invariant_monitor.excluded = sorted(n for n in handles if n in MONITOR_EXCLUDE)
    invariant_monitor.gaps = gaps
    invariant_monitor.violations = []
    invariant_monitor.qualifying_samples = 0

    await RisingEdge(dut.clk_sys)
    prev = {name: _bit(h) for name, h in checked.items()}
    clk_prev = _bit(dut.clk)
    while True:
        await RisingEdge(dut.clk_sys)
        clk_now = _bit(dut.clk)
        qualifying = clk_now == 1 and clk_prev == 1
        if qualifying:
            invariant_monitor.qualifying_samples += 1
        for name, h in checked.items():
            cur = _bit(h)
            if prev.get(name) == 0 and cur == 1 and qualifying:
                t_now = _bit(dut.t)
                t_str = f"0x{t_now:X}" if t_now is not None else "X"
                msg = (f"invariant violated: {name} rose while machine "
                       f"CLK was high (T={t_str}) -- CLAUDE.md's "
                       f"'everything commits on CLK low' invariant broken")
                cocotb.log.error(msg)
                invariant_monitor.violations.append(msg)
            if cur is not None:
                prev[name] = cur
        if clk_now is not None:
            clk_prev = clk_now
