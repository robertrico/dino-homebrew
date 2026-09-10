; step2pop.asm -- execute-from-RAM staircase, step 2 split: the two pops, without RET
;   load+run: make go-step2pop      then read OB.   OB = 0x01 passes (0xB3 shows first).
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. Step 2 (LDAI; OUT; RET from RAM) OUTs 0x22 and never comes
; home. RET is 13 rows: two pops through SP, the MDR park and replay,
; PC_LOAD, two PC_UPs. This does RET's stack reads as POPA, from RAM code,
; and shows each popped byte. The frame CALL go left is 01 B3, so OB
; reads B3 then 01, then HALT. Anything else names the pop path: SP_UP,
; SP -> MAR, a RAM read into a register.

          .org  0x8100
          POPA
          OUT
          POPA
          OUT
          HALT
