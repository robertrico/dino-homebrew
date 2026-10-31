#!/usr/bin/env python3
"""The FPGA twin's mainboard: dino_v0_0_2 -> fpga/gen/dino_core.v.

    python3 docs/notes/fpga_core_gen.py [--seed N] [--half TICKS]

Reads the Rev 1.0 netlist (the one the PCB is routed from) and nothing
else: no card project is read here. The eight slot sockets J1-J8 become
eight copies of the card contract (fpga_twin_gen.py), prefixed `jK_`:

    jK_eP_S_xo/_xe   what the card in slot K drives on pin P (in)
    jK_eP_S_do/_de   everything else on that net, for the card (out)

so the backplane (fpga_slots_gen.py) wires a card to a slot port for port.
Each socket pin lands on the net the netlist puts it on; a pin the board
leaves unconnected (the spares) is a port with nothing behind it.

Also: the reset RC node (C1.1) as stimulus `x_rc_node`, OB0-7 and CW15
(HALT) as probes, the shunts fitted on the bench (JP3 1-2 oscillator,
J14 1-2 1.024 MHz) and the microcode images in U9/U15/U23 (written next
to the Verilog as U9.hex etc.; U24, the program ROM, takes `U24_HEX`).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fpga_twin_gen as g  # noqa: E402

NAME = 'dino_core'
SCH = 'dino_v0_0_2/dino_v0_0_2.kicad_sch'
SLOTS = [f'J{k}' for k in range(1, 9)]
SHUNTS = [('JP3', '1', '2'), ('J14', '1', '2')]
MICROCODE = {'U9': 'roms/U9.bin', 'U15': 'roms/U15.bin', 'U23': 'roms/U23.bin'}


def slot_port(slot, stem):
    return f'{slot.lower()}_{stem}'


def generate(seed=1, half=g.HALF, out_dir=g.OUT_DIR):
    """Write dino_core.v and the microcode hex files; -> info."""
    comps, nets = g.netlist(NAME, SCH, out_dir)
    pin_net = {(r, p): n for n, nodes in nets.items() for r, p, _ in nodes}
    edge = []
    for slot in SLOTS:
        assert comps[slot] == 'DINO_BUS_SOCKET', slot
        for pin, _name, stem in g.CONTRACT:
            n = pin_net.get((slot, str(pin)))
            edge.append((n if g.live_net(n) else None, slot_port(slot, stem)))
    ext = [(pin_net[('C1', '1')], 'x_rc_node')]
    probes = []
    for n in nets:
        if re.fullmatch(r'OB[0-7]', g.leaf(n)):
            probes.append((n, f'p_{g.leaf(n)}'))
        elif g.leaf(n) == 'CW15':
            probes.append((n, 'p_HALT'))
    params = {}
    for ref in comps:
        if g.is_chip(comps[ref]) and g.part(comps[ref])[0] == 'f_eeprom':
            params[ref] = {'FILE': f'"{ref}.hex"' if ref in MICROCODE else f'`{ref}_HEX',
                           'TAG': f'"{ref}"'}
        elif g.is_chip(comps[ref]) and g.part(comps[ref])[0] == 'f_sram':
            params[ref] = {'TAG': f'"{ref}"'}
    text, info = g.build(NAME, f'fpga_core_gen.py from {SCH}', comps, nets, edge=edge,
                         ext=ext, probes=probes, shunts=SHUNTS, params=params,
                         seed=seed, half=half)
    open(os.path.join(out_dir, f'{NAME}.v'), 'w').write(text)
    for ref, src in MICROCODE.items():
        g.bin2hex(src, os.path.join(out_dir, f'{ref}.hex'))
    return info


def main(argv):
    seed = int(argv[argv.index('--seed') + 1]) if '--seed' in argv else 1
    half = int(argv[argv.index('--half') + 1]) if '--half' in argv else g.HALF
    info = generate(seed, half)
    print(f'{NAME}: {len(info["chips"])} chips, {len(SLOTS)} slots')


if __name__ == '__main__':
    main(sys.argv[1:])
