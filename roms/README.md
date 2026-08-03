# roms/ — what is physically in the sockets

These binaries are TRACKED ON PURPOSE. They were silently untracked in the
old `hardware` repo, swallowed by a bare `*.bin` rule inherited from the
MCU firmware projects. Do not reintroduce that rule — see `.gitignore`.

They are regenerable, but regenerable is not recorded. "What was burned on
2026-07-26" should be a `git show`, not "check out an old commit and re-run
the generator and hope OPCODES has not moved."

## The images

    U9.bin  U15.bin              microcode, REAL pair. CURRENTLY SEATED.
                                 CRC U9=0xAD70  U15=0xF49F
                                 U15 CHANGED 2026-08-02: the SA field is now
                                 packed BIT-REVERSED into CW9..CW11, because
                                 CW9 is labelled SA2 and wired to the '382's
                                 select MSB. The old image delivered ADD (011)
                                 as AND (110) — the bench measured 5 AND 3 = 1,
                                 0x39 AND 0 = 0 and 0 AND 0x39 = 0 across three
                                 images. U9 is UNCHANGED (CW0-7 do not carry
                                 SA), so only U15 needs reburning.
    U9_diag.bin  U15_diag.bin    microcode, DIAG pair (address self-proof)
                                 CRC U9=0x0F69  U15=0xF1B9
    PROG.bin                     program ROM, THE MILESTONE PROGRAM
                                 LDAI 0xFF; OUT      <- poisons OB first
                                 LDAI 0x2F; LDBI 0x1E; ADD; OUT; HALT
                                 safe-filled with HALT (0xFF)
                                 CRC 0x8577
                                 ADDENDS CHANGED 2026-08-02, was 5+3=8. One
                                 bit set, low nibble, one carry — blind to a
                                 stuck or swapped bit in the upper nibble.
                                 0x2F+0x1E=0x4D puts bits in both nibbles of
                                 both addends and the answer, and ripples the
                                 carry from bit 1 to bit 6, crossing bit 3->4
                                 where the two '382s hand over. Reburn PROG.bin.
    PROG_diag.bin                program ROM, DIAG (self-naming addresses)
                                 CRC 0xDFE7

### Progressive ISA-coverage images

The block ladder proves the machine EXECUTES. These prove it executes the
WHOLE of the current ISA. Each ends OUT; HALT because OB is the only
datapath observable on the ladder, and every answer is a MIRROR-WITNESS —
its bit-reversed read is a different byte, so a flipped OB ribbon names
itself. Burn as needed; none of them is required for the milestone.

    PROG_flow.bin                JMP over a poison HALT, then a JNZ that
                                 must NOT be taken. CRC 0xCED0, OB 0x39
                                 EARLIEST: block 3 (witnessed on the IRB
                                 opcode stream, not OB)
    PROG_alu.bin                 all eight SA codes chained, so a wrong
                                 code corrupts the signature rather than
                                 being masked. CRC 0x642A, OB 0x39
                                 EARLIEST: block 4
    PROG_mem.bin                 STA then LDA back through RAM. ALSO THE
                                 MAR-AS-LATCH WITNESS — LDA/STA are the
                                 only MAR loaders and the milestone has
                                 none. CRC 0x3E4B, OB 0xC5
                                 EARLIEST: block 4
    PROG_loop.bin                the JNZ TAKEN arm, iterated exactly 3
                                 times; a wrong count changes the answer.
                                 CRC 0x8727, OB 0x15
                                 EARLIEST: block 4

NOTE for blocks 1-3: FLAG_Z is STRAPPED HIGH, so COND_TAKEN is pinned low
and JNZ is NEVER taken there. PROG_flow exercises JMP and the not-taken
arm only; the taken arm needs a real ALU flag, hence block 4.

Expected OB values are NOT hand-computed. `progrom_gen.simulate()`
interprets the burned microcode rows, so image and hardware cannot
disagree — the same discipline cw_expect holds on the rig side.

Microcode CRCs are over the 4096 ADDRESSABLE bytes per chip — A12 is
grounded, so the 8K file is the image mirrored twice.

## Regenerating

    python3 docs/notes/microcode_gen.py
    python3 docs/notes/progrom_gen.py

Verified byte-identical on 2026-07-28: the tracked generators reproduce
these exact files. If a regeneration ever changes a byte, the CRCs in
`tests/dino_bringup/src/microcode_expect.h` and `progrom_expect.h` change
with it, and the rig's `microcode.crc` / `memory.romcrc` tests will say so
on the bench. That is the intended failure path.

## Burning

    make -C tests/dino_bringup burn-prog-diag
    make -C tests/dino_bringup burn-prog

TL866, and Rico does the burning. The rig verifies, never programs.

## Deferred hardening

`progrom_gen.py`'s `DIAG_ZERO = 0xA5` is bit-reverse-invariant, which makes
the diag image's byte 0 mirror-blind. Change it to a non-palindrome the
next time the DIAG image is reburned — no reason to reburn just for this.
