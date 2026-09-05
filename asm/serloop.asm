; serloop.asm -- PHASE G step 6. Internal loopback: the UART proves itself.
;
; MCR bit 4 ties SOUT to SIN inside the part. No wire leaves the card.
; Send 0x53, wait for DR, read it back.
;
; OB = 0x53  baud, framing, TX, RX, FIFO all work.
; OB = 0xFF  DR never set, loop spins forever. Divisor/crystal (step 5 clears
;            both), MCR bit 4 never took, or LCR left with DLAB set.
; OB = 0xCA  0x53 bit-reversed: a data path reversed end to end. That is
;            why 0x53 and not 0x3C, which is its own reversal.
;
; THE POLL LOOP: AND sets Z; LDA/LDBI/JNZ are not ALU sources so Z HOLDS to
; the JNZ. JNZ is taken when the masked bit is SET. There is no JZ, so the
; back edge is a JMP. 16 T-states per non-taken pass.

SER_THR:  .equ  0x4800        ; write, DLAB = 0
SER_RBR:  .equ  0x4800        ; read,  DLAB = 0
SER_DLL:  .equ  0x4800        ; write, DLAB = 1
SER_IER:  .equ  0x4801        ; DLAB = 0
SER_DLM:  .equ  0x4801        ; DLAB = 1
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
SER_LSR:  .equ  0x4805

          .org  0x0000

          LDAI  0xFF          ; poison
          OUT

; ---- init, 9600 8N1, FIFO on, polled (SECTION 4). ORDER IS LOAD-BEARING.
          LDAI  0x83          ; LCR: DLAB set, 8N1
          STA   SER_LCR
          LDAI  0x18          ; DLL = 24
          STA   SER_DLL
          LDAI  0x00          ; DLM = 0
          STA   SER_DLM
          LDAI  0x03          ; LCR: 8N1, DLAB CLEAR
          STA   SER_LCR
          LDAI  0x07          ; FCR: FIFO on, clear RX, clear TX
          STA   SER_FCR
          LDAI  0x00          ; IER = 0: polled mode (8.12). AFTER DLAB clear,
          STA   SER_IER       ; or this byte lands in DLM and changes the baud
          LDAI  0x10          ; MCR: bit 4 = LOOPBACK
          STA   SER_MCR

; ---- send one byte
          LDAI  0x53
          STA   SER_THR

; ---- wait for DR (LSR bit 0)
wait_dr:  LDA   SER_LSR
          LDBI  0x01
          AND
          JNZ   ready_dr      ; taken when DR = 1
          JMP   wait_dr
ready_dr: LDA   SER_RBR       ; pops the FIFO. ONE read.
          OUT
          HALT
