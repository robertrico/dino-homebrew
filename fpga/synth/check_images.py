#!/usr/bin/env python3
"""Image-content checks for the FPGA synthesis flow.

Two modes, both comparing against the committed `roms/*.bin` -- the same
bytes Rico burns onto the real EEPROMs, and the only authority either
side of this file trusts:

  --hex [tag ...]
      FAST, no toolchain. Decode `fpga/sim/hex/<image>.hex` (what the
      synthesis flow actually feeds to the VHDL memory models via their
      init_file generics) and assert it equals `roms/<image>.bin` byte for
      byte. Covers the program ROM for each tag plus the two microcode
      ROMs. This is a STALENESS gate: the .hex files are generated from
      the .bin files by docs/notes/fpga_gen.py's bin2hex(), and nothing
      previously stopped a bitstream being built from a .hex left over
      from an older microcode_gen.py/progrom_gen.py run. Wired into
      fpga/Makefile's `bit` rule as a prerequisite, so it runs before
      every synthesis.

  --meminit [tag ...]
      SLOW, needs oss-cad-suite. Synthesize versa_top per tag through the
      real production sequence (the same `synth_ecp5 -run begin:coarse` +
      `script synth/bus_resolve.ys` + `synth_ecp5 -run coarse:map_ram`
      fpga/Makefile's `bit` rule uses), pull the INIT parameter off every
      `$mem_v2` cell in the synthesized netlist, decode it back to bytes,
      and assert it equals the committed .bin. This is restated synthesis
      gate 2's second half ("each ROM $meminit matches roms/*.bin bytes,
      one path shared by sim and synth") as a repeatable repo check
      rather than a one-off session script. Run it via
      `make -C fpga check-images`.

Both modes exit non-zero with the first differing byte named on any
mismatch. Run from anywhere; paths are derived from this file's location.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FPGA = os.path.normpath(os.path.join(HERE, ".."))
REPO = os.path.normpath(os.path.join(FPGA, ".."))
ROMS = os.path.join(REPO, "roms")
HEXD = os.path.join(FPGA, "sim", "hex")

TOOLS = os.path.expanduser("~/oss-cad-suite/bin")
YOSYS = os.path.join(TOOLS, "yosys")
GHDL_PREFIX = os.path.normpath(os.path.join(TOOLS, "..", "lib", "ghdl"))

# progrom_gen.COVERAGE tag -> the image STEM shared by fpga/sim/hex/<stem>.hex
# and roms/<stem>.bin. Mirrors fpga/Makefile's HEX_<tag> table and
# conftest_helpers._hex_name()'s "real"->PROG, other->PROG_<tag> rule; kept
# here rather than imported so this check has no import-time dependency on
# the docs/notes host package (it runs inside a Makefile prerequisite).
#
# mardisc/pads: added with fpga/Makefile's IMAGE_TAGS (2026-08-08 doc
# task) -- both ARE in progrom_gen.COVERAGE. cylon is added too even
# though it is deliberately NOT in progrom_gen.COVERAGE (never halts, no
# (OB, ends) fingerprint) -- this TAGS table is its own hand-mirrored
# list, not derived from COVERAGE, so cylon just needs a stem entry to
# get the same --hex staleness check every other image gets.
TAGS = {"real": "PROG", "in": "PROG_in", "alu": "PROG_alu",
        "mem": "PROG_mem", "flow": "PROG_flow", "loop": "PROG_loop",
        "mardisc": "PROG_mardisc", "pads": "PROG_pads",
        "stack": "PROG_stack",
        "cylon": "PROG_cylon"}

# The two microcode ROMs are the SAME in every image tag (every tag shares
# the one burned microcode); checked once per run, not once per tag.
# U23 joined 2026-08-10 -- the third microcode EEPROM (CW16-23). Its image
# is all-0xFF today and that is the correct content, not a placeholder: every
# field in the third word is polarised so a blank third ROM reproduces the
# 16-bit machine exactly.
MICROCODE = ["U9", "U15", "U23"]

GEN_SHEETS = ["alu", "control_word", "input_output", "mar", "mdr", "memory",
              "stack_pointer",
              "microcode", "program_counter", "registers_a_b"]


def _sources():
    return (sorted(glob.glob(os.path.join(FPGA, "ttl", "*.vhd")))
            + [os.path.join(FPGA, "gen", f"{s}.vhd") for s in GEN_SHEETS]
            + [os.path.join(FPGA, "gen", "dino_core.vhd"),
               os.path.join(FPGA, "top", "versa_top.vhd")])


def _hex_bytes(path):
    """fpga_gen.bin2hex()'s format: one two-digit hex byte per line."""
    out = bytearray()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(int(line[:2], 16))
    return bytes(out)


def _report(label, got, want, want_name):
    if got == want:
        print(f"    {label}: {len(got)}B == roms/{want_name} -- MATCH")
        return True
    print(f"    {label}: {len(got)}B vs roms/{want_name} ({len(want)}B) "
          f"-- MISMATCH")
    for i in range(min(len(got), len(want))):
        if got[i] != want[i]:
            print(f"      first differing byte @{i}: image 0x{got[i]:02x}, "
                  f"roms 0x{want[i]:02x}")
            break
    else:
        print(f"      lengths differ: {len(got)} vs {len(want)}")
    return False


def check_hex(tags):
    ok = True
    print("hex-vs-roms staleness check")
    for name in MICROCODE:
        h = os.path.join(HEXD, f"{name}.hex")
        b = os.path.join(ROMS, f"{name}.bin")
        if not os.path.exists(h):
            print(f"    {name}.hex: MISSING")
            ok = False
            continue
        ok &= _report(f"{name}.hex", _hex_bytes(h), open(b, "rb").read(),
                      f"{name}.bin")
    for tag in tags:
        stem = TAGS[tag]
        h = os.path.join(HEXD, f"{stem}.hex")
        b = os.path.join(ROMS, f"{stem}.bin")
        if not os.path.exists(h):
            print(f"    {tag}: {stem}.hex MISSING")
            ok = False
            continue
        ok &= _report(f"{tag} ({stem}.hex)", _hex_bytes(h),
                      open(b, "rb").read(), f"{stem}.bin")
    if not ok:
        print("\nfpga/sim/hex/*.hex is STALE or absent relative to roms/*.bin."
              "\nRegenerate both, in this order, then rebuild:"
              "\n    python3 docs/notes/microcode_gen.py"
              "\n    python3 docs/notes/progrom_gen.py"
              "\n    python3 -c \"import sys; sys.path.insert(0,'fpga/sim'); "
              "import conftest_helpers as ch; "
              "ch.prepare_roms(tags=tuple(ch.progrom_gen.COVERAGE))\"")
    return ok


def _synth_rtlil(tag, out):
    hexrel = os.path.join("sim", "hex", TAGS[tag] + ".hex")
    script = (f"ghdl --std=08 -gPROG_HEX={hexrel} " + " ".join(_sources()) +
              " -e versa_top;"
              " synth_ecp5 -top versa_top -run begin:coarse;"
              " proc -latches warn;"
              " script synth/bus_resolve.ys;"
              " synth_ecp5 -top versa_top -run coarse:map_ram;"
              f" write_rtlil {out}")
    env = dict(os.environ, GHDL_PREFIX=GHDL_PREFIX)
    env["PATH"] = TOOLS + os.pathsep + env.get("PATH", "")
    r = subprocess.run([YOSYS, "-m", "ghdl", "-p", script], cwd=FPGA,
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(r.stdout[-4000:], r.stderr[-2000:])
        raise SystemExit(f"synthesis failed for tag {tag!r}")


_INT = r"(?:(\d+)'([01xz]+)|(\d+))\s*$"


def _mems_from_rtlil(path):
    """{cell_name: bytes} for every $mem_v2 cell in module \\versa_top."""
    out, cur, inside, width, size, bits = {}, None, False, None, None, None
    for line in open(path):
        if line.startswith("module \\versa_top"):
            inside = True
            continue
        if not inside:
            continue
        m = re.match(r"^  cell \$mem_v2 (\S+)", line)
        if m:
            cur, width, size, bits = m.group(1), None, None, None
            continue
        if cur is None:
            continue
        for key in ("WIDTH", "SIZE"):
            m = re.match(rf"^    parameter \\{key} " + _INT, line)
            if m:
                v = int(m.group(2), 2) if m.group(2) else int(m.group(3))
                if key == "WIDTH":
                    width = v
                else:
                    size = v
        m = re.match(r"^    parameter \\INIT (\d+)'([01xz]+)", line)
        if m:
            bits = m.group(2)
        if line.startswith("  end") and bits is not None:
            assert len(bits) == width * size, (cur, len(bits), width, size)
            b = bytearray()
            for i in range(size):
                hi = len(bits) - i * width
                b.append(int(bits[hi - width:hi].replace("x", "0")
                             .replace("z", "0"), 2))
            out[cur] = bytes(b)
            cur = None
        elif line.startswith("  end"):
            cur = None
    return out


def check_meminit(tags):
    ok = True
    for tag in tags:
        with tempfile.TemporaryDirectory() as td:
            il = os.path.join(td, "netlist.il")
            _synth_rtlil(tag, il)
            mems = _mems_from_rtlil(il)
        print(f"--- {tag}: {len(mems)} $mem_v2 cells in the synthesized "
              f"netlist")
        if len(mems) != 4:
            print(f"    EXPECTED 4 memories (microcode U9/U15 + program ROM "
                  f"U24 + RAM U26), found {len(mems)}")
            ok = False
        for name, got in sorted(mems.items()):
            low = name.lower()
            if "u24" in low:
                ref = TAGS[tag] + ".bin"
            elif "u9" in low:
                ref = "U9.bin"
            elif "u15" in low:
                ref = "U15.bin"
            else:                       # u26 -- RAM, blank by design
                blank = all(x == 0 for x in got)
                print(f"    {name}: {len(got)}B RAM, all-zero={blank}")
                ok &= blank
                continue
            ok &= _report(name, got, open(os.path.join(ROMS, ref), "rb").read(),
                          ref)
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hex", action="store_true",
                   help="fast .hex-vs-.bin staleness check (no toolchain)")
    p.add_argument("--meminit", action="store_true",
                   help="synthesize and compare $mem_v2 INIT vs roms/*.bin")
    p.add_argument("tags", nargs="*", default=None,
                   help="image tags to check (default: all nine)")
    a = p.parse_args()
    tags = a.tags or list(TAGS)
    for t in tags:
        if t not in TAGS:
            p.error(f"unknown image tag {t!r}; known: {', '.join(TAGS)}")
    if not (a.hex or a.meminit):
        p.error("pick --hex and/or --meminit")
    ok = True
    if a.hex:
        ok &= check_hex(tags)
    if a.meminit:
        ok &= check_meminit(tags)
    print("check_images:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
