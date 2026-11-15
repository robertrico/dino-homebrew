# Rev 1.0 IC sockets

Which socket goes where on the Rev 1.0 mainboard, and what has been bought.
Claims are tagged **fact**, **inference** or **open**, as in `CLAUDE.md`.

## Count per board

**fact** — extracted from `dino_v0_0_2.kicad_pcb` (footprints `Package_DIP:*`),
2026-11-14; agrees with the bare-board photo (`IMG_2502`, 2026-11-14):

| Footprint | Per board | Refs |
|---|---|---|
| DIP-14, 0.3" | 25 | U5 U10 U22 U27 U36 U37 U39 U50 U51 U52 U53 U56 U57 U60 U61 U62 U69 U74 U75 U78 U80 U81 U82 U83 U84 |
| DIP-16, 0.3" | 21 | U1 U2 U3 U4 U6 U7 U8 U20 U28 U29 U30 U48 U63 U64 U65 U66 U70 U71 U76 U77 U87 |
| DIP-20, 0.3" | 35 | U11-U14 U16-U19 U21 U25 U31-U35 U38 U40-U47 U49 U54 U55 U58 U59 U67 U68 U72 U73 U85 U86 |
| DIP-28, **0.6"** | 5 | U9 U15 U23 (microcode), U24 (program ROM), U26 (RAM) |

`Y1` (oscillator, DIP-14 footprint) is soldered, not socketed (Rico): clock
changes go through `J14`, an external clock through `J13`/`JP3`.

## Socket choice (Rico, 2026-11-14)

- **Machined** on the four ROMs, `U9 U15 U23 U24`: they come out for every
  TL866 burn. Adam Tech `ICM-628-1-GT-HT` (0.6", gold contact).
- **Stamped** everywhere else, RAM `U26` included. Adam Tech `ICS-314-T`,
  TE `1-2199298-4` (16-pin; Mouser has no `ICS-316-T`), Adam Tech
  `ICS-320-T`, Adam Tech `ICS-628-T` (0.6").
- Mill-Max `110-44` machined throughout was priced and rejected: about
  7x the stamped price per pin (**fact**, Mouser 2026-11-14: $1.04 vs
  $0.148 for 14-pin).
- Common 28-pin stamped parts (TE `1-2199298-9`, 3M `4828-3004-CP`) are
  **0.3"**: they do not fit `U9/U15/U23/U24/U26`.
- Spares rule: per board, 10% of each size rounded up, at least 2; 28-pin
  +2 per board.

**inference** — every IC socketed on the first boards: chip swaps are how
this machine has been debugged (`U56`, `U47`), and desoldering a DIP from a
4-layer board with solid GND/+5V planes risks the pads.

## ZIF on the ROMs: does not fit Rev 1.0

**fact** — Aries `28-6554-10` (Series 55, datasheet 10001 Rev 2.0): body
0.900" x 1.990" (22.86 x 50.55 mm), 3.81 mm past each pin row and 8.77 mm
past each end row. Checked against the PCB courtyards, 2026-11-14:

| Socket | Under the ZIF body |
|---|---|
| U9 | C27 (pin-1 end), C15 (far end) |
| U15 | C74 (pin-1 end) |
| U23 | C55 (pin-1 end), C80, edges of C16 and TP10 |
| U24 | C19 (pin-1 end), C22, C97 (100 uF electrolytic, 6.3 mm), U31 courtyard edge |

The 0.1 uF discs (`C_Disc_D5.0mm`) stand taller than the gap under a ZIF.
The pin-1 end beyond the body is clear on all four, so the handle would go
there; on U23 it overhangs the board's top edge.

**open** — the handle's reach (~11 mm, read from the drawing) and whether
the two 1.65 mm features on the drawing are locating pegs (they would land
on C27/C15 on U9) are not checked on a real part.

Rev 1.1 candidate: keep each ROM's decoupling cap outside a 23 x 51 mm
outline centred on the footprint.

## Bought

**fact** — Mouser cart, boards 1-2, quantities set 2026-11-14 (Rico
checks out):

| Part | Mouser PN | Qty | Basis |
|---|---|---|---|
| ICS-314-T | 737-ICS-314-T | 56 | 2 x (25 + 3) |
| 1-2199298-4 | 571-1-2199298-4 | 48 | 2 x (21 + 3) |
| ICS-320-T | 737-ICS-320-T | 78 | 2 x (35 + 4) |
| ICS-628-T | 737-ICS-628-T | 17 | 2 x (1 + 2) = 6; 17 is the price break; 15 spare |
| ICM-628-1-GT-HT | 737-ICM-628-1-GT-HT | 17 | 2 x (4 + 2) = 12; 17 is the price break; 9 spare |

Merchandise $60.11, estimated tariff $15.57, UPS Ground $8.49: $84.17.

## Boards 3-5

`rev1_0_sockets_mouser_boards3-5.csv`, Mouser BOM upload format. Ordered
only once board 1 works and the ICs for boards 3-5 are in hand (Rico).

| Part | Qty | Basis |
|---|---|---|
| ICS-314-T | 84 | 3 x (25 + 3) |
| 1-2199298-4 | 72 | 3 x (21 + 3) |
| ICS-320-T | 120 | 3 x (35 + 4) = 117; 120 is cheaper |
| ICM-628-1-GT-HT | 17 | 3 x (4 + 2) = 18, less 5 surplus from boards 1-2 = 13; 17 is cheaper than 13 |
| ICS-628-T | 0 | 3 x (1 + 2) = 9, from the 15 spares |

**fact** — priced 2026-11-14 with `mouser bom`: $72.12 merchandise, before
tariff and shipping. Prices move; re-run before ordering:

    mouser bom dino_v0_0_2/rev1_0_sockets_mouser_boards3-5.csv --boards 1 --format table
