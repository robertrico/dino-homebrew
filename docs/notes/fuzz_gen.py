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
  - IN IS GONE from the menu (phase F burn, 2026-08-27): it left the
    ISA, and SW1 is read with LDA now because card zero makes it
    memory. `meta["switches"]` survives — it is the seed-derived
    DIP-switch value the differential harness drives, still a
    `rng.randrange(256)` draw taken AFTER every program-shaping
    decision (body, jump targets) is finished, so it never perturbs
    the program itself and is fully reproducible from the seed alone.
  - JNC joins JNZ in the jump menu, with a STRICTER fixup rule. Z comes
    off the F0-7 NOR tree and is meaningful for every '382 function
    code, so any ALU op is a legitimate producer for JNZ. CN+4 is only
    meaningful for the three ARITHMETIC codes, so JNC needs ADD, SUB or
    BSUB before it and `simulate()` raises rather than inventing a
    carry after AND/OR/XOR/CLR/SET.

`gen(seed, main_len=24, limit=None)` -> `(program, meta)`. `program` is
a list of `progrom_gen` tuple-form steps, ready for
`progrom_gen.assemble()` / `progrom_gen.build_image()`. `meta` is a
dict with `text` (address-annotated listing), `jump_targets` (list of
`(src_addr, dst_addr)` byte pairs, one per JMP/JNZ/JNC), and
`switches` (int 0-255, the seed-derived DIP-switch value the
differential harness drives). `limit`
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
# IN LEFT THE ISA on 2026-08-27 (phase F burn). OUT is the whole I/O menu
# now -- SW1 is memory, at card zero's 0x4000-0x47FF, and it is read with
# LDA like any other address.
IO_OPS = ["OUT"]
JUMP_OPS = ["JMP", "JNZ", "JNC"]
FLAG_FIXUP_OPS = ["ADD", "SUB"]          # what gets inserted before a bare branch
# JNC IS FUSSIER THAN JNZ AND THE DIFFERENCE IS NOT COSMETIC. Z comes off the
# F0-7 NOR tree and is meaningful for every '382 function code; CN+4 is only
# meaningful for the three ARITHMETIC codes. So an AND before a JNZ is a
# legitimate flag producer and an AND before a JNC is not -- simulate() raises
# on it rather than inventing a carry. The fixup rule has to know that.
CARRY_OPS = ["ADD", "SUB", "BSUB"]

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
        producers = {"JNZ": ALU_OPS, "JNC": CARRY_OPS}.get(name)
        if producers is not None and last_name not in producers:
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
        # A JUMP MAY NOT LAND ON A BRANCH. The generator pairs each branch
        # with a flag producer immediately before it, and a jump into the
        # branch itself SKIPS THE PRODUCER -- which for JNC means arriving at
        # a carry no arithmetic op defined, and simulate() rightly refuses
        # it. Found by seed sweep the day JNC joined the menu; the static
        # "preceded by" rule alone is not enough once control flow can
        # arrive from elsewhere.
        future = [a for a, entry in zip(addrs[i + 1:], body[i + 1:])
                  if entry.name not in JUMP_OPS or entry.name == "JMP"]
        tgt = rng.choice(future) if future else addrs[-1]
        e.operand = (tgt & 0xFF, tgt >> 8)
        jump_targets.append((addrs[i], tgt))

    program = []
    text = []
    for e, ad in zip(body, addrs):
        step = (e.name,) if e.operand is None else (e.name, *e.operand)
        program.append(step)
        operand_s = "" if e.operand is None else " " + ",".join(
            f"{b:#04x}" for b in e.operand)
        text.append(f"{ad:#06x}: {e.name}{operand_s}")

    switches = rng.randrange(256)
    meta = {"text": text, "jump_targets": jump_targets,
            "switches": switches}
    return program, meta


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    prog, meta = gen(seed)
    print("\n".join(meta["text"]))
    print(f"; switches={meta['switches']:#04x} "
          f"jump_targets={meta['jump_targets']}")
