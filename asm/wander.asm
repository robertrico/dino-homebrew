; wander.asm -- WHY DOES OB MOVE AFTER HALT? One variable per slot, SW1 picks.
;
;   build:  make assemble-wander
;   check:  python3 docs/notes/test_wander.py       <- THE ANSWER KEY, per SW1
;   burn:   make burn-prog-wander
;
; 2026-09-05. After the ROM-as-data copper, every image that HALTs is seen
; to change OB later: test3 0x4D -> 0x89, isa 0xB4 <-> 0x01, mardisc 0x6D
; for 0x6B, mem/pads "LEDs blink". Two images HOLD: test.asm (a window-read
; loop, then LDAI/OUT/HALT, entered by driving SW1 to 0xFE) and ramexec.
; So a ROM-fetched HALT CAN hold at 1.024MHz; what decides is what ran
; before it, or what the machine is left holding. This image runs one
; difference per slot and halts. SW1 = slot, RESET, read OB, then WAIT.
;
; EVERY HALT HAS AN ESCAPE LADDER BEHIND IT (pads' trick, made explicit):
;
;     0xE1   the HALT let go once; the next instruction ran
;     0xE2   twice     0xE3   three times     0xEE   fell into the sink
;
; so the three outcomes read differently on the LEDs:
;
;     slot id holds            HALT holds. This slot is a HOLDER.
;     0xE1, then E2, E3, EE    HALT ESCAPES, sequentially. T advanced.
;     anything else, moving    OB corrupts while halted -- the U35 latch,
;                              not the T-counter. Different chase.
;
; SLOTS. Slot 1 is the control; every other slot is the control plus ONE
; thing a wanderer does that test.asm does not.
;
;     SW1   id    what it adds                      shape of
;      1   0x11   nothing. LDAI/OUT/HALT             pads' target, bare
;      2   0x12   one WINDOW read (SW1)              test.asm, known HOLDER
;      3   0x13   one ROM DATA read; the byte is     test3
;                 the answer
;      4   0x14   one RAM write                      --
;      5   0x15   RAM write, then read it back;      mem
;                 the read is the answer
;      6   0x16   two cells, read the first back     mardisc (gave 0x6D)
;      7   0x17   LXISP, PUSHA, POPA                 sp
;      8   0x18   LXISP, CALL / RET                  call
;      9   0x19   LDAX through B:C from ROM          the monitor's puts
;     10   0x1A   ~65K loop, counter in RAM, ~1s     "it ran a while"
;     other       OUT SW1 raw, then HALT             a stuck switch names
;                                                    itself
;
; MAR AFTER EACH SLOT, because HALT's row has mux_pc=0 and MAR drives M the
; whole time the machine sits halted (inference from the row, not measured):
; slots 1,7,8 leave MAR where the dispatch's JMP put it (this slot, ROM);
; 2 leaves it in the window; 3,9 in ROM at the data byte; 4,5,6,10 in RAM.

DIP:      .equ  0x4000
CELL:     .equ  0x8004
CELL2:    .equ  0x8010
CNT:      .equ  0x8020
STACK:    .equ  0x80FF

          .org  0x0000

          LDAI  0xFF              ; poison OB: 0xFF means nothing ran
          OUT

; ---- dispatch, the suite's compare chain verbatim ----------------------
          LDA   DIP
          LDBI  1
          SUB
          JNZ   n1
          JMP   s1
n1:       LDA   DIP
          LDBI  2
          SUB
          JNZ   n2
          JMP   s2
n2:       LDA   DIP
          LDBI  3
          SUB
          JNZ   n3
          JMP   s3
n3:       LDA   DIP
          LDBI  4
          SUB
          JNZ   n4
          JMP   s4
n4:       LDA   DIP
          LDBI  5
          SUB
          JNZ   n5
          JMP   s5
n5:       LDA   DIP
          LDBI  6
          SUB
          JNZ   n6
          JMP   s6
n6:       LDA   DIP
          LDBI  7
          SUB
          JNZ   n7
          JMP   s7
n7:       LDA   DIP
          LDBI  8
          SUB
          JNZ   n8
          JMP   s8
n8:       LDA   DIP
          LDBI  9
          SUB
          JNZ   n9
          JMP   s9
n9:       LDA   DIP
          LDBI  10
          SUB
          JNZ   nomatch
          JMP   s10

nomatch:  LDA   DIP               ; no slot: the switch byte, raw
          OUT
          HALT
          JMP   ladder

; ---- 1  bare -----------------------------------------------------------
s1:       LDAI  0x11
          OUT
          HALT
          JMP   ladder

; ---- 2  one window read (test.asm's shape, the known holder) -----------
s2:       LDA   DIP
          LDAI  0x12
          OUT
          HALT
          JMP   ladder

; ---- 3  one ROM data read; the byte IS the answer (test3's shape) ------
s3:       LDA   ROM3
          OUT
          HALT
          JMP   ladder
ROM3:     .db   0x13

; ---- 4  one RAM write ----------------------------------------------------
s4:       LDAI  0x14
          STA   CELL
          OUT
          HALT
          JMP   ladder

; ---- 5  RAM write, read back; the read is the answer (mem's shape) -----
s5:       LDAI  0x15
          STA   CELL
          LDAI  0x00
          LDA   CELL
          OUT
          HALT
          JMP   ladder

; ---- 6  two cells, read the first (mardisc's shape; it gave 0x6D) ------
s6:       LDAI  0x16
          STA   CELL
          LDAI  0x2D
          STA   CELL2
          LDA   CELL
          OUT
          HALT
          JMP   ladder

; ---- 7  stack -----------------------------------------------------------
s7:       LXISP STACK
          LDAI  0x17
          PUSHA
          LDAI  0x00
          POPA
          OUT
          HALT
          JMP   ladder

; ---- 8  CALL / RET (needs a stack; slot 7 is the stack alone) ------------
s8:       LXISP STACK
          CALL  sub8
          OUT
          HALT
          JMP   ladder
sub8:     LDAI  0x18
          RET

; ---- 9  LDAX from ROM through B:C (the monitor's puts) -------------------
s9:       LDBI  0x00              ; B = high byte of ROM9 -- under 0x0100
          LDCI  ROM9
          LDAX
          OUT
          HALT
          JMP   ladder
ROM9:     .db   0x19

; ---- 10  a long run: 256 x 256 DCR, counter in RAM, about a second -------
s10:      LDAI  0x00
          STA   CNT
outer:    LDAI  0x00
inner:    DCR
          JNZ   inner
          LDA   CNT
          DCR
          STA   CNT
          JNZ   outer
          LDAI  0x1A
          OUT
          HALT
          JMP   ladder

; ---- the escape ladder: each rung is one HALT that let go ----------------
ladder:   LDAI  0xE1
          OUT
          HALT
          LDAI  0xE2
          OUT
          HALT
          LDAI  0xE3
          OUT
          HALT
sink:     LDAI  0xEE
          OUT
          HALT
          JMP   sink
