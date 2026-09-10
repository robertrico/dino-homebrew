; step6.asm -- execute-from-RAM staircase, step 6: LDAX from RAM code
;   load+run: make go-step6      then read OB.   OB = 0x66 passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. ramexec proved LDBI/SUB/OUT/HALT from RAM and nothing else;
; every RAM program since did five firsts at once and froze. One first per
; step. OB stuck at FF (the monitor's poison) with the machine frozen means
; THIS step's first is the one that fails.
; FIRST-OF-ITS-KIND: a pointer read through B:C issued by RAM-resident code, of a byte
; in the same RAM.

          .org  0x8100
          LDBI  >tbl
          LDCI  <tbl
          LDAX
          OUT
          RET
tbl:      .db   0x66
