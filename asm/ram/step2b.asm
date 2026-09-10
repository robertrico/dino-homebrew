; step2b.asm -- execute-from-RAM staircase, step 2 split: RET with no OUT at all
;   load+run: make go-step2b      The prompt back passes; no OB.
;   check:    python3 docs/notes/test_ramsteps.py
; 2026-09-08. step2 (LDAI; OUT; RET from RAM) halts: HALT high at T1, so
; the fetch after OUT decoded as a one-row HALT, not as RET. Every RET
; from RAM that failed today had OUT right before it. No OUT anywhere. The prompt is the only witness. Returns = OUT is
; the trigger. Halts = the RET byte fetched from RAM is the trigger.

          .org  0x8100
          LDAI  0x22
          RET
