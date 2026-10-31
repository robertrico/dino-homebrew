"""Parity tests for the FPGA twin (fpga_twin_gen.py, fpga/ttl_fpga.v).

The FPGA twin must be the drawing, pin for pin, in all three projects:

  - connectivity: every chip pin in each project's netlist is read from,
    or drives, exactly the net the netlist puts it on, and nothing else.
    Read back from the generated Verilog text, not from the generator's
    own tables;
  - the parts only the cards carry (7406N, 16550, the 3.6864 MHz can): their
    pin tables against the pin names in the netlist (the main board's are
    netsim's, held by test_netsim.py);
  - (the edge, slots and backplane: test_fpga_slots.py);
  - the models: each fpga/ttl_fpga.v part driven side by side with its
    netsim/ttl_models.v counterpart (whose datasheet tables test_netsim.py
    holds), on a random walk of one-pin changes, and every output compared.
"""
import os
import random
import re
import shutil
import subprocess
import tempfile

import pytest

import fpga_cards
import fpga_core_gen
import fpga_slots_gen
import fpga_twin_gen as g
import netsim_gen as ng

PROJECTS = {'dino_core': fpga_core_gen.SCH,
            **{n: c['sch'] for n, c in fpga_cards.CARDS.items() if c['kind'] == 'kicad'}}
SHUNTS = {'dino_core': fpga_core_gen.SHUNTS}
FPGA_MODELS = os.path.join(g.ROOT, 'fpga', 'ttl_fpga.v')
NETSIM_MODELS = os.path.join(g.ROOT, 'netsim', 'ttl_models.v')
IVERILOG = shutil.which('iverilog') or os.path.expanduser('~/oss-cad-suite/bin/iverilog')
VVP = shutil.which('vvp') or os.path.expanduser('~/oss-cad-suite/bin/vvp')
SUPPLY = {'+5V': "1'b1", 'GND': "1'b0"}


@pytest.fixture(scope='module')
def twin():
    """{project: (comps, nets, parsed verilog)}, freshly generated."""
    d = tempfile.mkdtemp()
    fpga_slots_gen.generate(seed=1, out_dir=d)
    out = {}
    for name in PROJECTS:
        comps, nets = g.load(os.path.join(d, f'{name}.xml'))
        out[name] = (comps, nets, parse(open(os.path.join(d, f'{name}.v')).read()))
    yield out
    shutil.rmtree(d)


def parse(text):
    wires = dict(re.findall(r'^  wire (n_\w+);  // (.+)$', text, re.M))
    insts = {}
    for model, params, ref, value, body in re.findall(
            r'^  (f_\w+) (?:#\((.*?)\) )?(\w+) \(  // (.+)\n    (.*)\);$', text, re.M):
        conns = dict(re.findall(r'\.(\w+)\(([^()]*)\)', body))
        insts[ref] = (model, value, conns)
    assigns = {}
    for lhs, rhs in re.findall(r'assign (\w+) = ([^;]+);', text):
        assigns[lhs] = rhs
    ports = set(re.findall(r'input wire (\w+)_xo', text))
    return {'wires': wires, 'insts': insts, 'assigns': assigns, 'ports': ports}


def iref(ref):
    return re.sub(r'[^A-Za-z0-9_]', '_', ref)


def chip_refs(comps):
    return {r for r, v in comps.items() if v in ng.PARTS or v in g.EXTRA_PARTS
            or (v.startswith('74') and r[0] not in 'RCJ')}


# --- connectivity, all three projects ---------------------------------------

@pytest.mark.parametrize('name, count', [('dino_core', 87), ('dino_io', 2),
                                         ('dino_serial', 5)])
def test_every_chip_is_instanced(twin, name, count):
    comps, _, v = twin[name]
    want = {iref(r) for r in chip_refs(comps)}
    assert set(v['insts']) == want
    assert len(want) == count
    for r in chip_refs(comps):
        model, value, _ = v['insts'][iref(r)]
        assert value == comps[r]
        assert model == g.part(comps[r])[0], r


@pytest.mark.parametrize('name', list(PROJECTS))
def test_every_input_pin_reads_its_net(twin, name):
    comps, nets, v = twin[name]
    net_of = {n: w for w, n in v['wires'].items()}
    pin_net = {(r, p): n for n, nodes in nets.items() for r, p, _ in nodes}
    checked = 0
    for r in chip_refs(comps):
        _, _, pins = g.part(comps[r])
        conns = v['insts'][iref(r)][2]
        for pin, (fn, d) in pins.items():
            if d not in 'ib':
                assert f'i{pin}' not in conns, (r, pin)
                continue
            n = pin_net.get((r, str(pin)))
            if n is None or n.startswith('unconnected-'):
                want = "1'b1"                  # an open TTL input floats high
            else:
                want = SUPPLY.get(n) or net_of[n]
            assert conns[f'i{pin}'] == want, f'{name} {r}.{pin} ({fn}): netlist {n}'
            checked += 1
    assert checked > {'dino_core': 900, 'dino_io': 9, 'dino_serial': 50}[name]


def drivers(v, w, ports):
    """Chip outputs in the resolution of wire w (and its edge ports' drive out)."""
    rhs = v['assigns'].get(w, '')
    for port in ports:
        rhs += ' ' + v['assigns'].get(f'{port}_do', '') + ' ' + v['assigns'].get(f'{port}_de', '')
    return set(re.findall(r'\b(U\w+?|SWITCH_GATE\d+|Y\d+)_[oe](\d+)\b', rhs))


@pytest.mark.parametrize('name', list(PROJECTS))
def test_every_output_pin_drives_its_net_and_only_it(twin, name):
    comps, nets, v = twin[name]
    chips = chip_refs(comps)
    port_of = {}
    for w, rhs in v['assigns'].items():
        if w.startswith('n_'):
            port_of[w] = re.findall(r'\b(\w+)_xo\b', rhs)
    seen = set()
    for w, n in v['wires'].items():
        want = set()
        for r, p, _ in ([] if n.startswith('unconnected-') else nets[n]):  # an open output drives nothing
            if r in chips and g.part(comps[r])[2].get(int(p), ('', 'p'))[1] in 'ozbc':
                want.add((iref(r), p))
        got = drivers(v, w, port_of.get(w, []))
        assert got == want, f'{name} {n}: generated {sorted(got)}, netlist {sorted(want)}'
        seen |= got
    # every output of every chip lands on exactly one wire
    outs = {(iref(r), str(p)) for r in chips
            for p, (_, d) in g.part(comps[r])[2].items() if d in 'ozbc'}
    assert seen <= outs


@pytest.mark.parametrize('name', list(PROJECTS))
def test_every_pass_through_is_a_series_part(twin, name):
    """A net that copies another is a series R or a fitted shunt in the netlist."""
    comps, nets, v = twin[name]
    pin_net = {(r, p): n for n, nodes in nets.items() for r, p, _ in nodes}
    series = set()
    for r in comps:
        shunt = [s for s in SHUNTS.get(name, []) if s[0] == r]
        if re.match(r'R\d', r) or shunt:
            p1, p2 = shunt[0][1:] if shunt else ('1', '2')
            a, b = pin_net.get((r, p1)), pin_net.get((r, p2))
            if a and b and '+5V' not in (a, b):
                series.add(frozenset((a, b)))
    got = set()
    for w, n in v['wires'].items():
        rhs = v['assigns'].get(w, '')
        for src in re.findall(r'\b(n_\w+)\b', rhs):
            pair = frozenset((n, v['wires'][src]))
            assert pair in series, f'{name}: {n} copies {v["wires"][src]}, no series part'
            got.add(pair)
    assert got == series
    assert len(got) == {'dino_core': 6, 'dino_io': 0, 'dino_serial': 0}[name]


@pytest.mark.parametrize('name', list(PROJECTS))
def test_undriven_nets_float_high_only_where_nothing_drives(twin, name):
    comps, nets, v = twin[name]
    for w, n in v['wires'].items():
        rhs = v['assigns'].get(w)
        assert rhs is not None, f'{name} {n} has no resolution'
        if rhs == "1'b1" and not n.startswith('unconnected-'):
            drv = [(r, p) for r, p, _ in nets[n] if r in chip_refs(comps)
                   and g.part(comps[r])[2].get(int(p), ('', 'p'))[1] in 'ozbc']
            assert not drv, (name, n, drv)


# --- pin tables of the card-only parts --------------------------------------

def test_card_part_pin_names_match_netlist(twin):
    checked = 0
    for name in ('dino_io', 'dino_serial'):
        comps, nets, _ = twin[name]
        for n, nodes in nets.items():
            for r, p, fn in nodes:
                if comps[r] not in g.EXTRA_PARTS or fn is None:
                    continue
                model = g.EXTRA_PARTS[comps[r]][0]
                got = g.EXTRA_PINS[model][int(p)][0]
                want = re.sub(r'_\d+$', '', fn)
                norm = lambda s: re.sub(r'[~{}]', '', s).upper()
                assert norm(got) == norm(want), f'{name} {r}.{p}: netlist {fn}, table {got}'
                checked += 1
    assert checked >= 40


# --- the models, side by side with netsim's ----------------------------------

PAIRS = ['ttl_00', 'ttl_02', 'ttl_04', 'ttl_08', 'ttl_32', 'ttl_74', 'ttl_138',
         'ttl_157', 'ttl_163', 'ttl_169', 'ttl_193', 'ttl_244', 'ttl_245',
         'ttl_273', 'ttl_373', 'ttl_382']


def fpga_ports(model):
    src = open(FPGA_MODELS).read()
    m = re.search(rf'^module {model}\b.*?\);', src, re.M | re.S)
    return set(re.findall(r'\b([ioe]\d+)\b', m.group(0)))


def side_by_side(nm, steps=2500, seed=1):
    """Random walk of one-pin changes into both models; -> list of mismatches."""
    fm = g.MODEL[nm]
    pins = ng.PINS[nm]
    fp = fpga_ports(fm)
    npins = max(pins)
    rnd = random.Random(f'{nm}/{seed}')
    ins = [p for p, (_, d) in pins.items() if d in 'ib']
    clocked = fm in g.CLOCKED
    lines = ['`timescale 1ns/10ps', 'module t;', '  reg clk = 0, live = 1;',
             '  always #5 clk = ~clk;']
    for p in range(1, npins + 1):
        d = pins.get(p, ('', 'p'))[1]
        lines.append(f'  reg r{p} = 1\'b{rnd.getrandbits(1)};')
        if d == 'p':
            lines.append(f'  wire p{p} = 1\'b{1 if pins[p][0] != "GND" else 0};')
        else:
            # the bench side drives weakly, so a part's own drive wins
            lines.append(f'  wire p{p}; assign (weak1, weak0) p{p} = r{p};')
    conns_n = ', '.join(f'.p{p}(p{p})' for p in range(1, npins + 1))
    lines.append(f'  {nm} n ({conns_n});')
    fc = []
    if clocked:
        fc.append('.clk(clk)')
    if fm in g.LIVE:
        fc.append('.live(live)')
    for p in range(1, npins + 1):
        if f'o{p}' in fp:
            lines.append(f'  wire fo{p}, fe{p};')
            fc.append(f'.o{p}(fo{p})')
            if f'e{p}' in fp:
                fc.append(f'.e{p}(fe{p})')
            else:
                lines.append(f"  assign fe{p} = 1'b1;")
        if f'i{p}' in fp:
            # what the pin resolves to on the FPGA side: own drive, else the bench
            src = f'(fe{p} ? fo{p} : r{p})' if f'o{p}' in fp else f'r{p}'
            fc.append(f'.i{p}({src})')
    lines.append(f'  {fm} f ({", ".join(fc)});')
    outs = [p for p in range(1, npins + 1) if f'o{p}' in fp]
    fmt = ' '.join('%b%b%b' for _ in outs)
    args = ', '.join(f'p{p}, fe{p}, fo{p}' for p in outs)
    rv = ', '.join(f'r{p}' for p in reversed(outs))
    lines.append('  integer k; initial begin')
    lines.append('    #200;')
    for k in range(steps):
        p = rnd.choice(ins)
        lines.append(f'    r{p} = ~r{p}; #100;')
        lines.append(f'    $display("S {k} {p} %b {fmt}", {{{rv}}}, {args});')
    lines.append('    $finish; end')
    lines.append('endmodule')
    with tempfile.TemporaryDirectory() as d:
        tb = os.path.join(d, 't.v')
        open(tb, 'w').write('\n'.join(lines))
        exe = os.path.join(d, 'a.out')
        r = subprocess.run([IVERILOG, '-g2012', '-o', exe, NETSIM_MODELS, FPGA_MODELS, tb],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]
        out = subprocess.run([VVP, '-n', exe], capture_output=True, text=True).stdout
    synced, bad, nsteps = False, [], 0
    for line in out.splitlines():
        if not line.startswith('S '):
            continue
        _, k, flipped, rbits, *vals = line.split()
        bench = {p: rbits[len(outs) - 1 - i] for i, p in enumerate(outs)}
        nsteps += 1
        diffs = []
        for p, val in zip(outs, vals):
            # both sides as the pin resolves: the part's drive, else the bench's
            ns, fe, fo = val
            if ns in 'xX':
                continue                      # netsim: undefined (power-up, '382 C4/OVR)
            fr = fo if fe == '1' else bench[p]
            if fr != ns:
                diffs.append((p, ns, fe + fo))
        # stateful parts power up in different states; compare from the
        # first step where every output agrees (a clear or load made them equal)
        if not synced:
            synced = not diffs
            sync_at = int(k)
            continue
        if diffs:
            bad.append((int(k), int(flipped), diffs))
    assert nsteps == steps
    assert synced and sync_at < steps // 4, f'{nm}: never agreed (power-up state never cleared)'
    return bad


@pytest.mark.parametrize('nm', PAIRS)
def test_fpga_model_matches_netsim_model(nm):
    bad = side_by_side(nm)
    assert not bad, f'{nm} vs {g.MODEL[nm]}: {len(bad)} steps differ, first {bad[:3]}'
