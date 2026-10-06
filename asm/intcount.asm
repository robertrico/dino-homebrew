; intcount.asm -- INT ladder I3, read off the terminal. intresume's
; question (does an interrupt return to where main was?) with an answer
; you can read: intresume shows each count on OB for ~1 ms against 0.5 s
; of 0xE7, so the eye only ever sees E7.
;
;   build:  make assemble-intcount
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware + the burn. NOT PUSHF/POPF.
;
; SOURCE: the 16550 THRE interrupt (IER bit 1), armed by the image
; itself. Main sends "M" and arms THRE; INTR rises about one character
; later, inside main's delay. The handler clears IER (INTR drops), sends
; "I", and returns. No handler delay: one entry is one "I".
;
;     terminal                  meaning
;     R M I M I M I ...         PASS -- one interrupt per loop, IRET lands.
;                               About four M per second at 1.024 MHz
;     R M M M ..., no I         no interrupt taken: INTR, the OC inverter,
;                               IER, or EI
;     R M IIIIIIII...           the request does not clear: re-entered on
;                               every IRET. INTR never drops (the IER=0
;                               write), or ~{IRQ}/PEND stays low
;     R M I M IIII M I ...      sometimes re-fires: count the I per M
;     a second R                the machine RESET, it did not return
;     R M I, then nothing       IRET never landed
;
; OB shows the count, 01 02 03 ..., stepping about four times a second.

SER_THR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
VEC:      .equ  0x9090
STACK:    .equ  0x80FF
CNT:      .equ  0x8100
DC1:      .equ  0x8101          ; main's delay counter
OUTER:    .equ  128             ; x ~2 ms = ~0.25 s per count
INNER:    .equ  0xFF

          .org  0x0000
          LDAI  0xFF            ; poison
          OUT
          LXISP STACK
          MVI   VEC, 0x31       ; JMP
          MVI   VEC+1, <handler
          MVI   VEC+2, >handler

; ---- UART init, 9600 8N1, FIFOs on, all interrupts off (as intresume)
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
          LDAI  0x52            ; 'R': once per boot or RESET
          STA   SER_THR
          MVI   CNT, 0x00
          EI

loop:     LDA   CNT
          INR
          STA   CNT
          OUT
          LDAI  0x4D            ; 'M'
          STA   SER_THR
          LDAI  0x02            ; arm THRE: INTR ~1 char from now
          STA   SER_IER
          CALL  delay
          JMP   loop

delay:    LDAI  OUTER
          STA   DC1
dl1:      LDAI  INNER
dl2:      DCR
          JNZ   dl2
          LDA   DC1
          DCR
          STA   DC1
          JNZ   dl1
          RET

handler:  PUSHA
          LDAI  0x00            ; clear the source: INTR drops
          STA   SER_IER
          LDAI  0x49            ; 'I'
          STA   SER_THR
          POPA
          IRET
