; step5.asm -- execute-from-RAM staircase, step 5: CALL from RAM into ROM and back
;   load+run: make go-step5      then read OB.   OB = 0x55 passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. ramexec proved LDBI/SUB/OUT/HALT from RAM and nothing else;
; every RAM program since did five firsts at once and froze. One first per
; step. OB stuck at FF (the monitor's poison) with the machine frozen means
; THIS step's first is the one that fails.
; FIRST-OF-ITS-KIND: CALL from RAM into the monitor's PUTC and RET back to RAM. Prints K
; then OB 0x55, then RET to the prompt.

PUTC:     .equ  0x0345          ; monitor.asm, `make listing-monitor`
          .org  0x8100
          LDAI  'K'
          CALL  PUTC
          LDAI  0x55
          OUT
          RET
