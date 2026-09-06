; test4.asm -- the monitor's puts read path, without the UART. One byte, OB.
;
;   build:  make assemble-test4
;   check:  python3 docs/notes/asm.py asm/test4.asm --run    -> OB = 0x5A
;   burn:   make burn-prog-test4
;
; 2026-09-05. PROG_monitor prints its banner on power-up and prints RAM after
; RESET. PROG_serrx is clean both ways, and wander slot 9 (LDAX with B:C from
; immediates) is clean both ways. What the monitor does that neither does:
; it keeps the string pointer in RAM (MVI), reads it back into B and C (LDB,
; LDC), and LDAXes through it. This is that, and nothing else.
;
;   0x5A   the byte planted in ROM came back. The path is clean.
;   0xA5   never got past the poison: something before OUT went off the rails.
;   0xFF   OUT ran and the read returned fill or the bus park: the pointer
;          landed in unprogrammed ROM, or nothing drove the bus.
;   other  RAM content: the pointer's high byte grew bit 7. Compare BOOT/RESET.
;
; First burn of this image had poison 0xFF and read 0xFF boot and RESET, which
; could not say which of the two middle rows it was. Hence 0xA5.
;
; The cells are the monitor's own (0x80E0 page), the string is where the
; monitor's is (0x02xx), so every address bit that matters there matters here.

PTRL:     .equ  0x80E2
PTRH:     .equ  0x80E3

          .org  0x0000

          LDAI  0xA5              ; poison OB. NOT 0xFF: fill and park are 0xFF,
          OUT                     ; and a read of them must not look like "never ran"

          MVI   PTRL, <byte
          MVI   PTRH, >byte
          LDB   PTRH
          LDC   PTRL
          LDAX
          OUT
          HALT

          .org  0x029E            ; where the monitor's banner lives
byte:     .db   0x5A
