; seriir.asm -- PHASE G step 4c. IIR after enabling the FIFO.
;
; IIR after MR = 0x01. Writing FCR = 0x07 (FIFO on, clear both) sets IIR
; bits 7:6 (datasheet 8.6: "set when FCR0 = 1"). Nothing pending keeps bit 0.
; Expected 0xC1. Pins bits 0, 6, 7 against a value DINO never wrote.
;
; OB = 0xC1  write reached FCR AND read path carries the high bits.
; OB = 0x01  the write never landed (FCR0 stayed 0). ~WR path.
; OB = 0xFF  the park.

SER_FCR:  .equ  0x4802        ; write side of base+2
SER_IIR:  .equ  0x4802        ; read side of base+2, same address

          .org  0x0000

          LDAI  0xFF          ; poison
          OUT
          LDAI  0x07
          STA   SER_FCR       ; FIFO enable, RX clear, TX clear
          LDA   SER_IIR
          OUT
          HALT
