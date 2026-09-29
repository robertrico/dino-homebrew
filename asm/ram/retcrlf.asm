; retcrlf.asm -- bigxfer's ending, alone. RAM-resident: loaded, not burned.
; 2026-09-29: RETURNS (5/5, retlda 40/40) with the T-state-0 write gate in copper
;   (U62 g4 + U56 3->4, .git/sdd/RAM_RET_FETCH.md). The results below are PRE-GATE.
;   load+run: python3 docs/notes/dinoload.py asm/ram/retcrlf.asm --go
;
; 2026-09-28: bigxfer streams all 2233 bytes, prints S/X, then HALTs instead
; of returning to the monitor (T0 frozen, ~RD flat) -- with 22 pF on
; U103.28 (net M0, which is also ROM/RAM A0). Its last three instructions
; are PUTHEX; CALL CRLF; RET. This is that ending with nothing in front of
; it, small enough to load with or without the cap, so the two can be
; compared. Pass = OB 0x5A, a blank line, and the monitor's prompt back.

CRLF:     .equ  0x036B          ; monitor.asm, `make listing-monitor`

          .org  0x8100

          LDAI  0x5A
          OUT
          CALL  CRLF
          RET
