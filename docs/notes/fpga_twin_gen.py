#!/usr/bin/env python3
"""The FPGA twin's engine: a KiCad netlist as synthesizable Verilog, and the
card API every board in the twin plugs through.

The FPGA twin is the third twin (Rico, 2026-10-30): breadboard, netsim/
(event-driven, Icarus) and this one, which runs in Verilator and on the
Versa. It proves the drawing's logic, not its timing. Its generators:

    fpga_core_gen.py    dino_v0_0_2 (the Rev 1.0 mainboard) -> dino_core,
                        with slots J1-J8 as eight card ports
    fpga_card_gen.py    one KiCad card project -> one card module
    fpga/cards/*.v      hand-written RTL cards, on the same API
    fpga_cards.py       the card registry: every card's source, its I/O
                        window and its oracle model
    fpga_slots_gen.py   the slot table -> dino_system (the backplane), and
                        `generate()`, which runs all of the above

This module holds what they share: the part models' pin tables, the
netlist-to-module builder and the card contract.

THE CARD CONTRACT (the API)
---------------------------
A card is a Verilog module with exactly these ports, nothing else:

    input  wire clk, live          the system clock and the power-up window
    output wire contention         two drivers enabled on one of its nets
    for each pin P of the 50-pin edge (bus_gen.BUS) that is not a rail,
    named after its signal S (`~{IO_SEL}` -> `nIO_SEL`, spare pins `spare`):
        input  wire eP_S_xo, eP_S_xe   what the rest of the machine drives
                                       on the pin, and whether anything does
        output wire eP_S_do, eP_S_de   what the card drives, and whether
    plus, for a card with off-edge I/O (switches, a serial line), ports
    named io_*.

37 pins x 4 = 148 edge ports, the same on every card, by pin number. Rails
(+5V, GND, +/-12V, +3.3V) are not ports. A pin the card does not take is
still a port: it drives `_de = 0` and ignores `_xo`. No inout anywhere:
every net is resolved explicitly on clk_sys, and the twin synthesizes.
`fpga/gen/dino_card_ports.vh` is this port list, generated; a hand-written
card includes it as its port list (fpga/cards/proto_card.v is the
template).

Bus semantics a card sees: an undriven pin reads 1 (TTL floats high, W has
its bus-park pull-ups), so a card reads `xe ? xo : 1`. The core is the hub:
each slot's `_xo/_xe` carries everything driving the pin except that slot's
own card, and two enabled drivers on any pin raise `contention`.

A slot is a position, not an address: J1-J8 carry identical nets. A card
picks its 2K window itself with its own '138 on M11-M13.

THE MODEL
---------
One instance per chip, connected BY PIN NUMBER from the netlist, so a pin
wrong in the drawing is wrong here too. Part models: fpga/ttl_fpga.v, with
the pin tables shared with the netlist simulation (netsim_gen.PINS, read
only). Every net is resolved explicitly: each pin that can drive it
contributes (value, enable); a net nothing drives reads 1. Series resistors
and fitted shunts pass their driven side to the other.

Clock: CLK_HZ = 48 MHz system clock (fpga/pll_48mhz.v); Y1 toggles every
HALF = 6 ticks, so CLK = CLK_HZ / (8 * HALF) = 1.0 MHz, the breadboard's
speed. A half CLK period is 24 ticks, far longer than the deepest chain of
registered memory reads settles. Change both with fpga/versa_top.v (MCLK),
fpga/versa.lpf and fpga/sim/twin_tb.cpp.
"""
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import netsim_gen as ng  # noqa: E402  (pin tables only; netsim is not changed)
import bus_gen  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
OUT_DIR = os.path.join(ROOT, 'fpga', 'gen')
KICAD_CLI = ng.KICAD_CLI

CLK_HZ = 48_000_000
HALF = 6

# netsim model -> FPGA model. Same pin tables.
MODEL = {
    'ttl_00': 'f_00', 'ttl_02': 'f_02', 'ttl_04': 'f_04', 'ttl_08': 'f_08',
    'ttl_32': 'f_32', 'ttl_74': 'f_74', 'ttl_138': 'f_138', 'ttl_157': 'f_157',
    'ttl_163': 'f_163', 'ttl_169': 'f_169', 'ttl_193': 'f_193', 'ttl_244': 'f_244',
    'ttl_245': 'f_245', 'ttl_273': 'f_273', 'ttl_373': 'f_373', 'ttl_382': 'f_382',
    'eeprom_28': 'f_eeprom', 'sram_28': 'f_sram', 'osc_14': 'f_osc14',
}

# Parts only the cards carry. Direction 'c' = open collector.
EXTRA_PINS = {
    'f_06': {7: ('GND', 'p'), 14: ('VCC', 'p'),
             **{i: (f'I{i}', 'i') for i in (1, 3, 5, 9, 11, 13)},
             **{o: (f'O{o}', 'c') for o in (2, 4, 6, 8, 10, 12)}},
    'f_osc8': ng._named('1:EN:i 4:GND:p 5:OUT:o 8:Vcc:p'),
    'f_16550': ng._named(
        '1:D0:b 2:D1:b 3:D2:b 4:D3:b 5:D4:b 6:D5:b 7:D6:b 8:D7:b 9:RCLK:i 10:SIN:i '
        '11:SOUT:o 12:CS0:i 13:CS1:i 14:~{CS2}:i 15:~{BAUDOUT}:o 16:XIN:i 17:XOUT:o '
        '18:~{WR}:i 19:WR:i 20:GND:p 21:~{RD}:i 22:RD:i 23:DDIS:o 24:~{TXRDY}:o '
        '25:~{ADS}:i 26:A2:i 27:A1:i 28:A0:i 29:~{RXRDY}:o 30:INTR:o 31:~{OUT2}:o '
        '32:~{RTS}:o 33:~{DTR}:o 34:~{OUT1}:o 35:MR:i 36:~{CTS}:i 37:~{DSR}:i '
        '38:~{DCD}:i 39:~{RI}:i 40:VCC:p'),
}
EXTRA_PARTS = {'7406N': ('f_06', {}), '16550': ('f_16550', {}),
               '3.6864MHz': ('f_osc8', {})}

CLOCKED = {'f_74', 'f_163', 'f_169', 'f_193', 'f_245', 'f_273', 'f_373',
           'f_eeprom', 'f_sram', 'f_osc14', 'f_osc8', 'f_16550'}
LIVE = CLOCKED - {'f_245', 'f_eeprom', 'f_sram'}
INIT_BITS = {'f_74': 2, 'f_163': 4, 'f_169': 4, 'f_193': 4, 'f_273': 8, 'f_373': 8}

SUPPLY = {'+5V': "1'b1", 'GND': "1'b0"}
ONE = "1'b1"
OFFBOARD = {'+3.3V', '+12V', '-12V'}


# --- the card contract ------------------------------------------------------------

def signal_name(bus_name):
    """A bus signal as a Verilog identifier: `~{IO_SEL}` -> `nIO_SEL`."""
    return re.sub(r'[^A-Za-z0-9]', '_', bus_name.replace('~{', 'n').replace('}', ''))


# (pin, bus name, port stem) for every edge pin that is not a rail
CONTRACT = [(pin, name, f'e{pin}_{signal_name(name)}')
            for pin, name, kind in bus_gen.BUS if kind != 'power']
assert len(CONTRACT) == 37


def contract_ports():
    """{port: direction} of the card contract, io_* excluded."""
    out = {'clk': 'input', 'live': 'input', 'contention': 'output'}
    for _pin, _name, stem in CONTRACT:
        out.update({f'{stem}_xo': 'input', f'{stem}_xe': 'input',
                    f'{stem}_do': 'output', f'{stem}_de': 'output'})
    return out


def card_ports_vh():
    """fpga/gen/dino_card_ports.vh: the contract as a Verilog port list."""
    lines = ['// GENERATED by docs/notes/fpga_twin_gen.py: the DINO card contract.',
             '// A card module\'s port list is exactly this (fpga_twin_gen.py docstring).',
             '  input  wire clk, live,',
             '  output wire contention,']
    for pin, name, stem in CONTRACT:
        lines.append(f'  input  wire {stem}_xo, {stem}_xe,   // pin {pin} {name}')
        lines.append(f'  output wire {stem}_do, {stem}_de,')
    lines[-1] = lines[-1].rstrip(',')
    return '\n'.join(lines) + '\n'


def card_in_vh():
    """fpga/gen/dino_card_in.vh: each edge pin as the card reads it, `in_S`.
    An undriven pin reads 1 (TTL floats high; W has its park pull-ups)."""
    lines = ['// GENERATED by docs/notes/fpga_twin_gen.py: the edge as a card reads it.',
             '// Include inside a card module, after its port list.']
    for pin, name, stem in CONTRACT:
        sig = signal_name(name) if name != 'spare' else f'spare{pin}'
        lines.append(f"  wire in_{sig} = {stem}_xe ? {stem}_xo : 1'b1;   // pin {pin}")
    return '\n'.join(lines) + '\n'


# --- netlists -----------------------------------------------------------------------

def part(value):
    if value in EXTRA_PARTS:
        model, params = EXTRA_PARTS[value]
        return model, dict(params), EXTRA_PINS[model]
    m, params = ng.model_of(value)
    model = MODEL[m]
    keep = {k: v for k, v in params.items() if k == 'ABITS'}
    return model, keep, ng.PINS[m]


def is_chip(value):
    return value in ng.PARTS or value in EXTRA_PARTS


def export(sch, out):
    subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format', 'kicadxml',
                    '-o', out, os.path.join(ROOT, sch)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load(xml_path):
    return ng.load(xml_path)


def netlist(name, sch, out_dir):
    """(comps, nets) of one KiCad project, exported fresh."""
    os.makedirs(out_dir, exist_ok=True)
    xml = os.path.join(out_dir, f'{name}.xml')
    export(sch, xml)
    return load(xml)


def leaf(net):
    return net.rsplit('/', 1)[-1]


def vname(net):
    return ng.vname(net)


def live_net(n):
    return n is not None and not n.startswith('unconnected-')


# --- the builder ----------------------------------------------------------------------

def build(name, src, comps, nets, edge=(), ext=(), probes=(), shunts=(),
          params=None, seed=1, half=HALF):
    """-> (verilog, info): module `name` from one netlist.

    edge:   [(net or None, port)] bidirectional ports, port_xo/_xe in and
            port_do/_de out. port_do/_de is everything on the net except
            the port's own _xo/_xe; None = a pin with nothing behind it.
    ext:    [(net, port)] input-only stimulus, port_xo/_xe.
    probes: [(net, port)] output wires carrying the resolved net.
    shunts: [(ref, pin, pin)] fitted jumpers, passed through like a series R.
    params: {ref: {param: value}} extra instance parameters (microcode files).
    """
    rnd = random.Random(f'{name}/{seed}')
    params = params or {}
    pin_net = {(r, p): n for n, nodes in nets.items() for r, p, _ in nodes}
    names, used = {}, set()
    for n in nets:
        v = vname(n)
        while v in used:
            v += '_'
        used.add(v)
        names[n] = v

    def ref_net(n):
        return SUPPLY.get(n, names.get(n))

    chips = sorted((r for r in comps if is_chip(comps[r])),
                   key=lambda r: (re.sub(r'\d', '', r), int(re.sub(r'\D', '', r) or 0)))
    terms = {n: [] for n in nets}            # net -> [(o, e or None)]
    inst = []
    for ref in chips:
        iref = re.sub(r'[^A-Za-z0-9_]', '_', ref)    # SWITCH-GATE1 on card zero
        model, ps, pins = part(comps[ref])
        if model in INIT_BITS:
            ps['INIT'] = f"{INIT_BITS[model]}'d{rnd.getrandbits(INIT_BITS[model])}"
        ps.update(params.get(ref, {}))
        if model == 'f_osc14':
            ps['HALF'] = str(half)
        if model == 'f_osc8':
            ps['CLK_HZ'] = str(CLK_HZ)
        conns = []
        if model in CLOCKED:
            conns.append('.clk(clk)')
        if model in LIVE:
            conns.append('.live(live)')
        for pin in sorted(pins):
            fn, d = pins[pin]
            if d == 'p':
                continue
            n = pin_net.get((ref, str(pin)))
            open_ = not live_net(n)
            if d in 'ib':
                conns.append(f'.i{pin}({ONE if open_ else ref_net(n)})')
            if d in 'ozbc':
                o = f'{iref}_o{pin}'
                conns.append(f'.o{pin}({o})')
                e = None
                if d in 'zbc':
                    e = f'{iref}_e{pin}'
                    conns.append(f'.e{pin}({e})')
                if not open_ and n not in SUPPLY:
                    terms[n].append((o, e))
                inst.append(('wire', o))
                if e:
                    inst.append(('wire', e))
        pstr = ', '.join(f'.{k}({v})' for k, v in ps.items())
        inst.append(('inst', f'  {model} {"#(" + pstr + ") " if pstr else ""}{iref} '
                             f'(  // {comps[ref]}\n    ' + ', '.join(conns) + ');'))

    # resistors: a pull-up is the default level; a series R passes its
    # driven side across. Shunts the same.
    alias = {}
    driven = {n for n, t in terms.items() if t}
    pairs = []
    for ref in sorted(r for r in comps if re.match(r'R\d', r)):
        a, b = pin_net.get((ref, '1')), pin_net.get((ref, '2'))
        if '+5V' in (a, b) or None in (a, b):
            continue
        pairs.append((ref, a, b))
    for ref, p1, p2 in shunts:
        pairs.append((ref, pin_net[(ref, p1)], pin_net[(ref, p2)]))
    for ref, a, b in pairs:
        src_, dst = (a, b) if a in driven or a in alias else (b, a)
        if dst in driven:
            raise ValueError(f'{name} {ref}: both sides of {a} / {b} are driven')
        alias[dst] = src_
        driven.add(dst)
    for dst, s in alias.items():
        terms[dst].append((ref_net(s), None))
    for n in alias:
        if len(terms[n]) > 1:
            raise ValueError(f'{name}: {n} is driven and also passed through')

    # off-board ports join the nets they sit on
    port_terms = {}                          # port -> (o, e) it adds to its net
    on_net = {}                              # net -> [port]
    for n, p in list(edge) + list(ext):
        if n is None:
            continue
        port_terms[p] = (f'{p}_xo', f'{p}_xe')
        on_net.setdefault(n, []).append(p)

    hdr = [f'// GENERATED by docs/notes/{src}.',
           '// Do not edit. One instance per chip, connected by pin number.',
           f'module {name} (input wire clk, live,']
    plines = []
    for n, p in sorted(edge, key=lambda t: t[1]):
        plines.append(f'  input wire {p}_xo, {p}_xe,')
        plines.append(f'  output wire {p}_do, {p}_de,')
    for n, p in sorted(ext, key=lambda t: t[1]):
        plines.append(f'  input wire {p}_xo, {p}_xe,')
    for n, p in sorted(probes, key=lambda t: t[1]):
        plines.append(f'  output wire {p},')
    plines.append('  output wire contention);')
    body = []
    for n in sorted(nets):
        if n in SUPPLY or n in OFFBOARD:
            continue
        body.append(f'  wire {names[n]};  // {n}')
    for kind, w in inst:
        if kind == 'wire':
            body.append(f'  wire {w};')
    for kind, t in inst:
        if kind == 'inst':
            body.append(t)

    def resolve(t):
        anyd = ' | '.join(e or "1'b1" for _, e in t)
        val = ' | '.join(f'({e} & {o})' if e else o for o, e in t)
        return anyd, val

    cont = []
    edge_ports = {p for _, p in edge}
    for n in sorted(nets):
        if n in SUPPLY or n in OFFBOARD:
            continue
        own = list(terms[n])
        t = own + [port_terms[p] for p in on_net.get(n, [])]
        v = names[n]
        for p in on_net.get(n, []):
            if p not in edge_ports:
                continue
            others = [x for x in t if x != port_terms[p]]
            if others:
                anyd, val = resolve(others)
                body.append(f'  assign {p}_de = {anyd};')
                body.append(f'  assign {p}_do = {val};')
            else:
                body.append(f"  assign {p}_de = 1'b0;  assign {p}_do = 1'b0;")
        if not t:
            body.append(f"  assign {v} = 1'b1;  // undriven: floats high")
        elif len(t) == 1 and t[0][1] is None:
            body.append(f'  assign {v} = {t[0][0]};')
        else:
            anyd, val = resolve(t)
            body.append(f"  assign {v} = ({anyd}) ? ({val}) : 1'b1;")
            if len(t) > 1:
                en = [e or "1'b1" for _, e in t]
                pairs_ = [f'({en[i]} & {en[j]})' for i in range(len(en))
                          for j in range(i + 1, len(en))]
                cont.append(f'  wire c_{v} = {" | ".join(pairs_)};')
                cont.append(v)
    for n, p in edge:
        if n is None:
            body.append(f"  assign {p}_de = 1'b0;  assign {p}_do = 1'b0;  // not taken")
    for n, p in probes:
        body.append(f'  assign {p} = {names[n]};')
    body += [c for c in cont if c.startswith('  wire')]
    cn = [f'c_{c}' for c in cont if not c.startswith('  wire')]
    body.append(f"  assign contention = {' | '.join(cn) if cn else chr(39).join(['1', 'b0'])};")
    body.append('endmodule')
    text = '\n'.join(hdr + plines + body) + '\n'
    info = {'chips': chips, 'edge': [p for _, p in edge], 'ext': [p for _, p in ext],
            'probes': [p for _, p in probes]}
    return text, info


def bin2hex(src, dst):
    data = open(os.path.join(ROOT, src), 'rb').read()
    with open(dst, 'w') as f:
        f.write('\n'.join(f'{b:02x}' for b in data) + '\n')
