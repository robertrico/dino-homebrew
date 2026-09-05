; serlive.asm -- PHASE G step 8 DIAGNOSTIC. LCR and FCR on the LEDs, LIVE.
;
; Cold-boot fault (2026-09-04): LCR reads 0x03 right after init (serlcr)
; and 0x00 by the first character (serrxlcr). Nobody can time a scope to
; that. So OB shows the register state continuously, no typing needed:
;
;     OB = (IIR & 0xC0) | LCR
;
;   0xC3   normal: FIFO enabled (IIR 7:6 = 11), LCR = 8N1
;   0x00   BOTH reverted: LCR AND FCR. That is MR's fingerprint -- the
;          divisor survives MR, which is why baud stays right.
;   0xC0   LCR reverted, FIFO still on: something WROTE LCR. Not MR.
;   0x03   FIFO off, LCR fine: FCR alone. Would be new.
;
; Watch OB from power-up: it should sit at 0xC3. If it drops to 0x00 with
; NO serial traffic, the poll loop or plain time does it. If it stays 0xC3
; until a byte is sent, traffic does it. Press RESET: must return to 0xC3.
;
; No RBR is ever read, so nothing here depends on receiving. If the fault
; needs a received character to trigger, send one with the host probe:
;     python3 docs/notes/serprobe_host.py 55

SER_IIR:  .equ  0x4802
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


live:     LDA   SER_IIR       ; bits 7:6 = 11 iff FCR0 = 1 (datasheet 8.6)
          LDBI  0xC0
          AND                 ; A = IIR & 0xC0
          LDB   SER_LCR       ; B = LCR
          OR                  ; A = (IIR & 0xC0) | LCR
          OUT
          JMP   live
