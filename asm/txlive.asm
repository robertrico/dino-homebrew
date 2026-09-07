; txlive.asm -- IS THE UART BEING RESET UNDER THE MONITOR? Stream + witness.
;
;   build:  make assemble-txlive
;   check:  python3 docs/notes/test_txlive.py    (asserts the oracle REFUSES)
;   burn:   make burn-prog-txlive
;   watch:  make monitor        AND the LEDs, at the same time
;
; 2026-09-06. The monitor garbles more often than not; sertx and serrx too;
; isa is clean. The 09-05 raw capture of the monitor's garble kept bits 0-4
; and broke bits 5-7 (xor e0) -- byte for byte the 09-04 cold-boot
; fingerprint: LCR reverted to 0x00, the UART framing 5-BIT characters
; while the divisor (which MR does not touch) keeps the baud right. The
; UART's MR is RESET_B = U75.8, a '32 output sitting LOW in the SAME
; package as ~IO_WR (U75.6) and ~IO_RD_Q (U75.11), the two strobes that
; fire on every card access and drive long wires to the card. A runt on
; RESET_B partially resets the 16550; the CPU, clock-qualified, never sees
; it. isa cannot witness this: nothing but the UART counts strobes or has
; an asynchronous reset.
;
; This image is the monitor's TX path -- sertx's init, the puts walk, the
; putc RAM trip -- streaming "DINO MON\r\n" forever, with serlive's witness
; on OB after EVERY byte:
;
;     OB = (IIR & 0xC0) | LCR        (serlive.asm, datasheet 8.6 / 8.2)
;
;   0xC3   healthy: FIFO on (IIR 7:6 = 11), LCR = 8N1. Terminal clean.
;   0x00   LCR AND FCR reverted = MR's fingerprint. RESET_B carried a runt.
;          Scope U103.35, single-shot, rising edge > 1.5V, probe GND at the
;          star. Then U75.8 at the source: same runt = the package; clean
;          = the wire to the card (bundled with the strobes).
;   0xC0   LCR reverted, FIFO still on: a WRITE hit LCR. Not MR. A spurious
;          ~IO_WR with M0-2 = 3 -- MAR would have to hold 0x4803.
;   0x03   FIFO off, LCR fine: FCR alone. Would be new.
;   0xC3 held AND the terminal garbles: the UART is NOT being reset and the
;          framing is right. Then it is the data or the strobes: LA on
;          U103.18 (~WR), .21 (~RD), D0-7, SOUT, triggered on ~WR falling,
;          during "DINO MON".
;
; A revert is STICKY -- nothing here re-inits -- so a single hit at any time
; lands on the LEDs and stays: a witness that cannot miss. Once hit, the
; stream itself turns 5-bit shaped, so the terminal and OB agree.
;
; RESULT 2026-09-06, T0 cap OUT: 4-8 lines clean, then garble and OB 0x00
; TOGETHER. MR confirmed. Scope on U103.35 (trigger 0.8V, the 1.5V setting
; missed it) showed ~2.5V; U75.8 showed 3.3V/10ns full swing; a probe cured
; at U75.9 and at U10.6, anywhere on RESET, but not at MR alone. Cause: the
; RESET wire's ROUTE, in the bundle with fast edges root -> PC -> memory.
; Pulled clear of the parallel runs: C3, clean, no caps. PHASE_G_0.md.
;
; First-of-its-kind check: sertx init (green 09-04), puts walk with LDAX
; (test4/monitor green 09-05), putc via T_CH (monitor green 09-05), IIR|LCR
; on OB (serlive held 0xC3, 09-04). Nothing here has not run green before.

SER_THR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_IIR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
SER_LSR:  .equ  0x4805
T_CH:     .equ  0x80EC          ; the monitor's putc scratch, verbatim
PTRH:     .equ  0x80EF          ; the monitor's puts pointer, verbatim
PTRL:     .equ  0x80F0

          .org  0x0000

          LDAI  0xFF            ; poison
          OUT

; ---- UART init, sertx/monitor verbatim: 9600 8N1, FIFO on, MCR = 0
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
          STA   SER_IER
          LDAI  0x00
          STA   SER_MCR

; ---- the string, walked with the monitor's pointer pair, one char per pass
top:      MVI   PTRL, <s_line
          MVI   PTRH, >s_line
next:     LDB   PTRH
          LDC   PTRL
          LDAX
          CPI   0
          JNZ   send
          JMP   top

; ---- putc, the monitor's route verbatim: A -> RAM -> poll THRE -> A -> THR
send:     STA   T_CH
wait_tx:  LDA   SER_LSR
          LDBI  0x20            ; THRE
          AND
          JNZ   go_tx
          JMP   wait_tx
go_tx:    LDA   T_CH
          STA   SER_THR

; ---- the witness, serlive verbatim, after EVERY byte
          LDA   SER_IIR         ; bits 7:6 = 11 iff FCR0 = 1
          LDBI  0xC0
          AND
          LDB   SER_LCR
          OR                    ; A = (IIR & 0xC0) | LCR
          OUT

          LDA   PTRL
          INR
          STA   PTRL
          JMP   next

s_line:   .db   "DINO MON", 0x0D, 0x0A, 0
