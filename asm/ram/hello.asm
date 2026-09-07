; hello.asm -- the first RAM-resident program. Loaded, not burned.
;
;   load:   python3 docs/notes/dinoload.py asm/ram/hello.asm --go
;   check:  python3 docs/notes/test_dinoload.py
;
; Lives at 0x8100, above the monitor's page. Puts 0x5A on OB and RETs to
; the monitor's prompt: the LEDs are the witness, the prompt coming back
; is the second one. No .bin, no burn, no make target -- asm/ram/ is
; outside the assemble-% wildcard on purpose, because a RAM origin cannot
; be padded into a ROM image.
;
; The rules: `.org 0x8100` or above, end with RET, never touch
; 0x80E0-0x80FF (monitor state and stack). Monitor subroutines are
; callable by ROM address: `make listing-monitor` names putc, puthex,
; puts and crlf.

          .org  0x8100

          LDAI  0x5A
          OUT
          RET
