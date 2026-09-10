; step2.asm -- execute-from-RAM staircase, step 2: RET from RAM back into ROM
;   load+run: make go-step2      then read OB.   OB = 0x22 passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. ramexec proved LDBI/SUB/OUT/HALT from RAM and nothing else;
; every RAM program since did five firsts at once and froze. One first per
; step. OB stuck at FF (the monitor's poison) with the machine frozen means
; THIS step's first is the one that fails.
; FIRST-OF-ITS-KIND: RET executed from RAM landing in the monitor's dispatcher. The
; prompt must come back. (hello.asm is this with 0x5A.)

          .org  0x8100
          LDAI  0x22
          OUT
          RET
