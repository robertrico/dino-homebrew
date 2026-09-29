; inthalt.asm -- INT ladder I7. EI; HALT is a WAIT. The UART wakes it.
;
;   build:  make assemble-inthalt
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware (including the HALT-wake ~MR term) + the burn
;
; SOURCE: the 16550 THRE interrupt (IER bit 1), armed by the image
; itself -- no button, no 555 (Rico 2026-09-27). INTR goes high when the
; XMIT FIFO is empty and IER1 is set; writing THR or clearing IER drops
; it. FACT, datasheet 8.4 / 8.11 / TABLE I. INTR reaches ~{IRQ} through
; the open-collector inverter on dino_serial.
;
; "DINO" goes into the XMIT FIFO BEFORE IER is set, so THRE is clear when
; the interrupt is enabled and cannot fire until the FIFO drains, ~3 ms
; later -- thousands of clocks after the HALT. The handler clears IER.
;
;     OB / terminal    meaning
;     0x5A, "DINO"     PASS -- woke from HALT, the handler ran, IRET landed
;                      on the byte after the HALT, halted again, IE off
;     0x3C             woke with NO interrupt taken: T cleared out of the
;                      HALT row on its own -- a runt on U61.3 (PHASE_INT O6)
;     0xFF, "DINO"     never woke: the ~MR term (T never cleared out of
;                      the HALT row), HALT's CET, INTR or the OC inverter
;     0xE7             the handler ran and IRET never landed -- OR the
;                      interrupt came BEFORE the HALT, IRET returned to
;                      it, and nothing is left to wake it
;     0xFF, no text    the UART init; run serid/sertx first
;
; 0x5A cannot be forged: the handler plants SEEN, and "after" reads it. A
; wake that took no interrupt reaches "after" with SEEN still 0x00.

SER_THR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
VEC:      .equ  0x9090
STACK:    .equ  0x80FF
SEEN:     .equ  0x8100

          .org  0x0000
          LDAI  0xFF            ; poison
          OUT
          LXISP STACK
          MVI   VEC, 0x31       ; JMP
          MVI   VEC+1, <handler
          MVI   VEC+2, >handler
          MVI   SEEN, 0x00

; ---- UART init, 9600 8N1, FIFOs on, all interrupts off (as intser)
          LDAI  0x00
          STA   SER_IER
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
          STA   SER_MCR

          LDAI  0x44            ; 'D'  fill the FIFO first ...
          STA   SER_THR
          LDAI  0x49            ; 'I'
          STA   SER_THR
          LDAI  0x4E            ; 'N'
          STA   SER_THR
          LDAI  0x4F            ; 'O'
          STA   SER_THR
          LDAI  0x02            ; ... THEN enable THRE: it is clear now
          STA   SER_IER

          EI
          HALT                  ; sleep until the FIFO drains
after:    DI                    ; IE off: the HALTs below are final
          LDA   SEEN
          CPI   0x01
          JNZ   bare
          LDAI  0x5A
          OUT
          HALT
bare:     LDAI  0x3C            ; woke, but no handler ran
          OUT
          HALT

handler:  PUSHA
          LDAI  0x00            ; clear the source: INTR drops
          STA   SER_IER
          MVI   SEEN, 0x01
          LDAI  0xE7
          OUT
          POPA
          IRET
