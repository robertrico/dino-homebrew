#!/usr/bin/env python3
"""Netlist simulation: the Rev 1.0 schematic as gate-level Verilog.

Reads the KiCad XML netlist of `dino_v0_0_2/dino_v0_0_2.kicad_sch` (the
same netlist the PCB is routed from, parity 0) and emits
`netsim/gen/dino_rev1.v`: one wire per net, one model instance per chip,
connected BY PIN NUMBER. A pin wrong in the drawing is wrong here too.
The models are in `netsim/ttl_models.v`, one module per part type, ports
`p1..pN`, typical datasheet delays. `netsim/tb_isa.v` seats the real ROM
images and reads OB.

Purpose: answer "does the drawing, as routed, run the programs the
breadboard runs". This is DINO's only twin (Rico, 2026-10-30; the FPGA
twin is deleted): no synthesis, no fabric, event-driven simulation in
Icarus only. It proves the drawing's logic, not its analog behaviour.

Board-level rules the generator applies, each a fact of the netlist:
  - `+5V` / `GND` are supply nets; +3.3V/+12V/-12V reach only J1-J9.
  - A resistor between `+5V` and a net is a pull-up (`pullup`).
  - A resistor between two signal nets is a series element (R2, R3,
    R29, R34): driven from the side that carries an output pin.
  - Capacitors, switches, test points, holes, the logo: no logic.
  - Jumpers JP3 and J14 are shunted by the testbench (`--shunt`).
  - A net with no driver at all is a floating TTL input: it gets a
    pull-up, and is LISTED in the report, because it is a design fact.

CLI:
    python3 docs/notes/netsim_gen.py [--xml NETLIST.xml]
        exports the netlist with kicad-cli when --xml is not given.

The simulation is the TTL exactly as drawn. It has no option to rewire a
pin, and test_netsim.py holds the generated Verilog pin-for-pin against
the netlist (Rico, 2026-10-30).
"""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCH = os.path.join(ROOT, 'dino_v0_0_2', 'dino_v0_0_2.kicad_sch')
OUT_DIR = os.path.join(ROOT, 'netsim', 'gen')
KICAD_CLI = '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'

# --- part types --------------------------------------------------------------
# Each model: pin -> (function, direction). direction is 'i', 'o', 'z'
# (tri-state output), 'b' (bidirectional), 'p' (power). Function names
# follow KiCad's pinfunction strings where the symbol gives one, so
# test_netsim.py can hold every table against the real netlist.

def _quad2(o_pins):
    """Quad 2-input gate, DIP-14. o_pins: {out: (in_a, in_b)}."""
    t = {7: ('GND', 'p'), 14: ('VCC', 'p')}
    for o, (a, b) in o_pins.items():
        t[a] = (f'I{a}', 'i')
        t[b] = (f'I{b}', 'i')
        t[o] = (f'O{o}', 'o')
    return t

QUAD_STD = {3: (1, 2), 6: (4, 5), 8: (9, 10), 11: (12, 13)}   # '00 '08 '32
QUAD_NOR = {1: (2, 3), 4: (5, 6), 10: (8, 9), 13: (11, 12)}   # '02
HEX_INV = {2: 1, 4: 3, 6: 5, 8: 9, 10: 11, 12: 13}            # '04 '14


def _hex_inv():
    t = {7: ('GND', 'p'), 14: ('VCC', 'p')}
    for o, i in HEX_INV.items():
        t[i] = (f'I{i}', 'i')
        t[o] = (f'O{o}', 'o')
    return t


def _named(spec):
    """'1:A0:i 2:A1:i ...' -> table."""
    t = {}
    for tok in spec.split():
        pin, fn, d = tok.rsplit(':', 2)
        t[int(pin)] = (fn, d)
    return t

PINS = {
    'ttl_00': _quad2(QUAD_STD),
    'ttl_02': _quad2(QUAD_NOR),
    'ttl_04': _hex_inv(),
    'ttl_08': _quad2(QUAD_STD),
    'ttl_32': _quad2(QUAD_STD),
    'ttl_74': _named('1:~{R}:i 2:D:i 3:C:i 4:~{S}:i 5:Q:o 6:~{Q}:o 7:GND:p '
                     '8:~{Q}:o 9:Q:o 10:~{S}:i 11:C:i 12:D:i 13:~{R}:i 14:VCC:p'),
    'ttl_138': _named('1:A0:i 2:A1:i 3:A2:i 4:E1:i 5:E2:i 6:E3:i 7:O7:o 8:GND:p '
                      '9:O6:o 10:O5:o 11:O4:o 12:O3:o 13:O2:o 14:O1:o 15:O0:o 16:VCC:p'),
    'ttl_157': _named('1:S:i 2:I0a:i 3:I1a:i 4:Za:o 5:I0b:i 6:I1b:i 7:Zb:o 8:GND:p '
                      '9:Zc:o 10:I1c:i 11:I0c:i 12:Zd:o 13:I1d:i 14:I0d:i 15:E:i 16:VCC:p'),
    'ttl_163': _named('1:~{MR}:i 2:CP:i 3:D0:i 4:D1:i 5:D2:i 6:D3:i 7:CEP:i 8:GND:p '
                      '9:~{PE}:i 10:CET:i 11:Q3:o 12:Q2:o 13:Q1:o 14:Q0:o 15:TC:o 16:VCC:p'),
    'ttl_169': _named('1:U/~{D}:i 2:CP:i 3:P0:i 4:P1:i 5:P2:i 6:P3:i 7:~{CEP}:i 8:GND:p '
                      '9:~{PE}:i 10:~{CET}:i 11:Q3:o 12:Q2:o 13:Q1:o 14:Q0:o 15:~{TC}:o 16:VCC:p'),
    'ttl_193': _named('1:B:i 2:QB:o 3:QA:o 4:DOWN:i 5:UP:i 6:QC:o 7:QD:o 8:GND:p '
                      '9:D:i 10:C:i 11:~{LOAD}:i 12:~{CO}:o 13:~{BO}:o 14:CLR:i 15:A:i 16:VCC:p'),
    'ttl_244': _named('1:1~{G}:i 2:1A1:i 3:2Y4:z 4:1A2:i 5:2Y3:z 6:1A3:i 7:2Y2:z 8:1A4:i '
                      '9:2Y1:z 10:GND:p 11:2A1:i 12:1Y4:z 13:2A2:i 14:1Y3:z 15:2A3:i '
                      '16:1Y2:z 17:2A4:i 18:1Y1:z 19:2~{G}:i 20:VCC:p'),
    'ttl_245': _named('1:DIR:i 2:A0:b 3:A1:b 4:A2:b 5:A3:b 6:A4:b 7:A5:b 8:A6:b 9:A7:b '
                      '10:GND:p 11:B7:b 12:B6:b 13:B5:b 14:B4:b 15:B3:b 16:B2:b 17:B1:b '
                      '18:B0:b 19:CE:i 20:VCC:p'),
    'ttl_273': _named('1:~{Mr}:i 2:Q0:o 3:D0:i 4:D1:i 5:Q1:o 6:Q2:o 7:D2:i 8:D3:i 9:Q3:o '
                      '10:GND:p 11:Cp:i 12:Q4:o 13:D4:i 14:D5:i 15:Q5:o 16:Q6:o 17:D6:i '
                      '18:D7:i 19:Q7:o 20:VCC:p'),
    'ttl_373': _named('1:OE:i 2:O0:z 3:D0:i 4:D1:i 5:O1:z 6:O2:z 7:D2:i 8:D3:i 9:O3:z '
                      '10:GND:p 11:LE:i 12:O4:z 13:D4:i 14:D5:i 15:O5:z 16:O6:z 17:D6:i '
                      '18:D7:i 19:O7:z 20:VCC:p'),
    'ttl_382': _named('1:A1:i 2:B1:i 3:A0:i 4:B0:i 5:S0:i 6:S1:i 7:S2:i 8:F0:o 9:F1:o '
                      '10:GND:p 11:F2:o 12:F3:o 13:OVR:o 14:CN+4:o 15:CN:i 16:B3:i 17:A3:i '
                      '18:B2:i 19:A2:i 20:VCC:p'),
    'eeprom_28': _named('1:A14:i 2:A12:i 3:A7:i 4:A6:i 5:A5:i 6:A4:i 7:A3:i 8:A2:i 9:A1:i '
                        '10:A0:i 11:I/O0:z 12:I/O1:z 13:I/O2:z 14:GND:p 15:I/O3:z 16:I/O4:z '
                        '17:I/O5:z 18:I/O6:z 19:I/O7:z 20:~{CE}:i 21:A10:i 22:~{OE}:i '
                        '23:A11:i 24:A9:i 25:A8:i 26:A13:i 27:~{WE}:i 28:VCC:p'),
    'sram_28': _named('1:A14:i 2:A12:i 3:A7:i 4:A6:i 5:A5:i 6:A4:i 7:A3:i 8:A2:i 9:A1:i '
                      '10:A0:i 11:DQ0:b 12:DQ1:b 13:DQ2:b 14:GND:p 15:DQ3:b 16:DQ4:b '
                      '17:DQ5:b 18:DQ6:b 19:DQ7:b 20:~{CE}:i 21:A10:i 22:~{OE}:i 23:A11:i '
                      '24:A9:i 25:A8:i 26:A13:i 27:~{WE}:i 28:VCC:p'),
    'osc_14': _named('1:EN:i 7:GND:p 8:OUT:o 14:Vcc:p'),
}

# On the AT28C64B, pin 1 is NC and pin 26 is NC; the 8K model ignores A13/A14.
NPINS = {k: max(v) for k, v in PINS.items()}

# value (as drawn) -> (model, Verilog parameters). Delays are typical
# datasheet figures in ns; `TPD` is input-to-output.
PARTS = {
    '74LS00':     ('ttl_00', {'TPD': 10}),
    '7400':       ('ttl_00', {'TPD': 11}),
    'DM7400N':    ('ttl_00', {'TPD': 11}),
    '74LS02':     ('ttl_02', {'TPD': 10}),
    '74LS04':     ('ttl_04', {'TPD': 10}),
    '74LS08':     ('ttl_08', {'TPD': 10}),
    '74LS32':     ('ttl_32', {'TPD': 14}),
    '74F32':      ('ttl_32', {'TPD': 4}),
    '74LS14':     ('ttl_04', {'TPD': 15}),
    'SN7414N':    ('ttl_04', {'TPD': 15}),
    '74LS74':     ('ttl_74', {'TPD': 20}),
    '74LS138':    ('ttl_138', {'TPD': 20}),
    '74LS157':    ('ttl_157', {'TPD': 12}),
    '74LS163':    ('ttl_163', {'TPD': 15}),
    '74LS169':    ('ttl_169', {'TPD': 15}),
    '74LS193':    ('ttl_193', {'TPD': 20}),
    '74LS244N':   ('ttl_244', {'TPD': 12}),
    '74LS245':    ('ttl_245', {'TPD': 10}),
    '74LS273':    ('ttl_273', {'TPD': 18}),
    '74LS373':    ('ttl_373', {'TPD': 18}),
    '74F382N':    ('ttl_382', {'TPD': 9}),
    'AT28C64B':   ('eeprom_28', {'TACC': 150, 'TOE': 70, 'ABITS': 13}),
    'AT28C256':   ('eeprom_28', {'TACC': 150, 'TOE': 70, 'ABITS': 15}),
    'MCM60256AP': ('sram_28', {'TAA': 100, 'TOE': 50, 'TWP': 70}),
    '4.096MHz':   ('osc_14', {'HALF': '122.0703125'}),
}

# Parts that hold state power up random from `SEED_BASE (per run); the
# memories also draw their per-bit access timing from it.
STATEFUL = {'ttl_74', 'ttl_163', 'ttl_169', 'ttl_193', 'ttl_273', 'ttl_373',
            'eeprom_28', 'sram_28'}

# ROM images seated in each socket (roms/README.md).
ROM_IMAGES = {'U9': 'roms/U9.bin', 'U15': 'roms/U15.bin', 'U23': 'roms/U23.bin'}

# Shunts the testbench fits: JP3 1-2 (oscillator), J14 1-2 (1.024 MHz tap).
DEFAULT_SHUNTS = [('JP3', '1', '2'), ('J14', '1', '2')]

SUPPLY = {'+5V': "1'b1", 'GND': "1'b0"}
OFFBOARD_RAILS = {'+3.3V', '+12V', '-12V'}


def export_netlist(path):
    subprocess.run([KICAD_CLI, 'sch', 'export', 'netlist', '--format',
                    'kicadxml', '-o', path, SCH], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load(xml_path):
    """-> comps {ref: value}, nets {name: [(ref, pin, pinfunction)]}."""
    r = ET.parse(xml_path).getroot()
    comps = {c.get('ref'): c.findtext('value') for c in r.find('components')}
    nets = {}
    for n in r.find('nets'):
        nets[n.get('name')] = [(nd.get('ref'), nd.get('pin'), nd.get('pinfunction'))
                               for nd in n.findall('node')]
    return comps, nets


def vname(net):
    s = re.sub(r'[^A-Za-z0-9_]', '_', net.replace('~{', 'n').replace('}', ''))
    return 'n_' + re.sub(r'_+', '_', s).strip('_')


def model_of(value):
    if value not in PARTS:
        raise KeyError(f'no model for part value {value!r}')
    return PARTS[value]


def build(comps, nets, shunts=DEFAULT_SHUNTS):
    """Return (verilog_text, report dict). The netlist exactly as drawn:
    there is no way to rewire a pin here (Rico, 2026-10-30)."""
    pin_net = {}
    for net, nodes in nets.items():
        for ref, pin, _ in nodes:
            pin_net[(ref, pin)] = net
    names = {}
    for net in nets:
        v = vname(net)
        while v in names.values():
            v += '_'
        names[net] = v

    chips = sorted((r for r in comps if r[0] in 'UY'),
                   key=lambda r: (r[0], int(re.sub(r'\D', '', r) or 0)))
    driven = set(SUPPLY)
    for ref in chips:
        model, _ = model_of(comps[ref])
        for pin, (_, d) in PINS[model].items():
            if d in 'ozb' and (ref, str(pin)) in pin_net:
                driven.add(pin_net[(ref, str(pin))])

    lines = ['// GENERATED by docs/notes/netsim_gen.py from the Rev 1.0 netlist.',
             '// Do not edit. One wire per net, chips connected by pin number.',
             '`timescale 1ns/10ps',
             '`ifndef SEED_BASE', '`define SEED_BASE 1', '`endif', 'module dino_rev1;']
    for net in sorted(nets):
        if net in SUPPLY or net in OFFBOARD_RAILS:
            continue
        lines.append(f'  wire {names[net]};  // {net}')
    lines.append('  supply1 n_VCC;  // +5V')
    lines.append('  supply0 n_GND;  // GND')
    lines.append('  wire n_NC_HI; pullup (n_NC_HI);  // open chip inputs')

    def ref_net(net):
        if net == '+5V':
            return 'n_VCC'
        if net == 'GND':
            return 'n_GND'
        return names[net]

    report = {'pullups': [], 'series': [], 'floating': [], 'shunts': [],
              'unmodelled': [], 'chips': len(chips)}

    # resistors
    for ref in sorted(r for r in comps if re.match(r'R\d', r)):
        a, b = pin_net.get((ref, '1')), pin_net.get((ref, '2'))
        if '+5V' in (a, b):
            sig = b if a == '+5V' else a
            lines.append(f'  pullup ({ref_net(sig)});  // {ref} {comps[ref]} to +5V')
            report['pullups'].append((ref, sig))
            driven.add(sig)
        else:
            src, dst = (a, b) if a in driven else (b, a)
            if src not in driven:
                raise ValueError(f'{ref}: neither side of a series resistor is driven')
            lines.append(f'  assign #1 {ref_net(dst)} = {ref_net(src)};  '
                         f'// {ref} {comps[ref]} series, {src} -> {dst}')
            report['series'].append((ref, src, dst))
            driven.add(dst)

    # shunts: the jumper's first pin drives the second side
    for ref, p1, p2 in shunts:
        a, b = pin_net[(ref, p1)], pin_net[(ref, p2)]
        src, dst = (a, b) if a in driven else (b, a)
        lines.append(f'  assign {ref_net(dst)} = {ref_net(src)};  '
                     f'// shunt {ref} {p1}-{p2}')
        report['shunts'].append((ref, p1, p2, src, dst))
        driven.add(dst)

    # chips
    for ref in chips:
        model, params = model_of(comps[ref])
        if model in STATEFUL:
            params = dict(params, SEED=f'`SEED_BASE + {len(lines)}')
        ps = ', '.join(f'.{k}({v})' for k, v in params.items())
        ports = []
        for pin in range(1, NPINS[model] + 1):
            if pin not in PINS[model]:
                continue
            net = pin_net.get((ref, str(pin)))
            if net is None or net.startswith('unconnected-'):
                # an open TTL input floats high; an open output is just open
                hi = PINS[model][pin][1] == 'i'
                ports.append(f'.p{pin}(n_NC_HI)' if hi else f'.p{pin}()')
            else:
                ports.append(f'.p{pin}({ref_net(net)})')
        hdr = f'  {model} #({ps}) {ref}' if ps else f'  {model} {ref}'
        lines.append(f'{hdr} (  // {comps[ref]}')
        lines.append('    ' + ', '.join(ports) + ');')

    # floating TTL inputs: float high, and say so
    for net, nodes in sorted(nets.items()):
        if net in driven or net in OFFBOARD_RAILS or net.startswith('unconnected-'):
            continue
        loads = [f'{r}.{p}' for r, p, _ in nodes if r[0] == 'U']
        if loads:
            lines.append(f'  pullup ({names[net]});  // FLOATING: {net} -> {" ".join(loads)}')
            report['floating'].append((net, loads))

    # NC chip inputs float high too (TTL); outputs left open are fine
    for ref in chips:
        model, _ = model_of(comps[ref])
        for pin, (fn, d) in PINS[model].items():
            net = pin_net.get((ref, str(pin)))
            if d == 'i' and (net is None or net.startswith('unconnected-')):
                report['unmodelled'].append(f'{ref}.{pin} {fn} NC input (floats high)')

    lines.append('endmodule')
    report['netmap'] = {net: ref_net(net) for net in nets
                        if net not in OFFBOARD_RAILS}
    return '\n'.join(lines) + '\n', report


def main(argv):
    xml = None
    if '--xml' in argv:
        xml = argv[argv.index('--xml') + 1]
    os.makedirs(OUT_DIR, exist_ok=True)
    if xml is None:
        xml = os.path.join(OUT_DIR, 'dino_rev1.xml')
        export_netlist(xml)
    comps, nets = load(xml)
    text, report = build(comps, nets)
    with open(os.path.join(OUT_DIR, 'dino_rev1.v'), 'w') as f:
        f.write(text)
    with open(os.path.join(OUT_DIR, 'netmap.json'), 'w') as f:
        json.dump(report['netmap'], f, indent=1, sort_keys=True)
    print(f"{report['chips']} chips, {len(report['pullups'])} pull-ups, "
          f"{len(report['series'])} series R, {len(report['shunts'])} shunts")
    for net, loads in report['floating']:
        print(f'FLOATING {net}: {" ".join(loads)}')
    for s in report['unmodelled']:
        print('NC', s)


if __name__ == '__main__':
    main(sys.argv[1:])
