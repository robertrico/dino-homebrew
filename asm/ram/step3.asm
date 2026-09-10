; step3.asm -- execute-from-RAM staircase, step 3: 3-byte STA/LDA from RAM
;   load+run: make go-step3      then read OB.   OB = 0x33 passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. ramexec proved LDBI/SUB/OUT/HALT from RAM and nothing else;
; every RAM program since did five firsts at once and froze. One first per
; step. OB stuck at FF (the monitor's poison) with the machine frozen means
; THIS step's first is the one that fails.
; FIRST-OF-ITS-KIND: a three-byte instruction fetched from RAM, a RAM data write and a
; RAM data read issued by RAM-resident code. CLR between them so the
; read must really happen.

          .org  0x8100
          LDAI  0x33
          STA   0x8200
          CLR
          LDA   0x8200
          OUT
          RET
