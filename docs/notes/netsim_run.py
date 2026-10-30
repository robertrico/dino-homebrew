#!/usr/bin/env python3
"""Run a program ROM on the netlist simulation of Rev 1.0.

    python3 docs/notes/netsim_run.py PROG_isa [--trace] [--max-clks N] [--seed N]
    python3 docs/notes/netsim_run.py --ram asm/ram/retlda.asm [...]

--ram assembles a RAM program and preloads its bytes into U26, the way
the monitor's L command would; U24 then holds netsim/witness/call8100.asm,
which CALLs 0x8100 as G does and OUTs 0x5A if the RET comes back. A ROM
argument ending in .asm is assembled instead of read from roms/.

Regenerates netsim/gen/dino_rev1.v from the schematic, seats the burned
microcode (roms/U9.bin, U15.bin, U23.bin) and roms/<PROG>.bin in U24,
compiles with Icarus and runs. Prints the testbench's OB log and the
final HALT/TIMEOUT line. See netsim_gen.py for what this can and cannot
see.
"""
import os
import shutil
import subprocess
import sys

import asm
import netsim_gen as ng

ROOT = ng.ROOT
GEN = ng.OUT_DIR
BIN = os.path.expanduser('~/oss-cad-suite/bin')


def tool(name):
    return shutil.which(name) or os.path.join(BIN, name)


def rom_bytes(prog):
    if prog.endswith('.asm'):
        r = asm.assemble_text(open(os.path.join(ROOT, prog)).read())
        img = bytearray([0xFF] * 0x8000)
        img[r.origin:r.origin + len(r.code)] = bytes(r.code)
        return bytes(img)
    return open(os.path.join(ROOT, 'roms', prog + '.bin'), 'rb').read()


def main(argv):
    ram = argv[argv.index('--ram') + 1] if '--ram' in argv else None
    prog = argv[0] if argv and not argv[0].startswith('-') else (
        'netsim/witness/call8100.asm' if ram else 'PROG_isa')
    max_clks = argv[argv.index('--max-clks') + 1] if '--max-clks' in argv else '2000000'
    seed = argv[argv.index('--seed') + 1] if '--seed' in argv else '1'
    ng.main([])
    plus = []
    for chip, rom in (('U9', 'U9'), ('U15', 'U15'), ('U23', 'U23'), ('U24', prog)):
        hx = os.path.join(GEN, f'{chip}.hex')
        with open(hx, 'w') as f:
            f.write('\n'.join(f'{b:02x}' for b in rom_bytes(rom)) + '\n')
        plus.append(f'+{chip}={hx}')
    if ram:
        r = asm.assemble_text(open(os.path.join(ROOT, ram)).read())
        if r.origin < 0x8000:
            raise SystemExit(f'{ram}: origin {r.origin:#06x} is not in RAM')
        hx = os.path.join(GEN, 'U26.hex')
        with open(hx, 'w') as f:
            f.write(f'@{r.origin - 0x8000:x}\n' + '\n'.join(f'{b:02x}' for b in r.code) + '\n')
        plus.append(f'+U26={hx}')
    exe = os.path.join(GEN, 'dino_rev1.vvp')
    subprocess.run([tool('iverilog'), '-g2012', f'-DSEED_BASE={seed}', '-DPOWERUP_NS=1000', '-o', exe,
                    os.path.join(ROOT, 'netsim', 'ttl_models.v'),
                    os.path.join(GEN, 'dino_rev1.v'),
                    os.path.join(ROOT, 'netsim', 'tb_dino.v')], check=True)
    plus.append(f'+MAX_CLKS={max_clks}')
    if '--trace' in argv:
        plus.append('+trace')
    if ram:
        print(f'U26 preloaded with {ram}')
    print(f'U24 = {prog}, microcode U9/U15/U23 from roms/, clock J14 1-2, '
          f'power-up seed {seed}')
    sys.stdout.flush()
    subprocess.run([tool('vvp'), '-n', exe] + plus, check=True)


if __name__ == '__main__':
    main(sys.argv[1:])
