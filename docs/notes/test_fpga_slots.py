"""The FPGA twin's slot area and its one card API.

  T1 the contract: 37 non-rail pins of bus_gen.BUS, four ports each; every
     card, generated or hand-written, has exactly that port list (plus io_*),
     no inout, every output driven, synthesizes on its own
  T2 the core: J1-J8 are eight contract-shaped slot ports, each pin on the
     net the netlist puts that socket pin on
  T3 the card generators: each card's edge from its DINO_BUS_EDGE (card
     zero's J1, the serial card's J2), the label rule for a card drawn
     without one giving the same pinout; the core generator reads no card
  T4 the backplane: one slot table makes dino_system; a seated card meets
     its slot port for port; an empty slot drives nothing; a slot is a
     position, not an address; two cards on one window are refused, and a
     card that fights the bus raises contention
  T5 the prototype card never drives W outside its window or on a write,
     and never drives any other pin
  T6 the DEADBEEF card: its four cells, 0xFF elsewhere, quiet outside
  T7 the oracle sees the slot table; with none it is unchanged
  T8 asm/deadbeef.asm: pass code with the card, a failure code naming the
     read without it, the same pass from any slot
  T10 adding a card is: a card file, a registry entry, a slot line
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

import asm
import bus_gen
import fpga_card_gen
import fpga_cards
import fpga_core_gen
import fpga_slots_gen
import fpga_twin_gen as g
import fpga_twin_suite as suite
import progrom_gen as pg

ROOT = g.ROOT
FPGA = os.path.join(ROOT, 'fpga')
TOOLS = os.path.expanduser('~/oss-cad-suite/bin')
YOSYS = os.path.join(TOOLS, 'yosys')
IVERILOG = shutil.which('iverilog') or os.path.join(TOOLS, 'iverilog')
VVP = shutil.which('vvp') or os.path.join(TOOLS, 'vvp')
RTL_CARDS = [n for n, c in fpga_cards.CARDS.items() if c['kind'] == 'rtl']
KICAD_CARDS = [n for n, c in fpga_cards.CARDS.items() if c['kind'] == 'kicad']


@pytest.fixture(scope='module')
def gen():
    d = tempfile.mkdtemp()
    fpga_slots_gen.generate(seed=1, out_dir=d)
    for name in KICAD_CARDS:            # every KiCad card, seated or not
        fpga_card_gen.generate(name, seed=1, out_dir=d)
    yield d
    shutil.rmtree(d)


def read(d, f):
    return open(os.path.join(d, f)).read()


def wires(text):
    return dict(re.findall(r'^  wire (n_\w+);  // (.+)$', text, re.M))


def assigns(text):
    return dict(re.findall(r'assign (\w+) = ([^;]+);', text))


# --- T1 the contract ---------------------------------------------------------------

def test_contract_is_the_edge_minus_its_rails():
    pins = [p for p, _, _ in g.CONTRACT]
    assert pins == [p for p, n, k in bus_gen.BUS if k != 'power']
    assert len(pins) == 37 and len(set(s for _, _, s in g.CONTRACT)) == 37
    for p, n, s in g.CONTRACT:
        assert s == f'e{p}_{g.signal_name(n)}'
    ports = g.contract_ports()
    assert len(ports) == 37 * 4 + 3
    assert not any(n in ('+5V', 'GND') for _, n, _ in g.CONTRACT)


def test_ports_include_is_the_contract(gen):
    vh = read(gen, 'dino_card_ports.vh')
    got = {}
    for d, names in re.findall(r'^\s*(input|output)\s+wire\s+([^/\n]+)', vh, re.M):
        for n in re.findall(r'\w+', names):
            if n != 'wire':
                got[n] = d
    assert got == g.contract_ports()


def yosys_ports(top, files, gen_dir, params=None):
    """{port: direction} of a module after yosys elaboration; also runs
    `check -assert` (undriven outputs, multiple drivers) and a synth."""
    js = os.path.join(gen_dir, f'{top}.json')
    chp = ''.join(f' -set {k} {v}' for k, v in (params or {}).items())
    script = (f'read_verilog -I{gen_dir} {" ".join(files)}; '
              f'chparam{chp} {top}; ' if params else
              f'read_verilog -I{gen_dir} {" ".join(files)}; ')
    script += f'hierarchy -check -top {top}; proc; check -assert; synth -top {top}; ' \
              f'write_json {js}'
    r = subprocess.run([YOSYS, '-q', '-p', script], cwd=gen_dir, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    mod = json.load(open(js))['modules'][top]
    return {p: v['direction'] for p, v in mod['ports'].items()}


@pytest.mark.parametrize('name', RTL_CARDS)
def test_rtl_card_has_exactly_the_contract_and_synthesizes(gen, name):
    c = fpga_cards.CARDS[name]
    files = [os.path.join(FPGA, 'ttl_fpga.v'), os.path.join(ROOT, c['src'])] + \
            [os.path.join(ROOT, s) for s in fpga_slots_gen.CARD_LIBRARY]
    ports = yosys_ports(name, files, gen)
    assert ports == g.contract_ports()


@pytest.mark.parametrize('name', KICAD_CARDS)
def test_kicad_card_has_exactly_the_contract_and_synthesizes(gen, name):
    files = [os.path.join(FPGA, 'ttl_fpga.v'), os.path.join(gen, f'{name}.v')]
    ports = yosys_ports(name, files, gen)
    io = {p: d for p, d in ports.items() if p.startswith('io_')}
    assert {p: d for p, d in ports.items() if not p.startswith('io_')} == g.contract_ports()
    c = fpga_cards.CARDS[name]
    want = {f'{p}_{s}': 'input' for _, _, p in c['io_in'] for s in ('xo', 'xe')}
    want.update({p: 'output' for _, _, p in c['io_out']})
    assert io == want


def test_no_inout_anywhere(gen):
    files = [os.path.join(FPGA, 'ttl_fpga.v')] + \
            [os.path.join(ROOT, c['src']) for c in fpga_cards.CARDS.values() if c['kind'] == 'rtl'] + \
            [os.path.join(gen, f) for f in os.listdir(gen) if f.endswith(('.v', '.vh'))]
    for f in files:
        assert not re.search(r'\binout\b', re.sub(r'//.*', '', open(f).read())), f


# --- T2 the core's slots ----------------------------------------------------------------

def socket_nets():
    comps, nets = g.load(os.path.join(TMP_XML, 'dino_core.xml'))
    return comps, nets


TMP_XML = tempfile.mkdtemp()


@pytest.fixture(scope='module')
def core_netlist():
    return g.netlist('dino_core', fpga_core_gen.SCH, TMP_XML)


def test_core_has_eight_contract_slots(gen):
    text = read(gen, 'dino_core.v')
    for slot in fpga_core_gen.SLOTS:
        for _, _, stem in g.CONTRACT:
            p = fpga_core_gen.slot_port(slot, stem)
            assert re.search(rf'input wire {p}_xo, {p}_xe,', text), p
            assert re.search(rf'output wire {p}_do, {p}_de,', text), p
    assert len(re.findall(r'input wire j\d_e\d+_\w+_xo', text)) == 8 * 37


def test_every_socket_pin_is_on_its_netlist_net(gen, core_netlist):
    comps, nets = core_netlist
    text = read(gen, 'dino_core.v')
    w, a = wires(text), assigns(text)
    wire_of = {n: v for v, n in w.items()}
    pin_net = {(r, p): n for n, nodes in nets.items() for r, p, _ in nodes}
    taken = 0
    for slot in fpga_core_gen.SLOTS:
        assert comps[slot] == 'DINO_BUS_SOCKET'
        for pin, name, stem in g.CONTRACT:
            p = fpga_core_gen.slot_port(slot, stem)
            n = pin_net.get((slot, str(pin)))
            if not g.live_net(n):
                assert a[f'{p}_de'] == "1'b0", p
                assert not any(f'{p}_xo' in rhs for rhs in a.values()), p
                continue
            # the slot's drive is in that net's resolution and no other
            homes = [lhs for lhs, rhs in a.items()
                     if re.search(rf'\b{p}_xo\b', rhs) and lhs.startswith('n_')]
            assert homes == [wire_of[n]], (p, n, homes)
            taken += 1
    # every slot takes the same pins, and on each pin all eight share one net
    assert taken == 8 * (taken // 8)
    for pin, name, stem in g.CONTRACT:
        on = {pin_net.get((s, str(pin))) for s in fpga_core_gen.SLOTS}
        assert len(on) == 1 or all(not g.live_net(n) for n in on), (pin, on)


def test_slot_hears_everything_but_itself(gen):
    a = assigns(read(gen, 'dino_core.v'))
    # W0 is driven on the core (U25, U44's side) and by every slot
    for k in range(1, 9):
        p = f'j{k}_e8_W0'
        others = set(re.findall(r'\b(j\d)_e8_W0_xo\b', a[f'{p}_do']))
        assert others == {f'j{i}' for i in range(1, 9)} - {f'j{k}'}, (p, others)
        assert re.search(r'\bU25_o', a[f'{p}_do']), p


# --- T3 the card generators ------------------------------------------------------------

def card_edge(gen, name):
    """{pin: wire it resolves into, or None} from a generated card."""
    text = read(gen, f'{name}.v')
    a = assigns(text)
    out = {}
    for pin, _, stem in g.CONTRACT:
        homes = [lhs for lhs, rhs in a.items()
                 if lhs.startswith('n_') and re.search(rf'\b{stem}_xo\b', rhs)]
        assert len(homes) <= 1, (name, stem, homes)
        if homes:
            out[pin] = wires(text)[homes[0]]
        else:
            assert a[f'{stem}_de'] == "1'b0", (name, stem)
            out[pin] = None
    return out


def test_card_zero_edge_is_its_j1(gen):
    comps, nets = g.netlist('dino_io', fpga_cards.CARDS['dino_io']['sch'], TMP_XML)
    assert comps['J1'] == 'DINO_BUS_EDGE'
    pin_net = {p: n for n, nodes in nets.items() for r, p, _ in nodes if r == 'J1'}
    got = card_edge(gen, 'dino_io')
    for pin, name, _ in g.CONTRACT:
        n = pin_net.get(str(pin))
        assert got[pin] == (n if g.live_net(n) else None), (pin, name)
    taken = {name for pin, name, _ in g.CONTRACT if got[pin]}
    assert taken == bus_gen.CARD_ZERO_TAKES - {'+5V', 'GND'}
    assert 'from dino_io/dino_io.kicad_sch (edge: J1)' in read(gen, 'dino_io.v')


SERIAL_TAKES = {'~{IO_SEL}', '~{IO_RD_Q}', '~{IO_WR}', 'RESET_B', '~{IRQ}',
                'M0', 'M1', 'M2', 'M11', 'M12', 'M13'} | {f'W{i}' for i in range(8)}


def test_serial_card_edge_is_its_j2(gen):
    comps, nets = g.netlist('dino_serial', fpga_cards.CARDS['dino_serial']['sch'], TMP_XML)
    got = card_edge(gen, 'dino_serial')
    by_name = {g.leaf(n): n for n in nets}
    assert comps['J2'] == 'DINO_BUS_EDGE'
    j2 = {p: n for n, nodes in nets.items() for r, p, _ in nodes if r == 'J2'}
    for pin, name, _ in g.CONTRACT:
        assert got[pin] == (by_name.get(name) if name in SERIAL_TAKES else None), (pin, name)
        n = j2.get(str(pin))
        assert got[pin] == (n if g.live_net(n) else None), (pin, name)
    # netlist-extracted: the bus names among the sheet's labels
    bus = {n for _, n, k in bus_gen.BUS if k in ('signal', 'reserved')}
    assert set(by_name) & bus == SERIAL_TAKES
    assert 'CLK_B' not in SERIAL_TAKES
    # drawn 2026-10-30: J2, DINO_BUS_EDGE; the generator reads the edge from it
    assert 'from dino_serial/dino_serial.kicad_sch (edge: J2)' in read(gen, 'dino_serial.v')


def test_a_drawn_edge_and_labels_give_the_same_pinout():
    # one card drawn both ways: labels alone, then a DINO_BUS_EDGE on them
    nets = {'/M0': [('U1', '1', None)], '/W3': [('U1', '2', None)],
            '/~{IO_SEL}': [('U1', '3', None)], '/LOCAL': [('U1', '4', None)]}
    by_label, how = fpga_card_gen.edge_nets({'U1': '74LS00'}, nets)
    assert how == 'labels'
    pins = {28: '/M0', 11: '/W3', 3: '/~{IO_SEL}'}
    drawn = {n: nodes + [('J9', str(p), None)] for p, n in pins.items() for nodes in [nets[n]]}
    drawn['/LOCAL'] = nets['/LOCAL']
    by_pin, how = fpga_card_gen.edge_nets({'U1': '74LS00', 'J9': 'DINO_BUS_EDGE'}, drawn)
    assert how == 'J9'
    assert by_pin == by_label
    assert {p for p, n in by_pin.items() if n} == set(pins)


def test_core_generator_reads_only_the_mainboard(monkeypatch):
    seen = []
    real = g.netlist
    monkeypatch.setattr(g, 'netlist', lambda name, sch, d: seen.append(sch) or real(name, sch, d))
    d = tempfile.mkdtemp()
    fpga_core_gen.generate(seed=1, out_dir=d)
    assert seen == ['dino_v0_0_2/dino_v0_0_2.kicad_sch']
    src = open(fpga_core_gen.__file__).read()
    assert 'fpga_cards' not in src and 'fpga_card_gen' not in src
    shutil.rmtree(d)


def test_a_card_module_does_not_depend_on_the_slot_table(gen):
    d = tempfile.mkdtemp()
    fpga_slots_gen.generate(seed=1, slots={'J7': 'dino_io'}, out_dir=d)
    assert read(d, 'dino_io.v') == read(gen, 'dino_io.v')
    shutil.rmtree(d)


# --- T4 the backplane -----------------------------------------------------------------------

def test_system_seats_each_card_on_its_slot_by_pin(gen):
    text = read(gen, 'dino_system.v')
    insts = dict((tag, body) for _m, tag, body in
                 re.findall(r'^  (\w+) (?:#\(\.\w+\(\d+\)\) )?(\w+) \((.*)\);$', text, re.M))
    core = dict(re.findall(r'\.(\w+)\(([^()]*)\)', insts['core']))
    for slot in fpga_core_gen.SLOTS:
        k = slot.lower()
        name = fpga_slots_gen.SLOTS.get(slot)
        for _, _, stem in g.CONTRACT:
            sp = fpga_core_gen.slot_port(slot, stem)
            if name is None:
                assert core[f'{sp}_xe'] == "1'b0" and core[f'{sp}_xo'] == "1'b0", sp
                continue
            card = dict(re.findall(r'\.(\w+)\(([^()]*)\)', insts[k]))
            assert card[f'{stem}_xo'] == core[f'{sp}_do'] and card[f'{stem}_xe'] == core[f'{sp}_de']
            assert core[f'{sp}_xo'] == card[f'{stem}_do'] and core[f'{sp}_xe'] == card[f'{stem}_de']
    assert re.search(r'^  deadbeef_card #\(\.WINDOW\(2\)\) j3 \(', text, re.M)


def test_two_cards_on_one_window_are_refused():
    with pytest.raises(ValueError, match='window 2'):
        fpga_slots_gen.system({'J3': 'deadbeef_card', 'J5': 'deadbeef_card'})
    with pytest.raises(ValueError, match='window'):
        fpga_cards.oracle_cards({'J3': 'deadbeef_card', 'J5': 'deadbeef_card'})


def test_the_slot_table_is_cards_zero_one_two():
    assert fpga_slots_gen.SLOTS == {'J1': 'dino_io', 'J2': 'dino_serial',
                                    'J3': 'deadbeef_card'}
    assert [fpga_cards.CARDS[n]['window'] for n in fpga_slots_gen.SLOTS.values()] == [0, 1, 2]


# --- T5/T6 the RTL cards, alone on a test bench -------------------------------------------------

def card_bench(name, window, cycles):
    """cycles: [(addr 16-bit, nio_sel, nio_rd_q, nio_wr)] -> [(w_de, w_do, other_de)]"""
    stems = {n: s for _, n, s in g.CONTRACT}
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'dino_card_ports.vh'), 'w').write(g.card_ports_vh())
    open(os.path.join(d, 'dino_card_in.vh'), 'w').write(g.card_in_vh())
    lines = ['module t;', '  reg clk = 0, live = 1;', '  reg [15:0] m; reg sel, rd, wr;']
    conns = ['.clk(clk)', '.live(live)', '.contention()']
    for _, n, s in g.CONTRACT:
        if n.startswith('M'):
            xo, xe = f'm[{n[1:]}]', "1'b1"
        elif n in ('~{IO_SEL}', '~{IO_RD_Q}', '~{IO_WR}'):
            xo, xe = {'~{IO_SEL}': 'sel', '~{IO_RD_Q}': 'rd', '~{IO_WR}': 'wr'}[n], "1'b1"
        else:
            xo, xe = "1'b0", "1'b0"
        lines.append(f'  wire {s}_do, {s}_de;')
        conns += [f'.{s}_xo({xo})', f'.{s}_xe({xe})', f'.{s}_do({s}_do)', f'.{s}_de({s}_de)']
    lines.append(f'  {name} #(.WINDOW({window})) dut ({", ".join(conns)});')
    w = [stems[f'W{i}'] for i in range(7, -1, -1)]
    other = [s for _, n, s in g.CONTRACT if not n.startswith('W')]
    lines.append('  wire [7:0] wde = {' + ', '.join(f'{s}_de' for s in w) + '};')
    lines.append('  wire [7:0] wdo = {' + ', '.join(f'{s}_do' for s in w) + '};')
    lines.append('  wire ode = ' + ' | '.join(f'{s}_de' for s in other) + ';')
    lines.append('  initial begin')
    for addr, s_, r_, w_ in cycles:
        lines.append(f"    m = 16'h{addr:04X}; sel = {s_}; rd = {r_}; wr = {w_}; #1;")
        lines.append('    $display("C %b %h %b", wde, wdo, ode);')
    lines.append('    $finish; end')
    lines.append('endmodule')
    tb = os.path.join(d, 't.v')
    open(tb, 'w').write('\n'.join(lines))
    exe = os.path.join(d, 'a.out')
    src = os.path.join(ROOT, fpga_cards.CARDS[name]['src'])
    lib = [os.path.join(ROOT, s) for s in fpga_slots_gen.CARD_LIBRARY]
    r = subprocess.run([IVERILOG, '-g2012', '-I', d, '-o', exe,
                        os.path.join(FPGA, 'ttl_fpga.v'), *lib, src, tb],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([VVP, '-n', exe], capture_output=True, text=True).stdout
    shutil.rmtree(d)
    res = []
    for line in out.splitlines():
        if line.startswith('C '):
            _, de, do, ode = line.split()
            res.append((int(de, 2), int(do, 16), int(ode)))
    assert len(res) == len(cycles)
    return res


def strobe_cycles(rnd_offsets):
    """Every window x strobe combination, at several low addresses."""
    out = []
    for win in range(8):
        for off in rnd_offsets:
            for s_ in (0, 1):
                for r_ in (0, 1):
                    for w_ in (0, 1):
                        out.append((0x4000 + win * 0x800 + off, s_, r_, w_))
    return out


@pytest.mark.parametrize('window', range(8))
def test_proto_card_drives_w_only_inside_its_window_on_a_read(window):
    import random
    rnd = random.Random(window)
    cyc = strobe_cycles([0x000, 0x7FF] + [rnd.randrange(0x800) for _ in range(4)])
    for (addr, s_, r_, w_), (wde, wdo, ode) in zip(cyc, card_bench('proto_card', window, cyc)):
        mine = ((addr - 0x4000) >> 11) == window
        reading = mine and s_ == 0 and r_ == 0
        assert wde == (0xFF if reading else 0), (hex(addr), s_, r_, w_)
        assert ode == 0, hex(addr)
        if reading:
            assert wdo == 0xFF


def test_deadbeef_cells_and_the_rest_of_its_window():
    cells = fpga_cards.DEADBEEF
    assert set(cells) == {0x000, 0x555, 0x2AA, 0x7FF}
    for bit in range(11):                    # every one of M0-M10 toggles
        assert len({(o >> bit) & 1 for o in cells}) == 2, bit
    cyc = [(0x5000 + off, 0, 0, 1) for off in range(0x800)]
    res = card_bench('deadbeef_card', 2, cyc)
    for (addr, *_), (wde, wdo, ode) in zip(cyc, res):
        assert wde == 0xFF and ode == 0
        assert wdo == cells.get(addr - 0x5000, 0xFF), hex(addr)


def test_deadbeef_is_quiet_outside_its_window_and_on_writes():
    cyc = strobe_cycles([0x000, 0x555, 0x2AA, 0x7FF])
    for (addr, s_, r_, w_), (wde, wdo, ode) in zip(cyc, card_bench('deadbeef_card', 2, cyc)):
        reading = 0x5000 <= addr < 0x5800 and s_ == 0 and r_ == 0
        assert wde == (0xFF if reading else 0), (hex(addr), s_, r_, w_)
        assert ode == 0


# --- T7 the oracle --------------------------------------------------------------------------

def test_io_read_with_cards():
    cards = fpga_cards.oracle_cards(fpga_slots_gen.SLOTS, {'switches': 0x1E})
    assert sorted(cards) == [0, 2]                     # the serial card is not oracled
    assert pg.io_read(0x4000, 0xFF, cards=cards) == 0x1E
    assert [pg.io_read(a, 0xFF, cards=cards) for a in (0x5000, 0x5555, 0x52AA, 0x57FF)] == \
        [0xDE, 0xAD, 0xBE, 0xEF]
    assert pg.io_read(0x5001, 0xFF, cards=cards) == 0xFF
    assert pg.io_read(0x6000, 0xFF, cards=cards) == pg.IO_PARK
    assert pg.io_read(0x5555, 0xFF) == pg.IO_PARK      # no table: as before


def test_oracle_is_unchanged_for_every_existing_image():
    cards = fpga_cards.oracle_cards(fpga_slots_gen.SLOTS, {'switches': 0xFF})
    for stem, want, _ in suite.oracle_images({}):
        if stem == 'PROG_deadbeef':
            continue
        img = open(os.path.join(ROOT, 'roms', stem + '.bin'), 'rb').read()
        r = pg.simulate(None, image=img, switches=0xFF, serial=False, max_steps=5000000,
                        cards=cards)
        assert r['out'] == want, stem


# --- T8 the image ----------------------------------------------------------------------------

def deadbeef_out(slots):
    img = open(os.path.join(ROOT, 'roms', 'PROG_deadbeef.bin'), 'rb').read()
    r = pg.simulate(None, image=img, switches=0xFF, serial=False, max_steps=100000,
                    cards=fpga_cards.oracle_cards(slots, {'switches': 0xFF}))
    assert r['halted']
    return r['out']


def test_deadbeef_image_is_its_source():
    r = asm.assemble_text(open(os.path.join(ROOT, 'asm', 'deadbeef.asm')).read())
    burned = open(os.path.join(ROOT, 'roms', 'PROG_deadbeef.bin'), 'rb').read()
    assert burned[r.origin:r.origin + len(r.code)] == bytes(r.code)


def test_deadbeef_passes_with_the_card_from_any_slot():
    assert deadbeef_out(fpga_slots_gen.SLOTS) == 0x5A
    assert deadbeef_out({'J8': 'deadbeef_card'}) == 0x5A


def test_deadbeef_names_the_first_failing_read():
    assert deadbeef_out({}) == 0xE1                    # no card: 0x5000 reads 0xFF
    assert deadbeef_out({'J1': 'dino_io'}) == 0xE1


def test_twin_suite_seats_the_slot_table_and_runs_deadbeef():
    imgs = {s: w for s, w, _ in suite.oracle_images(fpga_slots_gen.SLOTS)}
    assert imgs['PROG_deadbeef'] == 0x5A
    assert imgs['PROG_dip'] == 0x2E


# --- T4/T10 on the twin, built (Verilator) ------------------------------------------------------

TEST_CARD = '''// a test card: 0x42 at every address of its window
module t_card #(parameter integer WINDOW = 5) (
`include "dino_card_ports.vh"
);
`include "dino_card_in.vh"
  wire win_sel, win_rd, win_wr;
  card_window #(.WINDOW(WINDOW)) window (
    .m11(in_M11), .m12(in_M12), .m13(in_M13),
    .nio_sel(in_nIO_SEL), .nio_rd_q(in_nIO_RD_Q), .nio_wr(in_nIO_WR),
    .sel(win_sel), .rd(win_rd), .wr(win_wr));
  wire [7:0] rdata = 8'h42;
'''


def build_and_run(slots, program, extra_cards=None, out_dir=None):
    """Generate the twin for `slots`, build it, run an asm program -> (OB, contention)."""
    d = out_dir or tempfile.mkdtemp()
    twin = suite.build(1, slots=slots, out_dir=d)
    r = asm.assemble_text(program)
    img = bytearray([0xFF] * 0x4000)
    img[r.origin:r.origin + len(r.code)] = bytes(r.code)
    hexf = os.path.join(d, 'PROG_t.hex')
    open(hexf, 'w').write(''.join(f'{b:02x}\n' for b in img))
    res = suite.run(twin, None, hexf=hexf, cwd=d, max_ticks=20_000_000)
    return res


def test_a_slot_is_a_position_not_an_address():
    prog = 'LDA 0x5555\nOUT\nHALT\n'
    for slots in ({'J3': 'deadbeef_card'}, {'J8': 'deadbeef_card'}):
        r = build_and_run(slots, prog)
        assert (r['end'], r['OB'], r['contention']) == ('HALT', 'ad', 0), slots


def test_a_card_that_fights_the_bus_raises_contention(monkeypatch, tmp_path):
    # a rogue card drives W on every cycle: the core's own drivers collide
    src = open(os.path.join(FPGA, 'cards', 'proto_card.v')).read()
    src = src.replace('module proto_card', 'module rogue_card')
    src = src.replace('= {8{win_rd}};', "= 8'hFF;")
    f = tmp_path / 'rogue_card.v'
    f.write_text(src)
    monkeypatch.setitem(fpga_cards.CARDS, 'rogue_card', dict(
        fpga_cards.CARDS['proto_card'], src=str(f), window=6))
    r = build_and_run({'J4': 'rogue_card'}, 'LDAI 0x12\nOUT\nHALT\n', out_dir=str(tmp_path))
    assert r['contention'] > 0


def test_adding_a_card_is_a_file_an_entry_and_a_slot_line(monkeypatch, tmp_path):
    proto = open(os.path.join(FPGA, 'cards', 'proto_card.v')).read()
    tail = proto[proto.index('  // ---- the edge:'):]
    f = tmp_path / 't_card.v'
    f.write_text(TEST_CARD + tail)
    monkeypatch.setitem(fpga_cards.CARDS, 't_card', {
        'kind': 'rtl', 'src': str(f), 'window': 5, 'io_in': [], 'io_out': [],
        'bind': {}, 'outputs': {}, 'oracle': lambda off, ctx: 0x42})
    slots = dict(fpga_slots_gen.SLOTS, J6='t_card')
    prog = 'LDA 0x6ABC\nOUT\nHALT\n'
    r = asm.assemble_text(prog)
    o = pg.simulate(None, image=bytes(r.code), switches=0xFF, serial=False,
                    cards=fpga_cards.oracle_cards(slots))
    assert o['out'] == 0x42
    res = build_and_run(slots, prog, out_dir=str(tmp_path))
    assert (res['end'], res['OB'], res['contention']) == ('HALT', '42', 0)
