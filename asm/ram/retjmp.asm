; retjmp.asm -- RET fetched from RAM straight after a JMP to the next byte (ends T3 = 0011).
;   load+run: python3 docs/notes/dinoload.py asm/ram/retjmp.asm --go
;   check:    python3 docs/notes/test_ramret.py
;
; 2026-09-28, rule-B batch. Rule B: a RAM-fetched RET halts when the END
; before it clears T through 2+ changing bits. 0011 has 2 set bit(s), so B
; PREDICTS: HALT. Written and predicted before the run.
;
; RESULT 2026-09-28, 1.024 MHz, 22 pF in: RETURNED x2 -- rule B predicted HALT: B is FALSIFIED.

          .org  0x8100

          JMP   next
next:     RET
