; callret.asm -- CALL into ROM from RAM, return, then RET to the monitor.
;   load+run: python3 docs/notes/dinoload.py asm/ram/callret.asm --go
;
; 2026-09-28: step2g (LDAI; OUT; NOP; RET) returns to the prompt;
; retcrlf (LDAI; OUT; CALL CRLF; RET) and bigxfer (... CALL CRLF; RET) HALT
; after the CRLF prints. This drops everything but the CALL/RET pair, and
; no OUT anywhere, so the known OUT-before-RAM-fetch hazard cannot apply.
; Pass = a blank line (CRLF) and the monitor's prompt back.

CRLF:     .equ  0x036B          ; monitor.asm, `make listing-monitor`

          .org  0x8100

          CALL  CRLF
          RET
