; step2ram.asm -- execute-from-RAM staircase, step 2 split: RET from RAM into RAM
;   load+run: make go-step2ram      then read OB.   OB = 0x2A passes; 0x2B and frozen = the RET did not return.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. Step 2 (LDAI; OUT; RET from RAM) OUTs 0x22 and never comes
; home. RET is 13 rows: two pops through SP, the MDR park and replay,
; PC_LOAD, two PC_UPs. A CALL to a RAM subroutine and a RET back into RAM: every RET row
; runs, fetched from RAM, but the landing is RAM, not ROM. Splits 'RET
; from RAM' from 'RET from RAM to ROM'.

          .org  0x8100
          CALL  sub
          LDAI  0x2A
          OUT
          HALT
sub:      LDAI  0x2B
          OUT
          RET
