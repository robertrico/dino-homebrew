; intser.asm -- INT ladder I8. Serial echo with NO poll loop: the CPU
; sleeps in HALT and the 16550's INTR wakes it.
;
;   build:  make assemble-intser
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware, the burn, and dino_serial's INTR reaching
;           ~{IRQ} through an open-collector inverter (PROPOSAL_INT R9)
;
; Type a character: it lands on OB in binary AND comes back to the
; terminal. Same two observables as PROG_serrx, and the same diagnosis,
; except that nothing here ever reads LSR.
;
;     OB / terminal       meaning
;     0xFF, no echo       never woke: INTR, the OC inverter, IER, or EI
;     char, echoed        PASS
;     first char only     the handler did not clear the source (RBR read)
;                         or IRET did not re-enable
;     garble              the UART init -- run serrx first, it is the same
;
; The handler touches only A and no flags (LDA/OUT/STA), so it needs no
; PUSHF/POPF hardware.

SER_THR:  .equ  0x4800
SER_RBR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
VEC:      .equ  0x9090
STACK:    .equ  0x80FF

          .org  0x0000
          LDAI  0xFF            ; poison
          OUT
          LXISP STACK
          MVI   VEC, 0x31       ; JMP
          MVI   VEC+1, <handler
          MVI   VEC+2, >handler

; ---- init, 9600 8N1, as serrx
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
          LDAI  0x01            ; IER: received-data-available interrupt
          STA   SER_IER

          EI
sleep:    HALT
          JMP   sleep

handler:  PUSHA
          LDA   SER_RBR         ; reading RBR clears the interrupt
          OUT
          STA   SER_THR         ; echo
          POPA
          IRET
