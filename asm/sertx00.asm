; sertx00.asm -- sertx VERBATIM, but every unclaimed ROM byte is 0x00 (NOP),
; not 0xFF (HALT). Rico's A/B of the fill choice, 2026-09-06.
;
;   build:  make assemble-sertx00        burn:  make burn-prog-sertx00
;   watch:  make monitor, LEDs, and the scope on U30.7 after 0x53
;
; ONE byte value differs from PROG_sertx: the fill. Same code, same HALT
; (0xFF at the end of the program), same init, same "DINO\r\n". So:
;
;   the HALT strobe on U30.7 is UNCHANGED   the fill never mattered to it;
;                                          the machine sits in the same HALT
;                                          row either way (IR=0xFF, T=1)
;   the strobe changes rate or vanishes    the fill DOES reach the halted
;                                          machine somehow, and that is new
;                                          information worth its own capture
;
; What this image is ALSO, on purpose: a LOUD escape witness. With HALT fill
; an escape from HALT lands on another HALT one byte later and is invisible.
; With NOP fill it slides 28K, wraps to 0x0000 and RE-RUNS the program:
;   OB flicks 0xFF (the poison) then 0x53 again, "DINO" prints again.
; Every escape shows on the LEDs and the terminal. PROG_sertx never could.
;
; What it costs: a mistyped immediate or a runaway no longer stops where it
; lands; it wraps and re-runs. That is the trade the 0xFF fill was chosen
; to avoid, and this image exists so the trade can be judged on the bench
; instead of argued.

          .fill 0x00

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
