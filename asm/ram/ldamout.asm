; ldamout.asm -- RET's two private paths, run by LDAM straight after OUT.
;   load+run: python3 docs/notes/dinoload.py asm/ram/ldamout.asm --go
;   check:    python3 docs/notes/test_ramret.py
;
; 2026-09-28. retlda halted because RET's pops read the right cells wrong:
; LO (RAM -> C -> MAR_LO) came back 0xB3 -> 0xA0, HI (RAM parked in MDR,
; replayed -> MAR_HI) came back 0x01 -> 0xFF. A plain POPA after OUT is
; clean (popout, OB 0x5A). LDAM uses exactly RET's two paths -- pointer LO
; into C, pointer HI parked and replayed -- so this runs them after OUT with
; no RET at risk, and OB names the half that broke:
;
;   OB 0xC3   both halves clean: the fault needs RET itself
;   OB 0xEE   HI replay gave 0xFF  (read [0xFF10])
;   OB 0xDD   HI 0xFF and LO lost bit 4  (read [0xFF00])
;   OB 0x10   LO lost bit 4, HI fine  (read [0x8200], the pointer's LO)
;   other     a mix -- read it as bits
;
; The final RET follows a NOP (T1), which has never failed.

          .org  0x8100

          MVI   0x8200, 0x10    ; pointer LO
          MVI   0x8201, 0x82    ; pointer HI -> 0x8210
          MVI   0x8210, 0xC3    ; the target
          MVI   0xFF10, 0xEE    ; HI replayed as 0xFF
          MVI   0xFF00, 0xDD    ; HI 0xFF and LO 0x00
          LDAI  0x00
          OUT
          LDAM  0x8200
          OUT
          NOP
          RET
