; inthalt.asm -- INT ladder I7. EI; HALT is a WAIT. One press wakes it.
;
;   build:  make assemble-inthalt
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware (including the HALT-wake ~MR term) + the burn
;
;     OB     meaning
;     0xFF   PASS so far -- halted, waiting. Press ~{IRQ}.
;     0x5A   PASS -- woke, the handler ran, IRET landed on the byte after
;            the HALT, and the machine is halted again with IE off.
;     0xE7   the handler ran and IRET never landed (IRET, or the pushed PC)
;     0xFF   after a press: no wake. The ~MR term (T never cleared out of
;            the HALT row) or HALT's CET.
;
; Holding the button re-enters the handler until DI; that is fine, DI then
; HALT leaves 0x5A on OB and nothing can wake it.

VEC:      .equ  0x9090
STACK:    .equ  0x80FF

          .org  0x0000
          LDAI  0xFF            ; poison
          OUT
          LXISP STACK
          MVI   VEC, 0x31       ; JMP
          MVI   VEC+1, <handler
          MVI   VEC+2, >handler

          EI
          HALT                  ; sleep until ~{IRQ}
after:    LDAI  0x5A
          OUT
          DI
          HALT                  ; IE off: this one is final

handler:  PUSHA
          LDAI  0xE7
          OUT
          POPA
          IRET
