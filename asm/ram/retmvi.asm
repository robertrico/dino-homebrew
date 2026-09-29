; retmvi.asm -- RET fetched from RAM straight after MVI, which ends at T5.
;   load+run: python3 docs/notes/dinoload.py asm/ram/retmvi.asm --go
;   check:    python3 docs/notes/test_ramret.py
;
; 2026-09-28. Rule B (test_ramret.py): a RAM-fetched RET halts when the END
; before it clears T through 2+ changing bits. It was FITTED to T3 (0011)
; and T13 (1101) halting and T1/T2 returning; rethlsp killed rule A. MVI
; ends at T5 = 0101 -- two bits -- and was never implicated, so this is B's
; first real PREDICTION: it says HALT. A prompt back means B is wrong too.
; Writes 0x77 to 0x8200 (off the monitor's 0x80E0-0x80FF).
;
; RESULT 2026-09-28, 1.024 MHz: HALTED (~RD flat, T0 frozen high), as B
; predicted before the run.

          .org  0x8100

          MVI   0x8200, 0x77
          RET
