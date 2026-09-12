#!/usr/bin/env python3
"""The peripheral bus, drawn. PERIPHERAL_BUS.md sections 1-3, 2026-09-12.

    python3 docs/notes/bus_gen.py --write

One pin table, BUS, is the source of truth. From it:

  dino_bus/dino_bus.kicad_sym      DINO_BUS_SOCKET (core side) and
                                   DINO_BUS_EDGE (card side): 50 pins,
                                   named by signal, all passive
  dino_bus/dino_bus.pretty/        EdgeFingers_2x25_P2.54mm   the card's
                                   gold fingers, 25 a side
                                   EdgeSocket_2x25_P2.54mm_THT  PLACEHOLDER
                                   pin array for the core-side socket until
                                   a part is chosen (PERIPHERAL_BUS.md OPEN 2)
  dino_v0_0_2/peripheral_bus.kicad_sch
                                   J1-J8 sockets bussed on global labels;
                                   U78 ('04) buffers ~{CLK} into CLK_B;
                                   spare pins no-connected
  dino_io/                         card zero as its own project: the old
                                   Input sheet, refs unchanged, plus edge
                                   connector J1

and on the core: `input.kicad_sch` is removed, `input_output.kicad_sch`
becomes `front_panel.kicad_sch`, the root sheet follows.

Proof (test_bus_gen.py): core and card netlists joined through the slot-0
pin numbers partition every pre-existing pin exactly as the core's
netlist did before the split.

Rails on the sockets are global labels named like the power nets; KiCad
merges them by name. Every generated uuid is uuid5 of its role, so a
rerun writes byte-identical files.
"""
import json
import os
import re
import shutil
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kicad_netlist import tokenize, parse, children, child  # noqa: E402
from footprint_gen import sheets  # noqa: E402
from global_labels import label_names, convert as globalise  # noqa: E402
import power_sheet_gen as psg  # noqa: E402

# --- SECTION 1: the 50-pin edge -----------------------------------------------
# (pin, name, kind)  kind: signal | power | reserved | spare
_FRONT = [
    "GND", "+5V", "~{IO_SEL}", "~{IO_RD_Q}", "~{IO_WR}", "RESET_B", "GND",
    "W0", "W1", "W2", "W3", "W4", "W5", "W6", "W7", "GND", "CLK_B",
    "~{IRQ}", "~{NMI}", "~{DMARQ}", "~{DMAAK}", "RDY", "spare", "spare", "+5V",
]
_BACK = ["GND", "+5V"] + [f"M{i}" for i in range(16)] + \
        ["GND", "+12V", "-12V", "spare", "+3.3V", "+5V", "GND"]
POWER = {"+5V", "GND", "+3.3V", "+12V", "-12V"}
RESERVED = {"~{IRQ}", "~{NMI}", "~{DMARQ}", "~{DMAAK}", "RDY"}


def _kind(n):
    return ("power" if n in POWER else "reserved" if n in RESERVED
            else "spare" if n == "spare" else "signal")


BUS = [(i + 1, n, _kind(n)) for i, n in enumerate(_FRONT + _BACK)]
assert len(BUS) == 50

# what card zero takes off the edge (netlist-extracted from input.kicad_sch)
CARD_ZERO_TAKES = {"~{IO_RD_Q}", "M11", "M12", "M13", "+5V", "GND"} | \
                  {f"W{i}" for i in range(8)}

LIB = "dino_bus"
SOCKET, EDGE = "DINO_BUS_SOCKET", "DINO_BUS_EDGE"
FP_FINGERS = "EdgeFingers_2x25_P2.54mm"
FP_SOCKET = "EdgeSocket_2x25_P2.54mm_THT"
NS = uuid.UUID("6d1a7e2c-0a4f-4c62-9c1e-2f1e0dba5b05")   # dino_bus namespace


def uid(*key):
    return str(uuid.uuid5(NS, "/".join(map(str, key))))


# --- symbol geometry (lib units, Y up) ----------------------------------------
PIN_X = 12.7            # pin connection point, both sides
PIN_TOP = 30.48         # pin 1 / pin 26 row
PITCH = 2.54


def pin_lib_xy(pin):
    """Lib coordinates of a pin's connection point: 1-25 left, 26-50 right,
    pin n opposite pin n+25."""
    row = (pin - 1) % 25
    y = PIN_TOP - row * PITCH
    return (-PIN_X, y) if pin <= 25 else (PIN_X, y)


def pin_sheet_xy(at, pin):
    x, y = pin_lib_xy(pin)
    return (round(at[0] + x, 4), round(at[1] - y, 4))


# --- the library --------------------------------------------------------------

def _sym_prop(name, value, x, y, hide=False):
    return (f'\t\t(property "{name}" {psg._q(value)}\n\t\t\t(at {x:g} {y:g} 0)\n'
            "\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n"
            + ("\t\t\t(hide yes)\n" if hide else "")
            + "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n")


def pin_type(symbol, sig, kind, pin):
    """Socket side: everything passive, the core's own pins carry the
    direction. Edge side: what the card SEES -- the bus drives its control
    and address lines in (output), W is bidirectional, rails are power
    outputs into the card. This is what lets a card project pass ERC on its
    own; it is not a claim that a card drives anything (CARD-2)."""
    if symbol == SOCKET or kind in ("reserved", "spare"):
        return "passive"
    if kind == "power":
        # one driver per rail; the other pins of the same rail are passive
        first = min(p for p, n, _ in BUS if n == sig)
        return "power_out" if pin == first else "passive"
    if sig.startswith("W"):
        return "bidirectional"
    return "output"


def _symbol(name, footprint, descr):
    out = (f'\t(symbol "{name}"\n\t\t(pin_names\n\t\t\t(offset 1.016)\n\t\t)\n'
           "\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n"
           "\t\t(in_pos_files yes)\n\t\t(duplicate_pin_numbers_are_jumpers no)\n"
           + _sym_prop("Reference", "J", 0, 35.56)
           + _sym_prop("Value", name, 0, -35.56)
           + _sym_prop("Footprint", f"{LIB}:{footprint}", 0, 0, hide=True)
           + _sym_prop("Datasheet", "", 0, 0, hide=True)
           + _sym_prop("Description", descr, 0, 0, hide=True)
           + f'\t\t(symbol "{name}_0_1"\n\t\t\t(rectangle\n'
           "\t\t\t\t(start -10.16 33.02)\n\t\t\t\t(end 10.16 -33.02)\n"
           "\t\t\t\t(stroke\n\t\t\t\t\t(width 0.254)\n\t\t\t\t\t(type default)\n\t\t\t\t)\n"
           "\t\t\t\t(fill\n\t\t\t\t\t(type background)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n"
           + f'\t\t(symbol "{name}_1_1"\n')
    for pin, sig, kind in BUS:
        x, y = pin_lib_xy(pin)
        rot = 0 if pin <= 25 else 180
        label = sig
        ptype = pin_type(name, sig, kind, pin)
        out += (f"\t\t\t(pin {ptype} line\n\t\t\t\t(at {x:g} {y:g} {rot})\n"
                "\t\t\t\t(length 2.54)\n"
                f"\t\t\t\t(name {psg._q(label)}\n\t\t\t\t\t(effects\n\t\t\t\t\t\t(font\n"
                "\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n"
                f'\t\t\t\t(number "{pin}"\n\t\t\t\t\t(effects\n\t\t\t\t\t\t(font\n'
                "\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n"
                "\t\t\t)\n")
    out += "\t\t)\n\t\t(embedded_fonts no)\n\t)\n"
    return out


def symbol_library():
    return ("(kicad_symbol_lib\n\t(version 20251024)\n"
            '\t(generator "kicad_symbol_editor")\n\t(generator_version "10.0")\n'
            + _symbol(SOCKET, FP_SOCKET,
                      "DINO peripheral bus, core-side socket, 2x25 0.1in card edge. "
                      "Pin n opposite pin n+25. PERIPHERAL_BUS.md section 1.")
            + _symbol(EDGE, FP_FINGERS,
                      "DINO peripheral bus, card-side edge fingers, 2x25 0.1in. "
                      "Pin n opposite pin n+25. PERIPHERAL_BUS.md section 1.")
            + ")\n")


def _fp_head(name, descr, attr):
    return (f'(footprint "{name}"\n\t(version 20260206)\n\t(generator "bus_gen.py")\n'
            f'\t(layer "F.Cu")\n\t(descr {psg._q(descr)})\n'
            '\t(tags "DINO bus card edge 2.54mm")\n'
            '\t(property "Reference" "REF**"\n\t\t(at 0 -3 0)\n\t\t(layer "F.SilkS")\n'
            f'\t\t(uuid "{uid(name, "ref")}")\n'
            "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n"
            f'\t(property "Value" "{name}"\n\t\t(at 0 3 0)\n\t\t(layer "F.Fab")\n'
            f'\t\t(uuid "{uid(name, "val")}")\n'
            "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n"
            f"\t(attr {attr})\n")


def _fp_rect(name, layer, x0, y0, x1, y1, w):
    return (f"\t(fp_rect\n\t\t(start {x0:g} {y0:g})\n\t\t(end {x1:g} {y1:g})\n"
            f"\t\t(stroke\n\t\t\t(width {w})\n\t\t\t(type solid)\n\t\t)\n"
            f'\t\t(fill no)\n\t\t(layer "{layer}")\n\t\t(uuid "{uid(name, layer, x0, y0)}")\n\t)\n')


def fingers_footprint():
    """25 fingers a side, 0.1in pitch, 1.6mm wide x 10mm long, board edge
    along the bottom of the pads. Pin 1 front-left; pin 26 sits behind it
    on B.Cu. Chamfer and finger length follow the socket (OPEN 2)."""
    name = FP_FINGERS
    w = 25 * PITCH
    out = _fp_head(name, "DINO bus card fingers, 2x25, 0.1in pitch. Front 1-25, back 26-50.", "smd")
    out += _fp_rect(name, "F.CrtYd", -w / 2 - 0.5, -11.5, w / 2 + 0.5, 0.5, 0.05)
    out += _fp_rect(name, "F.Fab", -w / 2, -11, w / 2, 0, 0.1)
    out += _fp_rect(name, "Edge.Cuts", -w / 2 - 20, 0, w / 2 + 20, 0.001, 0.05)   # the edge
    for pin in range(1, 51):
        col = (pin - 1) % 25
        x = -w / 2 + PITCH / 2 + col * PITCH
        layers = '"F.Cu" "F.Mask"' if pin <= 25 else '"B.Cu" "B.Mask"'
        out += (f'\t(pad "{pin}" smd rect\n\t\t(at {x:.3f} -5.5)\n\t\t(size 1.6 10)\n'
                f"\t\t(layers {layers})\n\t\t(uuid \"{uid(name, 'pad', pin)}\")\n\t)\n")
    return out + "\t(embedded_fonts no)\n)\n"


def socket_footprint():
    """PLACEHOLDER: two rows of 25 THT pads, 0.1in pitch, rows 5.08mm apart.
    Real edge sockets stagger or space their rows by part; replace when the
    part is chosen (PERIPHERAL_BUS.md OPEN 2). Courtyard is the pad field
    plus a generous body."""
    name = FP_SOCKET
    w = 25 * PITCH
    out = _fp_head(name, "PLACEHOLDER 2x25 0.1in card-edge socket, THT. Replace with the chosen part.", "through_hole")
    out += _fp_rect(name, "F.CrtYd", -w / 2 - 2, -6, w / 2 + 2, 6, 0.05)
    out += _fp_rect(name, "F.Fab", -w / 2 - 1.5, -5.5, w / 2 + 1.5, 5.5, 0.1)
    for pin in range(1, 51):
        col = (pin - 1) % 25
        x = -w / 2 + PITCH / 2 + col * PITCH
        y = -2.54 if pin <= 25 else 2.54
        shape = "rect" if pin == 1 else "circle"
        out += (f'\t(pad "{pin}" thru_hole {shape}\n\t\t(at {x:.3f} {y:g})\n\t\t(size 1.6 1.6)\n'
                f'\t\t(drill 0.9)\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(remove_unused_layers no)\n'
                f"\t\t(uuid \"{uid(name, 'pad', pin)}\")\n\t)\n")
    return out + "\t(embedded_fonts no)\n)\n"


def write_library(repo):
    d = os.path.join(repo, LIB)
    os.makedirs(os.path.join(d, LIB + ".pretty"), exist_ok=True)
    with open(os.path.join(d, LIB + ".kicad_sym"), "w") as f:
        f.write(symbol_library())
    with open(os.path.join(d, LIB + ".pretty", FP_FINGERS + ".kicad_mod"), "w") as f:
        f.write(fingers_footprint())
    with open(os.path.join(d, LIB + ".pretty", FP_SOCKET + ".kicad_mod"), "w") as f:
        f.write(socket_footprint())


def _add_lib_row(table_path, kind, name, uri):
    with open(table_path) as f:
        t = f.read()
    if f'(name "{name}")' in t:
        return
    row = f'\t(lib (name "{name}") (type "KiCad") (uri "{uri}") (options "") (descr ""))\n'
    t = t.rstrip()
    assert t.endswith(")")
    with open(table_path, "w") as f:
        f.write(t[:-1].rstrip("\n") + "\n" + row + ")\n")


# --- schematic pieces -----------------------------------------------------------

def global_label(name, x, y, rot, key):
    j = "left" if rot in (0, 90) else "right"
    return (f'\t(global_label {psg._q(name)}\n\t\t(shape passive)\n\t\t(at {x:g} {y:g} {rot})\n'
            "\t\t(fields_autoplaced yes)\n"
            "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
            f"\t\t\t(justify {j})\n\t\t)\n\t\t(uuid \"{uid(key)}\")\n"
            '\t\t(property "Intersheetrefs" "${INTERSHEET_REFS}"\n'
            f"\t\t\t(at {x:g} {y:g} {rot})\n\t\t\t(hide yes)\n"
            "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n"
            f"\t\t\t\t(justify {j})\n\t\t\t)\n\t\t)\n\t)\n")


def no_connect(x, y, key):
    return f'\t(no_connect\n\t\t(at {x:g} {y:g})\n\t\t(uuid "{uid(key)}")\n\t)\n'


def _instance(lib_id, ref, value, x, y, pins, path, project, footprint, unit=1,
              descr="", key=None, rot=0):
    """A placed symbol; like power_sheet_gen.symbol but deterministic uuids
    and a project name."""
    key = key or ref
    hidden = ref.startswith("#")
    pins_txt = "".join(f'\t\t(pin "{p}"\n\t\t\t(uuid "{uid(key, "pin", p)}")\n\t\t)\n' for p in pins)
    return (
        "\t(symbol\n"
        f'\t\t(lib_id "{lib_id}")\n'
        f"\t\t(at {x:g} {y:g} {rot})\n"
        f"\t\t(unit {unit})\n\t\t(body_style 1)\n\t\t(exclude_from_sim no)\n"
        "\t\t(in_bom yes)\n\t\t(on_board yes)\n\t\t(in_pos_files yes)\n"
        "\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n"
        f'\t\t(uuid "{uid(key, "sym", unit)}")\n'
        + psg._prop("Reference", ref, x, y - 38.1, hide=hidden)
        + psg._prop("Value", value, x, y + 38.1)
        + psg._prop("Footprint", footprint, x, y, hide=True)
        + psg._prop("Datasheet", "", x, y, hide=True)
        + psg._prop("Description", descr, x, y, hide=True)
        + pins_txt
        + "\t\t(instances\n"
        f'\t\t\t(project "{project}"\n'
        f'\t\t\t\t(path "{path}"\n'
        f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit {unit})\n'
        "\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n")


def connector(ref, lib_name, x, y, path, project, takes=None):
    """A bus connector with a global label on every wired pin and a
    no-connect on the rest. `takes`: the set of signal names this side
    uses; None means all of them (the core side)."""
    fp = f"{LIB}:{FP_SOCKET if lib_name == SOCKET else FP_FINGERS}"
    out = _instance(f"{LIB}:{lib_name}", ref, lib_name, x, y,
                    [str(p) for p, _, _ in BUS], path, project, fp,
                    descr="DINO peripheral bus", key=f"{project}/{ref}")
    for pin, name, kind in BUS:
        px, py = pin_sheet_xy((x, y), pin)
        rot = 180 if pin <= 25 else 0
        wired = kind != "spare" and (takes is None or name in takes)
        if wired:
            out += global_label(name, px, py, rot, f"{project}/{ref}/label/{pin}")
        else:
            out += no_connect(px, py, f"{project}/{ref}/nc/{pin}")
    return out


# --- the core's bus sheet -------------------------------------------------------

BUS_SHEET = "peripheral_bus.kicad_sch"
BUS_SHEET_NAME = "Peripheral Bus"
BUS_SHEET_AT = (212.09, 58.42)           # root page, right of the Power block
# everything on the 1.27 mm grid, or ERC reports endpoint_off_grid
SOCKET_XY = [(60.96, 80.01), (160.02, 80.01), (259.08, 80.01), (358.14, 80.01),
             (60.96, 199.39), (160.02, 199.39), (259.08, 199.39), (358.14, 199.39)]
CLKBUF_REF = "U78"
CLKBUF_Y = 267.97
CLKBUF_X = [101.6, 140.97, 180.34, 220.98, 260.35, 299.72]   # units 1-6
CLKBUF_PWR_X = 340.36                                        # unit 7


def bus_sheet(repo, root_uuid, sheet_uuid, project="dino_v0_0_2"):
    path = f"/{root_uuid}/{sheet_uuid}"
    lib_txt = ""
    with open(os.path.join(repo, LIB, LIB + ".kicad_sym")) as f:
        sym = f.read()
    blk = _extract(sym, SOCKET).replace(f'(symbol "{SOCKET}"', f'(symbol "{LIB}:{SOCKET}"', 1)
    lib_txt += "\n".join("\t" + l if l else l for l in blk.splitlines()) + "\n"
    lib_txt += psg.raw_symbol("74xx", "74LS04")
    body = []
    for i, (x, y) in enumerate(SOCKET_XY, 1):
        body.append(connector(f"J{i}", SOCKET, x, y, path, project))
    # CLK_B: one '04 section on ~{CLK}; the other five parked, outputs NC
    fp = "Package_DIP:DIP-14_W7.62mm"
    all_pins = [str(n) for n in range(1, 15)]
    for unit, x in enumerate(CLKBUF_X, 1):
        body.append(_instance("74xx:74LS04", CLKBUF_REF, "74LS04", x, CLKBUF_Y,
                              all_pins, path, project, fp, unit=unit,
                              descr="Hex Inverter", key=f"{project}/{CLKBUF_REF}"))
        in_x, out_x = x - 7.62, x + 7.62
        if unit == 1:
            body.append(global_label("~{CLK}", in_x, CLKBUF_Y, 180, f"{project}/clkb/in"))
            body.append(global_label("CLK_B", out_x, CLKBUF_Y, 0, f"{project}/clkb/out"))
        else:
            body.append(global_label("GND", in_x, CLKBUF_Y, 180, f"{project}/clkb/gnd/{unit}"))
            body.append(no_connect(out_x, CLKBUF_Y, f"{project}/clkb/nc/{unit}"))
    px = CLKBUF_PWR_X
    body.append(_instance("74xx:74LS04", CLKBUF_REF, "74LS04", px, CLKBUF_Y,
                          [str(n) for n in range(1, 15)], path, project, fp, unit=7,
                          descr="Hex Inverter", key=f"{project}/{CLKBUF_REF}"))
    body.append(global_label("+5V", px, CLKBUF_Y - 12.7, 90, f"{project}/clkb/vcc"))
    body.append(global_label("GND", px, CLKBUF_Y + 12.7, 270, f"{project}/clkb/gnd7"))
    body.append(psg.text(
        "PERIPHERAL BUS -- eight 2x25 0.1in card-edge slots on the core PCB.\n"
        "Pin table: .git/sdd/PERIPHERAL_BUS.md section 1. Generated by docs/notes/bus_gen.py\n"
        "from one table; the symbol, the footprints and the card projects come from the same table.\n"
        "Slot decode stays ON THE CARD ('138 on M11-M13, Rico 2026-09-12). Slot n = 0x4000 + n*0x800.\n"
        "CLK_B: ~{CLK} through one '04 section; no card's clock pin ever sees U27.5 raw.\n"
        "~{IRQ} ~{NMI} ~{DMARQ} ~{DMAAK} RDY: named, RESERVED, not driven. Spares: no-connect.\n"
        "Rails are what the picoPSU delivers (POWER.md SECTION 8). -12V is 50-100mA for the WHOLE\n"
        "machine: every card states its +/-12V draw on its root page.\n"
        "Socket footprint is a PLACEHOLDER pin array until the part is chosen (OPEN 2).",
        20, 30))
    return (
        "(kicad_sch\n\t(version 20260306)\n\t(generator \"eeschema\")\n"
        "\t(generator_version \"10.0\")\n"
        f'\t(uuid "{uid(project, "bus-sheet-file")}")\n\t(paper "A3")\n'
        "\t(title_block\n\t\t(title \"Dino v0.0.3\")\n\t\t(date \"2026-09-12\")\n"
        "\t\t(rev \"v1.2.0\")\n\t\t(comment 1 \"Peripheral bus: eight card-edge slots\")\n"
        "\t\t(comment 3 \"An 8-bit computer with 16-bit addressing and 16-bit control words\")\n"
        "\t\t(comment 4 \"A Turing-Complete 8-bit \\\"Computer\\\"\")\n\t)\n"
        "\t(lib_symbols\n" + lib_txt + "\t)\n"
        + "".join(body)
        + "\t(embedded_fonts no)\n)\n")


def _extract(lib_text, name):
    """`\\t(symbol "<name>" ...)` block out of a .kicad_sym, one-tab indent."""
    head = f'\t(symbol "{name}"\n'
    i = lib_text.index(head)
    j = lib_text.find("\n\t(symbol \"", i + len(head))
    j = lib_text.rindex("\n)", i) if j < 0 else j
    return lib_text[i:j + 1]


def _sheet_block(sheet_uuid, page, name, file, at):
    x, y = at
    return (
        "\t(sheet\n"
        f"\t\t(at {x:g} {y:g})\n\t\t(size 12.7 3.81)\n"
        "\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n"
        "\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n"
        "\t\t(stroke\n\t\t\t(width 0.1524)\n\t\t\t(type solid)\n\t\t)\n"
        "\t\t(fill\n\t\t\t(color 0 0 0 0)\n\t\t)\n"
        f'\t\t(uuid "{sheet_uuid}")\n'
        + psg._prop("Sheetname", name, x, y - 0.7116, extra="\t\t\t\t(justify left bottom)\n")
        + psg._prop("Sheetfile", file, x, y + 4.3946, extra="\t\t\t\t(justify left top)\n")
        + "\t\t(instances\n"
        f'\t\t\t(project "{psg.PROJECT}"\n'
        f'\t\t\t\t(path "/{psg.ROOT_UUID}"\n\t\t\t\t\t(page "{page}")\n'
        "\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n")


def _next_page(root):
    tree = parse(tokenize(root))
    pages = [int(child(child(child(child(sh, "instances"), "project"), "path"), "page")[1])
             for sh in children(tree, "sheet")]
    return max(pages + [1]) + 1


def add_bus_sheet(repo):
    core = os.path.join(repo, "dino_v0_0_2")
    root_path = os.path.join(core, "dino_v0_0_2.kicad_sch")
    with open(root_path) as f:
        root = f.read()
    if f'"{BUS_SHEET}"' in root:
        return False
    sheet_uuid = uid("dino_v0_0_2", "bus-sheet-block")
    with open(os.path.join(core, BUS_SHEET), "w") as f:
        f.write(bus_sheet(repo, psg.ROOT_UUID, sheet_uuid))
    block = _sheet_block(sheet_uuid, _next_page(root), BUS_SHEET_NAME, BUS_SHEET, BUS_SHEET_AT)
    root = root.replace("\t(sheet_instances\n", block + "\t(sheet_instances\n", 1)
    with open(root_path, "w") as f:
        f.write(root)
    _add_lib_row(os.path.join(core, "sym-lib-table"), "sym", LIB,
                 f"${{KIPRJMOD}}/../{LIB}/{LIB}.kicad_sym")
    _add_lib_row(os.path.join(core, "fp-lib-table"), "fp", LIB,
                 f"${{KIPRJMOD}}/../{LIB}/{LIB}.pretty")
    return True


# --- card zero: dino_io ---------------------------------------------------------

CARD = "dino_io"
OLD_INPUT = "input.kicad_sch"
OLD_INPUT_BLOCK_UUID = "eeb646fc-821f-4891-aade-9ed05142e1ec"
CARD_J1_AT = (215.9, 101.6)          # on the 1.27 grid: 170 x 80


def _drop_sheet_block(root, file):
    hit = root.find(f'"{file}"')
    if hit < 0:
        return root
    start = root.rfind("\n\t(sheet\n", 0, hit) + 1
    end = root.index("\n\t)\n", hit) + len("\n\t)\n")
    return root[:start] + root[end:]


def split_card_zero(repo):
    core = os.path.join(repo, "dino_v0_0_2")
    card = os.path.join(repo, CARD)
    src_path = os.path.join(core, OLD_INPUT)
    if os.path.exists(card) or not os.path.exists(src_path):
        return False
    os.makedirs(card)
    with open(src_path) as f:
        src = f.read()
    new_uuid = uid(CARD, "root")
    path = f"/{new_uuid}"
    # transplant: new file identity, new project identity, same parts
    txt = re.sub(r'\(uuid "[^"]+"\)\n\t\(paper', f'(uuid "{new_uuid}")\n\t(paper', src, count=1)
    txt = txt.replace('(project "dino_v0_0_2"', f'(project "{CARD}"')
    txt = re.sub(r'\(path "/%s/%s"' % (psg.ROOT_UUID, OLD_INPUT_BLOCK_UUID),
                 f'(path "{path}"', txt)
    txt = txt.replace('(title "Dino v0.0.3")', '(title "DINO card zero: DIP switch")', 1)
    # the edge connector, its lib symbol, and its labels
    with open(os.path.join(repo, LIB, LIB + ".kicad_sym")) as f:
        sym = f.read()
    blk = _extract(sym, EDGE).replace(f'(symbol "{EDGE}"', f'(symbol "{LIB}:{EDGE}"', 1)
    blk = "\n".join("\t" + l if l else l for l in blk.splitlines()) + "\n"
    txt = txt.replace("\t(lib_symbols\n", "\t(lib_symbols\n" + blk, 1)
    conn = connector("J1", EDGE, CARD_J1_AT[0], CARD_J1_AT[1], path, CARD, takes=CARD_ZERO_TAKES)
    note = psg.text(
        "CARD ZERO -- the DIP switch, slot 0 (0x4000-0x47FF). Split out of dino_v0_0_2 2026-09-12;\n"
        "references unchanged (U76, SWITCH-GATE1, SW1, R17-R24, C48, C81) so PHASE_E.md still reads.\n"
        "Takes off the bus: ~{IO_RD_Q}, M11-M13, W0-7, +5V, GND. Gives back nothing (CARD-2).\n"
        "Slot decode is U76 on M11-M13, enabled by ~{IO_RD_Q} as built. +/-12V draw: none.",
        15.24, 30)
    # the Input sheet has no embedded_fonts line; insert before the final ")"
    txt = txt.rstrip()
    assert txt.endswith(")")
    txt = txt[:-1].rstrip("\n") + "\n" + conn + note + ")\n"
    with open(os.path.join(card, CARD + ".kicad_sch"), "w") as f:
        f.write(txt)
    # project file: the serial card's, renamed, exclusions cleared
    with open(os.path.join(repo, "dino_serial", "dino_serial.kicad_pro")) as f:
        pro = json.load(f)
    pro["meta"]["filename"] = CARD + ".kicad_pro"
    pro["sheets"] = [[new_uuid, "Root"]]
    pro.setdefault("erc", {})["erc_exclusions"] = []
    with open(os.path.join(card, CARD + ".kicad_pro"), "w") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")
    with open(os.path.join(card, "sym-lib-table"), "w") as f:
        f.write("(sym_lib_table\n\t(version 7)\n)\n")
    with open(os.path.join(card, "fp-lib-table"), "w") as f:
        f.write("(fp_lib_table\n\t(version 7)\n)\n")
    _add_lib_row(os.path.join(card, "sym-lib-table"), "sym", LIB,
                 f"${{KIPRJMOD}}/../{LIB}/{LIB}.kicad_sym")
    _add_lib_row(os.path.join(card, "sym-lib-table"), "sym", "dino",
                 "${KIPRJMOD}/../dino_v0_0_2/dino_v0_0_2.kicad_sym")
    _add_lib_row(os.path.join(card, "fp-lib-table"), "fp", LIB,
                 f"${{KIPRJMOD}}/../{LIB}/{LIB}.pretty")
    # and the core lets go of it
    os.remove(src_path)
    root_path = os.path.join(core, "dino_v0_0_2.kicad_sch")
    with open(root_path) as f:
        root = f.read()
    with open(root_path, "w") as f:
        f.write(_drop_sheet_block(root, OLD_INPUT))
    return True


def rename_front_panel(core):
    old, new = os.path.join(core, "input_output.kicad_sch"), os.path.join(core, "front_panel.kicad_sch")
    if not os.path.exists(old):
        return False
    os.rename(old, new)
    root_path = os.path.join(core, "dino_v0_0_2.kicad_sch")
    with open(root_path) as f:
        root = f.read()
    root = root.replace('(property "Sheetfile" "input_output.kicad_sch"',
                        '(property "Sheetfile" "front_panel.kicad_sch"')
    root = root.replace('(property "Sheetname" "Output"', '(property "Sheetname" "Front Panel"')
    with open(root_path, "w") as f:
        f.write(root)
    return True


# --- proof --------------------------------------------------------------------

def flatten(core_nets, cards):
    """Partition of (ref, pin) across the core and the cards, joined through
    the slot pin numbers. `cards`: {slot: nets}. A card's own J1 is renamed
    'J1@card' (or 'J1@card<slot>' when several) so it cannot collide with
    the core's J1. Every other card ref is kept: refs came from the core."""
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    for pins in core_nets.values():
        pins = list(pins)
        find(pins[0])                      # a single-pin net is still a net
        for p in pins[1:]:
            union(pins[0], p)
    for slot, nets in cards.items():
        tag = "J1@card" if len(cards) == 1 else f"J1@card{slot}"
        for pins in nets.values():
            pins = [((tag, p) if r == "J1" else (r, p)) for r, p in pins]
            find(pins[0])
            for p in pins[1:]:
                union(pins[0], p)
        for pin, _, _ in BUS:
            union((f"J{slot + 1}", str(pin)), (tag, str(pin)))
    groups = {}
    for a in list(parent):
        groups.setdefault(find(a), set()).add(a)
    return {frozenset(g) for g in groups.values()}


# --- the pass -------------------------------------------------------------------

def run(repo):
    write_library(repo)
    core = os.path.join(repo, "dino_v0_0_2")
    out = {"bus_sheet": add_bus_sheet(repo),
           "card_zero": split_card_zero(repo),
           "front_panel": rename_front_panel(core)}
    # RESET_B, ~{IO_WR}, ~{IO_SEL} lived on the Memory sheet alone until the
    # bus sheet named them too; they are cross-sheet now and must go global
    out["globalised"] = globalise(core)
    return out


def main(argv):
    repo = os.path.normpath(os.path.join(HERE, "..", ".."))
    if "--write" not in argv:
        print(__doc__)
        return 2
    print(run(repo))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
