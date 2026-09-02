; ---------------------------------------------------------------------
; hello.asm — sum a five-byte table in RAM and show the total on OB.
;
;   build:  python3 docs/notes/asm.py asm/hello.asm -o roms/PROG_hello.bin
;   check:  python3 docs/notes/asm.py asm/hello.asm --run     -> OB = 0x96
;   list:   python3 docs/notes/asm.py asm/hello.asm --list
;
; Two things this program is careful about, and both will bite you:
;
;   B is the index pair's HIGH half AND the ALU's second operand. You cannot
;   use it for both at once, so the loop reloads it every pass.
;
;   INR and DCR reach the ALU by staging a constant in B, so they destroy it.
;   That is fine here only because B is reloaded at the top of the loop.
; ---------------------------------------------------------------------

; VARIABLES LIVE IN RAM, AT 0x8000 AND UP. Reserving space with .ds inside
; the program reserves it in the ROM IMAGE, which is read-only at run time --
; the store succeeds, the read-back returns the ROM byte, and the loop never
; ends. Name RAM cells with .equ instead.
STACK:  .equ 0x80FF             ; the stack pointer powers up random
total:  .equ 0x8100             ; running sum
left:   .equ 0x8101             ; bytes remaining
ptrlo:  .equ 0x8102             ; the index pair's low half
TABLE:  .equ 0x8200             ; five bytes, planted below
TABHI:  .equ >TABLE               ; the high half, written once
COUNT:  .equ 5

        .org 0x0000

        LDAI 0xFF               ; poison OB: it holds the previous program's
        OUT                     ; answer until something overwrites it
        LXISP STACK

; --- plant the table, without spending a register on any of it
        MVI  TABLE+0, 0x0A
        MVI  TABLE+1, 0x14
        MVI  TABLE+2, 0x1E
        MVI  TABLE+3, 0x28
        MVI  TABLE+4, 0x32

; --- set up the walk
        CLR                     ; A = 0
        STA  total
        MVI  left, COUNT
        MVI  ptrlo, <TABLE      ; low half of the table address

; --- the loop
loop:   LDBI TABHI              ; B = pointer high (destroyed every pass)
        LDA  ptrlo
        MOVCA                   ; C = pointer low
        LDAX                    ; A <- [B:C]

        LDB  total              ; B = running total
        ADD                     ; A <- A + B
        STA  total

        LDA  ptrlo              ; advance the pointer. INR destroys B,
        INR                     ; which is why B is reloaded above
        STA  ptrlo

        LDA  left               ; DCR sets Z, and Z survives the STA:
        DCR                     ; flags hold across everything but the ALU
        STA  left
        JNZ  loop

        LDA  total
        OUT
        HALT

