#!/usr/bin/env python3
"""Every runnable image on the FPGA twin, simulated, against the oracle.

    python3 docs/notes/fpga_twin_suite.py [--seeds N] [--only PROG_x] [--cards]

The twin is built for the slot table (fpga_slots_gen.SLOTS: card zero in
J1, the serial card in J2, the DEADBEEF card in J3). For each power-up seed
it is regenerated (each stateful part's power-up state) and built with
Verilator, then each image runs until HALT. Pass = HALT, OB as the oracle
says, and no tick with two drivers on one net.

The oracle (progrom_gen.simulate) runs each image with the same slot table
(fpga_cards.oracle_cards): card zero with every switch open reads 0xFF,
the DEADBEEF card its cells. The serial card is not oracled (its UART is
temporal), so the oracle sees slot 1 empty, as netsim_suite does, and the
images that drive it are not in this list.

--cards runs the images that need the serial card or a switch setting, on
seed 1, and prints what they send and show (no oracle: their answers are
datasheet-sourced; compare the log against a known-good one).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fpga_cards  # noqa: E402
import fpga_slots_gen  # noqa: E402
import netsim_suite  # noqa: E402  (image filter and source check only)
import progrom_gen as pg  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
FPGA = os.path.join(ROOT, 'fpga')
GEN = os.path.join(FPGA, 'gen')
TOOLS = os.path.expanduser('~/oss-cad-suite/bin')
EMPTY = 0xFF                 # SW1 with every switch open

# images that need a card the netsim twin does not have, and which card
CARD_IMAGES = {'PROG_deadbeef': 'deadbeef_card'}


def build(seed, slots=None, out_dir=GEN):
    """Generate the twin for a slot table and build it; -> the executable."""
    fpga_slots_gen.generate(seed=seed, slots=slots, out_dir=out_dir)
    files = open(os.path.join(out_dir, 'dino_system_files.txt')).read().split()
    env = dict(os.environ, PATH=TOOLS + ':' + os.environ['PATH'])
    mdir = os.path.join(out_dir, 'sim_build')
    r = subprocess.run(['verilator', '--cc', '--exe', '--build', '-O3', '-j', '8',
                        '-Wno-fatal', '-Wno-lint', '-Wno-style', '-DSIM', '-DU24_HEX=""',
                        f'-I{out_dir}', '--top-module', 'dino_system', '-Mdir', mdir,
                        '-o', 'twin', os.path.join(FPGA, 'ttl_fpga.v'), *files,
                        os.path.join(FPGA, 'sim', 'twin_tb.cpp')],
                       cwd=FPGA, env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stdout[-3000:] + r.stderr[-3000:])
    return os.path.join(mdir, 'twin')


def hexfile(stem, out_dir=GEN):
    out = os.path.join(out_dir, f'{stem}.hex')
    data = open(os.path.join(ROOT, 'roms', stem + '.bin'), 'rb').read()
    open(out, 'w').write('\n'.join(f'{b:02x}' for b in data) + '\n')
    return out


def run(twin, stem, max_ticks=2_000_000_000, hexf=None, cwd=GEN, extra=()):
    hexf = hexf or hexfile(stem, cwd)
    p = subprocess.run([twin, f'+U24={hexf}', f'+MAX_TICKS={max_ticks}', *extra],
                       cwd=cwd, capture_output=True, text=True)
    m = re.search(r'^(HALT|TIMEOUT) OB=(\w+) ticks=(\d+) contention=(\d+)', p.stdout, re.M)
    if not m:
        return {'end': 'ERROR', 'tail': (p.stdout + p.stderr)[-300:]}
    sout = [int(b, 16) for b in re.findall(r'^SOUT (\w\w)', p.stdout, re.M)]
    return {'end': m.group(1), 'OB': m.group(2), 'ticks': int(m.group(3)),
            'contention': int(m.group(4)), 'sout': sout}


def oracle_images(slots, skipped=None):
    """[(stem, expected OB, oracle steps)] for every image the twin can run
    with this slot table, expected values from the oracle with the same
    table."""
    skipped = [] if skipped is None else skipped
    cards = fpga_cards.oracle_cards(slots, {'switches': EMPTY})
    seated = set(slots.values())
    out = []
    for f in sorted(os.listdir(os.path.join(ROOT, 'roms'))):
        stem = f[:-4]
        if not (f.startswith('PROG') and f.endswith('.bin')):
            continue
        if stem in CARD_IMAGES:
            if CARD_IMAGES[stem] not in seated:
                skipped.append((stem, f'needs {CARD_IMAGES[stem]} seated'))
                continue
        elif netsim_suite.NEEDS_CARD.match(stem):
            continue
        if not netsim_suite.source_matches(stem):
            raise SystemExit(f'roms/{f} is not its asm source: rebuild before trusting it')
        img = open(os.path.join(ROOT, 'roms', f), 'rb').read()
        try:
            r = pg.simulate(None, image=img, switches=EMPTY, serial=False,
                            max_steps=5000000, cards=cards)
        except pg.BuildError as e:
            skipped.append((stem, f'oracle: {e}'))
            continue
        if r['halted'] and r['out'] is not None:
            out.append((stem, r['out'], r.get('steps')))
        else:
            skipped.append((stem, 'never HALTs'))
    return out


# --cards: (image, plusargs) -- the serial images, card zero's switches,
# the monitor and SCELBAL, as the 2026-10-30 before-slots log ran them
CARD_RUNS = [
    *[(s, ['+HALT_TICKS=500000', '+MAX_TICKS=200000000'])
      for s in ('sertx', 'serid', 'serid_aa', 'serlsr', 'seriir', 'serloop')],
    ('dip', ['+SW=00']), ('dip', ['+SW=e1']),
    ('imon', [r'+SIN=\rD 0000\r~', '+MAX_TICKS=150000000']),
    ('basic', [r'+SIN=\rG 0A00\r~PRINT 2/3\r~PRINT PEEK(16384)\r~',
               '+MAX_TICKS=400000000', '+SW=80']),
]


def card_runs(twin, cwd=GEN):
    for img, args in CARD_RUNS:
        r = run(twin, f'PROG_{img}', extra=args, cwd=cwd,
                max_ticks=int(next((a[11:] for a in args if a.startswith('+MAX_TICKS=')),
                                   2_000_000_000)))
        print(f'== {img} {" ".join(args)}')
        line = ''.join(f'{b:02x} ' for b in r['sout'])
        print(f'{line}{r["end"]} OB={r["OB"]} ticks={r["ticks"]} contention={r["contention"]}')


def main(argv):
    seeds = int(argv[argv.index('--seeds') + 1]) if '--seeds' in argv else 3
    only = argv[argv.index('--only') + 1] if '--only' in argv else None
    slots = fpga_slots_gen.SLOTS
    print('slots: ' + '  '.join(f'{s}={n}' for s, n in sorted(slots.items())))
    if '--cards' in argv:
        card_runs(build(1, slots))
        return 0
    skipped = []
    imgs = [i for i in oracle_images(slots, skipped) if only is None or i[0] == only]
    results = {stem: [] for stem, _, _ in imgs}
    fails = 0
    for seed in range(1, seeds + 1):
        twin = build(seed, slots)
        for stem, want, _ in imgs:
            r = run(twin, stem)
            ok = (r['end'] == 'HALT' and r.get('OB', '').lower() == f'{want:02x}'
                  and r.get('contention') == 0)
            fails += not ok
            cell = ('ok ' if ok else 'FAIL ') + r.get('OB', r['end'])
            if r.get('contention'):
                cell += f' c={r["contention"]}'
            results[stem].append(cell)
    for stem, want, _ in imgs:
        print(f'{stem:18s} want 0x{want:02X}   ' + '  '.join(results[stem]))
    for stem, why in skipped:
        print(f'{stem:18s} not run: {why}')
    print(f'{fails} failing run(s)')
    return fails


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
