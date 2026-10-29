#!/usr/bin/env python3
"""Recolour a single-solid STEP: base colour blue, contact faces gold.

    python3 docs/notes/step_color.py dino_bus/dino_bus.3dshapes/EBC25DCWN.step \
                                     dino_bus/dino_bus.3dshapes/EBC25DCWN_color.step

Written for the Sullins EBC25DCWN model (one solid, 1488 faces): faces
narrower than 1.05 mm in X and <= 3.5 mm in Z, on the 2.54 mm contact grid,
are the 50 contacts (within 0.65 mm of it); the ribs stay blue."""
import re,collections
def load(path):
    s=open(path,errors='ignore').read()
    ent=dict(re.findall(r"#(\d+)\s*=\s*([^;]*);",s))
    return s,ent
def refs(t): return re.findall(r"#(\d+)",t)
def face_bbox(ent,f,cache={}):
    pts=[]
    for b in refs(ent[f].split(',',1)[1])[:-1]:
        e=ent[b]
        if not e.startswith(('FACE_OUTER_BOUND','FACE_BOUND')): continue
        loop=refs(e)[0]
        if not ent[loop].startswith('EDGE_LOOP'): continue
        for oe in refs(ent[loop]):
            ec=refs(ent[oe])[-1]
            for v in refs(ent[ec])[:2]:
                c=refs(ent[v])[0]
                m=re.search(r"\(\s*([-\d.E+]+)\s*,\s*([-\d.E+]+)\s*,\s*([-\d.E+]+)\s*\)",ent[c])
                pts.append(tuple(float(x)*25.4 for x in m.groups()))
    if not pts: return None
    return [min(p[i] for p in pts) for i in range(3)]+[max(p[i] for p in pts) for i in range(3)]
# Recolour the Sullins EBC25DCWN STEP: insulator blue, contacts gold.
# Contacts are the faces narrower than 1.05 mm in X and <= 3.5 mm in Z
# (50 contacts x {tail, spring} faces); everything else is the insulator.
import re, sys
src, dst = sys.argv[1:3]
s, ent = load(src)
BLUE = (0.10, 0.28, 0.62)
GOLD = (0.85, 0.68, 0.25)
# base colour of the solid -> blue
for cid in [k for k, v in ent.items() if v.startswith('COLOUR_RGB')]:
    s = re.sub(r"#%s = COLOUR_RGB \( '',[^;]*;" % cid, "#%s = COLOUR_RGB ( '',%.4f, %.4f, %.4f ) ;" % ((cid,) + BLUE), s)
faces = [k for k, v in ent.items() if v.startswith('ADVANCED_FACE')]
gold = []
for f in faces:
    bb = face_bbox(ent, f)
    if bb and bb[3] - bb[0] <= 1.05 and bb[5] - bb[2] <= 3.5:
        # contacts sit on the 2.54 grid (pin x = +/-30.48 + n*2.54): bodies at
        # 0, tail sides 0.3, spring sides 0.5. The insulator's rib walls sit
        # at 0.8 and the rib tops at 1.27 off the grid: those stay blue
        ph = ((bb[0] + bb[3]) / 2 + 30.48) % 2.54
        if min(ph, 2.54 - ph) <= 0.65:
            gold.append(f)
n = max(int(k) for k in ent) + 1
ids = list(range(n, n + 7))
new = [
    "#%d = COLOUR_RGB ( '',%.4f, %.4f, %.4f ) ;" % ((ids[0],) + GOLD),
    "#%d = FILL_AREA_STYLE_COLOUR ( '', #%d ) ;" % (ids[1], ids[0]),
    "#%d = FILL_AREA_STYLE ('',( #%d ) ) ;" % (ids[2], ids[1]),
    "#%d = SURFACE_STYLE_FILL_AREA ( #%d ) ;" % (ids[3], ids[2]),
    "#%d = SURFACE_SIDE_STYLE ('',( #%d ) ) ;" % (ids[4], ids[3]),
    "#%d = SURFACE_STYLE_USAGE ( .BOTH. , #%d ) ;" % (ids[5], ids[4]),
    "#%d = PRESENTATION_STYLE_ASSIGNMENT (( #%d ) ) ;" % (ids[6], ids[5]),
]
styled = []
k = ids[-1] + 1
for f in gold:
    new.append("#%d = STYLED_ITEM ( 'NONE', ( #%d ), #%s ) ;" % (k, ids[6], f))
    styled.append(k); k += 1
# hang the face styles on the solid's presentation representation
m = re.search(r"(#44586 = MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION \(  '', \( #44588)( \), #44578 \) ;)", s)
assert m, 'MDGPR not found'
s = s.replace(m.group(0), m.group(1) + ''.join(', #%d' % i for i in styled) + m.group(2))
s = s.replace("ENDSEC;\nEND-ISO-10303-21;", "\n".join(new) + "\nENDSEC;\nEND-ISO-10303-21;")
assert "\n".join(new[:1]) in s, 'append failed'
open(dst, 'w').write(s)
print('faces', len(faces), 'gold', len(gold))
