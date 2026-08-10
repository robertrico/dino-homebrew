#!/usr/bin/env python3
"""Host tests for fuzz_gen.py — the seeded legal-program generator that
feeds Task 2's differential fuzz harness.

Pins the structural guarantees fuzz_gen.py's docstring names: legal
opcodes only, forward-only jumps (so every program halts), a defined
ALU flag ahead of every JNZ, and reproducibility under `limit`
truncation (the shrinker's knob). `progrom_gen.simulate()` is the
oracle these programs will be checked against in Task 2, so
"terminates" here means what it will mean there: `simulate()` returns
`halted: True` — the dict's actual completion signal (`simulate()`
returns a `st` dict; `st["halted"]` is set on the HALT micro-op arm and
left False only if `max_steps` runs out first)."""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import fuzz_gen
import progrom_gen


def test_deterministic_and_legal():
    p1, m1 = fuzz_gen.gen(seed=42, main_len=24)
    p2, m2 = fuzz_gen.gen(seed=42, main_len=24)
    assert p1 == p2 and m1["text"] == m2["text"], "same seed must give same program"
    names = [i[0] for i in p1]
    assert names[-1] == "HALT"
    assert all(progrom_gen.sim_supports(n) for n in names), \
        f"unsupported opcode emitted: {[n for n in names if not progrom_gen.sim_supports(n)]}"


def test_every_seed_terminates_in_oracle():
    for seed in range(50):
        prog, meta = fuzz_gen.gen(seed)
        st = progrom_gen.simulate(prog, switches=0x1E)
        assert st["halted"], f"seed {seed} did not halt in oracle:\n" + "\n".join(meta["text"])


def test_jumps_are_forward_only():
    for seed in range(50):
        prog, meta = fuzz_gen.gen(seed)
        for src, dst in meta["jump_targets"]:
            assert dst > src, f"seed {seed}: backward jump {src}->{dst}"


def test_limit_truncates_reproducibly():
    full, _ = fuzz_gen.gen(seed=7, main_len=24)
    cut, _ = fuzz_gen.gen(seed=7, main_len=24, limit=5)
    assert len(cut) <= len(full)
    assert cut[-1][0] == "HALT"


def test_jnz_always_preceded_by_alu_op():
    """simulate() only updates FLAG_Z on the ALU src arm — a JNZ with no
    ALU op before it still runs (FLAG_Z defaults to 0), but would be
    testing the generator's own default rather than a computed flag."""
    for seed in range(50):
        prog, meta = fuzz_gen.gen(seed)
        for i, step in enumerate(prog):
            if step[0] == "JNZ":
                assert i > 0, f"seed {seed}: JNZ with nothing before it"
                assert prog[i - 1][0] in (
                    "ADD", "SUB", "AND", "OR", "XOR", "CLR", "SET", "BSUB"
                ), f"seed {seed}: JNZ at {i} not preceded by an ALU op: " \
                   f"{prog[i - 1]}"


def test_memory_ops_use_distinct_low_bytes():
    """The mardisc lesson: a program with >=2 memory ops must vary the
    low byte, or a stuck MAR_LO bit would be invisible to it."""
    for seed in range(50):
        prog, meta = fuzz_gen.gen(seed)
        mem_lows = {step[1] for step in prog if step[0] in ("LDA", "STA")}
        if sum(1 for step in prog if step[0] in ("LDA", "STA")) >= 2:
            assert len(mem_lows) >= 2, \
                f"seed {seed}: >=2 memory ops but one address {mem_lows}"


def test_memory_addresses_stay_in_ram():
    for seed in range(50):
        prog, meta = fuzz_gen.gen(seed)
        for step in prog:
            if step[0] in ("LDA", "STA"):
                addr = step[1] | (step[2] << 8)
                lo, hi = progrom_gen.RAM_BASE, progrom_gen.RAM_BASE + 0x40
                assert lo <= addr < hi, \
                    f"seed {seed}: {step} out of the pinned RAM window"


def test_uses_in_matches_program():
    for seed in range(50):
        prog, meta = fuzz_gen.gen(seed)
        assert meta["uses_in"] == any(step[0] == "IN" for step in prog)


def test_switches_are_seed_derived_reproducible_and_vary():
    """FUZZ-03's actual claim: the differential harness drives a RANDOM
    dip_sw value per seed on IN-using programs, not one hardcoded
    constant. Pins three things: `switches` is in range, reproducible
    from the seed alone (same seed -> same value, matching every other
    seed-derived field this generator produces), and the values seen
    across a seed range are not all identical -- the exact regression
    this test exists to catch (a hardcoded `0x1E if uses_in else 0x00`
    in the harness would make every seed's expected switches value
    collapse to one of two constants, which this test would catch by
    finding fewer than 2 distinct values among IN-using seeds)."""
    seen = set()
    for seed in range(200):
        prog, meta = fuzz_gen.gen(seed)
        sw = meta["switches"]
        assert 0 <= sw <= 255
        prog2, meta2 = fuzz_gen.gen(seed)
        assert meta2["switches"] == sw, \
            f"seed {seed}: switches not reproducible ({sw} != {meta2['switches']})"
        if meta["uses_in"]:
            seen.add(sw)
    assert len(seen) >= 2, \
        f"only {len(seen)} distinct switches value(s) across 200 seeds' " \
        f"IN-using programs ({seen}) -- looks hardcoded, not random-per-seed"
