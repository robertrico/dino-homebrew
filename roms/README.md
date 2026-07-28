# roms/ — what is physically in the sockets

These binaries are TRACKED ON PURPOSE. They were silently untracked in the
old `hardware` repo, swallowed by a bare `*.bin` rule inherited from the
MCU firmware projects. Do not reintroduce that rule — see `.gitignore`.

They are regenerable, but regenerable is not recorded. "What was burned on
2026-07-26" should be a `git show`, not "check out an old commit and re-run
the generator and hope OPCODES has not moved."

## The images

    U9.bin  U15.bin              microcode, REAL pair. CURRENTLY SEATED.
                                 CRC U9=0xAD70  U15=0x58D7
    U9_diag.bin  U15_diag.bin    microcode, DIAG pair (address self-proof)
                                 CRC U9=0x0F69  U15=0xF1B9
    PROG.bin                     program ROM, THE MILESTONE PROGRAM
                                 LDAI 5; LDBI 3; ADD; OUT; HALT
                                 safe-filled with HALT (0xFF)
                                 CRC 0xF501
    PROG_diag.bin                program ROM, DIAG (self-naming addresses)
                                 CRC 0xDFE7

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
