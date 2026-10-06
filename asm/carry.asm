; carry.asm -- ADC / SBB / ACI / SBI on silicon. 256 passes, fail-stop.
;
;   build:  make assemble-carry
;   check:  python3 docs/notes/test_carry.py     <- oracle + mutation tests
;   burn:   make burn-prog-carry
;
; NEEDS THE CARRY MICROCODE (U9 0x4102 U15 0x9BC4 U23 0x8A40). On the
; 0x0C0A image 0x96-0x99 are blank blocks and this reads a subtest id.
;
; 2026-10-06. U76 ('157, ALU board) picks the '382's CN: S <- CW16,
; I0a <- FLAG_C, I1a <- NAND(SA1, SA0), Za -> U38.15. These four are the
; only rows with CW16 low.
;
; OB  0xAD  every subtest, every pass
;     0x01-0x0C  the first subtest that failed (table below)
;     0xFF  never finished (poison)
;
; Each subtest sets the carry with an ADD (0xFF+0x01 -> C=1, 0x01+0x01 ->
; C=0), loads the operands (src=ROM: the flags hold), runs the op, then
; checks the carry out (JNC) and the byte (CPI). Every op has a case with
; the carry flipping across it (in 1 -> out 0, or in 0 -> out 1): the flag
; register clocks the new carry on the same CLK fall that U47 closes on,
; so an ALU that latched its answer with the NEW carry reads one off.
;
; 256 passes, one failure stops it: a single-shot test on a marginal board
; reports noise, so the pass is unanimity.
;
;     id  op   C in  A     B     result  C out
;      1  ADC  1     0x12  0x01  0x14    0
;      2  ADC  0     0xFF  0x01  0x00    1
;      3  ADC  1     0xFF  0x00  0x00    1
;      4  ADC  0     0x12  0x01  0x13    0
;      5  SBB  1     0x12  0x01  0x11    1
;      6  SBB  0     0x05  0x01  0x03    1
;      7  SBB  1     0x00  0x01  0xFF    0
;      8  SBB  0     0x00  0x00  0xFF    0
;      9  ACI  1     0x34  0x00  0x35    0
;     10  ACI  0     0xFF  0x01  0x00    1
;     11  SBI  0     0x35  0x00  0x34    1
;     12  SBI  1     0x00  0x01  0xFF    0

CNT:      .equ  0x80E0

          .org  0x0000

          LDAI  0xFF              ; poison: never finished
          OUT
          CLR
          STA   CNT

pass:
t1:
          LDAI  0xFF              ; C <- 1
          LDBI  0x01
          ADD
          LDAI  0x12
          LDBI  0x01
          ADC
          JNC   c1                ; C out must be 0
          JMP   f1
c1:
          CPI   0x14
          JNZ   f1
          JMP   t2
f1:       OUTI  0x01
          HALT

t2:
          LDAI  0x01              ; C <- 0
          LDBI  0x01
          ADD
          LDAI  0xFF
          LDBI  0x01
          ADC
          JNC   f2                ; C out must be 1
          CPI   0x00
          JNZ   f2
          JMP   t3
f2:       OUTI  0x02
          HALT

t3:
          LDAI  0xFF              ; C <- 1
          LDBI  0x01
          ADD
          LDAI  0xFF
          LDBI  0x00
          ADC
          JNC   f3                ; C out must be 1
          CPI   0x00
          JNZ   f3
          JMP   t4
f3:       OUTI  0x03
          HALT

t4:
          LDAI  0x01              ; C <- 0
          LDBI  0x01
          ADD
          LDAI  0x12
          LDBI  0x01
          ADC
          JNC   c4                ; C out must be 0
          JMP   f4
c4:
          CPI   0x13
          JNZ   f4
          JMP   t5
f4:       OUTI  0x04
          HALT

t5:
          LDAI  0xFF              ; C <- 1
          LDBI  0x01
          ADD
          LDAI  0x12
          LDBI  0x01
          SBB
          JNC   f5                ; C out must be 1
          CPI   0x11
          JNZ   f5
          JMP   t6
f5:       OUTI  0x05
          HALT

t6:
          LDAI  0x01              ; C <- 0
          LDBI  0x01
          ADD
          LDAI  0x05
          LDBI  0x01
          SBB
          JNC   f6                ; C out must be 1
          CPI   0x03
          JNZ   f6
          JMP   t7
f6:       OUTI  0x06
          HALT

t7:
          LDAI  0xFF              ; C <- 1
          LDBI  0x01
          ADD
          LDAI  0x00
          LDBI  0x01
          SBB
          JNC   c7                ; C out must be 0
          JMP   f7
c7:
          CPI   0xFF
          JNZ   f7
          JMP   t8
f7:       OUTI  0x07
          HALT

t8:
          LDAI  0x01              ; C <- 0
          LDBI  0x01
          ADD
          LDAI  0x00
          LDBI  0x00
          SBB
          JNC   c8                ; C out must be 0
          JMP   f8
c8:
          CPI   0xFF
          JNZ   f8
          JMP   t9
f8:       OUTI  0x08
          HALT

t9:
          LDAI  0xFF              ; C <- 1
          LDBI  0x01
          ADD
          LDAI  0x34
          ACI   0x00
          JNC   c9                ; C out must be 0
          JMP   f9
c9:
          CPI   0x35
          JNZ   f9
          JMP   t10
f9:       OUTI  0x09
          HALT

t10:
          LDAI  0x01              ; C <- 0
          LDBI  0x01
          ADD
          LDAI  0xFF
          ACI   0x01
          JNC   f10                ; C out must be 1
          CPI   0x00
          JNZ   f10
          JMP   t11
f10:       OUTI  0x0A
          HALT

t11:
          LDAI  0x01              ; C <- 0
          LDBI  0x01
          ADD
          LDAI  0x35
          SBI   0x00
          JNC   f11                ; C out must be 1
          CPI   0x34
          JNZ   f11
          JMP   t12
f11:       OUTI  0x0B
          HALT

t12:
          LDAI  0xFF              ; C <- 1
          LDBI  0x01
          ADD
          LDAI  0x00
          SBI   0x01
          JNC   c12                ; C out must be 0
          JMP   f12
c12:
          CPI   0xFF
          JNZ   f12
          JMP   next
f12:       OUTI  0x0C
          HALT

next:     LDA   CNT
          INR
          STA   CNT
          JNZ   pass

          OUTI  0xAD
          HALT
