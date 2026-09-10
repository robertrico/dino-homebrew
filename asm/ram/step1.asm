; step1.asm -- execute-from-RAM staircase, step 1: G into RAM, fetch, OUT, HALT
;   load+run: make go-step1      then read OB.   OB = 0x11 passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. ramexec proved LDBI/SUB/OUT/HALT from RAM and nothing else;
; every RAM program since did five firsts at once and froze. One first per
; step. OB stuck at FF (the monitor's poison) with the machine frozen means
; THIS step's first is the one that fails.
; FIRST-OF-ITS-KIND: JMPX from the monitor into RAM; instruction fetch from RAM with a
; proper HALT at the end. RESET recovers.

          .org  0x8100
          LDAI  0x11
          OUT
          HALT
