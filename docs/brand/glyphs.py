from shapely.geometry import LineString, LinearRing, Polygon, box
from shapely.ops import unary_union
from shapely import affinity
H=100.0
def stroke(g,w,cap='flat'):
    return g.buffer(w/2, cap_style=cap, join_style='mitre', mitre_limit=2.0)

def centerlines(S, W=84, c=None, nstyle='diag', apex=None):
    h=S/2
    if c is None: c=S*1.0
    L={}
    # D: straight left, chamfered right corners
    L['D']=(W,[LinearRing([(h,h),(W-h-c,h),(W-h,h+c),(W-h,H-h-c),(W-h-c,H-h),(h,H-h)])])
    L['I']=(S,[LineString([(h,0),(h,H)])])
    if nstyle=='diag':
        e=S*0.35 if apex is None else apex   # flat apex at each turn keeps tracks off acute joins
        pts=[(h,0),(h,H-h),(h+e,H-h),(W-h-e,h),(W-h,h),(W-h,H)] if e>0 else [(h,0),(h,H-h),(W-h,h),(W-h,H)]
        L['N']=(W,[LineString(pts)])
    else: # arch with chamfer top-right
        L['N']=(W,[LineString([(h,0),(h,H-h),(W-h-c,H-h),(W-h,H-h-c),(W-h,0)])])
    L['O']=(W,[LinearRing([(h+c,h),(W-h-c,h),(W-h,h+c),(W-h,H-h-c),(W-h-c,H-h),(h+c,H-h),(h,H-h-c),(h,h+c)])])
    return L

def clip(g): return g.intersection(box(-50,0,500,H))

def glyph(cl,S):
    return clip(unary_union([stroke(x,S) for x in cl]))

def glyph_inline(cl,S,n=3,gap=None):
    """Split a stroke of width S into n parallel tracks with n-1 gaps."""
    if gap is None: gap=S*0.16
    t=(S-(n-1)*gap)/n
    res=glyph(cl,S)
    # gap edges as distances from the centerline, symmetric
    edges=[-S/2+k*t+(k-1)*gap for k in range(1,n)]   # each gap spans [e, e+gap]
    for e in edges:
        a,b=e,e+gap
        if a>=0 or b<=0:
            r1,r2=sorted((abs(a),abs(b)))
            if a>=0:  # mirrored partner handled by symmetric ring
                for c1 in cl: res=res.difference(stroke(c1,2*r2).difference(stroke(c1,2*r1)))
        else:   # gap straddles the centerline (even n)
            for c1 in cl: res=res.difference(stroke(c1,2*max(-a,b)))
    return clip(res)

def word(text,S=24,W=84,G=14,c=None,nstyle='diag',inline=False,n=3,gap=None,apex=None):
    L=centerlines(S,W,c,nstyle,apex)
    x=0; parts=[]
    for ch in text:
        w,cl=L[ch]
        g=glyph_inline(cl,S,n,gap) if inline else glyph(cl,S)
        parts.append(affinity.translate(g,x,0)); x+=w+G
    return unary_union(parts), x-G

def to_path(g, sx=1, ox=0, oy=0, flipH=H):
    from shapely.geometry import MultiPolygon
    polys = g.geoms if hasattr(g,'geoms') else [g]
    d=[]
    for p in polys:
        if p.geom_type!='Polygon': continue
        for ring in [p.exterior,*p.interiors]:
            pts=list(ring.coords)[:-1]
            d.append('M'+' L'.join(f'{ox+x*sx:.3f},{oy+(flipH-y)*sx:.3f}' for x,y in pts)+' Z')
    return ' '.join(d)

