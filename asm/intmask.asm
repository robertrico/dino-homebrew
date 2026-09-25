; intmask.asm -- INT ladder I2. With IE never set, ~{IRQ} does NOTHING.
;
;   build:  make assemble-intmask
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware + the interrupt microcode burn
;
; A handler is planted at the vector 0x9090 (JMP handler) exactly as a real
; program would, and then EI is never executed. Press the ~{IRQ} button as
; often as you like.
;
;     OB     meaning
;     0xFF   never reached the loop (poison)
;     0x39   PASS -- stays 0x39 whatever the button does
;     0xE7   FAIL -- the handler ran with IE clear, and it HALTs so the
;            reading STICKS. ACCEPT is ignoring IE, or IE powers up set.
;
; The E7 case cannot be missed: an unwatched press that ran the handler
; leaves the machine halted on 0xE7, not flickering back to 0x39.

VEC:      .equ  0x9090
STACK:    .equ  0x80FF

          .org  0x0000
          LDAI  0xFF            ; poison: U35 has no reset
          OUT
          LXISP STACK
          MVI   VEC, 0x31       ; JMP
          MVI   VEC+1, <handler
          MVI   VEC+2, >handler

loop:     LDAI  0x39
          OUT
          JMP   loop

handler:  LDAI  0xE7
          OUT
          HALT
