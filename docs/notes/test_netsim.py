"""Tests for netsim_gen.py and netsim/ttl_models.v.

Two kinds:
  - the pin tables against the real netlist (rule 4: netlist-verify);
  - each model against its datasheet function table, driven through
    Icarus. A model bug would look exactly like a wiring bug in the
    machine simulation, so every model is pinned here first.
"""
import os
import re
import shutil
import subprocess
import tempfile

import pytest

import netsim_gen as ng

ROOT = ng.ROOT
MODELS = os.path.join(ROOT, 'netsim', 'ttl_models.v')
IVERILOG = shutil.which('iverilog') or os.path.expanduser('~/oss-cad-suite/bin/iverilog')
VVP = shutil.which('vvp') or os.path.expanduser('~/oss-cad-suite/bin/vvp')


@pytest.fixture(scope='module')
def netlist():
    xml = os.path.join(ng.OUT_DIR, 'dino_rev1.xml')
    if not os.path.exists(xml):
        os.makedirs(ng.OUT_DIR, exist_ok=True)
        ng.export_netlist(xml)
    return ng.load(xml)


# --- the tables against the netlist -----------------------------------------

def test_every_chip_has_a_model(netlist):
    comps, _ = netlist
    for ref, val in comps.items():
        if ref[0] in 'UY':
            ng.model_of(val)


# AT28C64B: the 28-pin table carries A13/A14 at pins 26/1, which the 8K part
# leaves NC. The model ignores them (ABITS=13).
PIN_EXCEPTIONS = {('AT28C64B', 1): 'NC', ('AT28C64B', 26): 'NC'}


def test_pin_functions_match_netlist(netlist):
    comps, nets = netlist
    checked = 0
    for net, nodes in nets.items():
        for ref, pin, fn in nodes:
            if ref[0] not in 'UY' or fn is None:
                continue
            model, _ = ng.model_of(comps[ref])
            want = PIN_EXCEPTIONS.get((comps[ref], int(pin)))
            name = re.sub(r'_\d+$', '', fn)
            if want:
                assert name == want, (ref, pin, fn)
                continue
            got = ng.PINS[model][int(pin)][0]
            assert got == name, f'{ref}.{pin}: netlist says {fn}, model table says {got}'
            checked += 1
    assert checked > 600


def test_power_pins_on_rails(netlist):
    comps, nets = netlist
    pin_net = {(r, p): n for n, nodes in nets.items() for r, p, _ in nodes}
    for ref, val in comps.items():
        if ref[0] not in 'UY':
            continue
        model, _ = ng.model_of(val)
        for pin, (fn, d) in ng.PINS[model].items():
            if d == 'p':
                want = 'GND' if fn == 'GND' else '+5V'
                assert pin_net[(ref, str(pin))] == want, (ref, pin)


def test_generated_netlist_has_every_chip(netlist):
    comps, nets = netlist
    text, report = ng.build(comps, nets)
    for ref in comps:
        if ref[0] in 'UY':
            assert re.search(rf'\) {ref} \(|  \w+ {ref} \(', text), ref
    assert report['chips'] == 87          # 86 ICs + Y1
    assert {s[0] for s in report['series']} == {'R2', 'R3', 'R29', 'R34'}


# --- models against datasheets ----------------------------------------------

def sim(module, npins, params, steps, inouts=(), defines=()):
    """Drive a model through `steps` and return what each step read.

    steps: list of (drive, delay_ns, read_pins). drive maps pin -> '0'/'1'/'z'.
    Pins in `inouts` are driven through a reg that may be 'z'. Returns a
    list of dicts pin -> '0'/'1'/'x'/'z'.
    """
    ps = ', '.join(f'.{k}({v})' for k, v in params.items())
    inst = f'{module} #({ps}) dut' if ps else f'{module} dut'
    body = ['`timescale 1ns/10ps', 'module t;']
    for p in range(1, npins + 1):
        body.append(f'  reg r{p} = 1\'bz; wire p{p}; assign p{p} = r{p};')
    body.append(f'  {inst} (' + ', '.join(f'.p{p}(p{p})' for p in range(1, npins + 1)) + ');')
    body.append('  initial begin')
    for i, (drive, delay, read) in enumerate(steps):
        for p, v in drive.items():
            body.append(f"    r{p} = 1'b{v};")
        body.append(f'    #{delay};')
        fmt = ' '.join(f'{p}=%b' for p in read)
        args = ', '.join(f'p{p}' for p in read)
        body.append(f'    $display("S{i} {fmt}"{", " if read else ""}{args});')
    body.append('    $finish; end')
    body.append('endmodule')
    with tempfile.TemporaryDirectory() as d:
        tb = os.path.join(d, 't.v')
        open(tb, 'w').write('\n'.join(body))
        exe = os.path.join(d, 'a.out')
        subprocess.run([IVERILOG, '-g2012'] + [f'-D{d}' for d in defines] +
                       ['-o', exe, MODELS, tb], check=True,
                       capture_output=True)
        out = subprocess.run([VVP, '-n', exe], check=True, capture_output=True,
                             text=True).stdout
    res = []
    for line in out.splitlines():
        if not line.startswith('S'):
            continue
        d = {}
        for tok in line.split()[1:]:
            p, v = tok.split('=')
            d[int(p)] = v
        res.append(d)
    return res


def bits(v, n):
    return {i: str((v >> i) & 1) for i in range(n)}


def test_gates_truth_tables():
    for model, fn in (('ttl_00', lambda a, b: 1 - (a & b)),
                      ('ttl_08', lambda a, b: a & b),
                      ('ttl_32', lambda a, b: a | b),
                      ('ttl_02', lambda a, b: 1 - (a | b))):
        gates = ng.QUAD_NOR if model == 'ttl_02' else ng.QUAD_STD
        steps = []
        for a in (0, 1):
            for b in (0, 1):
                drive = {}
                for o, (ia, ib) in gates.items():
                    drive[ia] = str(a)
                    drive[ib] = str(b)
                steps.append((drive, 50, list(gates)))
        res = sim(model, 14, {'TPD': 10}, steps)
        i = 0
        for a in (0, 1):
            for b in (0, 1):
                for o in gates:
                    assert res[i][o] == str(fn(a, b)), (model, a, b, o)
                i += 1


def test_inverter():
    steps = [({i: v for i in ng.HEX_INV.values()}, 50, list(ng.HEX_INV)) for v in '01']
    res = sim('ttl_04', 14, {'TPD': 10}, steps)
    assert all(res[0][o] == '1' for o in ng.HEX_INV)
    assert all(res[1][o] == '0' for o in ng.HEX_INV)


def test_gate_delay():
    res = sim('ttl_00', 14, {'TPD': 10}, [({1: '0', 2: '0'}, 50, [3]),
                                          ({1: '1', 2: '1'}, 5, [3]),
                                          ({}, 10, [3])])
    assert [r[3] for r in res] == ['1', '1', '0']


def test_74_dff():
    # FF1: 1 ~R, 2 D, 3 C, 4 ~S, 5 Q, 6 ~Q
    s = [({1: '0', 4: '1', 2: '1', 3: '0'}, 50, [5, 6]),     # clear
         ({1: '1'}, 50, [5, 6]),                             # hold
         ({3: '1'}, 50, [5, 6]),                             # rising edge, D=1
         ({2: '0', 3: '0'}, 50, [5, 6]),                     # falling: hold
         ({3: '1'}, 50, [5, 6]),                             # rising, D=0
         ({4: '0'}, 50, [5, 6]),                             # preset
         ({1: '0'}, 50, [5, 6])]                             # both low: Q=~Q=1
    r = sim('ttl_74', 14, {'TPD': 20}, s)
    assert [(x[5], x[6]) for x in r] == [('0', '1'), ('0', '1'), ('1', '0'), ('1', '0'),
                                         ('0', '1'), ('1', '0'), ('1', '1')]


def test_138():
    outs = {0: 15, 1: 14, 2: 13, 3: 12, 4: 11, 5: 10, 6: 9, 7: 7}
    steps = []
    for a in range(8):
        steps.append(({1: str(a & 1), 2: str(a >> 1 & 1), 3: str(a >> 2 & 1),
                       4: '0', 5: '0', 6: '1'}, 50, list(outs.values())))
    steps.append(({4: '1'}, 50, list(outs.values())))      # E1 high: all high
    steps.append(({4: '0', 6: '0'}, 50, list(outs.values())))  # E3 low: all high
    r = sim('ttl_138', 16, {'TPD': 20}, steps)
    for a in range(8):
        for k, p in outs.items():
            assert r[a][p] == ('0' if k == a else '1'), (a, k)
    assert all(v == '1' for v in r[8].values())
    assert all(v == '1' for v in r[9].values())


def test_157():
    Z = [4, 7, 9, 12]
    I0 = {2: '0', 5: '1', 11: '0', 14: '1'}
    I1 = {3: '1', 6: '0', 10: '1', 13: '0'}
    r = sim('ttl_157', 16, {'TPD': 12},
            [({**I0, **I1, 1: '0', 15: '0'}, 50, Z),
             ({1: '1'}, 50, Z),
             ({15: '1'}, 50, Z)])
    assert [r[0][z] for z in Z] == ['0', '1', '0', '1']
    assert [r[1][z] for z in Z] == ['1', '0', '1', '0']
    assert [r[2][z] for z in Z] == ['0', '0', '0', '0']


def _clock(cp, n=1):
    """n rising edges on pin cp."""
    out = []
    for _ in range(n):
        out.append(({cp: '0'}, 100, []))
        out.append(({cp: '1'}, 100, []))
    return out


Q163 = [14, 13, 12, 11]


def _val(r, pins):
    return sum(int(r[p]) << i for i, p in enumerate(pins)) if all(r[p] in '01' for p in pins) else None


def test_163():
    base = {1: '0', 2: '0', 3: '1', 4: '0', 5: '1', 6: '0', 7: '1', 9: '1', 10: '1'}
    s = [(base, 100, Q163)]
    s += _clock(2)                                    # sync clear
    s.append(({1: '1'}, 100, Q163 + [15]))
    s += _clock(2, 3)                                 # count 3
    s.append(({}, 10, Q163))
    s.append(({9: '0'}, 0, []))
    s += _clock(2)                                    # load 0b0101
    s.append(({9: '1'}, 100, Q163))
    s += _clock(2, 10)                                # 5+10 = 15
    s.append(({}, 10, Q163 + [15]))
    s.append(({10: '0'}, 50, [15]))                   # TC gated by CET
    s += _clock(2)                                    # CET low: hold
    s.append(({}, 10, Q163))
    r = [x for x in sim('ttl_163', 16, {'TPD': 15}, s) if x]
    assert _val(r[1], Q163) == 0 and r[1][15] == '0'
    assert _val(r[2], Q163) == 3
    assert _val(r[3], Q163) == 5
    assert _val(r[4], Q163) == 15 and r[4][15] == '1'
    assert r[5][15] == '0'
    assert _val(r[6], Q163) == 15


def test_163_async_clear_is_not():
    # ~MR is synchronous on the '163: no clock, no clear.
    s = [({1: '1', 2: '0', 3: '1', 4: '1', 5: '1', 6: '1', 7: '1', 9: '0', 10: '1'}, 100, [])]
    s += _clock(2)
    s.append(({9: '1', 1: '0'}, 100, Q163))
    r = [x for x in sim('ttl_163', 16, {'TPD': 15}, s) if x]
    assert _val(r[0], Q163) == 15


def test_169():
    Q = [14, 13, 12, 11]
    base = {1: '1', 2: '0', 3: '0', 4: '1', 5: '1', 6: '1', 7: '0', 9: '0', 10: '0'}
    s = [(base, 100, [])]
    s += _clock(2)                                    # load 14
    s.append(({9: '1'}, 100, Q + [15]))
    s += _clock(2)                                    # up: 15
    s.append(({}, 10, Q + [15]))
    s += _clock(2)                                    # wraps to 0
    s.append(({1: '0'}, 100, Q + [15]))               # down at 0: ~TC low
    s += _clock(2, 2)                                 # 0 -> 15 -> 14
    s.append(({}, 10, Q))
    s.append(({7: '1'}, 0, []))
    s += _clock(2)                                    # ~CEP high: hold
    s.append(({}, 10, Q))
    r = [x for x in sim('ttl_169', 16, {'TPD': 15}, s) if x]
    assert _val(r[0], Q) == 14 and r[0][15] == '1'
    assert _val(r[1], Q) == 15 and r[1][15] == '0'
    assert _val(r[2], Q) == 0 and r[2][15] == '0'
    assert _val(r[3], Q) == 14
    assert _val(r[4], Q) == 14


def test_193():
    Q = [3, 2, 6, 7]                                  # QA QB QC QD
    D = {15: '1', 1: '0', 10: '1', 9: '0'}            # A..D = 5
    s = [({**D, 14: '1', 11: '1', 5: '1', 4: '1'}, 100, Q)]      # CLR high: 0
    s.append(({14: '0', 11: '0'}, 100, Q))            # async load 5
    s.append(({11: '1'}, 100, []))
    for _ in range(3):                                # up x3 on UP rising
        s.append(({5: '0'}, 100, []))
        s.append(({5: '1'}, 100, []))
    s.append(({}, 10, Q))
    for _ in range(9):                                # down x9: 8 -> 15
        s.append(({4: '0'}, 100, []))
        s.append(({4: '1'}, 100, []))
    s.append(({}, 10, Q))
    s.append(({5: '0'}, 50, [12]))                    # 15 with UP low: ~CO low
    r = [x for x in sim('ttl_193', 16, {'TPD': 20}, s) if x]
    assert _val(r[0], Q) == 0
    assert _val(r[1], Q) == 5
    assert _val(r[2], Q) == 8
    assert _val(r[3], Q) == 15
    assert r[4][12] == '0'


def test_244():
    r = sim('ttl_244', 20, {'TPD': 12},
            [({1: '0', 2: '1', 4: '0', 6: '1', 8: '0', 19: '1', 11: '1'}, 50, [18, 16, 14, 12, 9]),
             ({1: '1'}, 50, [18])])
    assert [r[0][p] for p in (18, 16, 14, 12)] == ['1', '0', '1', '0']
    assert r[0][9] == 'z'
    assert r[1][18] == 'z'


def test_245():
    A = list(range(2, 10))
    B = list(range(18, 10, -1))
    a_drive = {p: str(i & 1) for i, p in enumerate(A)}
    r = sim('ttl_245', 20, {'TPD': 10},
            [({**a_drive, 1: '1', 19: '0'}, 50, B),                      # A -> B
             ({**{p: 'z' for p in A}, 1: '0', 19: '0', **{p: str(1 - (i & 1)) for i, p in enumerate(B)}}, 50, A),  # B -> A
             ({**{p: 'z' for p in B}, 19: '1'}, 50, A + B)])              # off
    assert [r[0][p] for p in B] == [str(i & 1) for i in range(8)]
    assert [r[1][p] for p in A] == [str(1 - (i & 1)) for i in range(8)]
    assert all(v == 'z' for v in r[2].values())


def test_273():
    Dp = [3, 4, 7, 8, 13, 14, 17, 18]
    Qp = [2, 5, 6, 9, 12, 15, 16, 19]
    s = [({**{p: str(i & 1) for i, p in enumerate(Dp)}, 1: '0', 11: '0'}, 100, Qp),
         ({1: '1'}, 50, [])]
    s += _clock(11)
    s.append(({**{p: '0' for p in Dp}}, 50, Qp))
    r = [x for x in sim('ttl_273', 20, {'TPD': 18}, s) if x]
    assert _val(r[0], Qp) == 0
    assert _val(r[1], Qp) == 0b10101010


def test_373():
    Dp = [3, 4, 7, 8, 13, 14, 17, 18]
    Op = [2, 5, 6, 9, 12, 15, 16, 19]
    s = [({**{p: '1' for p in Dp}, 1: '0', 11: '1'}, 50, Op),     # transparent
         ({11: '0'}, 50, []),                                       # latch
         ({**{p: '0' for p in Dp}}, 50, Op),                        # held
         ({11: '1'}, 50, Op),                                       # follows
         ({1: '1'}, 50, Op)]                                        # OE high: z
    r = [x for x in sim('ttl_373', 20, {'TPD': 18}, s) if x]
    assert _val(r[0], Op) == 0xFF
    assert _val(r[1], Op) == 0xFF
    assert _val(r[2], Op) == 0
    assert all(r[3][p] == 'z' for p in Op)


A382 = [3, 1, 19, 17]
B382 = [4, 2, 18, 16]
F382 = [8, 9, 11, 12]


def _alu(s, a, b, cn):
    d = {5: str(s & 1), 6: str(s >> 1 & 1), 7: str(s >> 2 & 1), 15: str(cn)}
    d.update({p: str(a >> i & 1) for i, p in enumerate(A382)})
    d.update({p: str(b >> i & 1) for i, p in enumerate(B382)})
    return d


def test_382_arithmetic_exhaustive():
    steps = []
    cases = []
    for s in (1, 2, 3):
        for a in range(16):
            for b in range(16):
                for cn in (0, 1):
                    steps.append((_alu(s, a, b, cn), 30, F382 + [14, 13]))
                    cases.append((s, a, b, cn))
    r = sim('ttl_382', 20, {'TPD': 9}, steps)
    for (s, a, b, cn), got in zip(cases, r):
        x, y = {1: (b, (~a) & 15), 2: (a, (~b) & 15), 3: (a, b)}[s]
        tot = x + y + cn
        lo3 = (x & 7) + (y & 7) + cn
        c3, c4 = lo3 >> 3, tot >> 4
        assert _val(got, F382) == tot & 15, (s, a, b, cn)
        assert got[14] == str(c4), ('cn+4', s, a, b, cn)
        assert got[13] == str(c3 ^ c4), ('ovr', s, a, b, cn)


def test_382_logic_and_fixed():
    steps, want = [], []
    for s, fn in ((0, lambda a, b: 0), (4, lambda a, b: a ^ b), (5, lambda a, b: a | b),
                  (6, lambda a, b: a & b), (7, lambda a, b: 15)):
        for a, b in ((0, 0), (5, 3), (15, 15), (9, 6)):
            steps.append((_alu(s, a, b, 0), 30, F382 + [14]))
            want.append((s, fn(a, b)))
    r = sim('ttl_382', 20, {'TPD': 9}, steps)
    for (s, f), got in zip(want, r):
        assert _val(got, F382) == f, s
        if s == 0:
            assert got[14] == '1'       # CLEAR: Cn+4 H (datasheet table)
        else:
            assert got[14] == 'x'       # data-dependent, never measured: refuse


def mem_sim(module, params, image, steps):
    d = tempfile.mkdtemp()
    hexf = os.path.join(d, 'img.hex')
    with open(hexf, 'w') as f:
        f.write('\n'.join(f'{b:02x}' for b in image))
    params = dict(params, FILE=f'"{hexf}"')
    try:
        return sim(module, 28, params, steps)
    finally:
        shutil.rmtree(d)


ADDR = {0: 10, 1: 9, 2: 8, 3: 7, 4: 6, 5: 5, 6: 4, 7: 3, 8: 25, 9: 24, 10: 21,
        11: 23, 12: 2, 13: 26, 14: 1}
DQ = [11, 12, 13, 15, 16, 17, 18, 19]


def _addr(a, nbits):
    return {ADDR[i]: str(a >> i & 1) for i in range(nbits)}


def test_eeprom_read_and_access_time():
    # After an address change each differing bit flips ONCE, at a seeded
    # random moment between TACC/3 and TACC: before TACC/3 it is old data,
    # after TACC new data, between them each bit is old or new, never x.
    img = bytes((i * 7 + 3) & 0xFF for i in range(8192))
    p = {'TACC': 150, 'TOE': 70, 'ABITS': 13}
    s = [({**_addr(0x123, 13), 20: '0', 22: '0', 27: '1', 1: '0', 26: '0'}, 200, DQ),
         ({**_addr(0x124, 13)}, 40, DQ),           # before TACC/3: old
         ({}, 60, DQ),                             # 100 ns: old or new per bit
         ({}, 100, DQ),                            # settled
         ({22: '1'}, 100, DQ)]                     # OE high: z
    r = mem_sim('eeprom_28', p, img, s)
    old, new = img[0x123], img[0x124]
    assert _val(r[0], DQ) == old
    assert _val(r[1], DQ) == old
    for i, pin in enumerate(DQ):
        assert r[2][pin] in (str(old >> i & 1), str(new >> i & 1))
    assert _val(r[3], DQ) == new
    assert all(r[4][pin] == 'z' for pin in DQ)


def test_eeprom_bits_flip_at_different_times():
    # Across seeds, a mid-access sample must sometimes be neither the old
    # nor the new byte: that skew is what makes decoder runts.
    img = bytes([0x00, 0xFF]) * 4096
    p = {'TACC': 150, 'TOE': 70, 'ABITS': 13}
    mixed = 0
    for seed in range(1, 9):
        r = mem_sim('eeprom_28', dict(p, SEED=seed), img,
                    [({**_addr(0, 13), 20: '0', 22: '0', 27: '1'}, 200, []),
                     ({**_addr(1, 13)}, 100, DQ)])
        v = _val(r[1], DQ)
        assert v is not None
        mixed += v not in (0x00, 0xFF)
    assert mixed > 0


def test_gate_passes_a_runt_rejects_a_sliver():
    # A 12 ns input pulse through a 20 ns part comes out (the 14 ns runt at
    # U30.7 came out of a '138); a 2 ns sliver does not.
    res = sim('ttl_00', 14, {'TPD': 20},
              [({1: '1', 2: '0'}, 50, [3]),
               ({2: '1'}, 12, []), ({2: '0'}, 0, []),
               ({}, 16, [3]),                     # t = 78: runt out at 70..82
               ({}, 50, [3]),
               ({2: '1'}, 2, []), ({2: '0'}, 0, []),
               ({}, 19, [3]), ({}, 5, [3])])
    reads = [r[3] for r in res if r]
    assert reads == ['1', '0', '1', '1', '1']


def test_eeprom_8k_ignores_a13_a14():
    img = bytes(range(256)) * 32
    p = {'TACC': 150, 'TOE': 70, 'ABITS': 13}
    r = mem_sim('eeprom_28', p, img,
                [({**_addr(0x42, 13), 1: '1', 26: '1', 20: '0', 22: '0', 27: '1'}, 200, DQ)])
    assert _val(r[0], DQ) == 0x42


def _wr(a, v, width):
    return [({**_addr(a, 15), **{p: str(v >> i & 1) for i, p in enumerate(DQ)},
              20: '0', 22: '1', 27: '1'}, 50, []),
            ({27: '0'}, width, []),
            ({27: '1'}, 50, []),
            ({p: 'z' for p in DQ}, 0, [])]


def _rd(a):
    return [({**_addr(a, 15), 20: '0', 22: '0', 27: '1'}, 200, DQ), ({22: '1'}, 50, [])]


def test_sram_write_read():
    p = {'TAA': 100, 'TOE': 50, 'TWP': 70}
    s = _wr(0x1234, 0xA5, 100) + _wr(0x7FFF, 0x3C, 100) + _rd(0x1234) + _rd(0x7FFF)
    r = [x for x in mem_sim('sram_28', p, b'', s) if x]
    assert _val(r[0], DQ) == 0xA5
    assert _val(r[1], DQ) == 0x3C


def test_sram_single_write_then_deselect():
    # One write, then ~CE released before anything else happens: the cell
    # must hold the byte. (Back-to-back writes hid a start-on-the-wrong-edge
    # bug in the model.)
    p = {'TAA': 100, 'TOE': 50, 'TWP': 70}
    s = _wr(0x0040, 0x2E, 488) + [({20: '1'}, 100, [])] + _rd(0x0040)
    r = [x for x in mem_sim('sram_28', p, b'', s) if x]
    assert _val(r[0], DQ) == 0x2E


def test_sram_short_write_pulse_corrupts():
    # A ~WE pulse shorter than tWP is not a write the datasheet promises:
    # the cell is unknown afterwards (the 2026-09-29 14 ns runt).
    p = {'TAA': 100, 'TOE': 50, 'TWP': 70}
    s = _wr(0x0100, 0x55, 100) + _wr(0x0100, 0xAA, 14) + _rd(0x0100)
    r = [x for x in mem_sim('sram_28', p, b'', s) if x]
    assert all(v == 'x' for v in r[0].values())


def test_osc():
    # A can takes time to start after power-up; until then its output is
    # low, and every part has settled before the first clock edge.
    r = sim('osc_14', 14, {'HALF': 122.0703125, 'START': 1000},
            [({1: '1'}, 500, [8]), ({}, 683, [8]), ({}, 122, [8])])
    assert [x[8] for x in r] == ['0', '1', '0']   # 4.096 MHz once started


def test_powerup_differs_by_seed():
    # Real silicon powers up at some state; different seeds must give
    # different states, or "N seeds" is one seed N times (it was, once).
    Op = [2, 5, 6, 9, 12, 15, 16, 19]
    seen = set()
    for seed in range(1, 9):
        r = sim('ttl_373', 20, {'TPD': 18, 'SEED': seed},
                [({1: '0', 11: '0', **{p: '0' for p in (3, 4, 7, 8, 13, 14, 17, 18)}}, 50, Op)])
        seen.add(_val(r[0], Op))
    assert None not in seen and len(seen) >= 5, seen


def test_no_state_change_inside_powerup_window():
    # Rails ramp over milliseconds: nothing clocks while they do. Inside
    # POWERUP_NS a flop holds its power-up state through a clock edge;
    # after it, the same edge clocks.
    s = [({1: '1', 4: '1', 2: '0', 3: '0'}, 100, [5]),
         ({3: '1'}, 100, [5]),                    # edge at 100 ns: ignored
         ({3: '0'}, 900, []),
         ({3: '1'}, 100, [5])]                    # edge at 1100 ns: D=0 clocks
    res = [x for x in sim('ttl_74', 14, {'TPD': 20, 'SEED': 3}, s,
                          defines=('POWERUP_NS=1000',)) if x]
    assert res[0][5] in '01'
    assert res[1][5] == res[0][5]
    assert res[2][5] == '0'


def test_async_input_held_through_powerup_applies_after():
    # ~S held low from t = 0 (the reset RC) must preset the flop once the
    # power-up window ends, even though ~S never changes again.
    for seed in range(1, 6):
        res = [x for x in sim('ttl_74', 14, {'TPD': 20, 'SEED': seed},
                              [({1: '1', 4: '0', 2: '0', 3: '0'}, 1200, [5]),
                               ({4: '1'}, 100, [5])],
                              defines=('POWERUP_NS=1000',)) if x]
        assert res[0][5] == '1', seed
        assert res[1][5] == '1', seed


def _verilog_pins(text):
    """(ref, pin) -> KiCad net name, read back out of the generated Verilog
    by its own declarations, not by the generator's tables."""
    decl = {m.group(1): m.group(2)
            for m in re.finditer(r'^\s*wire (n_\w+);\s*// (.*)$', text, re.M)}
    decl.update({'n_VCC': '+5V', 'n_GND': 'GND', 'n_NC_HI': None})
    pins = {}
    for m in re.finditer(r'^\s*\w+(?: #\(.*?\))? ([UY]\d+) \(\s*//[^\n]*\n\s*(.*?)\);',
                         text, re.M | re.S):
        for pm in re.finditer(r'\.p(\d+)\((\w*)\)', m.group(2)):
            pins[(m.group(1), pm.group(1))] = decl.get(pm.group(2)) if pm.group(2) else None
    return pins


def test_simulation_is_the_schematic_pin_for_pin(netlist):
    # The sim is the TTL exactly as drawn: every chip pin on the net the
    # netlist puts it on, nothing added, nothing left out.
    comps, nets = netlist
    text, _ = ng.build(comps, nets)
    got = _verilog_pins(text)
    want = {}
    for net, nodes in nets.items():
        for ref, pin, _ in nodes:
            if ref[0] in 'UY':
                want[(ref, pin)] = None if net.startswith('unconnected-') else net
    assert {r for r, _ in got} == {r for r, _ in want}
    bad = [(k, want[k], got.get(k, 'MISSING')) for k in want if got.get(k, 'MISSING') != want[k]]
    assert not bad, bad[:10]
    assert not [k for k in got if k not in want and got[k] is not None]
    assert len(want) == 1530


def test_non_chip_elements_are_parts_on_the_board(netlist):
    # Pull-ups, series resistors and jumper shunts only: each one a part.
    comps, nets = netlist
    text, report = ng.build(comps, nets)
    extra = [l.strip() for l in text.splitlines() if re.match(r'\s*(pullup|assign)', l)]
    assert len(extra) == 12 + 4 + 2              # n_NC_HI's pull-up sits on its wire line
    assert {r for r, _ in report['pullups']} == {'R1', 'R9', 'R10', 'R11', 'R12', 'R13',
                                               'R28', 'R30', 'R31', 'R32', 'R33', 'R35'}
    assert {s[0] for s in report['shunts']} == {'JP3', 'J14'}
    assert report['floating'] == []

