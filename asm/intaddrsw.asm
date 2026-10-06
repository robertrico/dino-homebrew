; intaddrsw.asm -- INT ladder I4, with SW1 sliding where the request lands.
; intaddr's question: is the pushed return address the next OPCODE, never
; an operand byte? Same loop, same handler, same OB readings.
;
;   build:  make assemble-intaddrsw
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware + the burn
;
; WHY IT EXISTS (2026-10-06): intaddr showed 0x40 0x42 0x43 and never
; 0x45 in 34+ RESETs. THRE lands a fixed four characters (~4.17 ms) after
; the first THR write, give or take the 1/16-bit start alignment (~6.5 us,
; ~7 clocks). The loop is 10 clocks, so the request only ever reaches a
; ~7-clock slice of it. Here SW1 & 7 passes of DCR/JNZ (8 T each) sit
; between the THR writes and the loop: SW1 = 1..5 puts the loop at five
; different phases, 8 6 4 2 0 T (SW1 = 0 skips the pad and repeats SW1 =
; 3's phase). test_intaddrsw_sw1_slides_the_loop_through_five_phases.
;
;     OB     meaning
;     0x40 0x42 0x43 0x45        PASS -- an opcode address in the loop
;     0x41 0x44 0x46 0x47        FAIL -- an OPERAND byte: PC_UP was not
;                                inhibited at the injected T0 (C4)
;     0xFF, "...." on terminal   no interrupt taken: INTR, OC inverter, EI
;     anything else              the push or the absolute read
;
; Bench: ~10 RESETs at each SW1 = 1, 2, 3, 4, 5. The values should move
; with SW1, and 0x45 should turn up at some setting. 0x45 at NO setting
; means the boundary in front of the JMP at 0x0145 refuses the accept.

SER_THR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
SW1:      .equ  0x4000
VEC:      .equ  0x9090
STACK:    .equ  0x80FF
PUSHED_LO: .equ 0x80FE          ; INT pushes HI at 0x80FF, then LO

          .org  0x0000
          LDAI  0xFF            ; poison
          OUT
          LXISP STACK
          MVI   VEC, 0x31       ; JMP
          MVI   VEC+1, <handler
          MVI   VEC+2, >handler

; ---- UART init, 9600 8N1, FIFOs on, all interrupts off (as intaddr)
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

          LDAI  0x2E            ; '....' fill the FIFO first ...
          STA   SER_THR         ; <- the UART starts counting here
          STA   SER_THR
          STA   SER_THR
          STA   SER_THR

; ---- the slide: SW1 & 7 passes of 8 T, BEFORE the loop
          LDA   SW1
          ANI   0x07
          JNZ   pad
          JMP   go
pad:      DCR
          JNZ   pad

go:       LDAI  0x02            ; ... THEN enable THRE: it is clear now
          STA   SER_IER
          EI
          JMP   loop

          .org  0x0140
loop:     LDAI  0x11            ; 0x40 opcode, 0x41 operand
          NOP                   ; 0x42
          LDBI  0x22            ; 0x43 opcode, 0x44 operand
          JMP   loop            ; 0x45 opcode, 0x46 0x47 operands

handler:  LDA   PUSHED_LO
          OUT
          HALT
