; intresume.asm -- INT ladder I3. An interrupt runs the handler, and the
; main program carries on FROM WHERE IT WAS.
;
;   build:  make assemble-intresume
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware + the burn. NOT PUSHF/POPF -- see below.
;
; SOURCE: the 16550 THRE interrupt (IER bit 1), armed by the image
; itself -- no button, no 555 (Rico 2026-09-27). INTR goes high when the
; XMIT FIFO is empty and IER1 is set; writing THR or clearing IER drops
; it. FACT, datasheet 8.4 / 8.11 / TABLE I. INTR reaches ~{IRQ} through
; the open-collector inverter on dino_serial.
;
; Main counts on OB, about four a second, and after each count sends one
; "." and arms THRE. The interrupt lands a character-time later, somewhere
; inside main's delay loop -- the UART's crystal is not the CPU's, so where
; is not fixed. The handler clears IER and shows 0xE7 for ~0.5 s.
;
;     OB                        meaning
;     01 E7 02 E7 03 E7 ...     PASS -- IRET landed, CNT survived, A restored
;     01 02 03 ..., no E7       no interrupt taken: INTR, the OC inverter,
;                               IER, or EI. Terminal still shows dots
;     01 again after an E7      the machine RESET, it did not return
;     stuck on 0xE7             IRET never landed
;     count skips/garbles       the handler did not restore A (PUSHA/POPA)
;
; The handler's own delay changes the flags and B. Main keeps nothing
; live in B, and a flag clobbered between main's DCR and JNZ only shortens
; one delay. That is why this image needs no PUSHF/POPF hardware.

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
DH1:      .equ  0x8102          ; the handler's, so it never touches DC1
OUTER:    .equ  128             ; x ~2 ms = ~0.25 s per count
INNER:    .equ  0xFF

          .org  0x0000
          LDAI  0xFF            ; poison
          OUT
          LXISP STACK
          MVI   VEC, 0x31       ; JMP
          MVI   VEC+1, <handler
          MVI   VEC+2, >handler

; ---- UART init, 9600 8N1, FIFOs on, all interrupts off (as intser)
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
          MVI   CNT, 0x00
          EI

loop:     LDA   CNT
          INR
          STA   CNT
          OUT
          LDAI  0x2E            ; '.'
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
          PUSHB
          LDAI  0x00            ; clear the source: INTR drops
          STA   SER_IER
          LDAI  0xE7
          OUT
          LDAI  OUTER
          STA   DH1
hl1:      LDAI  INNER
hl2:      DCR
          JNZ   hl2
          LDA   DH1
          DCR
          STA   DH1
          JNZ   hl1
          LDAI  OUTER           ; twice as long: ~0.5 s of 0xE7
          STA   DH1
hl3:      LDAI  INNER
hl4:      DCR
          JNZ   hl4
          LDA   DH1
          DCR
          STA   DH1
          JNZ   hl3
          POPB
          POPA
          IRET
