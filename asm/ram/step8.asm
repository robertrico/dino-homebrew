; step8.asm -- execute-from-RAM staircase, step 8: a counted JNZ loop from RAM
;   load+run: make go-step8      then read OB.   OB = 0x88 passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. ramexec proved LDBI/SUB/OUT/HALT from RAM and nothing else;
; every RAM program since did five firsts at once and froze. One first per
; step. OB stuck at FF (the monitor's poison) with the machine frozen means
; THIS step's first is the one that fails.
; FIRST-OF-ITS-KIND: a loop: 16 taken JNZ branches from RAM with a RAM counter and a
; RAM accumulator. 0x88 = 16 x 0x08 + 0x08. Anything else names a
; miscount.

CNT:      .equ  0x8200
ACC:      .equ  0x8201
          .org  0x8100
          LDAI  16
          STA   CNT
          LDAI  0x08
          STA   ACC
loop:     LDA   ACC
          ADI   0x08
          STA   ACC
          LDA   CNT
          DCR
          STA   CNT
          JNZ   loop
          LDA   ACC
          OUT
          RET
