# DINO hardware growth plan

**2026-07-28, updated 2026-08-03. PLAN ONLY — nothing here is built or
burned.**

**What the 2026-08-03 pass changed**, all of it netlist-verified with
`kicad_netlist.build_report`, none of it from memory:

- **Step 4b is rewritten.** Two routes to the address bus, and the CHEAP one
  (SP via MAR, no `PC_MAR_MUX` surgery) is now the recommendation.
- **The SP counter is '169, not '193.** Synchronous, so `SP_UP`/`SP_DOWN` is a
  LEVEL, not a strobe. Strictly safer than the PC it was going to mirror.
- **"SP counter pair" was wrong.** '193 and '169 are 4-bit. 16-bit SP = **four**
  chips, matching the PC's `U1`-`U4`.
- **The baud clock is a 3.6864MHz oscillator CAN**, not a 1.8432MHz crystal.
- **The 8-bit budget is answered: exactly 8, zero slack.** Table in 4a.
- **CIN, SRC/DST widening and COND are priced at the pin**, with the pin-level
  evidence inline so nothing has to be re-derived.
- **Parts-on-hand section added.** Nothing in this plan needs ordering.

Context change since this was written: the block ladder is DONE (blocks 1-5
bench-proven, block 6 dropped), timing is retired, and the milestone gate is
open. The first ISA extension, `IN` at 0x52, shipped on 2026-08-02 as pure
microcode — no board work — so nothing in this document was needed for it.
The next item on Rico's stated roadmap is the minimum path to the 16550 so
DINO can talk to a terminal, which DOES need the I/O decode '138 below.

Rule 2 (CLAUDE.md) gates all of this on the machine adding two numbers. The
block ladder finished first (blocks 1-5, 2026-08-02), and only then does any of this
get wired. Companion document: `dino_isa_for_basic.md`, which covers the
instruction set these paths enable.

Every fact below was pulled from the netlist with `kicad_netlist.build_report`,
not from memory. The order is chosen by value-per-chip, and the first item is
first because it makes everything after it cheap.

---

## The five findings this plan is built on

| # | Fact | Netlist evidence |
|---|---|---|
| 1 | **I/O is strobe-mapped, not address-mapped** | switch '244 enable is `~{SW_OUT}` (a microcode strobe); OB latches on `REG_OUT_LOAD` |
| 2 | **Chip select is only `M15`** | `U24.20 ~CE = ROM_EN`, `U26.20 ~CE = ~{RAM_EN}`. ROM 0x0000-0x7FFF, RAM 0x8000-0xFFFF, nothing else decoded |
| 3 | **The microcode word is full** | SA(3)+MISC(3)+SRC(3)+DST(3)+END+PC_UP+MUX+HALT = 16/16. `MISC` has 2 codes left; `SRC` and `DST` have none |
| 4 | **Carry-in is wired to the opcode** | `U53` '08 gate 4 = `AND(SA1,SA0)`; `U50` '02 gate 4 inverts it into `ALU_CIN`. Microcode cannot set it |
| 5 | **The PC cannot be read, and the address mux has no third state** | `pc` OUT is `M0-15` only. `M` is a complementary-enable pair: `U54`/`U59` on `PC_MAR_MUX`, `U13`/`U14` on `~{PC_MAR_MUX}`, inverted by `U60` |

Findings 1 and 3 compound: **every new device currently costs a microcode
code, and there are two left.** A 16550 has eight registers. That arithmetic
is what sets the order below.

---

## STEP 1 — Memory-mapped I/O decode

**Do this before the UART. It is the highest value-per-chip item in the plan.**

One '138 decoding a window at the top of RAM — `0xFF00-0xFF7F` is the natural
choice — gated on `M15` and the upper address bits, giving 8 device selects.

    COST      one 74LS138 + one gate
    UNLOCKS   every future device, permanently

What it buys, in order of importance:

1. **The UART becomes reachable with ZERO new instructions.** `LDAX`/`STAX`
   (see `dino_isa_for_basic.md` §2.1) already address it.
2. **Two microcode codes come BACK.** Switches and LEDs stop being special
   cases, retiring `SRC=SW` and `MISC=REG_OUT_LOAD` — in a word that has two
   codes left, handing two back is not a rounding error.
3. **Every future device is free.** No microcode change, ever again, for I/O.

Without this, the UART needs `/CS`, `/RD`, `/WR` and three address lines
synthesised out of strobes, burning codes that do not exist.

**Bring-up:** new module `iodecode`, its own module test proving the window
boundary from both sides (the same shape as `memory.select`, which already
hits the 0x8000 boundary from both bus drivers), then it joins the block
ladder as a member of blocks 2-6.

**Watch for:** the decode must not alias into RAM. `memory.select` is the
model — assert the boundary address and the one below it, both directions.

---

## STEP 2 — The UART. **NO ISA CHANGE REQUIRED.**

**This is the key sequencing fact and it is easy to miss.** UART registers
live at FIXED addresses, and `LDA addr` / `STA addr` already reach fixed
addresses. So once step 1's decode exists, a polled echo loop runs on the
CURRENT 18-instruction ISA, with no microcode reburn at all:

    loop:  LDA  LSR        ; line status
           LDBI 0x01       ; Data Ready mask
           AND             ; sets FLAG_Z
           JNZ  ready
           JMP  loop
    ready: LDA  RBR        ; read the char
           STA  THR        ; echo it
           JMP  loop

`AND` sets `FLAG_Z` and `JNZ` branches on it; both already exist and both are
proven by the block ladder. A terminal can be talking to the machine before a
single new instruction is encoded.

**Corollary: `IN` is REMOVED from the instruction plan.** `SRC=SW` was only
ever the input path. Once the UART is memory-mapped the keyboard is the input,
and `SRC=SW` stays the unreachable curiosity it is today. Do not spend a
microcode row on it. (`dino_isa_for_basic.md` §2 updated to match.)

**Timing is not a concern.** A five-instruction poll loop is roughly 10us
against ~1ms per character at 9600 baud — about 100x headroom. Even 115200
(87us/char) is comfortable.

### The part list

**Part note:** the 16550 is National/TI lineage (`NS16550A`, today
`PC16550DN`). Intel's parts are the 8250 UART and the 8251 USART. The 16550
is still the right pick here — the 16-byte FIFOs matter a great deal when the
CPU is this slow, and 5V DIP-40 parts remain easy to source.

    COST      one PC16550DN + one 3.6864MHz oscillator can + decoupling
    NEEDS     8-bit data bus, A0-A2, /CS, /RD, /WR, baud clock

- **It needs its own baud clock.** It does not and cannot divide from the
  4.096MHz Y1. **ON HAND: a 3.6864MHz oscillator CAN** (bought 2026-08-03),
  which supersedes the 1.8432MHz crystal this document originally specified.
  3.6864 is exactly 2x 1.8432 and is the better part twice over:

      3686400 / 16 = 230400 max      divisor 24 ->   9600
                                     divisor  2 -> 115200
                                     divisor  1 -> 230400

  More range than 1.8432 gives, standard divisors, no fractional error. And a
  CAN beats a crystal on a breadboard: drive `XIN` directly, leave `XOUT`
  open, no load caps, no startup margin, and "is it oscillating?" never
  becomes a bring-up question. One fewer analog unknown.
- `/RD` and `/WR` come straight off the existing RAM read/write strobes once
  step 1 is done, so the glue is nearly nothing.
- A0-A2 come from `M0-M2`, already on the address bus.

**Bring-up:** module `uart`, tested standalone with the rig driving the bus
and reading back the scratch register (the 16550's register 7 is a plain
read/write scratch — the ideal presence test, and asymmetric, so it satisfies
the mirror-witness rule). Loopback mode (MCR bit 4) lets the rig prove TX→RX
without a terminal attached.

**Polling is fine.** At 1.024MHz against 9600 baud with a 16-byte FIFO, an
interrupt buys nothing yet. See step 6.

---

## STEP 3 — A shifter

Right shift is the one datapath operation with **no path at all**. The '382
does not shift and nothing else can. SCELBAL's float normalise, multiply and
divide all want it, and today each costs a software loop.

**The breadboard trick:** a second '245 from `A` onto `W`, wired **skewed by
one bit**. Shift becomes a bus permutation rather than an arithmetic unit.

    COST      one 74LS245 + one SRC code + one microcode row
    GIVES     SHR in a single instruction

The vacated bit ties to GND for a logical shift, or to `FLAG_C` for
rotate-through-carry — which is what multi-byte shifts need. Left shift
already exists as `A+A` (`dino_isa_for_basic.md` §2.5), so this closes the
pair.

**Note the ordering problem:** this needs a `SRC` code, and `SRC` is full
(finding 3). So it either waits for step 4, or it takes one of the two codes
step 1 hands back. Taking a returned code is legitimate and gets the shifter
years earlier — decide at the time.

**Bring-up:** folds into the existing `alu` module test as a new case; no new
module. It is a new W driver, so `alu.tristate`-style release checking applies.

---

## STEP 4 — Third microcode EEPROM + the stack

These are one design, not two, because both change how `M` and `W` are
sourced. Doing them in a single pass is one bring-up session instead of two.

### 4a. The wide microcode word

    COST      one AT28C64B + 8 more tap lines + a wider CW bus

Priority order for the new bits, by value:

1. **A dedicated CIN bit.** Replaces `ALU_CIN = NOT(SA1 AND SA0)` (finding 4).
   This is the single most valuable bit in the whole plan: 16-bit add stops
   being *add + `JC` + increment loop* and becomes `ADD` then `ADC`. It is what
   "figure out how to add 16-bit numbers later" actually resolves to — not new
   ALU hardware, just taking carry-in away from the SA field.

   **Netlist, 2026-08-03:**

       U53 ('08) gate4:  out 11 = AND(SA1, SA0)     [in 12=SA1, 13=SA0]
       U50 ('02) gate4:  in 11,12 tied -> inverter
                         out 13 = ALU_CIN -> U38.15 (CN)

   Against the SA table that gate is doing exactly one job — SUB needs
   `A + ~B + 1` so it injects the +1, ADD must not:

       CLR 000 -> CIN 1    BSUB 001 -> CIN 1    SUB 010 -> CIN 1
       ADD 011 -> CIN 0    SET  111 -> CIN 0

   Correct, free, two gates, and the right call when the word is 16/16 full.
   But CIN is then a PURE FUNCTION OF THE OPCODE — same instruction, same
   carry-in, always — and there is no path from `FLAG_C` (`U49.2`, latched,
   sitting right there) back to `U38.15`. `ADC` is not "unencoded", it is
   INEXPRESSIBLE.

   **The change is ONE NET.** Lift `U50.11/12` off `U53.11` and drive from the
   new CW bit. `U53` gate4 goes unused; leave it. Better: make the new bit
   SELECT between `FLAG_C` and a microcode-supplied value, so one bit plus one
   mux yields `ADD`/`ADC`/`SUB`/`SBB`. Cheapest rewire in the plan, highest
   value bit in it, alu board only, rig-verifiable.
2. **A real condition-code field.** Every flag, not two codes crammed into the
   last free slots. `FLAG_N` and `FLAG_V` are captured in `U49` today and
   routed nowhere. This is why the Tier 1 `JZ`/`JC` hack is CANCELLED — see
   `dino_isa_for_basic.md` §3.

   **Netlist, 2026-08-03.** The branch is welded to one flag, one sense:

       U62 ('02) gate1  COND_TAKEN = NOR(~{COND}, FLAG_Z)
                 gate2  PC_LOAD_JMP = NOT(~{PC_LOAD_JMP})
                 gate3  ~{PC_LOAD}  = NOR(COND_TAKEN, PC_LOAD_JMP)
                 gate4  in 11,12 = GND, out 13 = NC       <- FREE

   All four flags are already latched on `U49` (`Q0`=C, `Q1`=Z, `Q2`=V,
   `Q3`=N) and only `FLAG_Z` is routed. So this costs WIRE, not capture:

       flag select   one '157 (or '153) 4:1 on FLAG_C/Z/V/N   2 bits
       polarity      one '86 XOR gate: taken = flag XOR pol     1 bit

   The XOR is what gives both senses of every branch — `JZ`/`JNZ`, `JC`/`JNC`,
   `JN`/`JP`, `JV`/`JNV` — from one bit. `U62` gate4 is free for the glue.
   Three bits of the new word, ZERO new chip types, both parts on hand.
3. **`SRC` widened to 4 bits**, which is what makes `SRC=PC_LO`/`PC_HI`
   possible, which is what makes `CALL` possible. `DST` widens with it — the
   D:E pair (step 5), `SP_LO`/`SP_HI` and the RET scratch all need DST codes
   and DST is full.

   **Netlist, 2026-08-03 — the enables are STRAPPED, and that is the good
   news:**

       U28 (SRC)  A0-A2 = CW3,CW4,CW5   E1=GND  E2=GND  E3=+5V
       U29 (MISC) A0-A2 = CW6,CW7,CW8   E1=GND  E2=GND  E3=+5V
       U30 (DST)  A0-A2 = CW0,CW1,CW2   E1=GND  E2=GND  E3=+5V

   Occupancy, at the pin:

       U28 SRC   O0 SRC_ACTIVE, O1 ROM, O2 RAM, O3 A, O4 B,
                 O5 C, O6 ALU, O7 SW                        -> 0 free
       U30 DST   O1 A, O2 B, O3 C, O4 MAR_LO, O5 MAR_HI,
                 O6 IR, O7 RAM   (O0 = NC, the NONE slot)   -> 0 free
       U29 MISC  O1 PC_CLEAR, O2 PC_LOAD_JMP, O3 COND,
                 O4 MDR_OUT, O6 REG_OUT_LOAD                -> 2 free (O5,O7)

   Queued demand: shifter, PC_LO, PC_HI, SP_LO, SP_HI, D, E (SRC); D, E, SP_LO,
   SP_HI, TMP (DST). Available: zero and zero.

   **Widening is a strap lift, not surgery.** Feed the new bit to `E1` of the
   existing '138 and to a second '138's `E1`. The old decoder keeps codes 0-7
   with IDENTICAL behaviour, so **every burned microcode row stays valid and
   nothing re-encodes.** That property is why widening beats renumbering:
   renumbering to reclaim slots would invalidate every row and every host test.

   **`MISC` can dodge its second '138 entirely.** Free `O5` + `O7` + `O6` once
   step 1 retires `REG_OUT_LOAD` = exactly 3 codes = exactly `SP_UP`,
   `SP_DOWN`, `SP_LOAD`. Costs no bit and no chip; leaves zero MISC headroom
   after. Decide at the time.

#### IS 8 BITS ENOUGH? Exactly 8. Zero slack.

    bit(s)      buys                                              cost
    CIN         ADD/ADC/SUB/SBB, 16-bit arithmetic                 1
    SRC3        16 sources: PC_LO, PC_HI, SP_LO, SP_HI, shifter,   1
                D, E, TMP
    DST3        16 dests: D, E, SP_LO, SP_HI, TMP                  1
    ADDR_SEL1   MUX becomes {MAR, PC, SP, -}                       1
    COND[2:0]   '157 flag select + '86 polarity — all four flags,  3
                both senses
    MISC3       16 misc: SP_UP / SP_DOWN / SP_LOAD                 1
                                                             --------
                                                                8 / 8

Two ways to buy slack if wanted: drop `MISC3` and put SP control in MISC's
three freed codes (7 used, 1 spare, zero MISC headroom after); or cut `COND`
to 2 bits, flag-select only, losing branch polarity (2 spare).

**Verdict: 8 covers this document and nothing more.** If a 4th ROM is ever
needed it is the cheapest expansion in the machine — same shared
`{IR[7:0],T[3:0]}` address, 100% additive, no rewire. Burn 3 now, keep 4 on
the table, do not agonise.

**ERASED-EEPROM SAFETY — design the polarities for it.** `FILL = 0x1000`
(END) works today because unused rows halt. A blank AT28C64B is `0xFF`, so
pick the new field polarities such that **`0xFF` is harmless** — the same
reasoning that made `HALT=0xFF`. CIN active-low, `ADDR_SEL=11` = no address
driver, and so on. Otherwise an unburned third ROM asserts CIN on every row.

**Bits you do not decode yet must still be STRAPPED, not floating.** Skipping
decode on an unused new bit is legitimate and cheap; leaving a TTL input open
is the one thing this machine has not yet been bitten by. Encode and burn the
full field, wire only what is decoded, strap the rest to its safe level. The
field is then already in every burned row when the decode arrives — no reburn.

**Bring-up:** `microcode_gen.py` grows a third image and a third CRC; the
existing `check_word`/`check_table` policing extends to the new fields. The
`microcode` module test gains a third ROM and a third CRC assertion. Rig
firmware follows via the regenerated header — nothing retyped.

### 4b. The stack

**What a stack is FOR, in one line:** so a subroutine can come back. Today no
routine can `CALL`/`RET` — there is no place to remember where you came from,
so every reusable chunk is copy-pasted at each use. `print_char` written once
and called from forty places is the entire prize.

**Three netlist facts (2026-08-03) that decide the design:**

    MAR latches from W    U55/U58 ('373) D0-D7 = W0-W7, LE_MAR_LO/LE_MAR_HI
    PC loads from M       U11/U12 ('245) A=M0-M15 -> PCD -> '193 parallel load,
                                         /OE = ~{PC_LOAD}
    MDR shadows W free    U22 gate2: ~{MDR_EN} = NOR(SRC_ACTIVE, MDR_OUT)
                          -> the U25 bridge is ON whenever ANY source drives W

So `JMP` is already `MAR -> M -> PC`, and **MDR silently captures every W
transfer** — one byte of scratch the machine already owns, replayed with
`MISC=MDR_OUT`.

#### The counter: '169, NOT '193

**Decided 2026-08-03. Do not mirror the PC here — beat it.** '169s are on
hand and are strictly safer than the '193s the PC uses:

    |          | '193 (PC today)              | '169 (SP)                    |
    | count    | two clock pins, UP / DOWN    | one clock, direction a LEVEL |
    | enable   | implicit in the clock pin    | ~CEP / ~CET, levels          |
    | load     | ASYNCHRONOUS                 | SYNCHRONOUS, on the edge      |
    | cascade  | ripple ~CO -> next chip CLK  | ~TC -> ~CET, all chips clock  |

Why it matters here: on a '193 the UP/DOWN pins ARE clocks, so a glitch counts
— which is the entire reason the PC carries `U36` and the
`PC_UP_STABLE`/`PC_LOAD_STABLE` glue. On a '169, `SP_UP`/`SP_DOWN` collapses
to one direction LEVEL plus one count enable. **That deletes the worst wire
class in the block law — a wrong driven STROBE — from the SP outright**, and
`LXI SP` needs no stabiliser because the load is synchronous.

'169 and '163 share the family pinout (16-pin, `CP` on 2, `D0-D3` on 3-6,
`~PE` on 9, enables on 7/10, `TC` on 15); pin 1 differs — '163 `~MR`, '169
`U/~D`. **Verify against the datasheet before wiring.**

**GOTCHA — '169 HAS NO CLEAR.** None. The PC gets `PC_CLEAR_OR_RESET` from
`U10`; SP will not. Power-on SP is random until software runs `LXI SP`. Fine
for a stack, but write it down: "machine works, then randomly doesn't" traced
to an unset SP is a miserable afternoon.

`LXI SP` needs no '245 either. Wire `W0-W7` straight to all four '169 `D`
inputs and give the low and high pairs separate `~PE` strobes — exactly how
MAR does it, `U55` and `U58` both sitting on `W0-W7` split by
`LE_MAR_LO`/`LE_MAR_HI`. Two MISC codes, zero chips.

#### Two routes to the address bus — TAKE THE CHEAP ONE

**Route A (expensive, originally specified here).** SP drives `M` directly.
`M` is a complementary-enable pair today — one bit and its inverse, mutually
exclusive BY CONSTRUCTION, no third state:

    U54.19 /OE = PC_MAR_MUX      MAR lo -> M0-M7     (mar sheet)
    U59.19 /OE = PC_MAR_MUX      MAR hi -> M8-M15    (mar sheet)
    U13.19 /OE = ~{PC_MAR_MUX}   PC  lo -> M         (pc sheet)
    U14.19 /OE = ~{PC_MAR_MUX}   PC  hi -> M         (pc sheet)
    U60 ('02) gate4 = the inverter.  U60 HAS NO FREE GATE:
        gate1 LE_MAR_LO   gate2 LE_MAR_HI   gate3 ~{RAM_EN}=NOT(M15)

`U60` gate4 becomes a 1-of-3 decoder. A '138 with `A2` grounded IS a 2-to-4
decoder and is on hand, so no '139 is needed — and '138 leaves `E3` spare as a
global address inhibit plus four unused codes.

**Route B (cheap, RECOMMENDED). SP never touches `M`.** SP is just a number;
MAR is the thing that points. Copy SP into MAR and let MAR point. `DST=MAR_LO`
/`MAR_HI` are `U30.O4`/`O5` — already decoded, already burned, already policed.

    PUSH A                          POP A
      T1  SP_LO -> MAR_LO             T1  SP_UP
      T2  SP_HI -> MAR_HI             T2  SP_LO -> MAR_LO
      T3  A     -> RAM                T3  SP_HI -> MAR_HI
      T4  SP_DOWN, END                T4  RAM   -> A, END

`CALL` needs two 16-bit values alive at once (target and return) and MAR is
the only 16-bit holder — so **push first, fetch the target last**:

    CALL addr
      T0  fetch, PC++            ; PC now points at the operand bytes
      T1  SP_LO -> MAR_LO        ; push return HI
      T2  SP_HI -> MAR_HI
      T3  PC_HI -> RAM
      T4  SP_DOWN
      T5  SP_LO -> MAR_LO        ; push return LO
      T6  SP_HI -> MAR_HI
      T7  PC_LO -> RAM
      T8  SP_DOWN
      T9  ROM -> MAR_LO, PC++    ; MAR is free again — fetch the target
      T10 ROM -> MAR_HI, PC++
      T11 PC_LOAD, END           ; PC <- M <- MAR

**THE CONVENTION, and it is the price of route B:** what got pushed is the
address of CALL's OPERAND BYTES, not the instruction after. `RET` therefore
ends with two bare `PC_UP` states to step over them. Written once in
`microcode_gen.py`, host-tested, cannot drift.

    RET
      T1  SP_UP                  T8   RAM  -> (DST=NONE)  ; hi byte -> MDR free
      T2  SP_LO -> MAR_LO        T9   TMP     -> MAR_LO
      T3  SP_HI -> MAR_HI        T10  MDR_OUT -> MAR_HI
      T4  RAM   -> TMP           T11  PC_LOAD
      T5  SP_UP                  T12  PC_UP              ; over operand lo
      T6  SP_LO -> MAR_LO        T13  PC_UP, END         ; over operand hi
      T7  SP_HI -> MAR_HI

11 and 13 states. T-depth is 16 and the deepest instruction today is T3 —
room, and this is what that depth was always for.

**HAZARD, do not walk into it:** never make a RAM read's destination be part
of the address. `RAM -> MAR_HI` while MAR is addressing RAM feeds the address
back into itself mid-read. That is why both popped bytes get parked and moved
into MAR together, and it is why route B needs one byte of scratch beyond MDR:
MDR holds one, a '373 holds the other. Using `REG_C` instead saves the chip
and clobbers C on every `RET` — bad for BASIC. Spend the '373.

#### Cost, both routes

    | item             | route A (mux)      | route B (via MAR)   |
    | SP counter       | 4x '169            | 4x '169             |
    | SP output        | '245 pair -> M     | '245 pair -> W      |
    | PC -> W (CALL)   | '245 pair          | '245 pair           |
    | address decode   | '138 + REWIRE      | none                |
    |                  | U60/U54/U59/U13/U14|                     |
    | scratch byte     | none               | 1x '373             |
    | boards touched   | mar + pc + ctlword | pc only             |
    | re-verify        | LA, at speed, bl2-5| rig                 |
    | PUSH cost        | 2 ticks            | 4 ticks             |
    | RET quirk        | none               | pushes operand addr |

Near enough the same chip count. **The difference was never chip count.**
Route A touches three boards and re-opens address-bus mutual exclusion — the
one bus that has never had a fight, whose guarantee is STRUCTURAL. Route B
touches the pc board and adds a convention that lives in a generator. Four
extra ticks per push at 1.024MHz is not measurable.

If route A is ever taken anyway, decode from the 2-bit field so exactly one
`/OE` can be low BY CONSTRUCTION. Never microcode three independent enables —
that converts a fight-is-impossible bus into a fight-is-a-microcode-bug bus.
Spare code `11` = no driver (M floats; nothing latches from it unqualified).

**Bring-up:** SP is a new MODULE with its own test first — the same law
applies, no shortcuts. Then it joins blocks 2-5. Route B keeps it a plain W
source, which the rig can prove alone. Route A additionally makes it a
strike-6 tri-state handoff: assert that no two of MAR/PC/SP ever enable
together, on the LA, at speed.

---

## STEP 5 — A second index pair (D:E)

    COST      2 registers + SRC/DST codes (needs step 4a)

`B:C` alone forces constant save/restore in BASIC. A string copy needs a source
**and** a destination pointer; with one pair, every iteration spills to RAM.
This is a performance and code-size item, not a feasibility one, which is why
it sits below the stack.

**Build these from '173s** (on hand, 2026-08-03). A '173 is a 4-bit clocked
register with TRI-STATE outputs and a built-in input enable, so two of them
make one 8-bit register that both loads from `W` and drives `W` with **no
external '245**. Same chip count as '373+'245, but edge-triggered rather than
transparent — the safer part, and it is what the '173s are for.

---

## STEP 6 — Timer / counter, and only then interrupts

    COST      one 74LS393 + one decode line (free after step 1)

`RND` seeding and any wall-clock timing. Trivial once I/O is memory-mapped.

**Interrupts deliberately last.** Polling a 16550 FIFO at 1.024MHz against
9600 baud is genuinely adequate, and an IRQ needs the PC saved — the same
problem `CALL` has. Design the stack (4b) so an IRQ can be added later; do not
build it before there is a workload that needs it.

---

## The constraint that outranks all of this

**Breadboard fan-out, not logic, is what will bite.**

Every device added to `W` adds load. The LED drive is the canary: a 74LS373
sourcing roughly twice its rated `IOH` into a 330Ω LED, on the one node the
whole milestone is read from. A pin sitting at 2.0V reads as a clean HIGH to
the Mega and is garbage to a real gate — this project has already been bitten
by exactly that at 1.67V (`U45.2`).

**Step 4b makes this sharper than it was.** Route B puts five new permanent
`D`-input loads on `W` — four '169s (`LXI SP` wires `W0-W7` straight to their
parallel inputs) plus the scratch '373 — on top of whatever the UART and the
shifter add. These are inputs, not drivers, so no fight is possible; it is
purely a DC level question, which is exactly the kind this project has lost
before.

Before the UART and the shifter join `W`, that measurement stops being a
nice-to-have and becomes a gate. Re-measure `W` levels after **every** device
added, and budget for '245 buffering rather than assuming the existing drivers
scale. This is the one item in the plan that is not a logic question and
cannot be answered by the rig — it is a scope job.

---

## PARTS ON HAND (2026-08-03) — nothing here needs ordering

Bought or in the bin as of 2026-08-03. **Every part the plan calls for is
already here.**

    PART        QTY     WHERE IT GOES
    '169        bought  SP counter, 4 needed for 16-bit. THE good buy —
                        synchronous, so SP_UP/SP_DOWN is a LEVEL not a strobe
    '163        stock   already the T-state counter; spares
    '86         bought  COND polarity: taken = flag XOR pol. One gate.
    '173        bought  4-bit clocked register, TRI-STATE out + input enable.
                        No seat in 4b (scratch is 8-bit: one '373 beats two
                        '173s). PARK FOR STEP 5 — two '173s = one 8-bit D or E
                        register with no external '245, edge-triggered
    '157        stock   COND flag select, 4:1 on FLAG_C/Z/V/N (U48 is one)
    '138        plenty  I/O decode (step 1); SRC/DST widening (2, step 4a);
                        address decode IF route A is ever taken
    '245        tons    SP->W, PC->W, the skewed shifter
    '373        stock   RET scratch byte (53 in the design already)
    '193        stock   NOT for the SP — '169 supersedes. Spares for the PC
    16550       bought  step 2
    3.6864MHz can       bought — supersedes the 1.8432 crystal, see step 2
    AT28C64B    bought  third microcode ROM

**No '139 is needed** and none was bought. A '138 with `A2` grounded IS a
2-to-4 decoder, and it leaves `E3` spare plus four unused codes.

---

## Summary order

    1  I/O decode        one '138        makes everything after it cheap,
                                         and hands two microcode codes back
    2  UART              16550 + 3.6864  the terminal BASIC needs
                         MHz can
    3  shifter           one '245 skewed multiply/divide/normalise
    4a wide word         3rd ROM + 2     ADC/SBB via one net; real
                         '138 + '86 +    conditionals via one XOR gate.
                         '157            8 bits, exactly 8, zero slack
    4b stack             4x '169 + 2x    CALL/RET. Route B: SP via MAR,
                         '245 + 1 '373   no address-bus surgery
    5  D:E index pair    '173 pairs      string ops without spilling
    6  timer, then IRQ   one '393        RND, timing; IRQ only when earned

**Nothing before 4b touches the address mux.** Steps 1, 2, 3, 4a and 5 all
leave `PC_MAR_MUX` exactly as it is. Burn `ADDR_SEL` as a 2-bit field in the
third ROM from day one, wire `bit0` straight to `PC_MAR_MUX` and strap `bit1`
— if route B ever proves wrong, route A's decoder drops in with NO REBURN.

Each step is a module bring-up first, then a rejoin of the block ladder. The
block law does not change: sample only what depends on more than one member,
and the driven-wire count may never go up.

---

## PHASE TWO — PCBs and a real bus (stated 2026-08-02)

Everything above is breadboard work. Once the UART, the third microcode
EEPROM, the stack and the remaining add-ons are in, DINO moves to fabricated
cards on a backplane.

**The card boundaries already exist.** They are the KiCad sheet boundaries,
and `kicad_contracts.py` already emits the exact signal list crossing each
one — that per-sheet IN/OUT/BIDIR contract IS the card-edge pinout. It is
netlist-derived, host-tested, and regenerated on every schematic change, so
the backplane spec cannot drift from the design.

**Consequence for the work above:** anything added during phase one should
respect a sheet boundary rather than reach across it. A signal that crosses
sheets is a bus wire and gets a connector pin; a signal that reaches across
without one becomes a wire with no card to live on.

**WHAT THE BREADBOARD ACTUALLY BOUGHT: the schematics are proven.** That is
the point of it, and the proof is that they were WRONG in specific findable
ways — schematic bug 2 (U21 CE), bug 4 (the U25 bridge defect, which a
rig-emulated bridge passes clean), and the '121 one-shot, which came out
entirely in favour of a clock-phase gate. A schematic that had never been
built would still contain all three, and a PCB spun from it would be three
respins.

**And the schematic is UPSTREAM OF THE BOARD, always.** Nothing was ever
patched on the breadboard, and no fix lives only in BRINGUP.md. Every
correction went into the `.kicad_sch` files first and the board was wired
from what the generators emit — `layout_gen.py` for placement and slot maps,
`kicad_contracts.py` for the hookup tables. So the breadboard is a
VALIDATION of the schematic, not a divergent copy of it, and there is no
back-annotation debt to pay before layout. Phase two starts from a schematic
that is already proven, which is the whole reason phase one was worth doing.

Keep it that way. The moment a fix is made in copper without going through
the schematic, the breadboard stops being evidence about the design and
becomes evidence only about itself.

**The rig survives.** `pins <mod>` comes from the netlist, so a module that
becomes a card is brought up with the SAME module tests that proved it on
breadboard, and the block ladder (blocks 1-5) becomes the backplane's
integration test. AS-BUILT FREEZE stops mattering — the PCB is the record.

Open questions deferred to phase two, not answered here: bus loading and
whether anything needs termination if the clock ever goes above 1.024MHz;
whether the W bus keeps ungated output enables once it leaves breadboard
capacitance; and connector choice.

