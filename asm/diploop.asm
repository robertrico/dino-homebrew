; diploop.asm -- PROG_dip, read continuously: OB = SW1 + 0x2F, live.
;
;   build:  make assemble-diploop
;
; PROG_dip (progrom_gen.DIP_PROGRAM) reads card zero once, adds 0x2F, shows
; the sum and halts, so a switch change needs a reset. This is the same
; LDA / LDBI / ADD / OUT with a JMP back instead of the HALT: flip a switch
; and OB follows. PROG_dip stays the coverage image (pinned CRC, oracle
; 0x2E with SW1 open).
;
; SW1 is active low: a CLOSED switch reads 0. Close bits 7, 6, 5 and 0
; (SW1 = 0x1E) and OB reads 0x4D, the milestone sum. All open: 0xFF + 0x2F
; = 0x2E.

DIP:      .equ  0x4000

          .org  0x0000
loop:     LDA   DIP
          LDBI  0x2F
          ADD
          OUT
          JMP   loop
