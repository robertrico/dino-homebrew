# DINO block integration ladder — design

**Date:** 2026-07-28
**Status:** approved in conversation; not yet built
**Supersedes:** the INT-A..INT-E ladder, and the "~11 driven / single-stepped"
block plan that preceded it in BRINGUP.md

---

## 1. Problem

All ten modules are bench-proven. Coverage lint reports 0 gaps, 0 pending.
What remains is integration, and the first attempt at planning it produced
a Block 1 wiring table of 52 wires — which was wrong, not merely large.

The error was in kind, not degree: it re-sampled signals that module tests
had already retired. `CW0-8` probes to disambiguate ROM-from-decoder when
`microcode.crc` already proved ROM content exactly. `FLAG_Z` driven to
exercise both `U62` arms when `control_word.truth` already swept it. `CLK`
and `RESET` sampled when `root.clock` and `root.reset` own them.

That is a module test wearing a block's clothes, and it costs exactly what
extra rig wires always cost on this project: one-hole slips, ribbon
transpositions, and evenings.

## 2. The block law

> **Sample a signal at block level only if its value depends on more than
> one member of the block.**

If one module alone determines it, the module test retired it. If an
earlier block sampled it, that block retired it. What remains is precisely
the behavior that has never existed before — the seam.

Four categories, all **derived from the net-list**, none hand-written:

| Category | Rule                                                | Rig                                    |
| -------- | --------------------------------------------------- | -------------------------------------- |
| `COPPER` | OUT of one member AND IN of another                 | **dropped** — wired board-to-board     |
| `DRIVE`  | IN of a member, OUT of none, needed as stimulus     | drives, 220-470R series                |
| `STRAP`  | IN of a member, OUT of none, not needed as stimulus | **not a rig wire** — tied on the board |
| `SAMPLE` | OUT of a member, not copper, not already retired    | samples                                |

Every retirement must **name the test that earned it**. That is the
reviewable part, and it is why `retire` is a dict.

**Accepted exception:** `END` and `HALT` are copper (microcode → root) but
are sampled in every block. Nothing else can segment the instruction
stream or observe the freeze from outside. Stated as an exception rather
than smuggled in as a special case.

### Gate

Driven-wire count may never rise as blocks accrete. Risk is asymmetric: a
wrong sampled wire is a false FAIL, a wrong driven wire can fight a real
driver, and a wrong driven **strobe** is worst because strobes are enables
— that is how two boards end up on one bus.

### Nothing is ever pulled

Chips and board-to-board copper are never touched. Y1 stays seated from
Block 1 to Block 6. Rig **jumpers** come off freely as they retire — that
is the ladder. Temporary board straps come off when real copper takes over
the net, or a real driver meets a tie.

**Consequence.** `CLK` is `U27.5` and `RESET` is `U27.9`, both '74
totem-pole outputs. The only non-contending clock injection point
(`U20.2`) requires Y1 out of its socket. Therefore:

> The rig never owns the clock. Every block free-runs at 1.024MHz. There
> is no single-stepping anywhere on this ladder.

Every block test is burst-capture-and-decode. Reset is the physical button
on an `ARM ...` prompt, as `root`'s tests already do.

## 3. The ladder

| Block | Adds | Driven | Sampled | Jumpers |
|---|---|---|---|---|
| 1 | root, microcode, control_word | 8 | 26 | 34 + GND |
| 2 | pc, mar, memory | 8 | 10 | 18 + GND |
| 3 | mdr | **0** | 10 | 10 + GND |
| 4 | registers, alu | 0 | 10 | 10 + GND |
| 5 | io | 0 | 10 | 10 + GND |
| 6 | free-run | 0 | 9 | 9 + GND |

Driven hits zero at Block 3, when the real IR fetches the machine's own
instruction bytes. From there the rig configures no output pin and cannot
fight anything by construction.

`END`/`HALT` are the same two wires in all six blocks — **D45/D42, tapped
at `U61.3`/`U61.5`**, the consumer end where `END` reaches `U6.~{MR}` and
`HALT` reaches `U6.CET`. Sampling the ROM's own pins (`U15.16`/`.19`)
would prove the ROM pin and nothing about the two-board run that does the
work. Three independent derivation passes all picked the source end first;
this is easy to get wrong.

## 4. What gets built

### 4.1 `BLOCKS` in `kicad_contracts.py`

```python
BLOCKS = {
    "control": {
        "members": ["root", "microcode", "control_word"],
        "retire": {                       # single-member, already proven
            "CLK":      "root.clock",
            "~{CLK}":   "root.clock",
            "RESET":    "root.reset",
            "~{RESET}": "root.reset",
        },
        "strap": {"FLAG_Z": ("HIGH", "control_word.truth")},
        "sample_anyway": ["CW12=END", "CW15=HALT"],
    },
}
```

Emitter requirements:

- Derive `COPPER` / `DRIVE` / `STRAP` / `SAMPLE` per §2 from
  `build_contracts()` over the member union.
- **Hard-error**, never last-writer-wins, on: a pin claimed by two
  members; a `retire` or `strap` key not present in the union; a
  `sample_anyway` key that is not copper.
- Emit a **`FLOAT` list**: every IN of a member with no OUT in the block
  and no `strap` entry. Each one is a hazard until named — see
  `WRITE_DIR` in §5.2.
- `PIN_ASSIGN` still outranks everything.
- Block bundles join `MODMAPS` as ordinary entries, so `pins control`,
  `run control.*`, `sig_lookup`, `slot_of` and `coverage_lint` all work
  with no new plumbing.

### 4.2 Host test — RED first

Mirrors `test_kicad_contracts_pinmap.py`:

- copper (`T0-3`, `CW0-8`) appears in **neither** drive nor sample
- `DRIVE` is exactly `IRB0-7`
- `SAMPLE` is exactly the 26 of §5.1
- a duplicate pin across members raises
- a bogus `retire` / `strap` / `sample_anyway` name raises
- `FLOAT` is empty once `FLAG_Z` is strapped

### 4.3 `pins control` in the shell

Same contract as `pins <mod>`: the printout **is** the complete hookup.

### 4.4 `mod_control.c` + registry entries

## 5. Block detail

### 5.1 Block 1 — 8 drive, 26 sample

**Drive:** `IRB0-7` → `U16` .2 .4 .6 .8 .11 .13 .15 .17 (PK, A8-A15).
Note the 1A/2A split — the '244 pins are not monotonic.

**Sample, grouped by port** because `capture_burst()` reads whole ports
and a group split across two ports cannot be read coherently:

| Port | Mega | Signals | DUT |
|---|---|---|---|
| PL | D48-D42 | `SA2 SA1 SA0 END PC_UP PC_MAR_MUX HALT` | `U15` .12 .13 .15 · `U61.3` · `U15` .17 .18 · `U61.5` |
| PA | D22-D28 | 7 DST strobes | `U30` .14 .13 .12 .11 .10 .9 .7 |
| PC | D30-D37 | `SRC_ACTIVE` + 7 SRC strobes | `U28` .15 .14 .13 .12 .11 .10 .9 .7 |
| PF | A0-A3 | `~{PC_CLEAR} ~{MDR_OUT} ~{REG_OUT_LOAD} ~{PC_LOAD}` | `U29` .14 .11 .9 · `U62.10` |

Three burst passes: `(PL,PA)` dst, `(PL,PC)` src, `(PL,PF)` jmp. `IRB` is
held across all three and the machine repeats, so passes are comparable.
All 8 SRC bits on one port is what makes `control.onehot` coherent in a
single read.

**`PL` is extended I/O** on the 2560 — `lds`, not `in` — so a pass
touching it costs ~547ns/sample rather than root's 437ns. Still ample: a
one-T `END` pulse is 977ns, and any pulse at least as long as the sample
period yields at least one uniform sample.

**Strap:** `FLAG_Z` **HIGH**, 1k to +5V, at `U62.3`.
`COND_TAKEN = NOR(~{COND}, FLAG_Z)`, so HIGH pins `COND_TAKEN` low and
`~{PC_LOAD} = NOR(COND_TAKEN, PC_LOAD_JMP)` can only be pulled by a real
JMP decode. The milestone program has no JMP or JNZ, so `~{PC_LOAD}` must
stay HIGH all run. **Strapping LOW is the dangerous choice** — a spurious
`~{COND}` would branch into a garbage MAR. 1k rather than a hard tie so a
strap forgotten at Block 4 meets `U49.5` as a 5mA pull, not a short.

**Copper to wire by hand:** `T0-3` (`U6` .14 .13 .12 .11 → `U17` .2 .4 .6
.8), `CW0-8` (`U9` .11-.13 .15-.19 + `U15.11` → `U30`/`U28`/`U29` .1 .2
.3), and `U15.16`→`U61.3`, `U15.19`→`U61.5`.

**Why no `CW0-8` probes**, beyond the law: the 19 sampled decoder outputs
are an **invertible** encoding of `CW0-8` for every word `microcode_gen`
emits. `U28.O0` is wired (`SRC_ACTIVE`) so all 8 SRC codes read back;
`U30` code 0 reads all-high, unambiguous; `U29`'s only aliased codes are 5
and 7 and `MISC` never emits either. `CW9-15` are separately sampled. So
`CW0-15` is fully reconstructible with zero `CW0-8` wires.

**Tests.** Same stimulus throughout: force `IRB`, free-run, burst-capture,
decode offline.

- `decode` — cut the stream at each `END`. The frame after a cut is `t=0`,
  and **position within the run is `t`**. Compare against
  `MC_REAL_WORDS[(op<<4)|t]`. This asserts **order and run length**, not
  just contents; a wrong `END` row or a skipped state fails here and a
  per-`T` lookup would miss both. `T0-3` is not sampled — it is copper.
- `onehot` — never two SRC enables low at once, never two DST loads.
- `seq` — force `HALT`'s opcode: the run freezes and never resumes.
- `stability` — repeat N×, identical results.

`control.cond` is **deleted**. `control_word.truth` already swept `FLAG_Z`
both ways against the real `U62`.

**Manual, 2 probes:** `~{ROM_OUT}` (`U28.14`) + `~{RAM_OUT}` (`U28.13`),
trigger both-low — the 10-30ns decode transient the Mega structurally
cannot see. This is a **supply** measurement, not a correctness one (see
the machine invariant), and Block 1 is the safest place in the build to
take it: those outputs go to rig sample pins and nothing else, so there is
literally nothing to fight. Do not gate the '138s pre-emptively.

### 5.2 Block 2 — 8 drive, 10 sample

26 sample wires off, `MDR0-7` on at `U19` .18 .17 .16 .15 .14 .13 .12 .11
(PF, A0-A7). `IRB` and `END`/`HALT` unchanged.

**Straps, both removed at Block 3:**
- `WRITE_DIR` → GND at `U51.1`. Forces
  `~{RAM_WRITE_EN} = NAND(0, ~CLK) = 1` so no write ever fires, while
  `~{RAM_MDR_EN} = ~{RAM_OUT}` keeps reads working. **Floating it is a
  live hazard** — it also sets the `U21` '245 direction, and a floating
  HIGH gives a real RAM write every clock low into whatever `W` floats at.
- `W0-7` → **10k pulldowns** at `U55` .3 .4 .7 .8 .13 .14 .17 .18. Never a
  hard tie: `U25` drives this bus from Block 3.

**Test:** bytes on `MDR0-7` are the ROM image **in address order**.
Checked against `progrom_expect.h`.

**Run `PROG_diag.bin` first.** `diag_byte = ((addr*0x9D)^(addr>>5))&0xFF`
is injective over the first 32 addresses, so every fetched byte names its
own address. `MDR0-7` is the only address witness here (`M0-15` is
copper), and the real image's `0xFF` tail names nothing.

**Honest scope:** this does **not** prove PC→MAR→ROM. With no `W` driver,
`~{MAR_LO_LOAD}`/`~{MAR_HI_LOAD}` latch garbage; `LDA`/`STA`/`JMP`/`JNZ`
reach MAR only through the absent bridge. It proves the `PC_MAR_MUX`
handoff on `M` and `~{RAM_EN} = INV(M15)`.

### 5.3 Block 3 — 0 drive, 10 sample

`MDR0-7` off. `IRB0-7` **stays in the same holes at `U16`** and flips from
rig output to rig input; leave the series resistors in, they are harmless
on a sampled line and are the only thing between a stale bundle and `U34`
driving into a rig output. Remove the `WRITE_DIR` and `W0-7` straps
**before** landing the board — `U37.4` is a '04 output and a GND strap on
it is a dead short.

Sampling `IRB` at the **consumer** end makes it the **mirror-witness** for
the `U25` bridge: Block 2 read that same byte at `MDR`, before it crossed
`U25` and `U34`. A bridge or IR permutation that a MDR-side read cancels
out shows up here and nowhere else.

**Test:** opcode stream `0x11 0x12 0x41 0x51 0xFF`, PC stride `2,2,1,1,1`
derived from `PC_UP` counts in the burned microcode — no new table. Block
2 forced `IRB` constant so the stride was constant and a length error was
invisible; here a wrong length desyncs the very next fetch.

**Manual, 2 probes:** `BUS_DIR` (`U39.8`) vs `~{MDR_EN}` (`U22.4`) on the
bug-4 chip. Direction must settle before the bridge enables.

**Expected, not a fault:** during ADD's T1, `src=ALU` asserts
`~{ALU_OUT}`, `BUS_DIR` flips to W→MDR, and `U25` drives MDR from a
floating `W`. Nothing else drives MDR in that window — indeterminate data,
not a fight.

### 5.4 Block 4 — 0 drive, 10 sample

`IRB` off, `OB0-7` on at `U35` .2 .5 .6 .9 .12 .15 .16 .19 (the '373
zigzag — count chip pins, not header order). Remove the `FLAG_Z` strap:
`U49.5` drives `U62.3` now, and leaving it is a '273 output into a tie.

**First block that computes 5+3.**

**Test:** exactly 4 `END` pulses (LDAI, LDBI, ADD, OUT), then `HALT` high
forever and `END` never again — HALT's row is `0x8000` and carries no END
bit. `OB` reads `PR_EXPECT_SUM = 0x08` from HALT onward.

`bit-reverse(0x08) = 0x10`, so a flipped OB ribbon reads `0x10` and
self-names. The milestone value is self-witnessing; most bytes are not.

`U35` has **no reset**. On a re-run `OB` may already be `0x08` before the
program starts, degenerating the assertion. Power-cycle for the strong
form; if `OB` reads `0x08` at trigger, print `INCONCLUSIVE`, never `PASS`.

**Manual, 2 probes:** `CLK` (`U27.5`) vs `LE_TMP_A` (`U50.1`).

### 5.5 Block 5 — 0 drive, 10 sample

`OB0-7` moves to the io end, `R9-R16` pin 1, same Mega pins — far-end tap,
because that harness is what this block adds.

**Strap:** `IS0-7` = SW1 at `0xF7`. Switches are 10k pulled up and short
to GND, so no driver to fight. `0xF7` is a **witness**: `~{SW_OUT}` never
asserts in this program so the '244 must stay off, and its only 0-bit is
`W3` — exactly the bit of the answer `0x08`. A leaking '244 turns `OB`
into `0x00` and names itself. Re-run at `0xFF` as the control.

No scope work here. Save the probe budget for Block 6.

### 5.6 Block 6 — 0 drive, 9 sample

Drop the `END` jumper. Nothing added, moved, or reseated.

`HALT` is a clean two-state marker and the burst's own trigger:
LOW = reset cleared T to 0, fetch row `0x600E` selected, **running**;
HIGH = row `0x8000`, `CET` low, T frozen, clock still running, **halted**.

**Test:** `OB = 0x08` at HALT, still `0x08` after a second of re-polling,
and **ten resets give ten `0x08`s**. At 1.024MHz a marginal setup path
fails probabilistically; one pass is an anecdote. Plus the human check
that costs nothing: one LED lit, bit 3.

**This is where timing is retired.** Two probes, two setups:

- `CLK` (`U27.5`) vs `~{REG_A_LOAD}` (`U30.14`). The machine's longest
  control path: CLK rise → `U6` '163 → `U16`/`U17` buffers → AT28C64B
  access (tACC 150-250ns) → `U30` '138 decode. It must finish before CLK
  falls, because `LE_REG_A = NOR(~{REG_A_LOAD}, CLK)` commits the ADD
  result. Budget is 488ns minus '373 setup. EEPROM access alone can eat
  half, and Block 1 measured this node without the full fan-out.
  **Fix is a slower clock** (`U20` already provides divide taps), not
  gating the '138s.
- `OB3` at `U35.9`, VOH with the single LED lit. `U35` is an LS373 rated
  `IOH = -2.6mA`; `R12` is 330R drawing ~4-5mA. Roughly twice its rating,
  on the one node the milestone is read from. A pin at 2.0V reads clean on
  `PINK` and is garbage to a real gate — this project has been bitten by
  exactly that at 1.67V.

## 6. Build order

1. `BLOCKS` host test — RED
2. `BLOCKS` in `kicad_contracts.py` — GREEN
3. `pins control` in the shell
4. `coverage_lint` taught about blocks
5. `mod_control.c` + registry
6. `avr-gcc -Werror` clean, all host tests green
7. Bench: wire Block 1, `run control`

Steps 1-6 are verifiable on the host. Step 7 is Rico's.

## 7. Open

- Whether `control.seq` stays fully automated or takes the `ARM`-prompt
  reset path. Reset costs one driven wire at the RC node (`U56.1`) if
  automated; the button costs zero and is what every root test already
  does. Leaning button — the gate is the gate.
- Whether Block 2 wants a second `MDR` sample pass at a different tap
  point for mirror-witness purposes, or whether Block 3's consumer-end
  `IRB` read is sufficient. Leaning sufficient.
