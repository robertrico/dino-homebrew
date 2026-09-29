; intflags.asm -- INT ladder I5/I6. A handler that wrecks A, B and the
; flags, and saves and restores all of them, is INVISIBLE to the program it
; interrupts. 256 passes of a flag-driven loop under a 555 on ~{IRQ}.
;
;   build:  make assemble-intflags
;   check:  python3 docs/notes/test_intimages.py
;   needs:  the INT hardware, PUSHF/POPF hardware, the burn.
;           Run at 1.024 MHz AND 500 kHz.
;
; SOURCE: the 16550 THRE interrupt, armed by the image itself -- no 555
; (Rico 2026-09-27). The handler re-arms it by writing one byte to THR,
; which clears INTR (datasheet 8.11 A); the FIFO drains one character
; later and INTR rises again. So interrupts arrive every ~1 ms (9600
; baud), from a crystal that is not the CPU's: they land at unsynchronised
; points in main, which is what the 555 was for. The terminal fills with
; dots while it runs, one per interrupt.
;
; Each pass sums 7 sixty-four times, counting down with DCR/JNZ, and checks
; the sum is 0xC0. The handler lands between DCR and JNZ often enough that
; a Z it failed to restore ends a pass early and the sum is wrong.
;
;     OB     meaning
;     0xFF   never finished (still running, or lost: ~1.5 s is normal)
;     0x5A   PASS -- 256 passes clean AND the handler ran at least once
;     0x0E   no interrupt was ever taken. INTR, the OC inverter, IER, or
;            EI. Not a pass. Dots on the terminal = the UART is fine.
;     0xBD   a pass summed wrong: a flag or a register came back changed.
;            POPF first (P_POPF -- try 500 kHz), then the push order.
;
; Mirror: the host test runs this with PUSHF/POPF deleted and it MUST read
; 0xBD, so 0x5A here is not a reading a broken save could forge.

SER_THR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
VEC:      .equ  0x9090
STACK:    .equ  0x80FF
SUM:      .equ  0x8100
CNT:      .equ  0x8101
PASSES:   .equ  0x8102
SEEN:     .equ  0x8103

          .org  0x0000
          LDAI  0xFF            ; poison
          OUT
          LXISP STACK
          MVI   VEC, 0x31       ; JMP
          MVI   VEC+1, <handler
          MVI   VEC+2, >handler
          MVI   SEEN, 0x00
          MVI   PASSES, 0x00

; ---- UART init, 9600 8N1, FIFOs on, all interrupts off (as intser)
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
          LDAI  0x02            ; IER: THRE interrupt
          STA   SER_IER
          LDAI  0x2E            ; '.' primes it: INTR ~1 char from now
          STA   SER_THR
          EI

pass:     MVI   SUM, 0x00
          MVI   CNT, 0x40
loop:     LDA   SUM
          ADI   0x07
          STA   SUM
          LDA   CNT
          DCR                   ; Z live from here ...
          STA   CNT
          JNZ   loop            ; ... to here
          LDA   SUM
          CPI   0xC0
          JNZ   bad
          LDA   PASSES
          INR
          STA   PASSES
          JNZ   pass            ; 256 passes

          DI
          LDA   SEEN
          CPI   0x01
          JNZ   none
          LDAI  0x5A
          OUT
          HALT
none:     LDAI  0x0E
          OUT
          HALT
bad:      DI
          LDAI  0xBD
          OUT
          HALT

handler:  PUSHF
          PUSHA
          PUSHB
          MVI   SEEN, 0x01
          LDAI  0x2E            ; re-arm: clears INTR, next one ~1 ms on
          STA   SER_THR
          LDAI  0x00
          ANI   0x00            ; Z=1: wrecks the Z main may be holding
          LDBI  0x55
          POPB
          POPA
          POPF
          IRET
