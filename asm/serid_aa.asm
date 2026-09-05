; serid_aa.asm -- complement arm of PHASE G step 4b. The scratch register round trip.
;
; Card 1 (the serial card) sits at 0x4800-0x4FFF: U101 '138 decodes M11-M13,
; O1 is slot 1. The 16550's eight registers are at base+0..7 off M0-M2.
; SCR (base+7) is a plain R/W byte that controls nothing (datasheet 8.10).
;
; OB = 0xAA  the card answers: decode, ~RD, ~WR, both U102 directions.
; OB = 0xFF  the card never drove W (the park). Read path.
; OB = 0x00  SCR never took the write (SCR is 0 after MR). Write path.
; other      the byte names its own stuck data line: 0x54 = D0, 0x51 = D2.
;
; PERMUTATION-BLIND: a crossed U102 passes this. serlsr/seriir narrow it,
; sertx (a host reads the byte) closes it.

SER_SCR:  .equ  0x4807

          .org  0x0000

          LDAI  0xFF          ; poison OB: U35 has no reset, it holds the
          OUT                 ; previous answer until something overwrites it
          LDAI  0xAA
          STA   SER_SCR       ; W -> U102 A->B -> D0-7, latched on ~WR rise
          LDA   SER_SCR       ; ~RD low, DDIS low, U102 B->A, D0-7 -> W -> A
          OUT
          HALT
