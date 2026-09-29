; intmask.asm -- INT ladder I2. With IE never set, ~{IRQ} does NOTHING.
;
;   build:  make assemble-intmask
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware + the interrupt microcode burn
;
; SOURCE: the 16550 THRE interrupt (IER bit 1), armed by the image
; itself -- no button, no 555 (Rico 2026-09-27). INTR goes high when the
; XMIT FIFO is empty and IER1 is set; writing THR or clearing IER drops
; it. FACT, datasheet 8.4 / 8.11 / TABLE I. INTR reaches ~{IRQ} through
; the open-collector inverter on dino_serial.
;
; IER=THRE, then one byte into THR: INTR rises about one character later
; and nothing ever clears it, so ~{IRQ} is held low for the whole loop.
; A handler is planted at the vector 0x9090 exactly as a real program
; would, and EI is never executed.
;
;     OB     meaning
;     0xFF   never reached the loop (poison)
;     0x39   PASS -- stays 0x39 with ~{IRQ} held low. Terminal shows "."
;     0xE7   FAIL -- the handler ran with IE clear, and it HALTs so the
;            reading STICKS. ACCEPT is ignoring IE, or IE powers up set.
;
; The E7 case cannot be missed: the request is a level that never goes
; away, so a broken mask halts on 0xE7 within microseconds of arming.

SER_THR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
VEC:      .equ  0x9090
STACK:    .equ  0x80FF

          .org  0x0000
          LDAI  0xFF            ; poison: U35 has no reset
          OUT
          LXISP STACK
          MVI   VEC, 0x31       ; JMP
          MVI   VEC+1, <handler
          MVI   VEC+2, >handler

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

          LDAI  0x02            ; IER: THRE interrupt
          STA   SER_IER
          LDAI  0x2E            ; '.' -- FIFO empties ~1 char later: INTR
          STA   SER_THR

loop:     LDAI  0x39
          OUT
          JMP   loop

handler:  LDAI  0xE7
          OUT
          HALT
