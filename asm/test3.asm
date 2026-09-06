; test3.asm -- can ROM be read as DATA? Two bytes planted in ROM, one sum, OB.
;
;   build:  make assemble-test3
;   check:  python3 docs/notes/asm.py asm/test3.asm --run    -> OB = 0x4D
;   burn:   make burn-prog-test3
;
; Every green image fetches its INSTRUCTIONS from ROM and keeps its DATA in
; RAM. Nothing has ever done LDA of an address below 0x4000. This plants two
; bytes in ROM behind the HALT, reads both back by absolute address with
; LDA/LDB -- the same src=RAM rows a RAM read uses -- adds them, and shows
; the sum. Same shape as test2, other side of 0x8000.
;
;   0x4D   ROM reads as data. The monitor may keep its strings in ROM.
;   0xFF   OB never changed: did not get past the poison.
;   other  a ROM data read returned something that is not the ROM byte.
;          The ROM's ~OE is ~{ROM_OUT} (U24.22), which only the fetch
;          asserts; a src=RAM read below the window would leave the bus
;          undriven. 0xFE = 0xFF+0xFF, both reads saw the park.

        .org  0x0000

        LDAI  0xFF              ; poison OB
        OUT

        LDA   ROM_A             ; read both by absolute address, from ROM
        LDB   ROM_B
        ADD                     ; 0x2F + 0x1E = 0x4D
        OUT
        HALT

ROM_A:  .db   0x2F
ROM_B:  .db   0x1E
