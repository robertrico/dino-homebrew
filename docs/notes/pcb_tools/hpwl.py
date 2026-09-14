import re,sys,collections,json
pcb=sys.argv[1]
txt=open(pcb).read()
pads=collections.defaultdict(list)   # net -> [(ref,x,y)]
for blk in re.split(r'\n\t\(footprint ',txt)[1:]:
    ref=re.search(r'\(property "Reference" "([^"]+)"',blk).group(1)
    m=re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)',blk); ox,oy=float(m.group(1)),float(m.group(2)); rot=float(m.group(3) or 0)
    import math; a=math.radians(rot); c,s=math.cos(a),math.sin(a)
    for px,py,net in re.findall(r'\(pad "[^"]*"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)[^\n]*\n(?:[^\n]*\n){0,8}?\s*\(net "([^"]+)"\)',blk):
        px,py=float(px),float(py)
        pads[net].append((ref, ox+px*c+py*s, oy-px*s+py*c))
rows=[]
for net,ps in pads.items():
    if net in ('GND','+5V','+3.3V','+12V','-12V') or len(ps)<2: continue
    xs=[p[1] for p in ps]; ys=[p[2] for p in ps]
    rows.append((max(xs)-min(xs)+max(ys)-min(ys), net, sorted({p[0] for p in ps})))
rows.sort(reverse=True)
tot=sum(r[0] for r in rows)
print('nets',len(rows),'total HPWL mm',round(tot))
for h,net,refs in rows[:int(sys.argv[2]) if len(sys.argv)>2 else 30]: print(f'{h:6.0f} {net:28s} {" ".join(refs)}')
