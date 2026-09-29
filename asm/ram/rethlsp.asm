; rethlsp.asm -- RET fetched from RAM straight after an instruction ending at T2.
;   load+run: python3 docs/notes/dinoload.py asm/ram/rethlsp.asm --go
;   check:    python3 docs/notes/test_ramret.py
;
; 2026-09-28. A RET fetched from RAM halts on silicon after OUT (ends T3 on
; the burned U15 0x45F9) and after a ROM RET (ends T13); it returns after
; NOP and LDAI (end T1). Two rules fit all nine bench results:
;   A  the instruction before ends at T >= 2           -> this HALTS
;   B  its END clears T through 2+ changing bits       -> this RETURNS
;      (T3 = 0011, T13 = 1101; T1 = 0001 and T2 = 0010 flip one)
; HLSP (SP -> H:L, two rows, reads SP and never moves it) is the only
; T2-ender that leaves the stack alone, so this is the one image that splits
; A from B. Pass/fail is the monitor's prompt: back = B, frozen = A.
;
; RESULT 2026-09-28, 1.024 MHz: RETURNED to the prompt. Rule A is
; falsified; rule B stands (test_ramret.py).

          .org  0x8100

          HLSP
          RET
