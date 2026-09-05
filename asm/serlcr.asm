; serlcr.asm -- PHASE G step 8 DIAGNOSTIC. Read LCR back after the init.
;
; Cold-boot symptom (2026-09-04): the host probe shows DINO echoing 5-bit
; frames -- every wrong byte keeps bits 0-4, bit 5 is the stop bit, and a
; second 0xFF frame follows. RESET clears it. Word length is LCR bits 1:0;
; the init writes 0x83 then 0x03, and a cold LCR of 0x00 explains all of it
; (DLAB was set for the divisor writes, so baud stays right).
;
; Same init as serrx, then LCR is READ BACK and shown. Datasheet 8.2: LCR
; is R/W. No serial traffic needed.
;
;   OB = 0x03   LCR held. The 5-bit model is wrong; look elsewhere.
;   OB = 0x00   bits 0-1 of BOTH LCR writes lost. 5-bit, DLAB clear.
;   OB = 0x80   bits 0-1 lost AND DLAB still set: the second write never
;               landed at all.
;   OB = 0x83   the second write never landed; the first did.
;   other       the byte names which bits the register kept.
;
; Boot it COLD and read OB. Then press RESET and read OB again: warm must
; be 0x03, or the fault is not the cold/warm one being chased.

SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804

          .org  0x0000

          LDAI  0xFF          ; poison
          OUT

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

          LDA   SER_LCR       ; the witness
          OUT
          HALT
