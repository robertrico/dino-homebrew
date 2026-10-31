#!/usr/bin/env python3
"""Every ROM-only coverage image on the twin, against the oracle.

    python3 docs/notes/netsim_suite.py [--seeds N]

Runs each burned roms/PROG*.bin on netsim (the Rev 1.0 netlist as drawn)
at power-up seeds 1..N and checks, per run: OB equals the oracle's value,
the machine HALTs, no machine state went unknown (statex=0), and no RAM
~WE pulse was shorter than tWP (we_short=0). Exit status is the number of
failing runs.

Expected values are generated, never typed: progrom_gen.simulate() runs
the same burned image under the same conditions as the twin, which is the
mainboard with its slots empty: SW1 reads 0xFF (card 0 absent, the W
pull-ups) and there is no serial card. Where an asm/<name>.asm source
exists, the burned image must be byte-identical to it first.

Not run, and listed: images that exist to drive the serial card or
interrupts (the only interrupt source is the UART), images that never
HALT, and images the oracle cannot run (built for an older ISA).
"""
import os
import re
import subprocess
import sys

import asm
import progrom_gen as pg

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
RUN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'netsim_run.py')

# Images that exist to drive the serial card or interrupts, or that read a
# card only the FPGA twin seats (deadbeef: fpga_twin_suite.CARD_IMAGES).
NEEDS_CARD = re.compile(r'^PROG_(ser|int|rx|tx|hello|monitor|imon|basic|deadbeef)')
EMPTY_SLOT = 0xFF


def source_matches(stem):
    """False if asm/<name>.asm exists and the burned image differs from it."""
    src = os.path.join(ROOT, 'asm', stem[len('PROG_'):] + '.asm')
    if not os.path.exists(src):
        return True
    r = asm.assemble_text(open(src).read())
    burned = open(os.path.join(ROOT, 'roms', stem + '.bin'), 'rb').read()
    return burned[r.origin:r.origin + len(r.code)] == bytes(r.code)


SKIPPED = []


def images():
    """[(stem, expected OB, oracle steps)] for every runnable burned image.
    Images the oracle cannot run (an opcode the current ISA does not define,
    or no HALT) go to SKIPPED with the reason."""
    out = []
    for f in sorted(os.listdir(os.path.join(ROOT, 'roms'))):
        stem = f[:-4]
        if not (f.startswith('PROG') and f.endswith('.bin')) or NEEDS_CARD.match(stem):
            continue
        if not source_matches(stem):
            raise SystemExit(f'roms/{f} is not its asm source: rebuild before trusting it')
        img = open(os.path.join(ROOT, 'roms', f), 'rb').read()
        try:
            r = pg.simulate(None, image=img, switches=EMPTY_SLOT, serial=False,
                            max_steps=5000000)
        except pg.BuildError as e:
            SKIPPED.append((stem, f'oracle: {e}'))
            continue
        if r['halted'] and r['out'] is not None:
            out.append((stem, r['out'], r.get('steps')))
        else:
            SKIPPED.append((stem, 'never HALTs'))
    return out


def run(rom, seed):
    p = subprocess.run([sys.executable, RUN, rom, '--seed', str(seed),
                        '--max-clks', '3000000'], capture_output=True, text=True)
    m = re.search(r'^(HALT|TIMEOUT|STUCK)(.*)$', p.stdout, re.M)
    if not m:
        return {'end': 'ERROR', 'tail': (p.stdout + p.stderr)[-300:]}
    d = {'end': m.group(1)}
    for k, v in re.findall(r'(\w+)=(\S+)', m.group(2)):
        d[k] = v
    return d


def main(argv):
    seeds = int(argv[argv.index('--seeds') + 1]) if '--seeds' in argv else 3
    fails = 0
    for rom, want, _steps in images():
        tag = rom
        cells = []
        for seed in range(1, seeds + 1):
            r = run(rom, seed)
            ok = (r['end'] == 'HALT' and r.get('OB', '').lower() == f'{want:02x}'
                  and r.get('statex') == '0' and r.get('we_short') == '0')
            fails += not ok
            cells.append(('ok ' if ok else 'FAIL ') + f"{r.get('OB', r['end'])}")
        print(f'{rom:18s} want 0x{want:02X}   ' + '  '.join(cells), flush=True)
    for stem, why in SKIPPED:
        print(f'{stem:18s} not run: {why}')
    print(f'{fails} failing run(s)')
    return fails


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
