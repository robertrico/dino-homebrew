; test2.asm -- does RAM work ABOVE the proven page? Two cells, one sum, OB.
;
;   build:  make assemble-test2
;   check:  python3 docs/notes/asm.py asm/test2.asm --run    -> OB = 0x4D
;   burn:   make burn-prog-test2
;
; Every bench-green image keeps its RAM inside 0x8000-0x80FF. Nothing has
; ever driven RAM's A9-A14. This writes two values into the TOP page of RAM,
; reads both back by absolute address, adds them, and shows the sum.
;
;   0x4D   both cells held. RAM at 0xFFxx is fine; look elsewhere.
;   0xFF   OB never changed: the machine did not get past the poison.
;   other  a cell did not hold. 0x2F+0xFF = 0x2E and 0x1E+0xFF = 0x1D name
;          a cell reading the bus park; 0x3C or 0x5E name the two cells
;          aliasing onto each other (0x1E+0x1E, 0x2F+0x2F).
;
; The two cells differ in A4 only, so they cannot alias unless A4 is dead --
; and A4 is proven at 0x8040/0x8050 by the ISA self-test. What is new here
; is A9-A14, all HIGH.

HI_A:   .equ  0xFFE0
HI_B:   .equ  0xFFF0

        .org  0x0000

        LDAI  0xFF              ; poison OB
        OUT

        LDAI  0x2F
        STA   HI_A
        LDAI  0x1E
        STA   HI_B

        LDA   HI_A              ; read both back by absolute address
        LDB   HI_B
        ADD                     ; 0x2F + 0x1E = 0x4D
        OUT
        HALT
