; call8100.asm -- netsim ROM stub: enter a RAM program the way the
; monitor's G does (a CALL, SP where the monitor keeps it), then OUT 0x5A
; and HALT. OB = 0x5A means the RAM program's RET came back.
; Used by docs/notes/netsim_run.py --ram asm/ram/<prog>.asm.

        .org  0x0000
        LXISP 0x80DF
        CALL  0x8100
        LDAI  0x5A
        OUT
        HALT
