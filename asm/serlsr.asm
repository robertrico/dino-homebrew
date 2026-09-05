; serlsr.asm -- PHASE G step 4c. A byte the UART GENERATED, DINO never wrote.
;
; LSR after Master Reset = 0x60 (datasheet TABLE I): THRE | TEMT.
; DINO never places 0x60 on W, so a crossed data bus cannot echo it back.
; No write in this image at all: ~WR is not exercised.
;
; OB = 0x60  read path proven for bits 5 and 6 as 1, all others as 0.
; OB = 0xFF  the park. U102 never drove W, or the UART never drove D0-7.

SER_LSR:  .equ  0x4805

          .org  0x0000

          LDAI  0xFF          ; poison
          OUT
          LDA   SER_LSR       ; one read: ~RD low for one CLK-low half
          OUT
          HALT
