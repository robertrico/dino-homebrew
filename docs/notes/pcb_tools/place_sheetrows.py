#!/usr/bin/env python3
"""THROWAWAY: PCB_LAYOUT.md SECTION 2 -> absolute placements (JSON)."""
import json, re, sys
PCB = '/Users/hackbook/Development/dino-homebrew/dino_v0_0_2/dino_v0_0_2.kicad_pcb'
txt = open(PCB).read()
fp_of = {}
for blk in re.split(r'\n\t\(footprint ', txt)[1:]:
    fp_of[re.search(r'\(property "Reference" "([^"]+)"', blk).group(1)] = blk.split('"', 2)[1]

W, H = 305.0, 250.0
XL, Y0 = 5.0, 5.0
COL = 15.24
PIN1_OFF = 1.3
CHIP_TOP = 6.0            # pin-1 y below row top (cap lives above)

def npins(fp):
    m = re.search(r'DIP-(\d+)', fp); return int(m.group(1)) if m else None

def row_h(ics):
    h = 0
    for r in ics:
        fp = fp_of[r]
        if 'W15.24' in fp: h = max(h, 45.72)
        elif 'DIP-20' in fp: h = max(h, 35.56)
        elif 'DIP-16' in fp or 'Oscillator' in fp: h = max(h, 30.48)
        else: h = max(h, 27.94)
    return h

# rows: list of (ref, col) ; wide chips and Y1 take col, col+1
ROWS = [
    [('U9',0),('U15',2),('U23',4),('U16',6),('U17',7),('U74',8),('U75',9),('U24',10),('U26',12)],
    [('U6',0),('U7',1),('U8',2),('U61',3),('U28',4),('U29',5),('U30',6),('U34',7),('U70',8),('U71',9),('U19',10),('U21',11),('U18',12),('U25',13)],
    [('U1',0),('U2',1),('U3',2),('U4',3),('U10',4),('U36',5),('U20',6),('U27',7),('Y1',8),('U56',10),('U22',11),('U37',12),('U39',13)],
    [('U11',0),('U12',1),('U13',2),('U14',3),('U31',4),('U32',5),('U33',6),('U57',7),('U45',8),('U46',9),('U54',10),('U55',11),('U58',12),('U59',13)],
    [('U41',0),('U42',1),('U43',2),('U44',3),('U35',4),('U5',5),('U49',6),('U48',7),('U38',8),('U40',9),('U47',10),('U60',11),('U72',12),('U73',13)],
    [('U62',0),('U77',1),('U52',2),('U50',3),('U53',4),('U69',5),('U63',6),('U64',7),('U65',8),('U66',9),('U67',10),('U68',11),('U51',12),('U78',13)],
]
placed = []
def put(ref, x, y, rot=0.0): placed.append({'reference': ref, 'x': round(x, 3), 'y': round(y, 3), 'rotation': rot})

caps = sorted((r for r, fp in fp_of.items() if r.startswith('C') and 'C_Disc' in fp), key=lambda r: int(r[1:]))
cap_i = 0
def cap_for(vx, vy):
    """0.1uF above the VCC pin at (vx, vy): pads at vx-2.5 and vx, 4 mm up."""
    global cap_i
    if cap_i >= len(caps): return
    put(caps[cap_i], vx - 2.5, vy - 4.0); cap_i += 1

ytop = Y0
row_tops = []
for row in ROWS:
    h = row_h([r for r, _ in row]); row_tops.append((ytop, h))
    for ref, c in row:
        fp = fp_of[ref]; x0 = XL + COL * c
        if 'W15.24' in fp:
            x = x0 + 6.0; y = ytop + CHIP_TOP; put(ref, x, y); cap_for(x + 15.24, y)
        elif ref == 'Y1':
            x = x0 + 2.5; y = ytop + 12.0; put(ref, x, y)          # pads y-7.62..y
            put('R1', x0 + 2.0, ytop + 21.5)                          # horizontal, 10.16 pitch
            put('C1', x0 + 20.0, ytop + 21.5)                         # radial 2.0 pitch
            cap_for(x + 15.24, y - 7.62)                              # above osc VCC pin
        else:
            n = npins(fp); x = x0 + PIN1_OFF; y = ytop + CHIP_TOP; put(ref, x, y); cap_for(x + 7.62, y)
    ytop += h
logic_bottom = ytop
print('logic bottom', logic_bottom, 'caps used', cap_i, 'of', len(caps), file=sys.stderr)

# series clock resistors, vertical in a column channel (rot 90 -> pad 2 goes -Y)
r5top = row_tops[5][0]
put('R2', XL + COL * 6 - 2.4, r5top + 18.0, 90.0)     # channel c5|c6, beside U63
put('R3', XL + COL * 13 - 2.4, r5top + 18.0, 90.0)    # channel c12|c13, beside U51

# front panel: 16 resistors vertical at 5 mm, 8 LEDs, reset button
fy = logic_bottom + 3.0
rs = ['R9','R10','R11','R12','R13','R14','R15','R16','R4','R5','R6','R7','R8','R25','R26','R27']
for i, r in enumerate(rs): put(r, 10.0 + 5.0 * i, fy + 12.0, 90.0)
for i in range(8): put(f'D{i+1}', 12.0 + 7.62 * i, fy + 18.0)
put('SW2', 100.0, fy + 8.0)

# slots, flush right; picoPSU connector below them, clear of every card zone
cx = W - 33.75 - 0.5
for k in range(8): put(f'J{k+1}', cx, 12.0 + 17.78 * k)
put('J9', 224.0, 165.0)
put('J10', 290.0, 165.0)

refs = {p['reference'] for p in placed}
missing = sorted(set(fp_of) - refs); extra = sorted(refs - set(fp_of))
print('missing', missing, 'extra', extra, file=sys.stderr)
json.dump({'W': W, 'H': H, 'placements': placed}, open(sys.argv[1], 'w'), indent=0)
print('placed', len(placed), file=sys.stderr)
