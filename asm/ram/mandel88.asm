; mandel88.asm -- the Mandelbrot set in 8.8 fixed point, and it zooms.
; RAM-resident: loaded, not burned.
;
;   load:   make go-mandel88       (asm/ram/mandel88.asm -> RAM via L, then G)
;   check:  python3 docs/notes/test_mandel88.py
;   watch:  make monitor           then type  G 8100  at the prompt
;   stop:   one picture, 33 rows of 80, then RET to the `>` prompt.
;           Ctrl-C under imon; RESET if you cannot wait.
;
; NEEDS THE CARRY MICROCODE (U9 0x4102 U15 0x9BC4 U23 0x8A40, 2026-10-06).
; mandel.asm is the same picture in one-byte 1/32 units, written when there
; was no add-with-carry; it stays as the witness for the old microcode.
;
; ---- THE WINDOW IS IN RAM AND YOU CAN PATCH IT. Four 16-bit cells, low
; byte first, signed 8.8 (1.0 = 0x0100):
;
;     0x811C  CX0   left edge          default -2.0   00 FE
;     0x811E  CY0   top edge           default +1.0   00 01
;     0x8120  DX    step across        default 1/32   08 00
;     0x8122  DY    step down          default 1/16   10 00
;
; cx = CX0 + col*DX, cy = CY0 - row*DY. The default is mandel.asm's grid.
; 8x zoom on the cardioid's edge above elephant valley, from the prompt:
;
;     W 811C,48   W 811D,00   W 811E,90   W 811F,00
;     W 8120,01   W 8122,02                 then  G 8100
;
; The ramp is at 0x8103 as before (25 bytes; W 811B,23 draws inside as '#').
;
; ---- THE ARITHMETIC. Every value is a signed 16-bit 8.8 number; every
; 16-bit add is ADD then ADC, every subtract SUB then SBB. LDA/LDB/LDAI/STA
; hold the flags (U48 lets them change only when the ALU is the source), so
; a carry crosses a load to reach the high byte's ADC.
;
; SQUARES ONLY. 2xy = (x+y)^2 - x^2 - y^2, so no multiply. A square comes
; from one 256-byte table T[l] = floor(l*l/256), built at start: with a
; magnitude n = 256h + l (h <= 3),
;
;     n*n/256 = 256*h*h + 2*h*l + l*l/256
;
; and the first two terms are integers, so floor(n*n/256) is EXACTLY
; 256*h*h + 2*h*l + T[l]. sq adds l 2h times (16-bit, ACI) and h*h into the
; high byte. T is built with a 16-bit running sum, n*n = (n-1)^2 + n + n-1.
;
; One iteration:
;     escape if |x| >= 2 or |y| >= 2         (high byte of the magnitude)
;     X2 = sq|x|, Y2 = sq|y|
;     escape if X2 + Y2 >= 4.0               (high byte of the sum >= 4)
;     y' = sq|x+y| - X2 - Y2 + cy            |x+y| < 4, so h <= 3
;     x' = X2 - Y2 + cx
; Nothing overflows 16 bits: |x'| < 6, |y'| < 10.
;
; RAM. Table at 0x8600-0x86FF, variables at 0x8700-0x871F. Both monitors'
; pages (0x80A0-0x80FF) untouched. Under imon the RDA interrupt can land
; between ADD and ADC: imon's isr starts with PUSHF, so the carry survives.
;
; REGISTER DISCIPLINE, monitor.asm's rules: B is destroyed by every
; immediate-ALU op and by INR/DCR/SHL/NOT; C does not survive a RET.
;
; FIRST-OF-ITS-KIND, listed before the first run (CLAUDE.md rule): ADC,
; SBB and ACI from a RAM program (PROG_carry ran them from ROM, bigxfer runs
; ACI); a carry crossing LDA/LDB/LDAI/STA rows into ADC/SBB/ACI; SBB after
; a SUB whose operands came from RAM; a table page written whole (256
; STAX at 0x8600-0x86FF). Everything else is mandel.asm idiom.
;
; OB counts the rows, as mandel.asm's does.

PUTC:     .equ  0x0345          ; monitor.asm, `make listing-monitor`
CRLF:     .equ  0x036B

MAXIT:    .equ  24
TPAGE:    .equ  0x86            ; T[l] at 0x8600 + l

CX0L:     .equ  0x811C          ; the window, in the program: patch with W
CX0H:     .equ  0x811D
CY0L:     .equ  0x811E
CY0H:     .equ  0x811F
DXL:      .equ  0x8120
DXH:      .equ  0x8121
DYL:      .equ  0x8122
DYH:      .equ  0x8123

CXL:      .equ  0x8700          ; this column's cx
CXH:      .equ  0x8701
CYL:      .equ  0x8702          ; this row's cy
CYH:      .equ  0x8703
XL:       .equ  0x8704          ; z
XH:       .equ  0x8705
YL:       .equ  0x8706
YH:       .equ  0x8707
X2L:      .equ  0x8708          ; x^2
X2H:      .equ  0x8709
Y2L:      .equ  0x870A          ; y^2
Y2H:      .equ  0x870B
NL:       .equ  0x870C          ; sq's argument, a magnitude
NH:       .equ  0x870D
RL:       .equ  0x870E          ; sq's result
RH:       .equ  0x870F
K:        .equ  0x8710          ; sq's loop count
IT:       .equ  0x8711          ; iterations so far
COL:      .equ  0x8712
ROW:      .equ  0x8713
LINES:    .equ  0x8714          ; rows printed, on OB
TL:       .equ  0x8715          ; table builder: l
SQL:      .equ  0x8716          ;   l*l
SQH:      .equ  0x8717
TMP:      .equ  0x8718

          .org  0x8100

          JMP   start
ramp:     .db   "  ..,,::;;--==++**xx%%##@" ; ramp[it], ramp[24] = inside
win:      .db   0x00, 0xFE      ; CX0 -2.0
          .db   0x00, 0x01      ; CY0 +1.0
          .db   0x08, 0x00      ; DX  1/32
          .db   0x10, 0x00      ; DY  1/16
hsq:      .db   0, 1, 4, 9      ; h*h for sq, h = 0..3

; ==== the square table: T[l] = floor(l*l/256) ================================
start:    CLR
          STA   LINES
          STA   TL
          STA   SQL
          STA   SQH
          STA   0x8600          ; T[0]
gen:      LDA   TL
          INR
          STA   TL
          LDB   TL              ; l*l += l
          LDA   SQL
          ADD
          STA   SQL
          LDA   SQH
          ACI   0x00
          STA   SQH
          LDA   TL              ; l*l += l - 1
          DCR
          STA   TMP
          LDB   TMP
          LDA   SQL
          ADD
          STA   SQL
          LDA   SQH
          ACI   0x00
          STA   SQH
          LDA   TL              ; T[l] = the high byte
          MOVCA
          LDBI  TPAGE
          LDA   SQH
          STAX
          LDA   TL
          CPI   0xFF
          JNZ   gen

; ==== the picture ============================================================
          CLR
          STA   ROW
          LDA   CY0L
          STA   CYL
          LDA   CY0H
          STA   CYH
row_loop: CLR
          STA   COL
          LDA   CX0L
          STA   CXL
          LDA   CX0H
          STA   CXH
pix:      CLR                   ; z = 0
          STA   XL
          STA   XH
          STA   YL
          STA   YH
          STA   IT

; ---- X2 = |x|^2, escaping on |x| >= 2
iter:     LDA   XL
          STA   NL
          LDA   XH
          STA   NH
          CPI   0x80
          JNC   x_abs           ; XH < 0x80: x >= 0
          LDAI  0x00            ; N = 0 - x
          LDB   XL
          SUB
          STA   NL
          LDAI  0x00
          LDB   XH
          SBB
          STA   NH
x_abs:    LDA   NH
          CPI   2
          JNC   x_ok
          JMP   esc             ; |x| >= 2
x_ok:     CALL  sq
          LDA   RL
          STA   X2L
          LDA   RH
          STA   X2H

; ---- Y2 = |y|^2, escaping on |y| >= 2
          LDA   YL
          STA   NL
          LDA   YH
          STA   NH
          CPI   0x80
          JNC   y_abs
          LDAI  0x00
          LDB   YL
          SUB
          STA   NL
          LDAI  0x00
          LDB   YH
          SBB
          STA   NH
y_abs:    LDA   NH
          CPI   2
          JNC   y_ok
          JMP   esc             ; |y| >= 2
y_ok:     CALL  sq
          LDA   RL
          STA   Y2L
          LDA   RH
          STA   Y2H

; ---- |z|^2 >= 4 ?
          LDA   X2L
          LDB   Y2L
          ADD                   ; only the carry is wanted
          LDA   X2H
          LDB   Y2H
          ADC
          CPI   4
          JNC   z_ok
          JMP   esc

; ---- (x+y)^2
z_ok:     LDA   XL
          LDB   YL
          ADD
          STA   NL
          LDA   XH
          LDB   YH
          ADC
          STA   NH
          CPI   0x80
          JNC   s_abs
          LDAI  0x00
          LDB   NL
          SUB
          STA   NL
          LDAI  0x00
          LDB   NH
          SBB
          STA   NH
s_abs:    CALL  sq              ; |x+y| < 4: h <= 3

; ---- y' = (x+y)^2 - X2 - Y2 + cy
          LDA   RL
          LDB   X2L
          SUB
          STA   RL
          LDA   RH
          LDB   X2H
          SBB
          STA   RH
          LDA   RL
          LDB   Y2L
          SUB
          STA   RL
          LDA   RH
          LDB   Y2H
          SBB
          STA   RH
          LDA   RL
          LDB   CYL
          ADD
          STA   YL
          LDA   RH
          LDB   CYH
          ADC
          STA   YH

; ---- x' = X2 - Y2 + cx
          LDA   X2L
          LDB   Y2L
          SUB
          STA   XL
          LDA   X2H
          LDB   Y2H
          SBB
          STA   XH
          LDA   XL
          LDB   CXL
          ADD
          STA   XL
          LDA   XH
          LDB   CXH
          ADC
          STA   XH

          LDA   IT
          INR
          STA   IT
          CPI   MAXIT
          JNZ   iter            ; IT = MAXIT falls through: inside

; ---- print ramp[IT], step cx
esc:      LDA   IT
          ADI   <ramp
          MOVCA
          LDBI  >ramp
          LDAX
          CALL  PUTC
          LDA   CXL             ; cx += DX
          LDB   DXL
          ADD
          STA   CXL
          LDA   CXH
          LDB   DXH
          ADC
          STA   CXH
          LDA   COL
          INR
          STA   COL
          CPI   80
          JNZ   pix

; ---- end of row: step cy
          CALL  CRLF
          LDA   LINES
          INR
          STA   LINES
          OUT
          LDA   CYL             ; cy -= DY
          LDB   DYL
          SUB
          STA   CYL
          LDA   CYH
          LDB   DYH
          SBB
          STA   CYH
          LDA   ROW
          INR
          STA   ROW
          CPI   33
          JNZ   row_loop
          RET                   ; back to the monitor's prompt

; ==== sq -- R = floor(N*N/256) for a magnitude N < 0x400 =====================
; R = T[l] + 2h copies of l + 256*h*h, where N = 256h + l.
sq:       LDA   NL
          MOVCA
          LDBI  TPAGE
          LDAX
          STA   RL
          CLR
          STA   RH
          LDA   NH
          SHL
          STA   K               ; 2h
sq_loop:  LDA   K
          CPI   0
          JNZ   sq_add
          JMP   sq_h
sq_add:   LDB   NL              ; R += l
          LDA   RL
          ADD
          STA   RL
          LDA   RH
          ACI   0x00
          STA   RH
          LDA   K
          DCR
          STA   K
          JMP   sq_loop
sq_h:     LDA   NH              ; RH += h*h
          ADI   <hsq
          MOVCA
          LDBI  >hsq
          LDAX
          LDB   RH
          ADD
          STA   RH
          RET
