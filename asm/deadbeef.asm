; deadbeef.asm -- card 2 on the FPGA twin: four cells, its window, its quiet.
;
;   build:  make assemble-deadbeef
;   run:    python3 docs/notes/fpga_twin_suite.py --only PROG_deadbeef
;
; The DEADBEEF card (fpga/cards/deadbeef_card.v) answers window 2,
; 0x5000-0x57FF: DE AD BE EF at offsets 0x000, 0x555, 0x2AA, 0x7FF (between
; them every one of M0-M10 toggles), 0xFF everywhere else in the window.
; Window 4 (0x6000) has no card in the slot table and reads the W park.
;
; Seven reads, in order. OB = 0x5A when all seven match; otherwise 0xE1-0xE7
; names the first read that did not. 0xA5 = never reached a verdict.
;
;     read  address  expect  what it proves
;      1    0x5000   0xDE    the card answers, offset 0
;      2    0x5555   0xAD    M0, M2, M4, M6, M8, M10 high
;      3    0x52AA   0xBE    M1, M3, M5, M7, M9 high
;      4    0x57FF   0xEF    all of M0-M10 high
;      5    0x5001   0xFF    the rest of the window is 0xFF
;      6    0x5400   0xFF    (M10 alone)
;      7    0x6000   0xFF    an empty slot's window: the card is quiet there

          .org  0x0000

          LDAI  0xA5              ; poison
          OUT

          LDA   0x5000
          LDBI  0xDE
          SUB
          JNZ   f1
          LDA   0x5555
          LDBI  0xAD
          SUB
          JNZ   f2
          LDA   0x52AA
          LDBI  0xBE
          SUB
          JNZ   f3
          LDA   0x57FF
          LDBI  0xEF
          SUB
          JNZ   f4
          LDA   0x5001
          LDBI  0xFF
          SUB
          JNZ   f5
          LDA   0x5400
          LDBI  0xFF
          SUB
          JNZ   f6
          LDA   0x6000
          LDBI  0xFF
          SUB
          JNZ   f7
          LDAI  0x5A
          OUT
          HALT

f1:       LDAI  0xE1
          OUT
          HALT
f2:       LDAI  0xE2
          OUT
          HALT
f3:       LDAI  0xE3
          OUT
          HALT
f4:       LDAI  0xE4
          OUT
          HALT
f5:       LDAI  0xE5
          OUT
          HALT
f6:       LDAI  0xE6
          OUT
          HALT
f7:       LDAI  0xE7
          OUT
          HALT
