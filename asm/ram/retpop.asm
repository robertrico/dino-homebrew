; retpop.asm -- RET fetched from RAM straight after POPA (after a balancing PUSHA) (ends T4 = 0100).
;   load+run: python3 docs/notes/dinoload.py asm/ram/retpop.asm --go
;   check:    python3 docs/notes/test_ramret.py
;
; 2026-09-28, rule-B batch. Rule B: a RAM-fetched RET halts when the END
; before it clears T through 2+ changing bits. 0100 has 1 set bit(s), so B
; PREDICTS: RETURN. Written and predicted before the run.
;
; RESULT 2026-09-28, 1.024 MHz, 22 pF in: RETURNED, as rule B predicted.

          .org  0x8100

          PUSHA
          POPA
          RET
