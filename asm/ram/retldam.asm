; retldam.asm -- RET fetched from RAM straight after LDAM (memory-indirect) (ends T9 = 1001).
;   load+run: python3 docs/notes/dinoload.py asm/ram/retldam.asm --go
;   check:    python3 docs/notes/test_ramret.py
;
; 2026-09-28, rule-B batch. Rule B: a RAM-fetched RET halts when the END
; before it clears T through 2+ changing bits. 1001 has 2 set bit(s), so B
; PREDICTS: HALT. Written and predicted before the run.

          .org  0x8100

          LDAM  0x8200
          RET
