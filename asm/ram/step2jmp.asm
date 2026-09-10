; step2jmp.asm -- execute-from-RAM staircase, step 2 split: back to the monitor by JMP, no stack
;   load+run: make go-step2jmp      then read OB.   OB = 0x2D and the prompt back passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. Step 2 (LDAI; OUT; RET from RAM) OUTs 0x22 and never comes
; home. RET is 13 rows: two pops through SP, the MDR park and replay,
; PC_LOAD, two PC_UPs. JMP from RAM straight to the monitor's new_line (0x0034, `make
; listing-monitor`). No pop, no park, no PC_UP: just the fetch moving
; from RAM to ROM. The CALL-go frame stays on the stack; harmless.

NEW_LINE: .equ  0x0034          ; monitor.asm new_line
          .org  0x8100
          LDAI  0x2D
          OUT
          JMP   NEW_LINE
