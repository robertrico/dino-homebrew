# DINO ISA — what a SCELBAL-shaped BASIC needs

**2026-07-28, updated 2026-08-02. THEORETICAL EXCEPT WHERE MARKED.**

Rule 2 (CLAUDE.md) gated ISA extension on the machine adding two numbers.
**That gate is now open** — the ladder passed, blocks 1-5 are bench-proven,
and the machine free-runs. Block 6 was dropped as pure repetition in favour
of driving the machine interactively.

**`IN` (0x52) is BUILT AND RUNNING as of 2026-08-02** — see the tier 0 table
below. It cost one microword and no hardware, exactly as this document
predicted, and it kept the opcode number this document proposed. Everything
else here is still design, not reburn.

**Companion: `dino_hardware_growth_plan.md`** — the board-level paths (I/O
decode, UART, shifter, third microcode ROM, stack, index pair, timer) that
these instructions sit on top of. Read that one for what gets WIRED and in
what order; read this one for what gets ENCODED.

The single most important interaction between the two: **memory-mapped I/O
(growth plan step 1) hands two microcode codes BACK** by retiring `SRC=SW`
and `MISC=REG_OUT_LOAD`, in a word that has exactly two left. Several
instructions below are only affordable because of it.

Everything below was derived from the netlist and `microcode_gen.py`, not from
memory. The three structural findings came out of that sweep and they are what
shape the answer.

---

## 1. Three hardware facts that bound the ISA

### 1.1 The microcode word is FULL — SUPERSEDED 2026-08-10

**The third EEPROM exists.** `U23` is in the schematic (commit `9dc7217`) and
the word is 24 bits. This section described the 16-bit constraint; it is kept
because the reasoning downstream of it still holds, but the constraint itself
is gone.

    SA    bits 9-11   (3)      END     bit 12
    MISC  bits 6-8    (3)      PC_UP   bit 13
    SRC   bits 3-5    (3)      MUX_PC  bit 14
    DST   bits 0-2    (3)      HALT    bit 15
                              ------------------
                              16 of 16 -- U9 + U15

    CW16 ~{CIN_SEL}    CW20 ~{ADDR_SEL1}     <- U23, the third ROM
    CW17 ~{SRC_BANK}   CW21 FLAG_SEL0
    CW18 ~{DST_BANK}   CW22 FLAG_SEL1
    CW19 ~{MISC_BANK}  CW23 FLAG_POL

`~{SRC_BANK}` and `~{DST_BANK}` are **wired**: they lift `U28.E3` and `U30.E3`
off `+5V` and enable a second '138 each, giving 16 sources and 16 destinations.
The old codes 0-7 keep identical behaviour, so no burned row re-encodes. The
other six bits are burned into all 4096 rows and unwired.

Bank-1 codes as built: `SRC` 8-11 = `SP_LO_OUT`, `SP_HI_OUT`, `PC_LO_OUT`,
`PC_HI_OUT`; `DST` 8-9 = `SP_LO_LOAD`, `SP_HI_LOAD`.

**`MISC` is now FULL.** It had two unused codes (5 and 7) brought out on `U29`
`O5`/`O7`; both are spent on `~{SP_UP}` and `~{SP_DOWN}`. `O0` is the `NONE`
slot and can never be reclaimed. The next MISC code needs `~{MISC_BANK}` wired
plus a second MISC '138, or step 1's I/O decode retiring `REG_OUT_LOAD`.

### 1.2 Carry-in is wired to the opcode, not to the microcode

    U53 (74LS08) gate 4:  U53.11 = AND(SA1, SA0)
    U50 (74LS02) gate 4:  ALU_CIN = NOR(U53.11, U53.11) = NOT(SA1 AND SA0)

    SA=011 ADD   -> CIN=0    correct for add
    SA=010 SUB   -> CIN=1    correct for A-B two's complement
    SA=001 BSUB  -> CIN=1    correct for B-A
    logic codes  -> CIN=1    don't care

`ALU_CIN` is a pure function of the SA field. **Microcode cannot set it.**
So there is no `ADC`/`SBB` — no single-instruction multi-byte arithmetic.
`FLAG_C` IS captured in `U49`, so multi-byte add is still possible in
SOFTWARE: add low bytes, branch on carry, increment the high byte. That needs
`JC`, which is §3.

### 1.3 The PC cannot be read

`pc` contract OUT is `M0-15` only — the address bus. There is no `SRC=PC` and
no path from PC to `W`. A return address can never be captured by the machine.

**Consequence: a conventional `CALL` is impossible without new hardware.** But
see §2.3 — the way around it is free, and it is the finding that makes BASIC
reachable.

---

## 2. TIER 0 — free. Microcode rows only, no schematic change.

Every row below is built from `DST`/`SRC`/`MISC`/`SA` codes that already
decode on the real boards.

### 2.1 Indirect addressing via B:C — the one BASIC cannot exist without

    LDAX     T1  src=REG_C dst=MAR_LO
             T2  src=REG_B dst=MAR_HI
             T3  src=RAM   dst=REG_A  END
    STAX     T1/T2 as above
             T3  src=REG_A dst=RAM    END

`B:C` becomes the pointer pair, exactly the role `H:L` plays in SCELBAL on the
8008. Today every memory access is an absolute address baked into the
instruction stream, which makes arrays, string scanning, the variable table and
the line-number list all impossible. This one addressing mode unlocks all of
them, and it costs three microcode rows.

Same shape gives `LDBX LDCX STBX STCX`.

### 2.2 Register moves

`src=REG_x, dst=REG_y`, one row each. Six useful combinations. Note `C` is
currently WRITE-ONLY — `LDCI` can fill it and no instruction can read it back —
so `MOV A,C` alone makes an existing register useful.

### 2.3 Computed jump — this is what replaces CALL

    JMPX     T1  src=REG_C dst=MAR_LO
             T2  src=REG_B dst=MAR_HI
             T3  misc=PC_LOAD  END

`PC_LOAD` already loads the PC from MAR, and MAR can now be loaded from
registers. So the machine can jump to a computed address.

That gives a calling convention with no hardware at all:

    caller:   LDBI ret_hi ; LDCI ret_lo ; JMP subroutine
    callee:   ... ; JMPX                  <- returns

`JMPX` **is** `RET`. Nesting works if the callee spills `B:C` to RAM with
`STA`, which it can. It also gives dispatch tables, which is how a BASIC
tokeniser branches on a keyword. Return addresses are compile-time constants
rather than pushed values — a well-worn technique on minimal machines, and it
is sufficient.

### 2.4 Compare and test — flags without clobbering the accumulator

    CMP      src=ALU dst=NONE sa=SUB   END     A-B, flags only
    CMPB     src=ALU dst=NONE sa=BSUB  END     B-A, flags only
    TST      src=ALU dst=NONE sa=OR    END     A|A, sets Z/N only

`dst=NONE` is already decoded (`U30` code 0 is a legal no-load). BASIC's
relational operators are all `CMP` + a conditional branch.

### 2.5 Shift left, reset, increment

    SHL      T1  src=REG_A dst=REG_B          (clobbers B)
             T2  src=ALU sa=ADD dst=REG_A END  A+A
    RST      misc=PC_CLEAR END                 jump to 0
    INX      T1  src=REG_C dst=REG_A
             T2  ... +1 via ADD ...            (clobbers A)

Right shift has no hardware path — the '382 does not shift and there is no
shifter. Divide-by-two must be a software loop or a table.

---

## 3. TIER 1 — CANCELLED if the third EEPROM is on the roadmap

**Rico confirmed 2026-07-28 that a hardware stack and a third microcode EEPROM
are both planned. That cancels this tier — do NOT build it.**

Tier 1 spends the last two MISC codes (5, 7) and adds a 74LS27 to widen
`~{PC_LOAD}`. If the microcode word is about to grow, both are waste:
conditionals would end up split across an old 3-bit MISC field and a new one
FOREVER, and the '27 becomes vestigial the day the wide word lands. Design the
condition-code field ONCE, in the wide word, and get `JZ JNZ JC JNC JN JP JV`
coherently instead of two codes crammed into the last free slots.

The only argument for building it anyway: it is the cheapest possible path to
16-bit software math, and it is available now. Take it only if the third
EEPROM is far enough out that the machine needs to be useful in between.

The original design is kept below for that contingency.

### The contingency design

    JZ    misc=5  ->  U29.O5 (pin 10, NC today)
    JC    misc=7  ->  U29.O7 (pin 7, NC today)

Today only `FLAG_Z` reaches `COND`, so `JNZ` is the machine's only conditional.
`FLAG_C`, `FLAG_N` and `FLAG_V` are all registered in `U49` and all go nowhere.

`U62` has one free NOR gate (pins 11/12/13, NC). `~{PC_LOAD}` is currently
`NOR(COND_TAKEN, PC_LOAD_JMP)` — a 2-input NOR — so folding in a third and
fourth arm needs one more package, a 74LS27 (triple 3-input NOR) being the
natural fit.

**Cost: one chip, a handful of wires, and the last two MISC codes.** After this
the microcode word is completely exhausted.

**`JC` is what makes Rico's 16-bit software math work.** Add low bytes, `JC`
over an increment of the high byte. Without it, `FLAG_C` is captured and
unreachable, and multi-byte arithmetic is impossible at any cost.

---

## 4. TIER 2 — structural. Needs a third ROM or a new board.

| Want | Blocked by | Cost |
|---|---|---|
| `ADC` / `SBB` | `ALU_CIN = NOT(SA1 AND SA0)`, §1.2 | re-gate carry-in from a microcode bit — and there is no free bit, so a third EEPROM |
| Hardware `CALL`/`RET` with a stack | no `SRC=PC`, §1.3; `SRC` field full | PC→W buffer + SP register + wider microcode word |
| `JN` / `JV` | `MISC` exhausted after `JZ`/`JC` | wider microcode word |
| Right shift / `RRC` | no shifter in the datapath | new hardware |

None of these blocks a BASIC port. All of them make one faster or smaller.

---

## 4a. What the stack + third EEPROM actually change

Confirmed on the roadmap 2026-07-28. Impact, in order of how much it moves:

**1. `ADC`/`SBB` become one instruction each — the biggest single win.**
Replace `ALU_CIN = NOT(SA1 AND SA0)` (U50 gate 4, fed by U53's AND of SA1/SA0)
with a dedicated microcode CIN bit. 16-bit add stops being an add + `JC` +
increment loop and becomes two instructions. This is the change Rico's "we can
figure out how to add 16-bit numbers later" is actually asking for.

**2. Conditionals get designed once.** A proper condition-code field in the
wide word gives every flag, including the `FLAG_N`/`FLAG_V` that are captured
in U49 today and routed nowhere. Tier 1 becomes unnecessary — see §3.

**3. `CALL`/`RET` need `SRC=PC_LO` / `SRC=PC_HI`, so SRC gains a bank bit.**
That is exactly what the third ROM buys. **BUILT 2026-08-10**, with two
corrections to this paragraph:

- It is a bank **enable** (`~{SRC_BANK}` selecting between two '138s), not a
  fourth address input. A '138 has three.
- The new path lands on **`MDR0-7`, not `W`**, and taps **`PC0-15`, not `M`**.
  `U72`/`U73` are '245s from the '193 `Q` outputs into MDR, on the mdr sheet.
  Tapping `M` would make `CALL` impossible: the push row writes to RAM, so the
  address bus must carry MAR (the stack slot) and `M` is not carrying the PC.

**4. The SP needs a 1-of-3 address decode, and that is a BOARD CHANGE.**
Netlist-verified: `M` is sourced by a complementary-enable pair —
`U54`/`U59` (MAR) on `PC_MAR_MUX`, `U13`/`U14` (PC) on `~{PC_MAR_MUX}`, with
`U60` doing the inversion. Two states, one bit and its inverse, no room for a
third. Adding SP means replacing U60's inverter with a real decoder driving
three mutually exclusive enables. Design this WITH the PC→W path above — both
change how `M` and `W` are sourced, and doing them in one pass is one bring-up
session instead of two.

**5. What does NOT change.** Every Tier 0 instruction survives intact:

- `LDAX`/`STAX` on B:C stays the workhorse addressing mode. A dedicated index
  register can come later; code written against B:C stays valid.
- `JMPX` stays worth building even once a real `CALL` exists — computed jump is
  how a BASIC tokeniser dispatches on a keyword, and a hardware stack does not
  replace that.
- `MOV`, `IN`, `CMP`, `TST`, `SHL`, `RST` are all unaffected.

**So the first move is unchanged: build Tier 0.** It is pure microcode, none of
it is invalidated by the wider word, and it is what makes the machine
programmable at all. The roadmap changes what comes SECOND — not Tier 1's
74LS27, but the wide word and the two board changes together.

---

## 5. The proposed instruction set

Existing 18 unchanged. `HALT=0xFF` stays the erased-EEPROM safe value. High
nibble remains the family: 0=ctl, 1=imm, 2=mem, 3=flow, 4=ALU, 5=io, and two
new families 6=move, 7=indirect.

| Op | Instr | Rows | Tier | Notes |
|---|---|---|---|---|
| 0x00 | `NOP` | 1 | — | existing |
| 0x01 | `RST` | 1 | 0 | `misc=PC_CLEAR` |
| 0x11-13 | `LDAI LDBI LDCI` | 1 | — | existing |
| 0x21 | `LDA addr` | 3 | — | existing |
| 0x22 | `STA addr` | 3 | — | existing |
| 0x31 | `JMP addr` | 3 | — | existing |
| 0x32 | `JNZ addr` | 3 | — | existing |
| 0x33 | `JZ addr` | 3 | **1** | `misc=5`, `U29.O5` |
| 0x34 | `JC addr` | 3 | **1** | `misc=7`, `U29.O7` |
| 0x35 | `JMPX` | 3 | 0 | computed jump = `RET` + dispatch |
| 0x41-48 | 8 ALU ops | 1 | — | existing, all 8 SA codes |
| 0x49 | `CMP` | 1 | 0 | `dst=NONE sa=SUB` |
| 0x4A | `CMPB` | 1 | 0 | `dst=NONE sa=BSUB` |
| 0x4B | `TST` | 1 | 0 | `dst=NONE sa=OR` |
| 0x4C | `SHL` | 2 | 0 | clobbers B |
| 0x51 | `OUT` | 1 | — | existing |
| 0x52 | `IN` | 1 | 0 | **BUILT 2026-08-02.** `END \| src=SW \| dst=REG_B` = `0x103A`. Netlist-verified first: `SWITCH-GATE1` is a plain buffer `IS0-7 -> W0-7` with no permutation, both halves on the one `~{SW_OUT}` net; and `U50` makes `LE_TMP_B = NOR(~{REG_B_LOAD}, CLK)`, so the shadow follows the LOAD STROBE rather than the `LDBI` opcode and `ADD` sees the switch byte with no extra row. Only U9 reburned (`0xAD70 -> 0x0FBB`) — the high byte already matched the safe-fill. Bench: `0x2F + 0x01 = 0x30`, `0x2F + 0x1E = 0x4D` |
| 0x61-66 | `MOV` ×6 | 1 | 0 | makes `C` readable at last |
| 0x71 | `LDAX` | 3 | 0 | **the one that unlocks BASIC** |
| 0x72 | `STAX` | 3 | 0 | |
| 0x73-76 | `LDBX LDCX STBX STCX` | 3 | 0 | |
| 0x77 | `INX` | 3 | 0 | clobbers A |
| 0xFF | `HALT` | 1 | — | existing |

**38 instructions. 20 new, 18 of them free.**

Longest instruction is 4 T-states against a 4-bit T counter (16 available), so
the sequencer has ample headroom.

---

## 6. Is that enough for BASIC?

Against SCELBAL's 8008 requirements:

| SCELBAL needs | DINO has | |
|---|---|---|
| immediate loads | `LDAI/LDBI/LDCI` | yes |
| register moves | `MOV` ×6 | yes, tier 0 |
| memory via pointer pair | `LDAX/STAX` via B:C | yes, tier 0 |
| arithmetic + logic | 8 SA codes | yes |
| compare | `CMP/CMPB/TST` | yes, tier 0 |
| conditional branch | `JNZ` + `JZ` + `JC` | yes, tier 1 |
| subroutine call/return | `JMPX` + B:C convention | yes, tier 0 — §2.3 |
| terminal I/O | `IN`/`OUT` | yes, tier 0 |
| multi-byte arithmetic | software, `FLAG_C` + `JC` | yes, tier 1 |
| right shift | — | **no.** Software loop or table |
| hardware stack | — | **no.** Constant return addresses |

**Verdict: a SCELBAL-shaped BASIC is reachable with Tier 0 + Tier 1** — 18 free
microcode instructions plus one 74LS27 and two wires for `JZ`/`JC`.

The two genuine absences, right shift and a hardware stack, cost performance
and program size, not feasibility. 16-bit math works the way Rico called it:
in software, on the back of `FLAG_C`, which is why `JC` is the one piece of
hardware on the critical path.

---

## 7. Build order, when the gate lifts

1. ~~Block ladder, milestone green.~~ **DONE 2026-08-02 — Rule 2 lifted.**
   Blocks 1-5 bench-proven; block 6 dropped as repetition.
2. Tier 0 microcode: `LDAX/STAX`, `JMPX`, `MOV`, `IN`, `CMP`. One reburn, no
   schematic change, and `microcode_gen`'s `check_word`/`check_table` police it.
3. Coverage ROMs per new group, same pattern as `PROG_alu`/`PROG_mem`/
   `PROG_flow` — each reduces to a byte in A, then `OUT; HALT`, because `OB` is
   the only datapath observable.
4. **NOT Tier 1.** Skip the 74LS27 — see §3 and §4a. Go straight to the wide
   microcode word.
5. Third EEPROM + the two board changes designed together: the SP's 1-of-3
   address decode (replacing U60's inverter) and the PC→W path. Both change how
   `M` and `W` are sourced, so they are one bring-up session, not two.
6. In the wide word, in priority order: a microcode CIN bit (`ADC`/`SBB`), a
   real condition-code field (every flag, not two crammed codes), then
   `SRC=PC_LO/PC_HI` for `CALL`/`RET`.

Note for step 5: each new board gets a MODULE test first, then rejoins the
block ladder — the same law applies. A stack pointer is a new member of
blocks 2-6 and its address enable is exactly the kind of mutually-exclusive
strobe the ladder exists to police.
