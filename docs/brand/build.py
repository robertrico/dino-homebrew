# DINO logo geometry -> SVG. Run here: python3 build.py (shapely, cairosvg). Writes out/.
from glyphs import *
import os
OR='#E35F1A'; BK='#16130F'; GR='#4A3F37'; BE='#D8CCAA'
os.makedirs('out',exist_ok=True)
# the mark: 3 tracks; t = 7.33 u, gap 5 u. At 20 mm cap: 1.47 mm tracks, 1.0 mm gaps (FDM, 0.4 nozzle)
INL=dict(c=18,S=32,W=104,G=16,inline=True,n=3,gap=5,nstyle='diag')
SOL=dict(c=16,S=28,W=104,G=14,nstyle='diag',apex=0)   # compact, under ~12 mm cap
# bus colour orders, bottom line first; each colour its own height for layer-swap printing
BUS={'A':[OR,GR,BK],'B':[BK,OR,GR]}
HEIGHT={OR:0.6,GR:1.0,BK:1.4}    # mm above the panel; the wordmark is orange, +0.6

def svg_doc(wmm,hmm,body,bg=None):
    r=f'<rect width="{wmm}" height="{hmm}" fill="{bg}"/>' if bg else ''
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{wmm}mm" height="{hmm}mm" viewBox="0 0 {wmm} {hmm}">{r}{body}</svg>'
def P(g,fill,s,ox,oy,ident=''):
    i=f' id="{ident}"' if ident else ''
    return f'<path{i} fill-rule="evenodd" fill="{fill}" d="{to_path(g,s,ox,oy)}"/>'

def wordmark(name,g,w,s=0.2,m=2):
    W=round(w*s+2*m,2); Hh=H*s+2*m
    open(f'out/dino_wordmark_{name}.svg','w').write(svg_doc(W,Hh,P(g,'#000',s,m,m,'wordmark')))
    open(f'out/dino_wordmark_{name}_color.svg','w').write(svg_doc(W,Hh,P(g,OR,s,m,m),BE))

def panel(g,w,order):
    """Front panel from case_gen.py: 203.56 x 31.16 mm, beige, OB LEDs top right,
    the row ending where the bus's longest line ends, lx in from the right.
    One group per colour, named with its emboss height."""
    PW,PH=203.56,31.16
    cap=20.0; s=cap/H; lx=8.0; top=(PH-cap)/2
    S=INL['S']*s; gp=INL['gap']*s; t=(INL['S']-2*INL['gap'])/3*s
    bx0=lx+w*s+INL['G']*s; bx1=PW-lx; yb=top+cap   # the longest line ends as far in as the D starts (Rico 2026-11-06)
    assert yb-S > 5+5.2+2, 'bus clears the LED bores'
    lines={}
    for k,col in enumerate(BUS[order]):   # the bus: the letters' track width and gap, 45 deg ends
        y1=yb-k*(t+gp); y0=y1-t; e=bx1-(y1-(yb-S))
        lines[col]=f'M{bx0:.3f},{y0:.3f} L{e:.3f},{y0:.3f} L{e+t:.3f},{y1:.3f} L{bx0:.3f},{y1:.3f} Z'
    word_d=to_path(g,s,lx,top)
    groups=''
    for col,name in ((OR,'orange'),(GR,'grey'),(BK,'black')):
        d=lines[col]+(' '+word_d if col==OR else '')
        groups+=f'<g id="{name}_plus{HEIGHT[col]}mm"><path fill-rule="evenodd" fill="{col}" d="{d}"/></g>'
    leds=''.join(f'<circle cx="{bx1-2.6-k*10:.2f}" cy="7.6" r="2.6" fill="none" stroke="#777" stroke-width="0.3" stroke-dasharray="0.8 0.6"/>' for k in range(8))
    body=f'<g id="panel_0mm"><rect width="{PW}" height="{PH}" fill="{BE}"/></g>{groups}<g id="guide_OB_LEDs">{leds}</g>'
    open(f'out/dino_front_panel_{order}.svg','w').write(svg_doc(PW,PH,body))

inl,wi=word('DINO',**INL); sol,ws=word('DINO',**SOL)
wordmark('inline',inl,wi); wordmark('solid',sol,ws)
for o in BUS: panel(inl,wi,o)

# monogram: the 3-track D on a chamfered plate, 30 mm square
side=30.0; ch=5.0; s=0.2
pl=f'M{ch},0 L{side-ch},0 L{side},{ch} L{side},{side-ch} L{side-ch},{side} L{ch},{side} L0,{side-ch} L0,{ch} Z'
D=glyph_inline(centerlines(32,104,18,'diag')['D'][1],32,3,5)
ox=(side-104*s)/2; oy=(side-H*s)/2
open('out/dino_monogram.svg','w').write(svg_doc(side,side,f'<path fill="{GR}" d="{pl}"/>'+P(D,OR,s,ox,oy)))
open('out/dino_monogram_1c.svg','w').write(svg_doc(side,side,f'<path fill="#000" fill-rule="evenodd" d="{pl} '+to_path(D,s,ox,oy)+'"/>'))
print(sorted(os.listdir('out')))
