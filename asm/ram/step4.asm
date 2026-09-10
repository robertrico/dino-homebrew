; step4.asm -- execute-from-RAM staircase, step 4: branches from RAM
;   load+run: make go-step4      then read OB.   OB = 0x44 passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. ramexec proved LDBI/SUB/OUT/HALT from RAM and nothing else;
; every RAM program since did five firsts at once and froze. One first per
; step. OB stuck at FF (the monitor's poison) with the machine frozen means
; THIS step's first is the one that fails.
; FIRST-OF-ITS-KIND: a JMP taken and a JNZ not taken, both fetched from RAM. 0xB1 = the
; JMP fell through; 0xBB = the JNZ was taken when Z was set.

          .org  0x8100
          JMP   over
          LDAI  0xB1
          OUT
          RET
over:     LDAI  0x44
          CPI   0x44
          JNZ   bad
          OUT
          RET
bad:      LDAI  0xBB
          OUT
          RET
