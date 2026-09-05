; serprobe.asm -- PHASE G step 2 ONLY. U101 fitted, U102 and U103 NOT.
;
; Nothing on the card can drive W, so 0x4800 must read the park.
; OB = 0xFF  correct: the '138 is the only thing on the card
; anything   something else landed on W. Stop, do not fit U102.
; MEANINGLESS once U103 is seated: 0x4800 is then RBR.

SER_BASE: .equ  0x4800

          .org  0x0000

          LDAI  0xFF          ; poison
          OUT
          LDA   SER_BASE
          OUT
          HALT
