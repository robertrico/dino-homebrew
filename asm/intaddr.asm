; intaddr.asm -- INT ladder I4. Is the pushed return address the next
; OPCODE, never an operand byte?
;
;   build:  make assemble-intaddr
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware + the burn
;
; SOURCE: the 16550 THRE interrupt (IER bit 1), armed by the image
; itself -- no button, no 555 (Rico 2026-09-27). INTR goes high when the
; XMIT FIFO is empty and IER1 is set; writing THR or clearing IER drops
; it. FACT, datasheet 8.4 / 8.11 / TABLE I. INTR reaches ~{IRQ} through
; the open-collector inverter on dino_serial.
;
; Four bytes go into the XMIT FIFO BEFORE IER is set, so THRE cannot fire
; until the FIFO drains ~3 ms later -- well inside the loop at 0x0140,
; which mixes 1-, 2- and 3-byte instructions. The UART's crystal is not
; the CPU's, so where in the loop it lands varies run to run. The handler
; reads the pushed LO byte back by ABSOLUTE address (the PROG_calladdr
; shape) and HALTs, so the reading sticks.
;
;     OB     meaning
;     0x40 0x42 0x43 0x45        PASS -- an opcode address in the loop
;     0x41 0x44 0x46 0x47        FAIL -- an OPERAND byte: PC_UP was not
;                                inhibited at the injected T0 (C4)
;     0xFF, "...." on terminal   no interrupt taken: INTR, OC inverter, EI
;     anything else              the push or the absolute read
;
; RESET several times: all four PASS values should turn up. One value
; every time means the accept is not landing where it looks.

SER_THR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
VEC:      .equ  0x9090
STACK:    .equ  0x80FF
PUSHED_LO: .equ 0x80FE          ; INT pushes HI at 0x80FF, then LO

          .org  0x0000
          LDAI  0xFF            ; poison
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

          LDAI  0x2E            ; '....' fill the FIFO first ...
          STA   SER_THR
          STA   SER_THR
          STA   SER_THR
          STA   SER_THR
          LDAI  0x02            ; ... THEN enable THRE: it is clear now
          STA   SER_IER
          EI
          JMP   loop

          .org  0x0140
loop:     LDAI  0x11            ; 0x40 opcode, 0x41 operand
          NOP                   ; 0x42
          LDBI  0x22            ; 0x43 opcode, 0x44 operand
          JMP   loop            ; 0x45 opcode, 0x46 0x47 operands

handler:  LDA   PUSHED_LO
          OUT
          HALT
