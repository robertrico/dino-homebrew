; step2g.asm -- OUT->RET with a NOP between. THE FIX PROOF.
;   run: make go-step2g
; 2026-09-08. OUT immediately before RET from RAM latches HALT, data-
; independent (step2/2c/2e/2f, four OUT values, all halt). OUT->JMP and
; OUT->LDAI are fine. OUT is one row: it drives MDR from REG_A and strobes
; REG_OUT_LOAD in the SAME T-state it ends, so the next fetch (fast,
; FETCH_RAM) begins before the bus and the OB strobe have settled, and the
; transparent IR passes a glitch that U61 latches as HALT.
; NOP between OUT and RET gives the boundary one settle T-state. If this
; RETURNS while step2 halts, the fix is a settle row on OUT (src=NONE,
; carry END), reburn U9/U15. NOP has never executed on silicon; this
; retires that too.
;   OB = 0x22 and the prompt back = fix proven.
          .org  0x8100
          LDAI  0x22
          OUT
          NOP
          RET
