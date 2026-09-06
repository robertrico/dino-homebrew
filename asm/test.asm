; test.asm

INPUT:	.equ	0x4000
outb:	.equ	0x00

	.org	0x0000

	LDAI	0xFF
	OUT


LOOP:	LDA	0x4000
	OUT
	LDBI	0xFE
	CMP
	JNZ	LOOP

	LDAI 0x01
	OUT
	
	HALT
