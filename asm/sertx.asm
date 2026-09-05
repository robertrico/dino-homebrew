; sertx.asm -- PHASE G step 7. Real TX. THE MIRROR-WITNESS.
;
; MCR = 0. SOUT -> host adapter RX, GND common. Host terminal 9600 8N1.
; Sends "DINO\r\n", polling THRE (LSR bit 5) before each byte.
;
; THE WITNESS IS THE HOST TERMINAL. OB = 0x53 only says the program finished.
;   "DINO"              data bus PROVEN, not narrowed: a receiver DINO does
;                       not control decoded the bits by an absolute convention
;   garbage, 6 chars    data bus permutation. Send 'A' alone; the substitution
;                       table IS the crossing map
;   garbage, wrong n    baud. Step 5 measured 153.6 kHz; suspect the host
;   nothing             SOUT, adapter RX, or no common GND
;   one char, stops     THRE poll. 0x20 is bit 5; 0x01 is bit 0 and is RX

SER_THR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
SER_LSR:  .equ  0x4805

          .org  0x0000

          LDAI  0xFF          ; poison
          OUT

; ---- init, identical to serloop except MCR = 0x00
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
          STA   SER_IER
          LDAI  0x00          ; MCR = 0: real SOUT
          STA   SER_MCR

; ---- 'D'
wait_tx0: LDA   SER_LSR
          LDBI  0x20          ; THRE
          AND
          JNZ   send0
          JMP   wait_tx0
send0:    LDAI  'D'
          STA   SER_THR
; ---- 'I'
wait_tx1: LDA   SER_LSR
          LDBI  0x20
          AND
          JNZ   send1
          JMP   wait_tx1
send1:    LDAI  'I'
          STA   SER_THR
; ---- 'N'
wait_tx2: LDA   SER_LSR
          LDBI  0x20
          AND
          JNZ   send2
          JMP   wait_tx2
send2:    LDAI  'N'
          STA   SER_THR
; ---- 'O'
wait_tx3: LDA   SER_LSR
          LDBI  0x20
          AND
          JNZ   send3
          JMP   wait_tx3
send3:    LDAI  'O'
          STA   SER_THR
; ---- CR
wait_tx4: LDA   SER_LSR
          LDBI  0x20
          AND
          JNZ   send4
          JMP   wait_tx4
send4:    LDAI  0x0D
          STA   SER_THR
; ---- LF
wait_tx5: LDA   SER_LSR
          LDBI  0x20
          AND
          JNZ   send5
          JMP   wait_tx5
send5:    LDAI  0x0A
          STA   SER_THR

          LDAI  0x53          ; done. Says nothing about the wire.
          OUT
          HALT
