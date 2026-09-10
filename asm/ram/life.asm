; life.asm -- Rule 30 on the terminal. RAM-resident: loaded, not burned.
;
;   load:   make go-life           (asm/ram/life.asm -> RAM via L, then G)
;   check:  python3 docs/notes/test_life.py
;   watch:  make monitor           then type  G 8100  at the prompt
;   stop:   Enter. Any other key is eaten. RET lands on the `>` prompt.
;
; A one-dimensional cellular automaton, 64 cells wide, one generation per
; line, scrolling until Enter. Each cell's next state is a function of
; itself and its two neighbours, read out of an 8-byte table indexed by
; left*4 + self*2 + right. Rule 30 (0b00011110) is chaotic and, from a
; single seed cell, draws the well-known triangle. OB counts the rows.
;
; THE SEED IS SW1. Its eight bits land in cells 29..36 (bit 7 leftmost).
; All switches off gives the single centre cell, 32. Change the switches,
; RESET is NOT needed: `G 8100` again reads them afresh.
;
; THE RULE IS IN RAM AND YOU CAN PATCH IT. The table sits at 0x8103, one
; byte per neighbourhood, 0 or 1. From the prompt, without reloading:
;
;     Rule 110      W 8107,0    W 8108,1    W 8109,1
;     Rule 90       W 8104,1    W 8105,0    W 8106,1  W 8107,0  W 8108,1
;     Rule 30       W 8104,1    W 8105,1    W 8106,1  W 8107,1  W 8108,0
;                   W 8109,0    (back to the table as loaded)
;
; RAM. Data lives in 0x8000-0x80DF. RAM is proven whole, 0x8000-0xFFFF
; (Rico, 2026-09-07), so this is a convention, not a constraint -- it just
; keeps the two rows and the loop counter in one place with the monitor's
; own cells. CUR is 0x8001..0x8040 and NXT is 0x8081..0x80C0, both in page
; 0x80 so the next row is the same index plus a fixed 0x80 (ROW). Cell 0
; (0x8000) and cell 65 (0x8041) are guard zeros so an edge cell reads a
; dead neighbour and never wanders off the row. 0x8000-0x80CF is cleared at
; start, because RAM powers up as garbage; the variables at 0x80D0-0x80D6
; sit just above that. The monitor's 0x80E0-0x80FF (its cells and the
; stack a RET needs) is never touched.
;
; REGISTER DISCIPLINE, monitor.asm's rules: B is destroyed by every
; immediate-ALU op and by INR/DCR/SHL/NOT, so the pointer page is reloaded
; with LDBI PAGE before every LDAX/STAX; nothing lives in C across a CALL.
;
; FIRST-OF-ITS-KIND, listed before the first run (CLAUDE.md rule): a CALL
; from RAM into the monitor's ROM subroutines that RETs back into RAM
; (hello.asm only ever RETs out); a RAM program reading SW1 at 0x4000
; (every card-zero image so far ran from ROM); and SHL's Z flag ending a
; loop (the mask walk). Everything else is monitor/serrx idiom.
;
; The wire is 9600 baud, so a 66-character row takes ~70ms and the
; automaton runs about fourteen generations a second; the arithmetic is a
; few milliseconds of that. No delay loop is needed.

SER_RBR:  .equ  0x4800
SER_LSR:  .equ  0x4805
SW1:      .equ  0x4000          ; card zero, the DIP switch
PUTC:     .equ  0x0345          ; monitor.asm, `make listing-monitor`
CRLF:     .equ  0x036B

PAGE:     .equ  0x80            ; the page holding both rows, proven RAM
CUR:      .equ  0x01            ; index of cell 1; cell k is CUR+k-1
NXT:      .equ  0x81            ; cell k of the next row is NXT+k-1
ROW:      .equ  0x80            ; NXT - CUR: the same cell, next row
I:        .equ  0x80D0          ; cell index, 1..64
IDX:      .equ  0x80D1          ; the neighbourhood, 0..7
NEW:      .equ  0x80D2          ; the computed cell
MASK:     .equ  0x80D3          ; the seed's walking bit
POS:      .equ  0x80D4          ; where the seed bit lands
SW:       .equ  0x80D5          ; SW1 as read
GEN:      .equ  0x80D6          ; rows printed, on OB

          .org  0x8100

          JMP   start
rule:     .db   0, 1, 1, 1, 1, 0, 0, 0      ; Rule 30, indexed by L*4+C*2+R

; ---- clear 0x8000-0x80CF: both rows and the two CUR guards. Stops at
; 0xD0 so the variables above and the monitor's page are untouched.
start:    CLR
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
          CLR
          STA   GEN

; ---- seed from SW1: bit 0 -> cell 36, walking the mask up to bit 7 -> 29
          LDA   SW1
          STA   SW
          CPI   0
          JNZ   seeded
          MVI   0x8020, 1       ; all off: the single centre cell, 32
          JMP   main
seeded:   LDAI  0x01
          STA   MASK
          LDAI  CUR + 35        ; cell 36
          STA   POS
seed_bit: LDB   MASK
          LDA   SW
          AND
          JNZ   bit_on
          CLR
          JMP   bit_put
bit_on:   LDAI  1
bit_put:  STA   NEW
          LDBI  PAGE
          LDA   POS
          MOVCA
          LDA   NEW
          STAX
          LDA   POS
          DCR
          STA   POS
          LDA   MASK
          SHL                   ; 0x80 << 1 = 0x00: Z ends the walk
          STA   MASK
          JNZ   seed_bit

; ==== one generation per pass ===============================================
main:
; ---- print CUR: '#' for 1, ' ' for 0
          LDAI  1
          STA   I
pr_loop:  LDBI  PAGE
          LDA   I
          MOVCA
          LDAX
          CPI   0
          JNZ   pr_on
          LDAI  ' '
          JMP   pr_put
pr_on:    LDAI  '#'
pr_put:   CALL  PUTC
          LDA   I
          INR
          STA   I
          CPI   65
          JNZ   pr_loop
          CALL  CRLF
          LDA   GEN
          INR
          STA   GEN
          OUT

; ---- step: NXT[i] = rule[ CUR[i-1]*4 + CUR[i]*2 + CUR[i+1] ]
          LDAI  1
          STA   I
st_loop:  LDA   I
          DCR                   ; left neighbour (the guard at i=1)
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
          INR                   ; right neighbour (the guard at i=64)
          MOVCA
          LDBI  PAGE
          LDAX
          LDB   IDX
          ADD                   ; A = the neighbourhood, 0..7
          ADI   <rule
          MOVCA
          LDBI  >rule
          LDAX                  ; A = rule[idx]
          STA   NEW
          LDA   I
          ADI   ROW             ; the same cell in the next row
          MOVCA
          LDBI  PAGE
          LDA   NEW
          STAX
          LDA   I
          INR
          STA   I
          CPI   65
          JNZ   st_loop

; ---- copy NXT -> CUR
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

; ---- a key? DR is LSR bit 0. RBR is read once, only when DR says so.
          LDA   SER_LSR
          LDBI  0x01
          AND
          JNZ   key
          JMP   main
key:      LDA   SER_RBR
          CPI   0x0D
          JNZ   main            ; not Enter: eaten
          RET                   ; Enter: back to the monitor's prompt
