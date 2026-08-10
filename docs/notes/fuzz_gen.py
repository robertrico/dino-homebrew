#!/usr/bin/env python3
"""Seeded random-program generator for the DINO differential fuzzer.

Emits LEGAL DINO instruction streams only — every opcode comes from
`progrom_gen.sim_supports()`, so the oracle interpreter (`progrom_gen.
simulate()`) can execute anything this module produces. Structural
guarantees that make every program terminate and stay in-bounds,
adapted from the b8008 fuzzer's discipline
(~/Development/intel-8008-vhdl/sim/cocotb/fuzz_gen.py):

  - the body is straight-line except for JMP/JNZ; jumps are
    FORWARD-ONLY to instruction boundaries in the body (or the final
    HALT) — PC only ever increases, so every program halts inside
    `simulate()`'s max_steps by construction, no cycle is reachable
  - every program ends `("HALT",)`; HALT/NOP are never chosen mid-body
    on their own — NOP is the leftover-probability filler, HALT is
    appended once, after the loop
  - JNZ needs a defined FLAG_Z: `simulate()` only updates FLAG_Z on an
    ALU op (CW's `src == "ALU"` arm), so whenever a JNZ is chosen and
    the immediately preceding instruction is not already an ALU op, an
    ADD or SUB is inserted right before it
  - LDA/STA addresses are pinned to `RAM_BASE + rng.randrange(0x40)`
    (RAM_BASE = 0x8000, the M15 boundary) so every memory op lands in
    RAM, never ROM; when a program has >=2 memory ops it is repaired to
    use >=2 distinct low bytes — the mardisc lesson (2026-08-xx): a
    fuzzer that always reuses one address is blind to MAR_LO collapsing
    two addresses into one cell, same as MEM_PROGRAM's single-cell
    round trip
  - IN is allowed anywhere in the menu; `meta["uses_in"]` records
    whether it was chosen so the differential harness knows to drive
    switches on the real oracle run; `meta["switches"]` is a
    `rng.randrange(256)` draw taken AFTER every program-shaping
    decision (body, jump targets) is finished, so it never perturbs
    the program itself — same seed still gives byte-identical
    `program`/`meta["text"]` as before this field existed — but is
    still fully reproducible from the seed alone, no second source of
    entropy. Drawn unconditionally (even when `uses_in` is False) so
    the draw sequence, and therefore the value, is independent of
    which branch the harness takes with it.

`gen(seed, main_len=24, limit=None)` -> `(program, meta)`. `program` is
a list of `progrom_gen` tuple-form steps, ready for
`progrom_gen.assemble()` / `progrom_gen.build_image()`. `meta` is a
dict with `text` (address-annotated listing), `uses_in` (bool), and
`jump_targets` (list of `(src_addr, dst_addr)` byte pairs, one per
JMP/JNZ), and `switches` (int 0-255, the seed-derived DIP-switch value
the differential harness drives when `uses_in` is True). `limit`
truncates the body-generation loop to its first `limit` slots (the
shrinker's knob, 8008 precedent) — jump targets are chosen only from
what actually got generated, so they clamp to the (now closer) final
HALT automatically. Same (seed, main_len, limit) -> byte-identical
program and meta["text"] (and meta["switches"], since the switches
draw happens after program shaping is finished).
"""
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from progrom_gen import (OPCODES, sim_supports, RAM_BASE,  # noqa: E402
                         INSTRUCTIONS)

ALU_OPS = ["ADD", "SUB", "AND", "OR", "XOR", "CLR", "SET", "BSUB"]
IMM_OPS = ["LDAI", "LDBI", "LDCI"]
MEM_OPS = ["LDA", "STA"]
IO_OPS = ["OUT", "IN"]
JUMP_OPS = ["JMP", "JNZ"]
FLAG_FIXUP_OPS = ["ADD", "SUB"]          # what gets inserted before a bare JNZ

# every op this generator can choose is a real, sim-supported opcode —
# checked once at import time rather than re-checked per instruction
# (moving cost, not risk: both are pure functions of progrom_gen's own
# tables, so a bad menu entry fails the same way every run).
#
# `if not(...): raise AssertionError(...)`, not a bare `assert` (final-
# review minor fix): a bare `assert` is COMPILED OUT ENTIRELY under
# `python -O`/`-OO` (CPython strips assert statements at optimization
# level >=1, module-level ones included -- this is not a corner case,
# `-O` is a real invocation mode, and an import-time check that silently
# vanishes under it is the same class of hollow guard Task 8's fix round
# already found and fixed twice elsewhere in this repo, for
# test_progrom_coverage.py/test_kicad_blocks.py's own pytest-vs-__main__
# idiom). These three guard the generator's own menu against naming an
# opcode `progrom_gen`'s oracle can't execute -- worth keeping real under
# every invocation, not just a bare `python3 fuzz_gen.py`.
_MENU = ALU_OPS + IMM_OPS + MEM_OPS + IO_OPS + JUMP_OPS + ["NOP"]
if not (set(_MENU) <= set(OPCODES)):
    raise AssertionError(
        "generator menu names an opcode not in progrom_gen.OPCODES: "
        f"{[n for n in _MENU if n not in OPCODES]}")
if not all(sim_supports(n) for n in _MENU):
    raise AssertionError(
        "generator menu contains an unsupported opcode: "
        f"{[n for n in _MENU if not sim_supports(n)]}")
if not sim_supports("HALT"):
    raise AssertionError("oracle cannot execute HALT")


class _Entry:
    """One not-yet-addressed instruction. `operand` is a tuple of raw
    bytes (immediate, or address lo/hi), or None for zero-operand ops.
    `is_jump` marks JMP/JNZ, whose operand is filled in during the
    address-patch pass once every instruction has a byte address."""

    __slots__ = ("name", "operand", "is_jump")

    def __init__(self, name, operand=None, is_jump=False):
        self.name = name
        self.operand = operand
        self.is_jump = is_jump


def _mem_addr(rng):
    return RAM_BASE + rng.randrange(0x40)


def _emit_one(rng, body, last_name):
    """Append one instruction (occasionally two, for the JNZ flag
    fixup) to `body`. Returns the new `last_name`."""
    choice = rng.randrange(100)
    if choice < 35:                                       # ALU
        name = rng.choice(ALU_OPS)
        body.append(_Entry(name))
        return name
    if choice < 55:                                        # immediate load
        name = rng.choice(IMM_OPS)
        body.append(_Entry(name, (rng.randrange(256),)))
        return name
    if choice < 70:                                        # memory
        name = rng.choice(MEM_OPS)
        addr = _mem_addr(rng)
        body.append(_Entry(name, (addr & 0xFF, addr >> 8)))
        return name
    if choice < 80:                                        # I/O
        name = rng.choice(IO_OPS)
        body.append(_Entry(name))
        return name
    if choice < 95:                                        # jump
        name = rng.choice(JUMP_OPS)
        if name == "JNZ" and last_name not in ALU_OPS:
            fixup = rng.choice(FLAG_FIXUP_OPS)
            body.append(_Entry(fixup))
        body.append(_Entry(name, None, is_jump=True))    # target: patched later
        return name
    body.append(_Entry("NOP"))                           # leftover-mass filler
    return "NOP"


def _repair_mem_diversity(rng, body):
    """The mardisc lesson: >=2 memory ops must use >=2 distinct low
    bytes. Cheap post-pass rather than rejection-sampling every mem op,
    since the collision case is rare (1-in-64) and this stays O(n)."""
    mem_entries = [e for e in body if e.name in MEM_OPS]
    if len(mem_entries) < 2:
        return
    lows = {e.operand[0] for e in mem_entries}
    if len(lows) >= 2:
        return
    stuck = next(iter(lows))
    new_low = (stuck + 0x20) & 0x3F                      # guaranteed != stuck
    addr = RAM_BASE + new_low
    mem_entries[-1].operand = (addr & 0xFF, addr >> 8)


def gen(seed, main_len=24, limit=None):
    """Seeded legal DINO program. See module docstring for the
    structural guarantees this enforces."""
    rng = random.Random(seed)
    body = []
    last_name = None
    n = main_len if limit is None else min(limit, main_len)
    for _ in range(n):
        last_name = _emit_one(rng, body, last_name)

    _repair_mem_diversity(rng, body)
    body.append(_Entry("HALT"))

    # address assignment (byte offsets from 0, matching progrom_gen.
    # assemble()'s default base — simulate() always assembles at base 0)
    addrs, addr = [], 0
    for e in body:
        addrs.append(addr)
        addr += INSTRUCTIONS[e.name][0]

    # patch forward jump targets: only ever a future instruction boundary
    # (HALT included, since it is always the last entry) -> strictly > src
    jump_targets = []
    for i, e in enumerate(body):
        if not e.is_jump:
            continue
        future = addrs[i + 1:]
        tgt = rng.choice(future) if future else addrs[-1]
        e.operand = (tgt & 0xFF, tgt >> 8)
        jump_targets.append((addrs[i], tgt))

    program = []
    text = []
    uses_in = False
    for e, ad in zip(body, addrs):
        step = (e.name,) if e.operand is None else (e.name, *e.operand)
        program.append(step)
        operand_s = "" if e.operand is None else " " + ",".join(
            f"{b:#04x}" for b in e.operand)
        text.append(f"{ad:#06x}: {e.name}{operand_s}")
        if e.name == "IN":
            uses_in = True

    switches = rng.randrange(256)
    meta = {"text": text, "uses_in": uses_in, "jump_targets": jump_targets,
             "switches": switches}
    return program, meta


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    prog, meta = gen(seed)
    print("\n".join(meta["text"]))
    print(f"; uses_in={meta['uses_in']} switches={meta['switches']:#04x} "
          f"jump_targets={meta['jump_targets']}")
