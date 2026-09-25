; intbtn.asm -- INT ladder I3. A press runs the handler; release, and the
; main program carries on FROM WHERE IT WAS.
;
;   build:  make assemble-intbtn
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware + the burn. NOT PUSHF/POPF -- see below.
;
; Main counts on OB, about four a second: 0x01, 0x02, 0x03 ...
; Press ~{IRQ}: OB shows 0xE7 for about half a second (and keeps showing
; it while the button is held -- the line is a LEVEL, so IRET re-enters).
; Release: the count resumes at the NEXT number, not at 0x01.
;
;     OB after release     meaning
;     n+1                  PASS -- IRET landed, CNT survived, A restored
;     0x01 again           the machine RESET, it did not return
;     stuck on 0xE7        IRET never landed
;     count skips/garbles  the handler did not restore A (PUSHA/POPA)
;
; The handler's own delay changes the flags and B. Main keeps nothing
; live in B, and a flag clobbered between main's DCR and JNZ only shortens
; one delay. That is why this image needs no PUSHF/POPF hardware.

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
          MVI   CNT, 0x00
          EI

loop:     LDA   CNT
          INR
          STA   CNT
          OUT
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
