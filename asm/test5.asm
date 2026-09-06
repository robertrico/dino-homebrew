; test5.asm -- WHERE does test4 lose the byte? Six slots, SW1 picks, OB answers.
;
;   build:  make assemble-test5
;   check:  python3 docs/notes/test_test5.py       <- answer key per SW1
;   burn:   make burn-prog-test5
;
; PROG_test4 (MVI the pointer, LDB/LDC it back, LDAX, OUT) reads 0xFF on boot
; and on RESET, poison 0xA5. The monitor prints its banner from the same ROM
; address on boot. Two things test4 does that no green image combined: MVI,
; and LDAX with a NON-ZERO high byte from ROM (wander slot 9 used B=0x00).
; Each slot below adds one step. Poison is 0xA5 everywhere: 0xA5 = never
; reached OUT, 0xFF = OUT ran and read fill/park, other = a wrong cell.
;
;     SW1  expect  what
;      1   0x5A    LDBI 0x02 / LDCI 0x9E / LDAX      LDAX, high byte 0x02, no RAM
;      2   0x02    MVI PTRH,0x02 / LDA PTRH          MVI writes, RAM reads back
;      3   0x9E    MVI PTRL,0x9E / LDA PTRL          same, other cell
;      4   0x02    LDAI/STA PTRH / LDA PTRH          STA instead of MVI
;      5   0x5A    STA both / LDB / LDC / LDAX       test4 without MVI
;      6   0x5A    MVI both / LDB / LDC / LDAX       test4 itself
;     other        SW1 raw

DIP:      .equ  0x4000
PTRL:     .equ  0x80E2
PTRH:     .equ  0x80E3

          .org  0x0000

          LDAI  0xA5              ; poison, not 0xFF
          OUT

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
          JNZ   nomatch
          JMP   s6
nomatch:  LDA   DIP
          OUT
          HALT

; 1  LDAX alone, high byte 0x02 from immediates
s1:       LDBI  >byte
          LDCI  <byte
          LDAX
          OUT
          HALT

; 2  MVI the high byte, read it back with LDA
s2:       MVI   PTRH, 0x02
          LDA   PTRH
          OUT
          HALT

; 3  MVI the low byte, read it back
s3:       MVI   PTRL, 0x9E
          LDA   PTRL
          OUT
          HALT

; 4  STA instead of MVI
s4:       LDAI  0x02
          STA   PTRH
          LDAI  0x00
          LDA   PTRH
          OUT
          HALT

; 5  test4 without MVI: STA the pointer, LDB/LDC it, LDAX
s5:       LDAI  >byte
          STA   PTRH
          LDAI  <byte
          STA   PTRL
          LDB   PTRH
          LDC   PTRL
          LDAX
          OUT
          HALT

; 6  test4 verbatim
s6:       MVI   PTRL, <byte
          MVI   PTRH, >byte
          LDB   PTRH
          LDC   PTRL
          LDAX
          OUT
          HALT

          .org  0x029E
byte:     .db   0x5A
