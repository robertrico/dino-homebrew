; step2e.asm -- OUT->RET bus-turnaround probe, sends 0x34.
;   run: make go-step2e
; 2026-09-08. step2 (LDAI 0x22; OUT; RET) HALTs at T1 from RAM: OUT drives
; MDR from REG_A and ends in the same T-state, so REG_A still holds the bus
; when the next FETCH (fast, FETCH_RAM) latches the RET opcode. IR caught
; 0x22 AND 0x34 = 0x20 = unassigned = HALT. If the fetched opcode is
; (OUT value AND 0x34), THIS value = 0x34 gives IR = 0x34.
;   returns: 0x34 survives
; The oracle (ideal bus) RETURNS for every value; a HALT on the bench with
; some values and not others IS the bus fight, invisible to the oracle.
          .org  0x8100
          LDAI  0x34
          OUT
          RET
