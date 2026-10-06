; spin.asm -- a RAM program that never returns: imon's Ctrl-C witness.
;
;   load:   python3 docs/notes/dinoload.py asm/ram/spin.asm --go
;   check:  python3 docs/notes/test_imon.py
;
; Counts on OB about four times a second, forever. Under PROG_imon, Ctrl-C
; stops it: "^C" and the prompt come back, and OB freezes on the count it
; had reached. Under the polling PROG_monitor nothing can stop it but RESET.
;
; Its state lives at 0x8180, above its own code and outside the monitor's
; 0x80A0-0x80FF.

CNT:      .equ  0x8180
DC:       .equ  0x8181
OUTER:    .equ  128             ; x ~2 ms = ~0.25 s per count
INNER:    .equ  0xFF

          .org  0x8100
          MVI   CNT, 0x00
loop:     LDA   CNT
          INR
          STA   CNT
          OUT
          LDAI  OUTER
          STA   DC
d1:       LDAI  INNER
d2:       DCR
          JNZ   d2
          LDA   DC
          DCR
          STA   DC
          JNZ   d1
          JMP   loop
