#!/usr/bin/env python3
"""THROWAWAY: SA over DIP cell assignment, cost = weighted HPWL. Emits placements JSON."""
import re, sys, json, math, random, collections
PCB='/Users/hackbook/Development/dino-homebrew/dino_v0_0_2/dino_v0_0_2.kicad_pcb'
txt=open(PCB).read()
fp_of={}; padoff=collections.defaultdict(list)   # ref -> [(dx,dy,net)]
for blk in re.split(r'\n\t\(footprint ',txt)[1:]:
    ref=re.search(r'\(property "Reference" "([^"]+)"',blk).group(1); fp_of[ref]=blk.split('"',2)[1]
    for px,py,net in re.findall(r'\(pad "[^"]*"[^\n]*\n\s*\(at ([-\d.]+) ([-\d.]+)[^\n]*\n(?:[^\n]*\n){0,8}?\s*\(net "([^"]+)"\)',blk):
        padoff[ref].append((float(px),float(py),net))
SKIP={'GND','+5V','+3.3V','+12V','-12V'}
WEIGHT={'CLK':6.0,'~{CLK}':4.0,'CLK_B':6.0,'Net-(U20-CP)':6.0,'/RST_SIG':5.0,'Net-(C1-Pad1)':5.0,'RESET':2.0}

W,H=305.0,250.0; XL,Y0=5.0,5.0; COL=15.24; PIN1=1.3; TOP=6.0
ROWH=[45.72,35.56,30.48,35.56,35.56,35.56]
rowtop=[]; y=Y0
for h in ROWH: rowtop.append(y); y+=h
# cells: (x_pin1, y_pin1, cls)   cls: 'wide','n35','n30'
cells=[]
for c in (0,2,4,10,12): cells.append((XL+COL*c+6.0, rowtop[0]+TOP, 'wide'))
for c in (6,7,8,9):     cells.append((XL+COL*c+PIN1, rowtop[0]+TOP, 'n35'))
for r in (1,3,4,5):
    for c in range(14): cells.append((XL+COL*c+PIN1, rowtop[r]+TOP, 'n35'))
for c in (0,1,2,3,4,5,6,7,10,11,12,13): cells.append((XL+COL*c+PIN1, rowtop[2]+TOP, 'n30'))
Y1X=XL+COL*8
def chipcls(ref):
    fp=fp_of[ref]
    if 'W15.24' in fp: return 'wide'
    if 'DIP-20' in fp: return 'n35'
    return 'small'
chips=[r for r in fp_of if r.startswith('U')]
assert len(chips)==77, len(chips)
def ok(ref,cell):
    cc=chipcls(ref); k=cell[2]
    return (cc=='wide' and k=='wide') or (cc=='n35' and k=='n35') or (cc=='small' and k in('n35','n30'))
# fixed pad positions (non-U parts) from current board; Y1/R1/C1 from place.py geometry
fixed=collections.defaultdict(list)
cur={}
for blk in re.split(r'\n\t\(footprint ',txt)[1:]:
    ref=re.search(r'\(property "Reference" "([^"]+)"',blk).group(1)
    m=re.search(r'\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)',blk); cur[ref]=(float(m.group(1)),float(m.group(2)),float(m.group(3) or 0))
cur['R1']=(110.0,236.0,0.0); cur['C1']=(123.5,236.0,0.0)
for ref,(ox,oy,rot) in cur.items():
    if ref.startswith('U') or (ref.startswith('C') and ref!='C1') or ref in ('R2','R3'): continue
    a=math.radians(rot); c,s=math.cos(a),math.sin(a)
    for dx,dy,net in padoff[ref]:
        if net in SKIP: continue
        fixed[net].append((ox+dx*c+dy*s, oy-dx*s+dy*c))
# initial assignment: greedy by class, then anneal
random.seed(int(sys.argv[2]) if len(sys.argv)>2 else 1)
free={k:[i for i,c in enumerate(cells) if c[2]==k] for k in ('wide','n35','n30')}
assign={}
for r in sorted(chips, key=lambda r: {'wide':0,'n35':1,'small':2}[chipcls(r)]):
    k=chipcls(r)
    pool=free['wide'] if k=='wide' else free['n35'] if k=='n35' else (free['n30'] if free['n30'] else free['n35'])
    assign[r]=pool.pop(0)
assert not any(free.values()), free
nets_of=collections.defaultdict(set)
for r in chips:
    for dx,dy,net in padoff[r]:
        if net not in SKIP: nets_of[r].add(net)
allnets=set(fixed)|{n for r in chips for n in nets_of[r]}
def chip_pads(r, cell):
    x,y=cell[0],cell[1]
    return [(x+dx,y+dy,net) for dx,dy,net in padoff[r] if net not in SKIP]
def net_cost(net, pts):
    if len(pts)<2: return 0.0
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    return WEIGHT.get(net,1.0)*((max(xs)-min(xs))+(max(ys)-min(ys)))
def net_points(net, assign):
    pts=list(fixed.get(net,()))
    for r in members[net]:
        c=cells[assign[r]]
        pts+= [(c[0]+dx,c[1]+dy) for dx,dy,n in padoff[r] if n==net]
    return pts
members=collections.defaultdict(list)
for r in chips:
    for n in nets_of[r]: members[n].append(r)
cost={n:net_cost(n,net_points(n,assign)) for n in allnets}
total=sum(cost.values())
print('start HPWL',round(total),file=sys.stderr)
T=40.0; best=total; bestA=dict(assign); it=0
while T>0.05:
    for _ in range(400):
        a,b=random.sample(chips,2)
        ca,cb=cells[assign[a]],cells[assign[b]]
        if not(ok(a,cb) and ok(b,ca)): continue
        assign[a],assign[b]=assign[b],assign[a]
        touched=nets_of[a]|nets_of[b]
        new={n:net_cost(n,net_points(n,assign)) for n in touched}
        d=sum(new.values())-sum(cost[n] for n in touched)
        if d<0 or random.random()<math.exp(-d/T):
            cost.update(new); total+=d
            if total<best: best=total; bestA=dict(assign)
        else:
            assign[a],assign[b]=assign[b],assign[a]
    T*=0.92
print('best weighted',round(best),'unweighted',round(sum(net_cost(n,net_points(n,bestA))/WEIGHT.get(n,1.0) for n in allnets)),file=sys.stderr)
assign=bestA
# emit placements
placed=[]
def put(ref,x,y,rot=0.0): placed.append({'reference':ref,'x':round(x,3),'y':round(y,3),'rotation':rot})
caps=sorted((r for r,fp in fp_of.items() if r.startswith('C') and 'C_Disc' in fp), key=lambda r:int(r[1:]))
ci=0
def cap(vx,vy):
    global ci
    put(caps[ci],vx-2.5,vy-4.0); ci+=1
for r in chips:
    x,y,k=cells[assign[r]]
    put(r,x,y)
    cap(x+(15.24 if k=='wide' else 7.62), y)
# Y1 block fixed (row 2, cols 8-9)
put('Y1',Y1X+2.5,rowtop[2]+12.0); put('R1',110.0,236.0); put('C1',123.5,236.0)
assert ci==len(caps),(ci,len(caps))
# R2 beside U63 (left channel), R3 beside U51
def beside(ref):
    x,y,k=cells[assign[ref]]; return (x-PIN1-2.4, y+12.0)
for rr,u in (('R2','U63'),('R3','U51')):
    bx,by=beside(u); put(rr,bx,by,90.0)
for ref,(ox,oy,rot) in cur.items():
    if ref not in {p['reference'] for p in placed}: put(ref,ox,oy,rot)
json.dump({'placements':placed},open(sys.argv[1],'w'))
# report
rowmap=collections.defaultdict(list)
for r in chips:
    x,y,k=cells[assign[r]]; rowmap[round(y,2)].append((x,r))
for y in sorted(rowmap): print(f'y={y:6.1f}: '+' '.join(r for x,r in sorted(rowmap[y])),file=sys.stderr)
