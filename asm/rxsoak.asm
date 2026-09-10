; rxsoak.asm -- DOES THE RBR READ LIE? Loopback soak: no host, no wire, no
; probe. 65280 bytes, every value 255 times, through THR and back.
;
;   build:  make assemble-rxsoak
;   burn:   make burn-prog-rxsoak
;   watch:  make monitor (any terminal, 9600 8N1). ~70s of silence while OB
;           counts passes 00..FF, then the report, then OB = the verdict.
;
; 2026-09-08: dinoload fails about 1 character in 30. The monitor echoes
; 0x00 where '0' or '2' was typed and aborts with `?`. Always 0x00, random
; position, never a drop, never a banner. One 0x00 out of `LDA SER_RBR`
; explains the whole transcript: putc echoes it, hexval rejects it.
;
; This image puts the SAME read under load with nothing outside the card.
; MCR bit 4 loops SOUT to SIN inside the part (serloop, 0x53, proven), so
; a bad byte HERE is the read path -- A0-2, ~CS2, ~RD, U102, U25, the
; latch edge -- and a clean 65536 here puts the fault on SIN, the adapter,
; or its ground. Loopback silences the SOUT pin, so nothing is printed
; until the soak is over: events go to RAM, the report comes at the end.
;
; The report:
;
;     E xx            RBR read with the FIFO EMPTY, once, before any byte is
;                     sent. If the loader's 0x00 is an empty pop after a
;                     false DR, this reads 00.
;     F xx            false DRs in 65536 idle LSR polls with nothing in
;                     flight. Any nonzero is a poll that lied; each one is
;                     drained so it counts once.
;     S ss G gg L ll  a mismatch: sent ss, got gg, LSR ll at the poll that
;                     saw DR. First 16 events only; the count goes on.
;     T ss G 00 L ll  sent ss, DR never came in ~2048 polls: the byte is
;                     LOST. ll is the last LSR seen. Same 16-event budget.
;     M mm T tt       mismatch count (saturates at FE), timeout count.
;
;     OB = 0x00   every byte read back exact, none lost. The read path is
;                 clean at 65280 samples; the fault is not on the card.
;     OB = 0xFF   at least one byte lost. T lines name them.
;     OB = mm     mismatches, none lost. G names what the read returned:
;                 00 every time = a register that reads 0 (IER at A=001,
;                 MCR at A=100) or an empty pop; the PREVIOUS byte = a
;                 double pop, or a late arrival after a T line; random =
;                 the data bus.
;
; OB shows the pass number FF..01 during the soak, so a hang names its
; pass; the verdict overwrites it at the end.
;
; INIT CHECK FIRST (v2, 2026-09-08). The first burn streamed bytes to the
; terminal for 75 minutes: SOUT was not marking, so MCR bit 4 was not set,
; and every byte timed out. The monitor never proves a write to 0x4804 --
; it writes MCR = 0x00, which is what MR leaves there. So before anything
; else, every init register that can be read back is, and a wrong one
; HALTs within a second of RESET with a coded OB. A HALT in the first
; second IS this check; the soak's own verdict comes after ~70s.
;
;     OB = 0x01..0x9F   LCR read back wrong after init; rewriting LCR = 0x03
;                       took after OB tries (~25us each). The init's writes
;                       were MISSED and later ones land: a dead time after
;                       RESET. OB x 25us is roughly how long.
;     OB = 0xA0         LCR never took in 159 rewrites, and SCR did: the
;                       write path works, LCR's address does not, or the
;                       LCR read lies.
;     OB = other        LCR never took AND SCR read back wrong: OB is the
;                       raw SCR readback. 00 = the card answers zero.
;     OB = 0x0B         LCR fine, FIFO off: the FCR write was missed.
;     OB = 0xE1..0xEF   MCR wrong after init; rewriting 0x10 took after
;                       OB-0xE0 tries (capped at 15).
;     OB = 0xE0         MCR never took in 159 rewrites.
;     OB = 0xC0         MCR CHANGED mid-soak, read twice. Only MR clears
;                       MCR.
;
; A wrong read is re-read before it counts, so the 1-in-30 read fault
; cannot fake a failed init on its own. v3, 2026-09-08: v2 halted A0 on a
; RESET press with MR proven 4.18V held / 68mV released, so the question
; is no longer whether the chip was reset but whether writes land.
;
; FIRST-OF-ITS-KIND, listed before the burn:
;   - RBR read on an empty FIFO, on purpose (the E line)
;   - every byte value 0x00-0xFF through THR and RBR (serloop sent 0x53,
;     sertx sent letters, the monitor sends ASCII)
;   - 65280 loopback round trips (serloop did one)
;   - a DR poll with a timeout (every other image spins forever)
;   - MCR written twice: loopback on, then off before the report
;   - LCR, IIR and MCR READ BACK after init (serid read SCR only)
;   - LCR / MCR REWRITTEN in a loop until they read back
;   - a RAM record table at 0x8100 written by STAX, read back by LDAX
; Unoracled by design: PHASE_G.md SECTION 5 forbids modelling THR, RBR,
; the FIFOs and loopback. Init, putc, puthex and the counters are the
; monitor's and serloop's, verbatim.

SER_THR:  .equ  0x4800        ; write, DLAB = 0
SER_RBR:  .equ  0x4800        ; read,  DLAB = 0
SER_DLL:  .equ  0x4800        ; write, DLAB = 1
SER_IER:  .equ  0x4801        ; DLAB = 0
SER_DLM:  .equ  0x4801        ; DLAB = 1
SER_FCR:  .equ  0x4802
SER_IIR:  .equ  0x4802        ; read: FIFO state in bits 7:6
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
SER_LSR:  .equ  0x4805
SER_SCR:  .equ  0x4807        ; scratch, serid proved it

SENT:     .equ  0x80E0        ; the byte just written to THR
GOT:      .equ  0x80E1        ; the byte RBR returned
LSRV:     .equ  0x80E2        ; LSR at the poll that saw DR (or the last)
VAL:      .equ  0x80E3        ; byte value, 0x00..0xFF per pass
PASS:     .equ  0x80E4        ; passes left, 256 down to 0
MM:       .equ  0x80E5        ; mismatches, saturates at 0xFE
TO:       .equ  0x80E6        ; timeouts, saturates at 0xFF
SHOWN:    .equ  0x80E7        ; records written, max 16
TOL:      .equ  0x80E8        ; poll timeout, low
TOH:      .equ  0x80E9        ; poll timeout, high
IDL:      .equ  0x80EA        ; idle poll count, low
IDH:      .equ  0x80EB        ; idle poll count, high
FDR:      .equ  0x80EC        ; false DRs while idle, saturates at 0xFF
EMP:      .equ  0x80ED        ; the empty-FIFO RBR read
T_CH:     .equ  0x80EE        ; putc's scratch
T_BYTE:   .equ  0x80EF        ; puthex's scratch
T_CNT:    .equ  0x80F0
T_TY:     .equ  0x80F1        ; record type char, 'S' or 'T'
T_N:      .equ  0x80F2        ; records left to print
RECL:     .equ  0x80F3        ; record pointer, low
RECH:     .equ  0x80F4        ; record pointer, high
TRIES:    .equ  0x80F5        ; init rewrite attempts
STACK:    .equ  0x80FF
RECS:     .equ  0x8100        ; 16 records x 4 bytes: type, sent, got, lsr

          .org  0x0000

          LDAI  0xFF          ; poison OB: U35 has no reset
          OUT
          LXISP STACK

; ---- UART init, serloop verbatim: 9600 8N1, FIFO on, polled, LOOPBACK.
; ORDER IS LOAD-BEARING (PHASE_G.md SECTION 4).
          LDAI  0x83          ; LCR: DLAB set, 8N1
          STA   SER_LCR
          LDAI  0x18          ; DLL = 24: 9600 at 3.6864MHz (serbaud)
          STA   SER_DLL
          LDAI  0x00          ; DLM = 0
          STA   SER_DLM
          LDAI  0x03          ; LCR: 8N1, DLAB CLEAR
          STA   SER_LCR
          LDAI  0x07          ; FCR: FIFO on, clear RX, clear TX
          STA   SER_FCR
          LDAI  0x00          ; IER = 0: polled. AFTER DLAB clear.
          STA   SER_IER
          LDAI  0x10          ; MCR: bit 4 = LOOPBACK. SOUT pin marks.
          STA   SER_MCR

; ---- did the init take? Read back what can be read back.
          LDA   SER_LCR
          CPI   0x03
          JNZ   lcr_again
          JMP   lcr_ok
lcr_again: LDA  SER_LCR
          CPI   0x03
          JNZ   lcr_fix
          JMP   lcr_ok
; LCR is wrong. Rewrite it until it reads back, counting tries.
lcr_fix:  CLR
          STA   TRIES
lcr_try:  LDA   TRIES
          INR
          STA   TRIES
          CPI   0xA0
          JNC   lcr_wr        ; TRIES < 0xA0: try again
          JMP   lcr_never
lcr_wr:   LDAI  0x03
          STA   SER_LCR
          LDA   SER_LCR
          CPI   0x03
          JNZ   lcr_try
          LDA   TRIES         ; it took: OB = how many tries
          OUT
          HALT
lcr_never: LDAI 0x5A          ; pure register test: SCR, no side effects
          STA   SER_SCR
          LDA   SER_SCR
          CPI   0x5A
          JNZ   scr_bad
          LDAI  0xA0          ; SCR takes, LCR never does
          OUT
          HALT
scr_bad:  OUT                 ; raw SCR readback
          HALT
lcr_ok:   LDA   SER_IIR       ; FIFO on reads 0xC1: bits 7:6 set, no int
          ANI   0xC0
          CPI   0xC0
          JNZ   iir_again
          JMP   iir_ok
iir_again: LDA  SER_IIR
          ANI   0xC0
          CPI   0xC0
          JNZ   iir_bad
          JMP   iir_ok
iir_bad:  LDAI  0x0B
          OUT
          HALT
iir_ok:   LDA   SER_MCR       ; bits 7:5 read 0; loopback = 0x10
          CPI   0x10
          JNZ   mcr_again
          JMP   mcr_ok
mcr_again: LDA  SER_MCR
          CPI   0x10
          JNZ   mcr_fix
          JMP   mcr_ok
mcr_fix:  CLR
          STA   TRIES
mcr_try:  LDA   TRIES
          INR
          STA   TRIES
          CPI   0xA0
          JNC   mcr_wr
          LDAI  0xE0          ; never took
          OUT
          HALT
mcr_wr:   LDAI  0x10
          STA   SER_MCR
          LDA   SER_MCR
          CPI   0x10
          JNZ   mcr_try
          LDA   TRIES         ; took after TRIES: OB = E0 | min(tries, 15)
          CPI   0x10
          JNC   mcr_small     ; TRIES < 16
          LDAI  0x0F
mcr_small: ORI  0xE0
          OUT
          HALT
mcr_ok:   CLR
          STA   MM
          STA   TO
          STA   SHOWN
          STA   FDR
          MVI   RECL, 0x00
          MVI   RECH, 0x81

; ==== E: read RBR with the FIFO empty. Nothing has been sent. ============
          LDA   SER_RBR
          STA   EMP

; ==== F: 65536 idle polls. DR must never set. =============================
          CLR
          STA   IDL
          STA   IDH
idle:     LDA   SER_LSR
          LDBI  0x01
          AND
          JNZ   id_false      ; DR with nothing in flight
          JMP   id_next
id_false: LDA   SER_RBR       ; drain it, so it counts once
          LDA   FDR
          CPI   0xFF
          JNZ   id_inc
          JMP   id_next
id_inc:   INR
          STA   FDR
id_next:  LDA   IDL
          INR
          STA   IDL
          JNZ   idle
          LDA   IDH
          INR
          STA   IDH
          JNZ   idle

; ==== the soak: 255 passes x 256 values = 65280 bytes =====================
; PASS runs FF..01 so OB never shows 00 mid-soak: 00 on OB means the
; verdict, never a hang in pass zero.
          LDAI  0xFF
          STA   PASS
pass:     LDA   PASS
          OUT                 ; progress on OB; a hang names its pass
          LDA   SER_MCR       ; still in loopback? Twice before believing no.
          CPI   0x10
          JNZ   mcr_re
          JMP   mcr_held
mcr_re:   LDA   SER_MCR
          CPI   0x10
          JNZ   mcr_lost
          JMP   mcr_held
mcr_lost: ANI   0x1F
          ORI   0xC0
          OUT
          HALT
mcr_held:
          CLR
          STA   VAL
val:      LDA   VAL
          STA   SENT
          STA   SER_THR       ; out through the shifter, back in via SIN
          CLR
          STA   TOL
          LDAI  0x08          ; 8 x 256 polls, ~80ms; a byte takes ~1ms
          STA   TOH
wait_dr:  LDA   SER_LSR
          STA   LSRV
          LDBI  0x01
          AND
          JNZ   got_dr
          LDA   TOL           ; DCR sets Z; STA holds it to the JNZ
          DCR
          STA   TOL
          JNZ   wait_dr
          LDA   TOH
          DCR
          STA   TOH
          JNZ   wait_dr
; timeout: the byte never arrived
          CLR
          STA   GOT
          LDA   TO
          CPI   0xFF
          JNZ   to_inc
          JMP   to_rec
to_inc:   INR
          STA   TO
to_rec:   LDAI  'T'
          CALL  record
          JMP   next_val
got_dr:   LDA   SER_RBR       ; pops the FIFO. ONE read.
          STA   GOT
          LDB   SENT
          SUB                 ; A = got - sent; Z when equal
          JNZ   mismatch
          JMP   next_val
mismatch: LDA   MM
          CPI   0xFE
          JNZ   mm_inc
          JMP   mm_rec
mm_inc:   INR
          STA   MM
mm_rec:   LDAI  'S'
          CALL  record
next_val: LDA   VAL
          INR
          STA   VAL
          JNZ   val
          LDA   PASS
          DCR
          STA   PASS
          JNZ   pass

; ==== the report: leave loopback, SOUT reaches the pin again =============
          LDAI  0x00
          STA   SER_MCR

          LDAI  'E'
          CALL  putc
          LDAI  ' '
          CALL  putc
          LDA   EMP
          CALL  puthex
          CALL  crlf

          LDAI  'F'
          CALL  putc
          LDAI  ' '
          CALL  putc
          LDA   FDR
          CALL  puthex
          CALL  crlf

          MVI   RECL, 0x00
          MVI   RECH, 0x81
          LDA   SHOWN
          STA   T_N
rp_loop:  LDA   T_N
          CPI   0
          JNZ   rp_go
          JMP   rp_done
rp_go:    CALL  rec_byte      ; type char
          CALL  putc
          LDAI  ' '
          CALL  putc
          CALL  rec_byte      ; sent
          CALL  puthex
          LDAI  ' '
          CALL  putc
          LDAI  'G'
          CALL  putc
          LDAI  ' '
          CALL  putc
          CALL  rec_byte      ; got
          CALL  puthex
          LDAI  ' '
          CALL  putc
          LDAI  'L'
          CALL  putc
          LDAI  ' '
          CALL  putc
          CALL  rec_byte      ; lsr
          CALL  puthex
          CALL  crlf
          LDA   T_N
          DCR
          STA   T_N
          JMP   rp_loop
rp_done:  LDAI  'M'
          CALL  putc
          LDAI  ' '
          CALL  putc
          LDA   MM
          CALL  puthex
          LDAI  ' '
          CALL  putc
          LDAI  'T'
          CALL  putc
          LDAI  ' '
          CALL  putc
          LDA   TO
          CALL  puthex
          CALL  crlf

; ==== the verdict on OB ===================================================
          LDA   TO
          CPI   0
          JNZ   lost
          LDA   MM
          OUT
          HALT
lost:     LDAI  0xFF
          OUT
          HALT

; ==== subroutines =========================================================

; record -- A = type char. Writes type, SENT, GOT, LSRV at [REC] and
; advances it, for the first 16 events; later ones only count.
record:   STA   T_TY
          LDA   SHOWN
          CPI   16
          JNC   rec_go        ; A < 16: room
          RET
rec_go:   INR
          STA   SHOWN
          LDA   T_TY
          CALL  rec_put
          LDA   SENT
          CALL  rec_put
          LDA   GOT
          CALL  rec_put
          LDA   LSRV
          CALL  rec_put
          RET

; rec_put -- [REC] <- A, REC += 1. The table is 64 bytes inside page 0x81,
; so the low byte never wraps.
rec_put:  LDB   RECH
          LDC   RECL
          STAX
          LDA   RECL
          INR
          STA   RECL
          RET

; rec_byte -- A <- [REC], REC += 1
rec_byte: LDB   RECH
          LDC   RECL
          LDAX
          STA   T_CH
          LDA   RECL
          INR
          STA   RECL
          LDA   T_CH
          RET

; putc -- send A. Returns with A intact. Polls THRE, LSR bit 5. The
; monitor's, verbatim.
putc:     STA   T_CH
pc_wait:  LDA   SER_LSR
          LDBI  0x20
          AND
          JNZ   pc_go
          JMP   pc_wait
pc_go:    LDA   T_CH
          STA   SER_THR
          RET

; crlf
crlf:     LDAI  0x0D
          CALL  putc
          LDAI  0x0A
          CALL  putc
          RET

; puthex -- A as two upper-case hex digits. The monitor's, verbatim: no
; SHR, so the high nibble is counted off by repeated subtraction.
puthex:   STA   T_BYTE
          CLR
          STA   T_CNT
ph_loop:  LDA   T_BYTE
          CPI   0x10
          JNC   ph_done
          SUI   0x10
          STA   T_BYTE
          LDA   T_CNT
          INR
          STA   T_CNT
          JMP   ph_loop
ph_done:  LDA   T_CNT
          CALL  nib_asc
          CALL  putc
          LDA   T_BYTE
          CALL  nib_asc
          CALL  putc
          RET

; nib_asc -- A = 0..15 -> '0'..'9', 'A'..'F'
nib_asc:  ADI   '0'
          CPI   0x3A
          JNC   na_done
          ADI   7
na_done:  RET
