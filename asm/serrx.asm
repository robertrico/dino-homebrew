; serrx.asm -- PHASE G step 8. Real RX, echoed. NEVER HALTS. Phase G ends here.
;
; Type a character on the host: it lands on OB in binary AND comes back to
; the terminal. Two observables from one keystroke.
;   both agree        RX and TX real. Card done.
;   OB right, no echo TX. Step 7 cleared it; suspect the THRE mask.
;   echo right, OB    the OUT, not the card.
;   neither, forever  SIN, adapter TX, or DR never sets. Probe SIN while
;                     typing: moves = UART not receiving; still = the wire.
;
; THRE is polled BEFORE the RBR read, so the byte goes A -> OB -> THR with
; nothing clobbering A between. RBR is read EXACTLY ONCE per character:
; the read pops the FIFO and cannot be repeated (GOTCHA 2).
;
; WITH NO HOST ATTACHED this loops on LDA SER_LSR forever: a continuous
; read of slot 1 every ~16 T-states. That is the scope stimulus.

SER_THR:  .equ  0x4800
SER_RBR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
SER_LSR:  .equ  0x4805

          .org  0x0000

          LDAI  0xFF          ; poison
          OUT

; ---- init, MCR = 0
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

top:
; ---- wait for a received byte: DR, LSR bit 0
wait_rx:  LDA   SER_LSR
          LDBI  0x01
          AND
          JNZ   ready_rx
          JMP   wait_rx
ready_rx:
; ---- wait until the transmitter can take it: THRE, LSR bit 5
wait_echo: LDA  SER_LSR
          LDBI  0x20
          AND
          JNZ   ready_echo
          JMP   wait_echo
ready_echo:
          LDA   SER_RBR       ; the ONE read. Pops the FIFO.
          OUT                 ; on the LEDs
          STA   SER_THR       ; and back to the host
          JMP   top
