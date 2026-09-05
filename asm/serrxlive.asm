; serrxlive.asm -- PHASE G step 8 DIAGNOSTIC. The serrx loop, with the
; live LCR/FCR witness on OB after every echo.
;
; serlive (no LSR poll, no RBR read, no THR write) holds 0xC3 cold, even
; with a byte waiting in the FIFO. serrxlcr (the real loop) shows LCR = 0x00
; by the first echo. So the loop does it. This image is the real loop and
; OB = (IIR & 0xC0) | LCR after each character:
;
;   0xC3   healthy
;   0x00   LCR AND FCR reverted: MR fingerprint
;   0xC0   LCR reverted, FIFO on: a WRITE hit LCR
;
; The echo itself still goes to the host; the probe prints it exact.
;     python3 docs/notes/serprobe_host.py 55

SER_IIR:  .equ  0x4802
SER_THR:  .equ  0x4800
SER_RBR:  .equ  0x4800
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

; ---- init, MCR = 0
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
          LDAI  0x00
          STA   SER_MCR

top:
; ---- wait for a received byte: DR, LSR bit 0
wait_rx:  LDA   SER_LSR
          LDBI  0x01
          AND
          JNZ   ready_rx
          JMP   wait_rx
ready_rx:
; ---- wait until the transmitter can take it: THRE, LSR bit 5
wait_echo: LDA  SER_LSR
          LDBI  0x20
          AND
          JNZ   ready_echo
          JMP   wait_echo
ready_echo:
          LDA   SER_RBR       ; the ONE read. Pops the FIFO.
          STA   SER_THR       ; back to the host
          LDA   SER_IIR       ; DIAGNOSTIC witness, as in serlive
          LDBI  0xC0
          AND
          LDB   SER_LCR
          OR
          OUT                 ; (IIR & 0xC0) | LCR
          JMP   top
