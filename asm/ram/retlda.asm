; retlda.asm -- RET fetched from RAM straight after LDA from RAM data (ends T3 = 0011).
; 2026-09-29: RETURNS (5/5, retlda 40/40) with the T-state-0 write gate in copper
;   (U62 g4 + U56 3->4, .git/sdd/RAM_RET_FETCH.md). The results below are PRE-GATE.
;   load+run: python3 docs/notes/dinoload.py asm/ram/retlda.asm --go
;   check:    python3 docs/notes/test_ramret.py
;
; 2026-09-28, rule-B batch. Rule B: a RAM-fetched RET halts when the END
; before it clears T through 2+ changing bits. 0011 has 2 set bit(s), so B
; PREDICTS: HALT. Written and predicted before the run.

          .org  0x8100

          LDA   0x8200
          RET
