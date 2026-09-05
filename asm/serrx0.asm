; serrx0.asm -- PHASE G step 8 DIAGNOSTIC. serrx with A and B ZEROED before
; the RBR read. One-line difference; everything else byte-identical.
;
; The fault (2026-09-04): after POWER-UP only, every received byte comes
; back | 0x20, sometimes | 0x40. RESET clears it. 0x20 is exactly what B
; (the THRE mask) and A (the AND result) hold at the RBR read, and A+B =
; 0x40. If REG_B, the ALU output or stale A leaks onto the bus during the
; read, that is the OR. This image makes every one of those 0x00.
;
;   capitals right, [ -> 0x5B   DINO-side leak from A/B/ALU. Bisect next.
;   still | 0x20                not A/B/ALU. The UART, SIN, or the read.
;
; Boot it cold. Do NOT press RESET: RESET is the state where it works.

SER_THR:  .equ  0x4800
SER_RBR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
SER_LSR:  .equ  0x4805

          .org  0x0000

          LDAI  0xFF          ; poison
          OUT

; ---- init, MCR = 0
          LDAI  0x83
          STA   SER_LCR
          LDAI  0x18
          STA   SER_DLL
          LDAI  0x00
          STA   SER_DLM
          LDAI  0x03
          STA   SER_LCR
          LDAI  0x07
          STA   SER_FCR
          LDAI  0x00
          STA   SER_IER
          LDAI  0x00
          STA   SER_MCR

top:
; ---- wait for a received byte: DR, LSR bit 0
wait_rx:  LDA   SER_LSR
          LDBI  0x01
          AND
          JNZ   ready_rx
          JMP   wait_rx
ready_rx:
; ---- wait until the transmitter can take it: THRE, LSR bit 5
wait_echo: LDA  SER_LSR
          LDBI  0x20
          AND
          JNZ   ready_echo
          JMP   wait_echo
ready_echo:
          LDAI  0x00          ; DIAGNOSTIC: kill every DINO-side leak source
          LDBI  0x00          ;   A = B = 0, so any ALU function of them is 0
          LDA   SER_RBR       ; the ONE read. Pops the FIFO.
          OUT                 ; on the LEDs
          STA   SER_THR       ; and back to the host
          JMP   top
