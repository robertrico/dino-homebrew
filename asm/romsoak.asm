; romsoak.asm -- ROM-AS-DATA SOAK. 65536 passes, count the misses, OB.
;
;   build:  make assemble-romsoak
;   check:  python3 docs/notes/test_romsoak.py     <- answer key per SW1
;   burn:   make burn-prog-romsoak
;
; 2026-09-05. With U15 replaced, MVI settled and LE_MDR held through the
; replay, PROG_isa reads 0xB4 four for four and the monitor runs its session.
; What remains is a rate: puts walks, D 0 prints garbage, once in a while.
; Every miss is a ROM-as-data read. Two things can do that at a rate, and a
; RATE is what tells them apart:
;
;     the ROM's ~OE path is 3 gates + tOE since the G_0.2 copper, and the
;     margin at 1.024MHz has never been measured            -> misses at
;     1.024MHz, none at 500kHz
;     a contact on the MAR side of M (slot 3 read 0x2D once) -> misses at
;     both speeds, and the count does not scale with the clock
;
; SW1 picks WHICH read to soak; OB is the miss count, live, so the LEDs tick
; up as they happen. 0x00 at HALT = clean. 0xFF = never finished (poison).
; Counts saturate at 0xFE.
;
;     SW1  reads
;      1   LDA absolute, ROM byte under 0x0100     (test3's shape)
;      2   LDA absolute, ROM byte at 0x02xx        (the monitor's strings)
;      3   LDAX through B:C, ROM byte at 0x02xx    (puts' shape)
;      4   all three, every pass
;     other  OUT SW1 raw, HALT
;
; Pass count: 256 x 256 through two RAM cells. Passes take ~20-40 T-states,
; so a run is 1.3-2.6s at 1.024MHz.

DIP:      .equ  0x4000
CNTL:     .equ  0x80E0
CNTH:     .equ  0x80E1
FAILS:    .equ  0x80E2
WHICH:    .equ  0x80E3

          .org  0x0000

          LDAI  0xFF              ; poison: never finished
          OUT
          LDA   DIP
          STA   WHICH
          CLR
          STA   FAILS
          STA   CNTL
          STA   CNTH

          LDA   WHICH             ; anything outside 1-4: OUT it raw and stop
          CPI   5
          JNC   in_range          ; FLAG_C = A >= B unsigned; clear means A < 5
          JMP   raw
in_range: LDA   WHICH
          CPI   0
          JNZ   pass
raw:      LDA   WHICH
          OUT
          HALT

pass:     LDA   WHICH             ; no JZ in this ISA: JNZ chains
          CPI   1
          JNZ   not1
          JMP   do1
not1:     CPI   2
          JNZ   not2
          JMP   do2
not2:     CPI   3
          JNZ   do4
          JMP   do3

do1:      LDA   LOWB              ; ---- 1: LDA under 0x0100
          CPI   0x5A
          JNZ   miss
          JMP   next

do2:      LDA   HIGHB             ; ---- 2: LDA at 0x02xx
          CPI   0xA5
          JNZ   miss
          JMP   next

do3:      LDBI  >HIGHB            ; ---- 3: LDAX at 0x02xx
          LDCI  <HIGHB
          LDAX
          CPI   0xA5
          JNZ   miss
          JMP   next

do4:      LDA   LOWB              ; ---- 4: all three
          CPI   0x5A
          JNZ   miss
          LDA   HIGHB
          CPI   0xA5
          JNZ   miss
          LDBI  >HIGHB
          LDCI  <HIGHB
          LDAX
          CPI   0xA5
          JNZ   miss
          JMP   next

miss:     LDA   FAILS
          CPI   0xFE
          JNZ   count
          JMP   next              ; saturated
count:    LDA   FAILS
          INR
          STA   FAILS
          OUT

next:     LDA   CNTL
          INR
          STA   CNTL
          JNZ   pass
          LDA   CNTH
          INR
          STA   CNTH
          JNZ   pass

          LDA   FAILS
          OUT
          HALT

LOWB:     .db   0x5A

          .org  0x029E
HIGHB:    .db   0xA5
