#!/usr/bin/env python3
"""Draw the core's Power sheet: a 24-pin ATX header for the picoPSU, its
rails on the project's power nets, PS_ON# on a 2-pin header for the panel
switch.

    python3 docs/notes/power_sheet_gen.py --write     dino_v0_0_2/power.kicad_sch
                                                      + a sheet block on the root

Rico, 2026-09-12: power is off the shelf (picoPSU-160-XT or -120-WI-25,
both 24-pin ATX). The rails drawn are exactly the ones those deliver and
the core uses or publishes: +5V, +3.3V, +12V, -12V, GND. No -5V (no ATX
unit since 2003 has one), no regulator on the core. +5VSB and PWR_OK are
brought to no-connects: real pins, nothing consumes them.

The sheet is a one-shot scaffold. Once it exists KiCad owns it; rerunning
`--write` on a project that already has a power sheet changes nothing.

Symbol definitions are copied VERBATIM out of KiCad 10's own libraries, so
the embedded lib_symbols match what the editor would embed itself.
"""
import os
import re
import sys
import uuid as _uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kicad_netlist import tokenize, parse, children, child  # noqa: E402
import footprint_gen as fg  # noqa: E402

SYM_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
PROJECT = "dino_v0_0_2"
ROOT_UUID = "e43166a5-d972-471d-b3cf-9f4f12c7f541"

ATX_REF = "J9"          # J1-J8 are reserved for the eight edge sockets
PSON_REF = "J10"
SHEET_NAME = "Power"
SHEET_FILE = "power.kicad_sch"
SHEET_AT = (182.88, 58.42)      # free cell on the root page, under Register Modules

# --- symbol geometry (lib units, Y up) ---------------------------------------
# ATX-24 pin connection points, read from Connector.kicad_sym. Stacked pins
# share a point, so one wire serves the whole rail.
ATX_PINS = {
    "+3.3V": (12.7, -2.54),
    "+5V": (12.7, 2.54),
    "+5VSB": (12.7, 0.0),
    "+12V": (12.7, 5.08),
    "PWR_OK": (12.7, 10.16),
    "-12V": (12.7, -10.16),
    "GND": (0.0, -15.24),
    "PS_ON#": (-12.7, 10.16),
}
ATX_AT = (101.6, 88.9)
RAIL_RUN = 12.7          # wire length from the header's right-hand pins

# --- s-expression text helpers ------------------------------------------------


def _uid():
    return str(_uuid.uuid4())


def raw_symbol(lib, name):
    """The `(symbol "<name>" ...)` block from KiCad's <lib>.kicad_sym, text
    verbatim, renamed to "<lib>:<name>" the way eeschema embeds it."""
    with open(os.path.join(SYM_DIR, lib + ".kicad_sym")) as f:
        src = f.read()
    head = f'(symbol "{name}"'
    start = src.index("\t" + head + "\n")
    depth, i, in_str = 0, start + 1, False
    while True:
        c = src[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    block = src[start + 1:i + 1]
    return "\t" + block.replace(head, f'(symbol "{lib}:{name}"', 1) + "\n"


def _q(s):
    """Quote a string the way eeschema does. 2026-09-12: an unescaped `"`
    inside a Description made KiCad stop reading the sheet at that symbol,
    silently -- half the page vanished and no tool said a word."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _prop(name, value, x, y, hide=False, extra=""):
    h = "\t\t\t(hide yes)\n" if hide else ""
    return (f'\t\t(property {_q(name)} {_q(value)}\n'
            f"\t\t\t(at {x:g} {y:g} 0)\n{h}"
            "\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n"
            "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n"
            f"{extra}\t\t\t)\n\t\t)\n")


def symbol(lib_id, ref, value, x, y, pins, path, footprint="", rot=0,
           datasheet="", description="", mirror=None):
    hidden_ref = ref.startswith("#")
    pins_txt = "".join(f'\t\t(pin "{p}"\n\t\t\t(uuid "{_uid()}")\n\t\t)\n'
                       for p in pins)
    return (
        "\t(symbol\n"
        f'\t\t(lib_id "{lib_id}")\n'
        f"\t\t(at {x:g} {y:g} {rot})\n"
        + (f"\t\t(mirror {mirror})\n" if mirror else "")
        + "\t\t(unit 1)\n\t\t(body_style 1)\n\t\t(exclude_from_sim no)\n"
        "\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(in_pos_files yes)\n"
        "\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n"
        f'\t\t(uuid "{_uid()}")\n'
        + _prop("Reference", ref, x, y - 7.62, hide=hidden_ref)
        + _prop("Value", value, x, y - 5.08)
        + _prop("Footprint", footprint, x, y, hide=True)
        + _prop("Datasheet", datasheet, x, y, hide=True)
        + _prop("Description", description, x, y, hide=True)
        + pins_txt
        + "\t\t(instances\n"
        f'\t\t\t(project "{PROJECT}"\n'
        f'\t\t\t\t(path "{path}"\n'
        f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n'
        "\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n")


def wire(x1, y1, x2, y2):
    return (f"\t(wire\n\t\t(pts\n\t\t\t(xy {x1:g} {y1:g}) (xy {x2:g} {y2:g})\n"
            "\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n"
            f'\t\t(uuid "{_uid()}")\n\t)\n')


def no_connect(x, y):
    return f'\t(no_connect\n\t\t(at {x:g} {y:g})\n\t\t(uuid "{_uid()}")\n\t)\n'


def text(s, x, y):
    # eeschema stores a newline as the two characters `\n`; quote first,
    # then break lines, or the backslash gets escaped too
    s = _q(s).replace("\n", "\\n")
    return (f'\t(text {s}\n\t\t(exclude_from_sim no)\n\t\t(at {x:g} {y:g} 0)\n'
            "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
            f"\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid \"{_uid()}\")\n\t)\n")


def power_refs(src):
    return set(re.findall(r'"(#PWR0?\d+)"', src))


def _pin_xy(at, lib_xy):
    """Lib coordinates are Y-up; the sheet is Y-down."""
    return (at[0] + lib_xy[0], at[1] - lib_xy[1])


# --- the sheet ----------------------------------------------------------------


def power_sheet(path, next_pwr):
    """Text of power.kicad_sch. `path` is the KiCad sheet path for symbol
    instances; `next_pwr` the first free #PWR number."""
    libs = "".join(raw_symbol(*s) for s in [
        ("Connector", "ATX-24"), ("Connector_Generic", "Conn_01x02"),
        ("power", "+5V"), ("power", "+3.3V"), ("power", "+12V"),
        ("power", "-12V"), ("power", "GND")])

    body = []
    ax, ay = ATX_AT
    body.append(symbol(
        "Connector:ATX-24", ATX_REF, "ATX-24", ax, ay,
        [str(n) for n in range(1, 25)], path,
        footprint=fg.assign("Connector:ATX-24", "ATX-24"),
        datasheet="https://www.intel.com/content/dam/www/public/us/en/"
                  "documents/guides/power-supply-design-guide-june.pdf#page=33",
        description="ATX Power supply 24pins"))

    n = next_pwr
    # Each rail's run is longer than the one above it. 2026-09-12: with equal
    # runs the +5V tick ended ON the +12V corner and KiCad joined them -- a
    # wire endpoint touching any wire is a connection, no junction needed.
    for k, rail in enumerate(("+12V", "+5V", "+3.3V", "-12V")):
        px, py = _pin_xy(ATX_AT, ATX_PINS[rail])
        ex = px + RAIL_RUN + k * 5.08
        body.append(wire(px, py, ex, py))
        body.append(wire(ex, py, ex, py - 2.54))
        body.append(symbol(f"power:{rail}", f"#PWR0{n}", rail, ex, py - 2.54,
                           ["1"], path, description="Power symbol creates a "
                           "global label with name \"" + rail + "\""))
        n += 1

    gx, gy = _pin_xy(ATX_AT, ATX_PINS["GND"])
    body.append(wire(gx, gy, gx, gy + 2.54))
    body.append(symbol("power:GND", f"#PWR0{n}", "GND", gx, gy + 2.54, ["1"],
                       path, description="Power symbol creates a global "
                       "label with name \"GND\" , ground"))
    n += 1

    for nc in ("+5VSB", "PWR_OK"):
        body.append(no_connect(*_pin_xy(ATX_AT, ATX_PINS[nc])))

    # PS_ON#: the ATX unit runs while this pin is held low. A 2-pin header
    # takes the panel's latching switch (or a jumper on the bench).
    sx, sy = _pin_xy(ATX_AT, ATX_PINS["PS_ON#"])
    jx = sx - 15.24
    # Conn_01x02: pin 1 at lib (-5.08, 0), pin 2 at (-5.08, -2.54), facing
    # LEFT. Mirrored about Y they face the ATX pin: pin 1 lands on
    # (jx+5.08, sy), pin 2 one grid step BELOW it.
    body.append(wire(sx, sy, jx + 5.08, sy))
    body.append(symbol("Connector_Generic:Conn_01x02", PSON_REF, "PS_ON", jx, sy,
                       ["1", "2"], path, mirror="y",
                       footprint=fg.assign("Connector_Generic:Conn_01x02", "PS_ON"),
                       description="Generic connector, single row, 01x02"))
    body.append(wire(jx + 5.08, sy + 2.54, jx + 7.62, sy + 2.54))
    body.append(wire(jx + 7.62, sy + 2.54, jx + 7.62, sy + 7.62))
    body.append(symbol("power:GND", f"#PWR0{n}", "GND", jx + 7.62, sy + 7.62,
                       ["1"], path, description="Power symbol creates a global "
                       "label with name \"GND\" , ground"))
    n += 1

    body.append(text(
        "POWER IS OFF THE SHELF: picoPSU-160-XT or picoPSU-120-WI-25 in J9.\n"
        "Rails drawn are what the unit delivers: +5V, +3.3V, +12V, -12V, GND.\n"
        "No -5V exists on any 24-pin ATX unit since 2003; none is drawn.\n"
        "-12V is 50-100mA for the WHOLE machine (unit dependent): every card\n"
        "states its +/-12V draw on its root page.\n"
        "PS_ON#: the unit runs while J10 is shorted. Panel switch or jumper.\n"
        "+5VSB and PWR_OK: real pins, nothing consumes them.",
        25.4, 40.64))

    return (
        "(kicad_sch\n\t(version 20260306)\n\t(generator \"eeschema\")\n"
        "\t(generator_version \"10.0\")\n"
        f'\t(uuid "{_uid()}")\n\t(paper "USLetter")\n'
        "\t(title_block\n\t\t(title \"Dino v0.0.3\")\n\t\t(date \"2026-09-12\")\n"
        "\t\t(rev \"v1.2.0\")\n\t\t(comment 1 \"Power: 24-pin ATX header for a picoPSU\")\n"
        "\t\t(comment 3 \"An 8-bit computer with 16-bit addressing and 16-bit control words\")\n"
        "\t\t(comment 4 \"A Turing-Complete 8-bit \\\"Computer\\\"\")\n\t)\n"
        "\t(lib_symbols\n" + libs + "\t)\n"
        + "".join(body)
        + "\t(embedded_fonts no)\n)\n")


def sheet_block(sheet_uuid, page):
    x, y = SHEET_AT
    return (
        "\t(sheet\n"
        f"\t\t(at {x:g} {y:g})\n\t\t(size 12.7 3.81)\n"
        "\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n"
        "\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n"
        "\t\t(stroke\n\t\t\t(width 0.1524)\n\t\t\t(type solid)\n\t\t)\n"
        "\t\t(fill\n\t\t\t(color 0 0 0 0)\n\t\t)\n"
        f'\t\t(uuid "{sheet_uuid}")\n'
        + _prop("Sheetname", SHEET_NAME, x, y - 0.7116,
                extra="\t\t\t\t(justify left bottom)\n")
        + _prop("Sheetfile", SHEET_FILE, x, y + 4.3946,
                extra="\t\t\t\t(justify left top)\n")
        + "\t\t(instances\n"
        f'\t\t\t(project "{PROJECT}"\n'
        f'\t\t\t\t(path "/{ROOT_UUID}"\n\t\t\t\t\t(page "{page}")\n'
        "\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n")


def unlink(proj):
    """Remove the power sheet and its block on the root, so `generate` can
    draw a fresh one. Tests use it; on the real project it throws away
    whatever was hand-edited since, so it is not on the command line."""
    root_path = os.path.join(proj, PROJECT + ".kicad_sch")
    with open(root_path) as f:
        root = f.read()
    hit = root.find(f'"{SHEET_FILE}"')
    if hit >= 0:
        start = root.rfind("\n\t(sheet\n", 0, hit) + 1
        end = root.index("\n\t)\n", hit) + len("\n\t)\n")
        with open(root_path, "w") as f:
            f.write(root[:start] + root[end:])
    sheet = os.path.join(proj, SHEET_FILE)
    if os.path.exists(sheet):
        os.remove(sheet)


def generate(proj):
    """Write power.kicad_sch and link it from the root. No-op if linked."""
    root_path = os.path.join(proj, PROJECT + ".kicad_sch")
    with open(root_path) as f:
        root = f.read()
    if f'"{SHEET_FILE}"' in root:
        return False
    tree = parse(tokenize(root))
    pages = [int(child(child(child(child(sh, "instances"), "project"),
                             "path"), "page")[1])
             for sh in children(tree, "sheet")]
    page = max(pages + [1]) + 1
    used = set()
    for f in fg.sheets(proj):
        with open(f) as fh:
            used |= {int(re.sub(r"\D", "", r)) for r in power_refs(fh.read())}
    next_pwr = max(used) + 1
    sheet_uuid = _uid()
    path = f"/{ROOT_UUID}/{sheet_uuid}"
    with open(os.path.join(proj, SHEET_FILE), "w") as f:
        f.write(power_sheet(path, next_pwr))
    marker = "\t(sheet_instances\n"
    assert marker in root, "root sheet without sheet_instances"
    root = root.replace(marker, sheet_block(sheet_uuid, page) + marker, 1)
    with open(root_path, "w") as f:
        f.write(root)
    return True


def main(argv):
    proj = os.path.join(HERE, "..", "..", PROJECT)
    if "--write" not in argv:
        print(__doc__)
        return 2
    print("written" if generate(proj) else "already present, nothing done")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
