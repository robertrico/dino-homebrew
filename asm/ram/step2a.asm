; step2a.asm -- execute-from-RAM staircase, step 2 split: LDAI between OUT and RET
;   load+run: make go-step2a      then read OB. OB = 0x22 and the prompt back passes.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. step2 (LDAI; OUT; RET from RAM) halts: HALT high at T1, so
; the fetch after OUT decoded as a one-row HALT, not as RET. Every RET
; from RAM that failed today had OUT right before it. One instruction between them. Returns = 'RET straight after OUT'
; is the failing pair. Halts = RET from RAM fails regardless.

          .org  0x8100
          LDAI  0x22
          OUT
          LDAI  0x22
          RET
