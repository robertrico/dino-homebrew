# DINO hardware growth plan

**2026-07-28, updated 2026-08-02. PLAN ONLY — nothing here is built or
burned.**

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

    COST      one PC16550DN + one 1.8432MHz crystal + decoupling
    NEEDS     8-bit data bus, A0-A2, /CS, /RD, /WR, baud crystal

- **It needs its own 1.8432MHz baud crystal.** It does not and cannot divide
  from the 4.096MHz Y1.
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
2. **A real condition-code field.** Every flag, not two codes crammed into the
   last free slots. `FLAG_N` and `FLAG_V` are captured in `U49` today and
   routed nowhere. This is why the Tier 1 `JZ`/`JC` hack is CANCELLED — see
   `dino_isa_for_basic.md` §3.
3. **`SRC` widened to 4 bits**, which is what makes `SRC=PC_LO`/`PC_HI`
   possible, which is what makes `CALL` possible.

**Bring-up:** `microcode_gen.py` grows a third image and a third CRC; the
existing `check_word`/`check_table` policing extends to the new fields. The
`microcode` module test gains a third ROM and a third CRC assertion. Rig
firmware follows via the regenerated header — nothing retyped.

### 4b. The stack

Two board changes, both forced by finding 5:

- **SP needs a 1-of-3 address decode.** `M` is a complementary-enable pair
  today: one bit and its inverse, mutually exclusive by construction, with no
  third state. `U60`'s inverter must become a real decoder driving three
  mutually exclusive enables — MAR, PC, SP.
- **`CALL` needs a PC→W path.** The PC drives `M`, and `M` is address-only, so
  this is a new '245 pair on the pc board feeding `W`, plus the widened `SRC`
  from 4a.

    COST      SP counter pair ('193s, mirroring the PC) + a decoder replacing
              U60's inverter + a '245 pair for PC->W

**Bring-up:** SP is a new MODULE with its own test first — the same law
applies, no shortcuts. Then it joins blocks 2-6. Its address enable is exactly
the kind of mutually-exclusive strobe the block ladder exists to police, and
the 1-of-3 decode is precisely a strike-6 tri-state handoff: assert that no two
of MAR/PC/SP ever enable together, on the LA, at speed.

---

## STEP 5 — A second index pair (D:E)

    COST      2 registers + SRC/DST codes (needs step 4a)

`B:C` alone forces constant save/restore in BASIC. A string copy needs a source
**and** a destination pointer; with one pair, every iteration spills to RAM.
This is a performance and code-size item, not a feasibility one, which is why
it sits below the stack.

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

Every device added to `W` adds load. The `OB3` VOH check already scheduled for
The LED drive is the canary: a 74LS373 sourcing roughly twice its rated `IOH` into a
330Ω LED, on the one node the whole milestone is read from. A pin sitting at
2.0V reads as a clean HIGH to the Mega and is garbage to a real gate — this
project has already been bitten by exactly that at 1.67V (U45.2).

Before the UART and the shifter join `W`, that measurement stops being a
nice-to-have and becomes a gate. Re-measure `W` levels after **every** device
added, and budget for '245 buffering rather than assuming the existing drivers
scale.

---

## Summary order

    1  I/O decode        one '138        makes everything after it cheap,
                                         and hands two microcode codes back
    2  UART              16550 + xtal    the terminal BASIC needs
    3  shifter           one '245 skewed multiply/divide/normalise
    4  wide word + stack 3rd ROM + SP    ADC/SBB, real conditionals, CALL/RET
    5  D:E index pair    2 registers     string operations without spilling
    6  timer, then IRQ   one '393        RND, timing; IRQ only when earned

Each step is a module bring-up first, then a rejoin of the block ladder. The
block law does not change: sample only what depends on more than one member,
and the driven-wire count may never go up.
