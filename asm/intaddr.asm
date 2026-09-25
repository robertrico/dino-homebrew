; intaddr.asm -- INT ladder I4. Is the pushed return address the next
; OPCODE, never an operand byte?
;
;   build:  make assemble-intaddr
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware + the burn
;
; The main loop sits at 0x0140 and mixes 1-, 2- and 3-byte instructions.
; One press: the handler reads the pushed LO byte back by ABSOLUTE address
; (the PROG_calladdr shape) and HALTs, so the reading sticks.
;
;     OB     meaning
;     0x40 0x42 0x43 0x45        PASS -- an opcode address in the loop
;     0x41 0x44 0x46 0x47        FAIL -- an OPERAND byte: PC_UP was not
;                                inhibited at the injected T0 (C4)
;     anything else              the push or the absolute read
;
; Press several times with RESET between: all four PASS values should turn
; up. One value every time means the accept is not landing where it looks.

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
