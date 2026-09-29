; popout.asm -- a stack READ straight after OUT, witnessed on OB, no RET at risk.
;   load+run: python3 docs/notes/dinoload.py asm/ram/popout.asm --go
;   check:    python3 docs/notes/test_ramret.py
;
; 2026-09-28. retlda halted with IR 0xFF, MAR 0xFFA0, SP 0x80FF: RET RAN,
; SP was right, and its two pops read the right cells wrong -- LO 0xB3 came
; back 0xA0 (1->0 only), HI 0x01 came back 0xFF (the MDR park/replay gave
; an undriven bus). This asks whether a plain POP read after OUT is damaged
; too, or whether it takes RET's park. OB = 0x5A and the prompt: the POP
; read is clean. OB = 0x5A with bits missing: any RAM read after OUT is.
; The final RET follows a NOP (T1), the one predecessor that has never
; failed, so the prompt should come back either way.

          .org  0x8100

          LDAI  0x5A
          PUSHA
          LDAI  0x00
          OUT
          POPA
          OUT
          NOP
          RET
