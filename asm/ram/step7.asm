; step7.asm -- execute-from-RAM staircase, step 7: MVI from RAM
;   load+run: make go-step7      then read OB.   OB = 0x77 passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. ramexec proved LDBI/SUB/OUT/HALT from RAM and nothing else;
; every RAM program since did five firsts at once and froze. One first per
; step. OB stuck at FF (the monitor's poison) with the machine frozen means
; THIS step's first is the one that fails.
; FIRST-OF-ITS-KIND: MVI fetched from RAM: a PC-fetched byte parked in MDR and replayed
; into RAM. The park's settle row was timed against the ROM's access;
; from RAM the same fetch is FETCH_RAM and faster.

          .org  0x8100
          MVI   0x8200, 0x77
          CLR
          LDA   0x8200
          OUT
          RET
