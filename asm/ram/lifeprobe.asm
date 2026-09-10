; lifeprobe.asm -- WHICH LOOP HANGS life.asm? OB-only, no serial in the run.
;
;   load:   make load-lifeprobe        (over the monitor, same as life)
;   run:    make monitor ; then  G 8100
;   read:   THE LEDS. No terminal output by design -- the UART is the flaky
;           part and this probe keeps it out of the loop entirely.
;
; life freezes after row 0 with OB = 0x01 and no response to keys. That is
; an infinite loop with no UART access, and the only such code between
; row 0 and row 1 is the first st_loop / cp_loop. This runs the SAME clear,
; seed, st_loop and cp_loop bodies as life.asm, byte-for-byte, but drops an
; OB checkpoint between each stage and HALTs at the end so OB latches the
; last stage reached:
;
;     OB = 0xA1   hung in the CLEAR loop            (would surprise: life
;                 got past it -- row 0 printed)
;     OB = 0xA5   clear done, hung in MVI           <- MVI is the machine's
;                 known-marginal instruction; this is the expected result
;     OB = 0xB1   MVI done, hung in st_loop         <- the SHL/ADD suspect
;     OB = 0xC1   st_loop done, hung in cp_loop
;     OB = 0xC5   ALL loops ran, machine HALTed cleanly. Then the compute
;                 is fine and life's freeze is in the scroll/poll, not here.
;
; Same RAM map as life: rows in page 0x80, variables at 0x80D0-0x80D6,
; nothing above 0x80DF, monitor's 0x80E0-0x80FF untouched.

I:        .equ  0x80D0
IDX:      .equ  0x80D1
NEW:      .equ  0x80D2
PAGE:     .equ  0x80
CUR:      .equ  0x01
NXT:      .equ  0x81
ROW:      .equ  0x80

          .org  0x8100

          JMP   start
rule:     .db   0, 1, 1, 1, 1, 0, 0, 0

start:    LDAI  0xA1            ; checkpoint: entering the clear loop
          OUT
          CLR
          STA   I
clr_loop: LDBI  PAGE
          LDA   I
          MOVCA
          CLR
          STAX
          LDA   I
          INR
          STA   I
          CPI   0xD0
          JNZ   clr_loop

          LDAI  0xA5            ; checkpoint: clear loop done, MVI next
          OUT
          MVI   0x8020, 1       ; centre cell, 32 -- the fragile one

          LDAI  0xB1            ; checkpoint: MVI done, entering st_loop
          OUT
          LDAI  1
          STA   I
st_loop:  LDA   I
          DCR
          MOVCA
          LDBI  PAGE
          LDAX
          SHL
          SHL
          STA   IDX
          LDA   I
          MOVCA
          LDBI  PAGE
          LDAX
          SHL
          LDB   IDX
          ADD
          STA   IDX
          LDA   I
          INR
          MOVCA
          LDBI  PAGE
          LDAX
          LDB   IDX
          ADD
          ADI   <rule
          MOVCA
          LDBI  >rule
          LDAX
          STA   NEW
          LDA   I
          ADI   ROW
          MOVCA
          LDBI  PAGE
          LDA   NEW
          STAX
          LDA   I
          INR
          STA   I
          CPI   65
          JNZ   st_loop

          LDAI  0xC1            ; checkpoint: st_loop done, entering cp_loop
          OUT
          LDAI  1
          STA   I
cp_loop:  LDA   I
          ADI   ROW
          MOVCA
          LDBI  PAGE
          LDAX
          STA   NEW
          LDBI  PAGE
          LDA   I
          MOVCA
          LDA   NEW
          STAX
          LDA   I
          INR
          STA   I
          CPI   65
          JNZ   cp_loop

          LDAI  0xC5            ; all three loops ran; HALT latches this
          OUT
          HALT
