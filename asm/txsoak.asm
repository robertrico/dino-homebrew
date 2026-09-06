; txsoak.asm -- WHICH ROUTE INTO STA THR GARBLES? Four slots, SW1 picks.
;
;   build:  make assemble-txsoak
;   check:  python3 docs/notes/test_txsoak.py       <- answer key (transcript)
;   burn:   make burn-prog-txsoak
;   watch:  make monitor        clean "DINO MON" lines forever, or garbage
;
; 2026-09-05, raw serprobe capture of PROG_monitor: every host-paced echo
; came back exact; every byte the monitor sent back-to-back from its own
; putc came back with bits 5-7 wrong (xor e0, 10, 20, f2). PROG_sertx
; streams back-to-back through the SAME init and THRE poll and is clean.
; The one difference is the route of the byte into STA SER_THR:
;
;     sertx           LDAI 'D'                        ; immediate -> A -> THR
;     monitor putc    STA T_CH / poll / LDA T_CH      ; A -> RAM -> A -> THR
;
; Each slot streams "DINO MON\r\n" forever by one route. Clean or garbled
; on the terminal is the answer; no OB.
;
;     SW1  route into THR
;      1   immediate, sertx verbatim                    control
;      2   putc verbatim: STA T_CH, poll THRE, LDA T_CH the monitor
;      3   STA T_CH, LDA T_CH, then poll THRE           RAM trip, poll after
;      4   MOVCA, poll THRE, MOVAC                      register trip, no RAM
;     other  OUT SW1 raw, HALT

DIP:      .equ  0x4000
SER_THR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
SER_LSR:  .equ  0x4805
T_CH:     .equ  0x80EE          ; the monitor's putc scratch
WHICH:    .equ  0x80E3
PTRL:     .equ  0x80E0
PTRH:     .equ  0x80E1
STACK:    .equ  0x80FF

          .org  0x0000

          LDAI  0xFF
          OUT
          LXISP STACK
          LDA   DIP
          STA   WHICH
          CPI   5
          JNC   in_range
          JMP   raw
in_range: CPI   0
          JNZ   init
raw:      LDA   WHICH
          OUT
          HALT

; ---- UART init, sertx/monitor verbatim
init:     LDAI  0x83
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

; ---- the string, walked with a RAM pointer like puts, one char per pass
top:      MVI   PTRL, <s_line
          MVI   PTRH, >s_line
next:     LDB   PTRH
          LDC   PTRL
          LDAX
          CPI   0
          JNZ   send
          JMP   top
send:     CALL  putc
          LDA   PTRL
          INR
          STA   PTRL
          JMP   next

; ---- putc, four ways. A = the character on entry; parked in C while the
; route is picked (the pick clobbers A and B). Slot 4 then USES that park.
putc:     MOVCA
          LDA   WHICH
          CPI   1
          JNZ   n1
          JMP   p1
n1:       CPI   2
          JNZ   n2
          JMP   p2
n2:       CPI   3
          JNZ   p4
          JMP   p3

; 1  immediate route: the char is thrown away and 'D' is sent, sertx's way.
;    Not a string, but the control is the ROUTE, not the text.
p1:       CALL  wait_thre
          LDAI  'D'
          STA   SER_THR
          RET

; 2  the monitor's putc, verbatim
p2:       MOVAC
          STA   T_CH
          CALL  wait_thre
          LDA   T_CH
          STA   SER_THR
          RET

; 3  RAM trip first, poll after: is it the RAM, or RAM-then-window timing?
p3:       MOVAC
          STA   T_CH
          LDA   T_CH
          STA   T_CH
          LDA   T_CH
          CALL  wait_thre
          LDA   T_CH
          STA   SER_THR
          RET

; 4  register trip, no RAM: C holds it across the poll, which is INLINE
;    because RET uses C as scratch and a CALLed poll would eat it.
p4:       LDA   SER_LSR
          LDBI  0x20
          AND
          JNZ   p4_go
          JMP   p4
p4_go:    MOVAC
          STA   SER_THR
          RET

wait_thre: LDA  SER_LSR
          LDBI  0x20
          AND
          JNZ   wt_done
          JMP   wait_thre
wt_done:  RET

s_line:   .db   "DINO MON", 0x0D, 0x0A, 0
