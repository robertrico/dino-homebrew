import re,json,math,collections,sys
txt=open('/Users/hackbook/Development/dino-homebrew/dino_v0_0_2/dino_v0_0_2.kicad_pcb').read()
pos={p['reference']:(p['x'],p['y'],p['rotation']) for p in json.load(open(sys.argv[1]))['placements']}
pads=collections.defaultdict(list); boxes={}
for blk in re.split(r'\n\t\(footprint ',txt)[1:]:
    ref=re.search(r'\(property "Reference" "([^"]+)"',blk).group(1)
    ox,oy,rot=pos[ref]; a=math.radians(rot); c,s=math.cos(a),math.sin(a)
    pts=[]
    for px,py,net in re.findall(r'\(pad "[^"]*"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)[^\n]*\n(?:[^\n]*\n){0,8}?\s*\(net "([^"]+)"\)',blk):
        px,py=float(px),float(py); X,Y=ox+px*c+py*s,oy-px*s+py*c; pads[net].append((ref,X,Y)); pts.append((X,Y))
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]; boxes[ref]=(min(xs)-1,min(ys)-1,max(xs)+1,max(ys)+1)
for net in ('CLK','~{CLK}','CLK_B','Net-(U20-CP)','Net-(C1-Pad1)','/RST_SIG','PC6','CW14','/Memory/~{RAM_WRITE_EN}'):
    ps=pads[net]; xs=[p[1] for p in ps]; ys=[p[2] for p in ps]
    print(f'{max(xs)-min(xs)+max(ys)-min(ys):6.0f} {net:24s} {" ".join(sorted({p[0] for p in ps}))}')
refs=list(boxes); bad=[(a,b) for i,a in enumerate(refs) for b in refs[i+1:] if boxes[a][0]<boxes[b][2] and boxes[b][0]<boxes[a][2] and boxes[a][1]<boxes[b][3] and boxes[b][1]<boxes[a][3]]
print('overlaps',bad)
for r in ('U27','U20','U78','U56','U6'): print(r, pos[r][:2])
