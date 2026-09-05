; serrxlcr.asm -- PHASE G step 8 DIAGNOSTIC. serrx, but OB shows LCR.
;
; Cold-boot fault (2026-09-04): RBR values prove the RECEIVER frames 5-bit
; characters ([ -> 0x1D, b -> 0x1F, exact), yet PROG_serlcr reads LCR = 0x03
; on a cold boot. Either that boot missed the fault, or the UART's framing
; is not following LCR. This image echoes every character to the host (the
; probe script prints the exact bytes) and puts LCR on the LEDs after each.
;
;   echo 5-bit-shaped, OB = 0x03   framing ignores LCR: chip-internal state
;                                  a cold MR does not clear. Test: cold boot
;                                  with the adapter UNPLUGGED, then plug in.
;   echo 5-bit-shaped, OB != 0x03  LCR was corrupted after the init. The
;                                  byte says how.
;   echo clean, OB = 0x03          this boot missed the fault; boot again.
;
; Boot COLD, run: python3 docs/notes/serprobe_host.py 55 41 0d 62

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
          STA   SER_THR       ; back to the host: the probe prints it exact
          LDA   SER_LCR       ; DIAGNOSTIC: what does LCR hold RIGHT NOW?
          OUT                 ; on the LEDs. 0x03 = 8N1, DLAB clear
          JMP   top
