; mandel.asm -- the Mandelbrot set on the terminal. RAM-resident: loaded,
; not burned.
;
;   load:   make go-mandel         (asm/ram/mandel.asm -> RAM via L, then G)
;   check:  python3 docs/notes/test_mandel.py
;   watch:  make monitor           then type  G 8100  at the prompt
;   stop:   it draws one picture, 33 rows of 80, and RETs to the `>` prompt.
;           RESET if you cannot wait.
;
; The grid: cx = -2.0 .. +0.47 across 80 columns, cy = +1.0 .. -1.0 down 33
; rows, x steps 1/32 and y steps 1/16 because a terminal cell is about twice
; as tall as it is wide. Escape time, 24 iterations; each cell prints
; ramp[iterations], and ramp[24] is a cell that never escaped.
;
; THE RAMP IS IN RAM AND YOU CAN PATCH IT. 25 bytes at 0x8103. From the
; prompt, without reloading:   W 811B,23   draws the set in '#'.
;
; ---- THE ARITHMETIC. No multiply, no right shift, no add-with-carry (CIN
; is NOT(SA1 AND SA0), CW16 lands on nothing). So every number is ONE BYTE:
;
;   1/32 UNITS, OFFSET BINARY. A value v is stored as v*32 + 64, so 0.0 is
;   64 and the stored byte must stay in 1..127 (|v| < 2). Every range check
;   is then an unsigned compare: CPI 128 / JNC, or a SUB's borrow.
;
;   SQUARES BY TABLE. S[n] = floor(n*n/32) for n = 0..63 is x^2 in 1/32
;   units; Q[n] = floor(n*n/64) for n = 0..126 gives 2xy, because
;   (a+b)^2 - (a-b)^2 = 4ab, so 2|x||y| = Q[|x|+|y|] - Q[||x|-|y||]. The
;   sign of 2xy is sign(x) XOR sign(y), kept in SGN.
;
;   One iteration, with ax = |x|, ay = |y| (both 0..63):
;     escape if S[ax] + S[ay] >= 128                          |z|^2 >= 4
;     u = S[ax] + cxo - S[ay]   escape on borrow, u >= 128 or u == 0
;     v = cyo +/- (Q[ax+ay] - Q[|ax-ay|])   same three checks
;     x, y = u, v
;   where cxo = cx*32 + 64 is the column number itself (0..79) and
;   cyo = cy*32 + 64 steps 96, 94, .. 32 down the rows.
;
;   No sum can carry out of a byte where it matters: S[ax] + cxo <= 203,
;   S[ax] + S[ay] <= 248, and cyo + m is checked with the carry.
;
; THE TABLES ARE BUILT HERE, NOT LOADED. n*n by running sum, r += n then
; r += n-1 (each add stays under 256), r folded into q in 64s, so
; n*n = 64q + r and S[n] = 2q + (r >= 32). S at 0x8600, Q at 0x8680; Q's
; index is 0x80 + n, at most 0xFE, so it never crosses the page.
;
; RAM. Tables at 0x8600-0x86FE, variables at 0x8700-0x870D, both clear
; of the program and of BOTH monitors: PROG_monitor keeps 0x80E0-0x80FF,
; PROG_imon keeps 0x80A0-0x80FF (ring, cells, stack from 0x80DF down).
; Under imon the program runs with IE set and the RDA vector planted; a
; key typed mid-picture lands in imon's ring and Ctrl-C breaks out.
;
; REGISTER DISCIPLINE, monitor.asm's rules: B is destroyed by every
; immediate-ALU op and by INR/DCR/SHL/NOT; C does not survive a RET.
; Everything that must survive lives in a named RAM cell.
;
; FIRST-OF-ITS-KIND, listed before the first run (CLAUDE.md rule): BSUB
; and XRI from a RAM program (both in PROG_isa, from ROM); a SUB's borrow
; ending a range check on JNC (CPI's carry is life.asm/monitor idiom, a
; register SUB's is PROG_isa's); LDB addr as a second operand mid-loop;
; RAM writes and LDAX reads at 0x86xx-0x87xx, outside page 0x80/0x81; a RAM
; program running for seconds with imon's IE set. Everything
; else is life.asm idiom.
;
; OB counts the rows, as life.asm's does. The run is ~26,000 iterations
; and 2,640 characters; the wire alone is ~3 s at 9600 baud.

PUTC:     .equ  0x0345          ; monitor.asm, `make listing-monitor`
CRLF:     .equ  0x036B

MAXIT:    .equ  24
STAB:     .equ  0x86            ; S[n] at 0x8600 + n
QOFF:     .equ  0x80            ; Q[n] at 0x8680 + n

COL:      .equ  0x8700          ; column, 0..79, and cx*32 + 64
ROW:      .equ  0x8701          ; cy*32 + 64: 96, 94, .. 32
XO:       .equ  0x8702          ; x*32 + 64
YO:       .equ  0x8703          ; y*32 + 64
AX:       .equ  0x8704          ; |x|*32
AY:       .equ  0x8705          ; |y|*32
SGN:      .equ  0x8706          ; 1 when x and y differ in sign
SA:       .equ  0x8707          ; S[ax], then Q[ax+ay]
T:        .equ  0x8708          ; scratch: S[ay], then |2xy|
IT:       .equ  0x8709          ; iterations so far
N:        .equ  0x870A          ; table builder: n
QQ:       .equ  0x870B          ;   n*n / 64
RR:       .equ  0x870C          ;   n*n mod 64
LINES:    .equ  0x870D          ; rows printed, on OB

          .org  0x8100

          JMP   start
ramp:     .db   "  ..,,::;;--==++**xx%%##@" ; ramp[it], ramp[24] = inside

; ==== the square tables ======================================================
start:    CLR
          STA   N
          STA   QQ
          STA   RR
          STA   LINES
          STA   0x8600          ; S[0]
          STA   0x8680          ; Q[0]
gen:      LDA   N
          INR
          STA   N
          LDB   N               ; r += n
          LDA   RR
          ADD
          STA   RR
          CALL  norm
          LDA   N               ; r += n - 1
          DCR
          STA   T
          LDB   T
          LDA   RR
          ADD
          STA   RR
          CALL  norm
          LDA   N               ; Q[n] = q
          ADI   QOFF
          MOVCA
          LDBI  STAB
          LDA   QQ
          STAX
          LDA   N
          CPI   64
          JNC   gen_s           ; n < 64: S[n] too
          JMP   gen_next
gen_s:    LDA   QQ              ; S[n] = 2q + (r >= 32)
          SHL
          STA   T
          LDA   RR
          CPI   32
          JNC   gen_s_put
          LDA   T
          INR
          STA   T
gen_s_put: LDA  N
          MOVCA
          LDBI  STAB
          LDA   T
          STAX
gen_next: LDA   N
          CPI   126
          JNZ   gen
          JMP   picture

; ---- norm -- fold RR into QQ in 64s until RR < 64
norm:     LDA   RR
          CPI   64
          JNC   norm_done
          SUI   64
          STA   RR
          LDA   QQ
          INR
          STA   QQ
          JMP   norm
norm_done: RET

; ==== the picture ============================================================
picture:  LDAI  96
          STA   ROW
row_loop: CLR
          STA   COL
pix:      LDAI  64              ; z = 0
          STA   XO
          STA   YO
          CLR
          STA   IT

; ---- ax, ay and the sign of xy
iter:     CLR
          STA   SGN
          LDA   XO
          CPI   64
          JNC   x_neg           ; XO < 64: x < 0
          SUI   64
          STA   AX
          JMP   y_abs
x_neg:    LDBI  64
          BSUB                  ; A = 64 - XO
          STA   AX
          LDAI  1
          STA   SGN
y_abs:    LDA   YO
          CPI   64
          JNC   y_neg
          SUI   64
          STA   AY
          JMP   squares
y_neg:    LDBI  64
          BSUB
          STA   AY
          LDA   SGN
          XRI   1
          STA   SGN

; ---- |z|^2 >= 4 ?
squares:  LDA   AX
          MOVCA
          LDBI  STAB
          LDAX
          STA   SA              ; S[ax]
          LDA   AY
          MOVCA
          LDBI  STAB
          LDAX
          STA   T               ; S[ay]
          LDB   SA
          ADD
          CPI   128
          JNC   new_x
          JMP   esc

; ---- x' = x^2 - y^2 + cx
new_x:    LDA   SA
          LDB   COL
          ADD                   ; S[ax] + cxo, at most 203
          LDB   T
          SUB                   ; - S[ay]
          JNC   esc             ; borrow: x' < -2
          CPI   128
          JNC   x_hi_ok
          JMP   esc             ; x' >= 2
x_hi_ok:  CPI   0
          JNZ   x_ok
          JMP   esc             ; x' = -2
x_ok:     STA   XO              ; old x is done with: AX, AY, SGN hold it

; ---- |2xy| = Q[ax+ay] - Q[|ax-ay|]
          LDA   AX
          LDB   AY
          ADD
          ADI   QOFF
          MOVCA
          LDBI  STAB
          LDAX
          STA   SA              ; Q[ax+ay]
          LDA   AX
          LDB   AY
          SUB
          JNC   d_neg           ; ax < ay
          JMP   d_abs
d_neg:    LDA   AX
          LDB   AY
          BSUB                  ; A = ay - ax
d_abs:    ADI   QOFF
          MOVCA
          LDBI  STAB
          LDAX
          STA   T               ; Q[|ax-ay|]
          LDA   SA
          LDB   T
          SUB
          STA   T               ; |2xy|

; ---- y' = 2xy + cy
          LDA   SGN
          CPI   0
          JNZ   y_minus
          LDA   ROW
          LDB   T
          ADD
          JNC   y_plus_ok
          JMP   esc             ; carried: y' >= 2
y_plus_ok: CPI  128
          JNC   y_ok
          JMP   esc             ; y' >= 2
y_minus:  LDA   ROW
          LDB   T
          SUB
          JNC   esc             ; borrow: y' < -2
          CPI   0
          JNZ   y_ok
          JMP   esc             ; y' = -2
y_ok:     STA   YO

          LDA   IT
          INR
          STA   IT
          CPI   MAXIT
          JNZ   iter            ; IT = MAXIT falls through: inside

; ---- print ramp[IT]
esc:      LDA   IT
          ADI   <ramp
          MOVCA
          LDBI  >ramp
          LDAX
          CALL  PUTC
          LDA   COL
          INR
          STA   COL
          CPI   80
          JNZ   pix
          CALL  CRLF
          LDA   LINES
          INR
          STA   LINES
          OUT
          LDA   ROW
          SUI   2
          STA   ROW
          CPI   30
          JNZ   row_loop
          RET                   ; back to the monitor's prompt
