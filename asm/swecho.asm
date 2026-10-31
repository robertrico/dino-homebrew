; swecho.asm -- SW1 on OB, live: a closed switch lights its LED.
;
;   build:  make assemble-swecho
;
; Card zero (the DIP switch, 0x4000) read every pass, inverted, latched on
; OB. SW1 is active low (R17-R24 pull IS0-7 high, a closed switch pulls its
; bit to 0), so the XOR with 0xFF makes closed = 1 = lit. Bit n of SW1 is
; bit n of OB. Never halts. Written for the FPGA twin on the Versa, where
; the board's DIPs are SW1 and its LEDs are OB (fpga/versa_top.v).

DIP:      .equ  0x4000

          .org  0x0000
loop:     LDA   DIP
          LDBI  0xFF
          XOR
          OUT
          JMP   loop
