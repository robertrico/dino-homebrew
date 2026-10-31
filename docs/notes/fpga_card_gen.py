#!/usr/bin/env python3
"""One KiCad card project -> one card module on the card contract.

    python3 docs/notes/fpga_card_gen.py <card> [--seed N]

<card> is a 'kicad' entry of fpga_cards.CARDS (dino_io, dino_serial).
Reads that project's netlist and nothing else, and writes
fpga/gen/<card>.v: the card's chips, one instance each by pin number, and
the 37 contract pins of the edge (fpga_twin_gen.py docstring).

Where the edge comes from:
  - the card's DINO_BUS_EDGE symbol, pin by pin (card zero's J1, the
    serial card's J2, drawn 2026-10-30);
  - for a card drawn without one, its labels: a label named after a bus
    signal IS that signal's pin, on its bus_gen.BUS pin, as a drawn edge
    would put it. test_fpga_slots.py holds the two rules to the same
    pinout.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fpga_cards  # noqa: E402
import fpga_twin_gen as g  # noqa: E402

EDGE_SYMBOL = 'DINO_BUS_EDGE'


def edge_nets(comps, nets):
    """{pin: net} of the card's edge, and how it was found."""
    pin_net = {(r, p): n for n, nodes in nets.items() for r, p, _ in nodes}
    edges = [r for r, v in comps.items() if v == EDGE_SYMBOL]
    if len(edges) > 1:
        raise ValueError(f'card has {len(edges)} edge connectors: {edges}')
    if edges:
        return {pin: pin_net.get((edges[0], str(pin))) for pin, _, _ in g.CONTRACT}, edges[0]
    by_label = {}
    for n in nets:
        by_label.setdefault(g.leaf(n), []).append(n)
    out = {}
    for pin, name, _stem in g.CONTRACT:
        hits = by_label.get(name, [])
        if len(hits) > 1:
            raise ValueError(f'label {name} names {len(hits)} nets')
        out[pin] = hits[0] if hits else None
    return out, 'labels'


def generate(name, seed=1, half=g.HALF, out_dir=g.OUT_DIR):
    card = fpga_cards.CARDS[name]
    assert card['kind'] == 'kicad', name
    comps, nets = g.netlist(name, card['sch'], out_dir)
    pin_net = {(r, p): n for n, nodes in nets.items() for r, p, _ in nodes}
    by_pin, how = edge_nets(comps, nets)
    edge = [(by_pin[pin] if g.live_net(by_pin[pin]) else None, stem)
            for pin, _name, stem in g.CONTRACT]
    ext = [(pin_net[(r, p)], port) for r, p, port in card['io_in']]
    probes = [(pin_net[(r, p)], port) for r, p, port in card['io_out']]
    text, info = g.build(name, f'fpga_card_gen.py from {card["sch"]} (edge: {how})',
                         comps, nets, edge=edge, ext=ext, probes=probes,
                         seed=seed, half=half)
    open(os.path.join(out_dir, f'{name}.v'), 'w').write(text)
    info['edge_from'] = how
    return info


def main(argv):
    seed = int(argv[argv.index('--seed') + 1]) if '--seed' in argv else 1
    for name in [a for a in argv if not a.startswith('--') and not a.isdigit()]:
        info = generate(name, seed)
        print(f'{name}: {len(info["chips"])} chips, edge from {info["edge_from"]}')


if __name__ == '__main__':
    main(sys.argv[1:])
