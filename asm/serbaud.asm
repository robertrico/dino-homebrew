; serbaud.asm -- PHASE G step 5. The divisor dance, then stop.
;
; No OB witness. Scope U103.15 (~BAUDOUT): 153.6 kHz = 3686400 / 24.
; 76.8 kHz means DLL took 0x30 (one-bit shift); 600 Hz means DLM took the
; byte meant for DLL; nothing means DLAB never banked the latches (GOTCHA 1).
;
; LCR bit 7 is DLAB. While set, base+0 is DLL and base+1 is DLM.

SER_DLL:  .equ  0x4800        ; base+0 while DLAB = 1
SER_DLM:  .equ  0x4801        ; base+1 while DLAB = 1
SER_LCR:  .equ  0x4803

          .org  0x0000

          LDAI  0xFF          ; poison
          OUT
          LDAI  0x83          ; DLAB | 8 data | 1 stop | no parity
          STA   SER_LCR
          LDAI  0x18          ; divisor = 24 -> 9600 at 3.6864 MHz
          STA   SER_DLL
          LDAI  0x00
          STA   SER_DLM
          LDAI  0x03          ; 8N1, DLAB clear. EVERY routine that sets DLAB
          STA   SER_LCR       ; clears it before it returns.
          HALT
