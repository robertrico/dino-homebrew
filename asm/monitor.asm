; monitor.asm -- the serial monitor. NEVER HALTS. First program after phase G.
;
;   build:  make assemble-monitor          (asm/monitor.asm -> roms/PROG_monitor.bin)
;   check:  python3 docs/notes/test_monitor.py     <- THE ANSWER KEY
;   burn:   make burn-prog-monitor
;   talk:   make monitor                   (minicom, 9600 8N1)
;
; `asm.py --run` reports UNORACLED for this image: it polls LSR, which the
; oracle refuses to model (PHASE_G.md SECTION 5). The host test drives the
; same bytes through simulate(serial_in=...) -- a scripted stimulus, not a
; UART model -- and compares the WHOLE transcript. That is the check.
;
; THE LANGUAGE. One command per line, CR ends it. Five commands:
;
;     D addr          dump one byte             > D 8044
;                                               0x00
;     W addr,val      write one byte, then       > W 8044,A5
;                     READ IT BACK and print     0xA5
;                     what is really there
;     O addr          put [addr] on OB           > O 8044
;                     (the LEDs; prints nothing)
;     L addr,len      then 2*len HEX DIGITS      > L 8100,4
;                     follow -- typed or         115A5F34
;                     pasted, echoed, spaces     0xF0
;                     and newlines skipped --    >
;                     and land at addr. Reply:
;                     their 8-bit sum, the
;                     witness. A non-hex char
;                     is `?` and stops the load
;     G addr          CALL addr. RET comes back  > G 8100
;                     to the prompt; HALT stays  >
;                     halted (RESET recovers)
;
; L and G together are the loader. docs/notes/dinoload.py assembles an
; .asm and sends the `L` line and the hex for you (`make load-hello`);
; then `make monitor` and type `G 8100` yourself, or `--go` sends it.
; A loaded program lives at 0x8100 and up (`.org 0x8100`), may CALL putc /
; puthex / puts / crlf by their ROM addresses (`make listing-monitor`), and
; ends with RET. It must not touch 0x80E0-0x80FF: that is this monitor's
; state and the stack the RET needs.
;
; Hex, 1-4 digits, case does not matter, `0x` prefix optional, spaces
; ignored. Anything else on the line gets `?` and NOTHING is written.
;
; ADDRESSES ARE THE WHOLE 16-BIT MAP, NOT A RAM OFFSET. RAM is 0x8000-0xFFFF.
;     D 0         the reset vector (0x11, LDAI)     ROM
;     W 44,A5     writes into ROM, and the read-back shows the ROM byte --
;                 the reply is the witness, not the wish
;     W 8044,A5   RAM. This is the one you want.
; The monitor's own state lives at 0x80E0-0x80FF (variables, then the
; stack). W into those cells is allowed and will confuse it. RESET recovers.
;
; No line buffer and no backspace: digits shift into a four-nibble register
; as they arrive, so a typo cannot be un-typed. Finish the line, take the
; `?`, type it again. Extra leading digits fall off the top: D 18046 is
; D 8046.
;
; REGISTER DISCIPLINE, the two rules that bite on this machine:
;   B is destroyed by every immediate-ALU op (CPI/ADI/SUI/ANI...) and by
;     INR/DCR/SHL/NOT, which stage a constant there. Never hold a pointer
;     half in B across one of those. Pointers are reloaded from RAM cells.
;   C is RET's scratch register. Nothing survives a RET in C.
; Everything that must survive lives in a named RAM cell.
;
; The UART init and both polling loops are PROG_serrx verbatim, which is
; on silicon. The only new thing on the wire is the program.

SER_THR:  .equ  0x4800
SER_RBR:  .equ  0x4800
SER_DLL:  .equ  0x4800
SER_IER:  .equ  0x4801
SER_DLM:  .equ  0x4801
SER_FCR:  .equ  0x4802
SER_LCR:  .equ  0x4803
SER_MCR:  .equ  0x4804
SER_LSR:  .equ  0x4805

; ---- RAM. THE PROVEN PAGE. Every bench-green image (isa, mem, stack, hello,
; the suite) keeps its cells and its stack inside 0x8000-0x80FF. The first
; burn of this monitor put them at 0xFFE0-0xFFFF -- the first time anything
; drove RAM's A9-A14 -- and the machine streamed garbage to the UART
; (2026-09-04). Whether RAM above 0x80FF works is OPEN and needs its own
; witness image; until it has one, nothing lives up there.
STACK:    .equ  0x80FF          ; PUSH writes at [SP] then decrements
CMD:      .equ  0x80E0          ; command letter, 0 = none yet this line
ERR:      .equ  0x80E1          ; nonzero = the line is bad, answer `?`
FIELD:    .equ  0x80E2          ; 0 = filling the address, 1 = the value
NDIG:     .equ  0x80E3          ; hex digits seen in the current field
N0:       .equ  0x80E4          ; nibble shift register: N0 newest ...
N1:       .equ  0x80E5
N2:       .equ  0x80E6
N3:       .equ  0x80E7          ; ... N3 oldest
ADRH:     .equ  0x80E8          ; packed address
ADRL:     .equ  0x80E9
VAL:      .equ  0x80EA          ; packed value
CH:       .equ  0x80EB          ; the character being parsed
T_CH:     .equ  0x80EC          ; putc's scratch
T_BYTE:   .equ  0x80ED          ; puthex's scratch
T_CNT:    .equ  0x80EE
PTRH:     .equ  0x80EF          ; puts' string pointer
PTRL:     .equ  0x80F0
CNTH:     .equ  0x80F1          ; L's byte count, 16 bits
CNTL:     .equ  0x80F2
SUM:      .equ  0x80F3          ; L's running 8-bit sum

          .org  0x0000

          LDAI  0xFF            ; poison OB
          OUT
          LXISP STACK

; ---- UART init, PROG_serrx verbatim: 9600 8N1, FIFO on, MCR = 0
          LDAI  0x83
          STA   SER_LCR
          LDAI  0x18
          STA   SER_DLL
          LDAI  0x00
          STA   SER_DLM
          LDAI  0x03
          STA   SER_LCR
          LDAI  0x07
          STA   SER_FCR
          LDAI  0x00
          STA   SER_IER
          LDAI  0x00
          STA   SER_MCR

          MVI   PTRL, <s_banner
          MVI   PTRH, >s_banner
          CALL  puts

; ==== a new line: clear the parse state, prompt ============================
new_line: CLR
          STA   CMD
          STA   ERR
          STA   FIELD
          STA   NDIG
          STA   N0
          STA   N1
          STA   N2
          STA   N3
          MVI   PTRL, <s_prompt
          MVI   PTRH, >s_prompt
          CALL  puts

; ==== one character ========================================================
next_ch:  CALL  getc
          CPI   0x0A            ; LF: swallowed, not echoed
          JNZ   not_lf
          JMP   next_ch
not_lf:   CPI   0x0D            ; CR: the line is complete
          JNZ   not_cr
          JMP   do_line
not_cr:   CALL  putc            ; echo. putc returns with A intact
          STA   CH

          LDA   CMD
          CPI   0
          JNZ   have_cmd
; ---- no command letter yet: skip blanks, take the first other character
          LDA   CH
          CPI   ' '
          JNZ   set_cmd
          JMP   next_ch
set_cmd:  CPI   'a'             ; fold lower case: 'a'.. -> 'A'..
          JNC   store_cmd       ; A < 'a', leave it
          SUI   0x20
store_cmd: STA  CMD
          JMP   next_ch

; ---- inside the operand field
have_cmd: LDA   CH
          CPI   ' '
          JNZ   not_sp
          JMP   next_ch
not_sp:   CPI   'x'             ; the `0x` prefix: the 0 was a harmless
          JNZ   not_x           ; leading nibble, the x is noise
          JMP   next_ch
not_x:    CPI   'X'
          JNZ   not_xx
          JMP   next_ch
not_xx:   CPI   0x2C            ; ',' -- the literal would split the operand
          JNZ   not_comma
; ---- comma: the address is finished, start the value
          LDA   FIELD
          CPI   0
          JNZ   bad             ; a second comma
          LDA   NDIG
          CPI   0
          JNZ   comma_ok
          JMP   bad             ; a comma with no address before it
comma_ok: CALL  pack            ; ADRH:ADRL <- N3 N2 N1 N0
          LDAI  1
          STA   FIELD
          CLR
          STA   NDIG
          STA   N0
          STA   N1
          STA   N2
          STA   N3
          JMP   next_ch
; ---- anything else must be a hex digit
not_comma: CALL hexval          ; A <- 0..15, or 0xFF
          CPI   0xFF
          JNZ   shift_in
          JMP   bad
shift_in: STA   CH              ; the nibble; CH's character is spent
          LDA   N2
          STA   N3
          LDA   N1
          STA   N2
          LDA   N0
          STA   N1
          LDA   CH
          STA   N0
          LDA   NDIG
          INR
          STA   NDIG
          JMP   next_ch

bad:      LDAI  1
          STA   ERR
          JMP   next_ch

; ==== CR: run the line ======================================================
do_line:  CALL  crlf
          LDA   ERR
          CPI   0
          JNZ   what
          LDA   CMD
          CPI   0
          JNZ   has_cmd
          JMP   new_line        ; an empty line: just a new prompt
; ---- close the open field
has_cmd:  LDA   FIELD
          CPI   0
          JNZ   fin_val
          LDA   NDIG            ; address field still open
          CPI   0
          JNZ   fin_adr
          JMP   what            ; a command with no address
fin_adr:  CALL  pack
          JMP   dispatch
fin_val:  LDA   NDIG            ; value field open
          CPI   0
          JNZ   fin_val2
          JMP   what            ; `W addr,` with nothing after the comma
fin_val2: CALL  lo8
          STA   VAL
; ---- which command
dispatch: LDA   CMD
          CPI   'D'
          JNZ   not_d
          LDA   FIELD           ; D takes no value
          CPI   0
          JNZ   what
          CALL  show
          JMP   new_line
not_d:    CPI   'W'
          JNZ   not_w
          LDA   FIELD           ; W needs one
          CPI   0
          JNZ   w_ok
          JMP   what
w_ok:     LDA   VAL
          LDB   ADRH
          LDC   ADRL
          STAX                  ; [ADR] <- VAL
          CALL  show            ; and print what is REALLY there now
          JMP   new_line
not_w:    CPI   'O'
          JNZ   not_o
          LDA   FIELD           ; O takes no value
          CPI   0
          JNZ   what
          LDB   ADRH
          LDC   ADRL
          LDAX
          OUT                   ; [ADR] on the LEDs. Says nothing here
          JMP   new_line
not_o:    CPI   'G'
          JNZ   not_g
          LDA   FIELD           ; G takes no value
          CPI   0
          JNZ   what
          CALL  go              ; a RET in the program lands here
          JMP   new_line
not_g:    CPI   'L'
          JNZ   what
          LDA   FIELD           ; L needs a length
          CPI   0
          JNZ   l_ok
          JMP   what
; ---- L addr,len: the value field is the whole 16-bit length, N3..N0
l_ok:     LDA   N3
          CALL  sh4
          MOVBA
          LDA   N2
          ADD
          STA   CNTH
          LDA   VAL
          STA   CNTL
          CLR
          STA   SUM
; the load loop. The payload is HEX TEXT, two digits per byte, echoed as it
; arrives so a human at minicom sees what they typed; spaces, CR and LF
; between digits are skipped and not counted. NDIG is reused as the
; half flag (0 = waiting for the high nibble) and N3 parks that nibble.
; A non-hex character is `?` and the load stops: bytes already landed
; stay, the sum is never printed.
          CLR
          STA   NDIG
l_loop:   LDA   CNTL
          LDB   CNTH
          OR
          JNZ   l_more
          JMP   l_done
l_more:   CALL  getc
          CPI   0x0A            ; LF: skipped, not echoed, like the parser
          JNZ   l_notlf
          JMP   l_loop
l_notlf:  CPI   0x0D            ; CR: skipped, not echoed
          JNZ   l_notcr
          JMP   l_loop
l_notcr:  CALL  putc            ; echo
          CPI   ' '
          JNZ   l_notsp
          JMP   l_loop
l_notsp:  CALL  hexval          ; A <- 0..15 or 0xFF
          CPI   0xFF
          JNZ   l_nib
          CALL  crlf            ; end the echoed line
          JMP   what            ; `?`, and the load is over
l_nib:    STA   CH
          LDA   NDIG
          CPI   0
          JNZ   l_lo
          LDA   CH              ; high nibble: park it, wait for the low
          STA   N3
          LDAI  1
          STA   NDIG
          JMP   l_loop
l_lo:     CLR
          STA   NDIG
          LDA   N3
          CALL  sh4
          MOVBA
          LDA   CH
          ADD                   ; A = the byte
          STA   CH
          LDB   ADRH
          LDC   ADRL
          STAX                  ; [ADR] <- the byte
          LDA   SUM
          MOVBA
          LDA   CH
          ADD
          STA   SUM
          LDA   ADRL            ; ADR += 1
          INR
          STA   ADRL
          JNZ   l_count
          LDA   ADRH
          INR
          STA   ADRH
l_count:  LDA   CNTL            ; CNT -= 1
          DCR
          STA   CNTL
          CPI   0xFF
          JNZ   l_loop
          LDA   CNTH            ; low byte wrapped: borrow from the high
          DCR
          STA   CNTH
          JMP   l_loop
l_done:   CALL  crlf            ; end the echoed payload's line
          LDAI  '0'             ; "0x", the sum, CRLF: the witness
          CALL  putc
          LDAI  'x'
          CALL  putc
          LDA   SUM
          CALL  puthex
          CALL  crlf
          JMP   new_line

what:     LDAI  '?'
          CALL  putc
          CALL  crlf
          JMP   new_line

; ==== subroutines ============================================================

; go -- jump to ADR. Reached by CALL, so the return address is on the
; stack and a RET in the loaded program comes straight back to the
; dispatcher. JMPX takes B:C and touches nothing else. A program that
; HALTs instead stays halted; RESET recovers, RAM survives it.
go:       LDB   ADRH
          LDC   ADRL
          JMPX

; show -- print "0x", [ADR] in hex, CRLF
show:     LDAI  '0'
          CALL  putc
          LDAI  'x'
          CALL  putc
          LDB   ADRH
          LDC   ADRL
          LDAX
          CALL  puthex
          CALL  crlf
          RET

; puthex -- A as two upper-case hex digits. There is no SHR, so the high
; nibble is counted off by repeated subtraction; what is left IS the low
; nibble, so no mask is needed either.
puthex:   STA   T_BYTE
          CLR
          STA   T_CNT
ph_loop:  LDA   T_BYTE
          CPI   0x10
          JNC   ph_done         ; A < 0x10: the high nibble is counted
          SUI   0x10
          STA   T_BYTE
          LDA   T_CNT
          INR
          STA   T_CNT
          JMP   ph_loop
ph_done:  LDA   T_CNT
          CALL  nib_asc
          CALL  putc
          LDA   T_BYTE
          CALL  nib_asc
          CALL  putc
          RET

; nib_asc -- A = 0..15 -> '0'..'9', 'A'..'F'
nib_asc:  ADI   '0'
          CPI   0x3A            ; '9' + 1
          JNC   na_done         ; A < ':' -- a digit
          ADI   7               ; ':' -> 'A'
na_done:  RET

; hexval -- A = a character -> 0..15, or 0xFF if it is not a hex digit.
; Both cases accepted. JNC is taken when the last SUB/CPI found A < operand.
hexval:   SUI   '0'
          JNC   hv_bad          ; below '0'
          CPI   10
          JNC   hv_ok           ; '0'..'9'
          CPI   0x31            ; 'a' - '0'
          JNC   hv_up           ; below 'a': already upper, or junk
          SUI   0x20            ; 'a'.. -> 'A'..
hv_up:    SUI   7               ; 'A' - '0' - 7 = 10
          CPI   10
          JNC   hv_bad          ; ':'..'@' land here
          CPI   16
          JNC   hv_ok           ; 'A'..'F'
hv_bad:   LDAI  0xFF
hv_ok:    RET

; pack -- ADRH:ADRL <- N3 N2 N1 N0
pack:     LDA   N3
          CALL  sh4
          MOVBA
          LDA   N2
          ADD
          STA   ADRH
          CALL  lo8
          STA   ADRL
          RET

; lo8 -- A <- N1 N0
lo8:      LDA   N1
          CALL  sh4
          MOVBA
          LDA   N0
          ADD
          RET

; sh4 -- A <- A << 4. SHL destroys B; callers reload it.
sh4:      SHL
          SHL
          SHL
          SHL
          RET

; putc -- send A. Returns with A intact. Polls THRE, LSR bit 5.
putc:     STA   T_CH
pc_wait:  LDA   SER_LSR
          LDBI  0x20
          AND
          JNZ   pc_go
          JMP   pc_wait
pc_go:    LDA   T_CH
          STA   SER_THR
          RET

; getc -- A <- the next received byte. Polls DR, LSR bit 0. RBR is read
; EXACTLY ONCE per character: the read pops the FIFO (PHASE_G.md GOTCHA 2).
getc:     LDA   SER_LSR
          LDBI  0x01
          AND
          JNZ   gc_go
          JMP   getc
gc_go:    LDA   SER_RBR
          RET

; crlf
crlf:     LDAI  0x0D
          CALL  putc
          LDAI  0x0A
          CALL  putc
          RET

; puts -- the NUL-terminated string at PTRH:PTRL. B is reloaded every
; character because CPI destroys it.
puts:     LDB   PTRH
          LDC   PTRL
          LDAX
          CPI   0
          JNZ   ps_go
          RET
ps_go:    CALL  putc
          LDA   PTRL
          INR
          STA   PTRL
          JNZ   puts
          LDA   PTRH            ; low byte wrapped: carry into the high
          INR
          STA   PTRH
          JMP   puts

; ==== strings ================================================================
s_banner: .db   "DINO MON", 0x0D, 0x0A, 0
s_prompt: .db   "> ", 0
