#!/usr/bin/env python3
"""Per-sheet I/O contracts: derive each module's boundary signals and stamp
them onto the physical sheets.

For every sheet in the hierarchy, lists the signals that CROSS its boundary:
  IN    — consumed here, driven on another sheet (shows the driving sheet)
  OUT   — driven here, consumed on other sheets (shows the consuming sheets)
  BIDIR — both (shared buses like W)
Direction comes from netlist pin types (output/power_out = drives,
tri_state = drives-when-enabled, input = consumes). Power nets (+5V/GND) and
sheet-internal nets are excluded — the contract is exactly what a bench rig
(MCU, logic analyzer) must supply and observe to test the board alone.

Usage:
  python3 kicad_contracts.py            # print contracts + write markdown
  python3 kicad_contracts.py --continuity U23 U63 U64 U65 U66 U67 U68 U69 U70 U71 U72 U73
                                        # continuity walk for the named chips
  python3 kicad_contracts.py --since 2fe4d7c
                                        # which pins changed net since a rev,
                                        # classified: copper to move vs label
                                        # added to an already-landed wire
  python3 kicad_contracts.py --stamp    # also place/refresh a text block on
                                        # each .kicad_sch (idempotent: any
                                        # previous MODULE CONTRACT block is
                                        # replaced)

Markdown lands in docs/notes/dino_sheet_contracts.md.
"""
import os
import re
import sys
import uuid
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kicad_xsheet_audit as kxa

MARK = "MODULE CONTRACT"
NS = uuid.uuid5(uuid.NAMESPACE_URL, "dino-kicad-contracts")


def sheet_name_map(root_path):
    """netlist sheet path ('/Memory/') -> .kicad_sch file, plus '/' -> root."""
    text = open(root_path).read()
    d = os.path.dirname(root_path)
    out = {"/": root_path}
    for m in re.finditer(
            r'\(property "Sheetname" "([^"]+)"[\s\S]*?\(property "Sheetfile" "([^"]+)"',
            text):
        out["/" + m.group(1) + "/"] = os.path.join(d, m.group(2))
    return out


def compress(names):
    """['W0'..'W7','CLK'] -> ['W0-7','CLK'] (numeric runs collapsed)."""
    groups = defaultdict(list)
    plain = []
    for n in sorted(set(names)):
        m = re.match(r"^(.*?)(\d+)$", n)
        if m:
            groups[m.group(1)].append(int(m.group(2)))
        else:
            plain.append(n)
    out = []
    for base, nums in groups.items():
        nums.sort()
        runs, s = [], nums[0]
        for a, b in zip(nums, nums[1:] + [None]):
            if b != a + 1:
                runs.append(f"{base}{s}" if s == a else f"{base}{s}-{a}")
                s = b
        out.extend(runs)
    return sorted(out + plain)


def component_sheets(text):
    """ref -> sheetpath name ("/", "/Memory/", ...) from the netlist's
    components section. 2026-09-12: the sheet used to be read off the net
    NAME's /Sheet/ prefix. Global labels have no prefix, so every node
    landed on the root and no contract crossed anything."""
    out = {}
    comps = text[text.index("(components"):text.index("(libparts")]
    for chunk in re.split(r"\(comp\n", comps)[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', chunk).group(1)
        names = re.search(r'\(sheetpath\s*\(names "([^"]+)"\)', chunk)
        out[ref] = names.group(1) if names else "/"
    return out


def parse_with_pinfunction(netfile):
    text = open(netfile).read()
    values = dict(re.findall(
        r'\(comp\s*\(ref "([^"]+)"\)\s*\(value "([^"]+)"\)', text))
    values["__sheets__"] = component_sheets(text)
    nets = []
    body = text[text.index("(nets"):]
    for chunk in re.split(r"\(net\n", body)[1:]:
        name = re.search(r'\(name "([^"]+)"\)', chunk).group(1)
        nodes = re.findall(
            r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)\s*(?:\(pinfunction "([^"]*)"\)\s*)?\(pintype "([^"]+)"\)',
            chunk)
        nets.append((name, nodes))
    return values, nets


# Instrument pins: J15 is the Rev 1.0 LA header (2026-10-29), TPn the scope
# test points. All passive, so without this every signal J15 exposes would
# read as an input of the sheet the header sits on. DNP parts (the C94-C96
# cap pads on root) are skipped for the same reason: not fitted, no load.
PROBE_REFS = re.compile(r"^(J15|TP\d+)$")


def build_contracts(root_path):
    netfile = kxa.export_netlist(root_path)
    values, nets = parse_with_pinfunction(netfile)
    os.unlink(netfile)

    alias_rep, alias_note = {}, {}
    for sf in kxa.sheet_files(root_path):
        for group in kxa.label_alias_groups(sf):
            rep = min(group)
            for g in group:
                rep = alias_rep.get(g, rep)
            for g in group:
                alias_rep[g] = rep
            alias_note[rep] = "=".join(sorted(group))

    # merged[label] = {sheetpath: set((ref, pintype))}
    merged = defaultdict(lambda: defaultdict(set))
    for name, nodes in nets:
        if name.startswith(("unconnected-", "Net-(")):
            continue
        label = kxa.leaf(name)
        label = alias_note.get(alias_rep.get(label, label), label)
        if label in ("+5V", "GND"):
            continue
        sheets_of = values["__sheets__"]
        for r, _p, fn, t in nodes:
            if PROBE_REFS.match(r) or values.get(r) == "DNP":
                continue  # an instrument pin or an unfitted pad consumes nothing
            sheet = sheets_of.get(r, "/")
            merged[label][sheet].add((r, fn or "", t.split("+")[0]))

    DRV = {"output", "power_out"}

    def is_mem_data(ref, fn):
        # EEPROM/RAM I/O pins are mistyped 'input' in the 74xx lib; only the
        # DATA pins can drive — address/CE/OE/WE really are inputs.
        return (kxa.MEMORY_REFS_HINT.search(values.get(ref, ""))
                and re.match(r"(D|DQ|I/?O)\d*(_\d+)?$", fn))

    contracts = defaultdict(lambda: {"IN": [], "OUT": [], "BIDIR": []})
    for label, sheets in merged.items():
        if len(sheets) < 2:
            continue  # sheet-internal
        hard_on = {s for s, rft in sheets.items()
                   if any(t in DRV for _, _, t in rft)}
        tri_on = {s for s, rft in sheets.items()
                  if any(t == "tri_state" for _, _, t in rft)}
        mem_on = {s for s, rft in sheets.items()
                  if any(is_mem_data(r, fn) for r, fn, _ in rft)}
        for s, rft in sheets.items():
            has_in = any(t == "input" and not is_mem_data(r, fn)
                         for r, fn, t in rft)
            others = set(sheets) - {s}
            if s in hard_on:
                contracts[s]["OUT"].append((label, others))
            elif s in tri_on and has_in:
                contracts[s]["BIDIR"].append((label, others))
            elif s in tri_on:
                contracts[s]["OUT"].append((label, others))
            elif s in mem_on:
                # RAM data pins are true bidir; EEPROM data with no other
                # driver anywhere is the plain source
                kind = "BIDIR" if (hard_on | tri_on) else "OUT"
                contracts[s][kind].append((label, others))
            else:
                contracts[s]["IN"].append(
                    (label, (hard_on | tri_on | mem_on) - {s}))
    return contracts


def short(sheetpath):
    return sheetpath.strip("/") or "root"


def render(contracts):
    lines = ["# DINO sheet-to-sheet contracts",
             "",
             "Generated by docs/notes/kicad_contracts.py — regenerate after any",
             "schematic change; do not hand-edit. Direction is derived from pin",
             "types: OUT(tri) means drives-when-enabled (a tri-state bus driver).",
             ""]
    for sheet in sorted(contracts):
        c = contracts[sheet]
        lines.append(f"## {short(sheet)}")
        for kind in ("IN", "OUT", "BIDIR"):
            if not c[kind]:
                continue
            bysrc = defaultdict(list)
            for label, others in c[kind]:
                bysrc[", ".join(sorted(short(o) for o in others))].append(label)
            for src, labels in sorted(bysrc.items()):
                arrow = {"IN": "<-", "OUT": "->", "BIDIR": "<->"}[kind]
                lines.append(f"- {kind:5s} {', '.join(compress(labels))}  {arrow} {src}")
        lines.append("")
    return "\n".join(lines)


def stamp(contracts, root_path):
    names = sheet_name_map(root_path)
    for sheetpath, sch_file in names.items():
        c = contracts.get(sheetpath)
        if not c:
            continue
        rows = [f"{MARK} — generated, do not hand-edit (kicad_contracts.py --stamp)"]
        for kind in ("IN", "OUT", "BIDIR"):
            if not c[kind]:
                continue
            bysrc = defaultdict(list)
            for label, others in c[kind]:
                bysrc[", ".join(sorted(short(o) for o in others))].append(label)
            for src, labels in sorted(bysrc.items()):
                arrow = {"IN": "<-", "OUT": "->", "BIDIR": "<->"}[kind]
                rows.append(f"{kind}: {', '.join(compress(labels))} {arrow} {src}")
        body = "\\n".join(r.replace('"', '\\"') for r in rows)

        t = open(sch_file).read()
        # STICKY POSITION: if a previous stamp exists, keep its (at x y) —
        # hand-moves in the editor survive every restamp. Heuristic
        # placement (below content, left margin) only on first stamp.
        prev = re.search(r'\(text "' + re.escape(MARK) +
                         r'[\s\S]*?\(at ([\d.-]+) ([\d.-]+)', t)
        # remove any previous stamped block (idempotent regeneration)
        t = re.sub(r'\t\(text "' + re.escape(MARK) + r'[\s\S]*?\n\t\)\n', "", t)
        if prev:
            x, y = float(prev.group(1)), float(prev.group(2))
        else:
            ys = [float(m.group(2)) for m in re.finditer(r"\(xy ([\d.]+) ([\d.]+)\)", t)]
            ys += [float(m.group(2)) for m in re.finditer(r"\(at ([\d.]+) ([\d.]+)", t)]
            x, y = 15.24, min(round(max(ys) + 10, 2), 280.0)
        uid = uuid.uuid5(NS, sch_file)
        block = (f'\t(text "{body}"\n'
                 f'\t\t(exclude_from_sim no)\n'
                 f'\t\t(at {x:g} {y:g} 0)\n'
                 f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
                 f'\t\t\t(justify left bottom)\n\t\t)\n'
                 f'\t\t(uuid "{uid}")\n\t)')
        t = t.rstrip()
        assert t.endswith(")")
        t = t[:-1] + block + "\n)\n"
        open(sch_file, "w").write(t)
        print(f"stamped {os.path.basename(sch_file)} ({len(rows)-1} contract lines)")


MEGA_PORT_BY_PREFIX = [   # (regex over signal name, port letter, bit = captured index)
    (re.compile(r"^W(\d)$"), "PA", {"0":"D22","1":"D23","2":"D24","3":"D25","4":"D26","5":"D27","6":"D28","7":"D29"}),
    (re.compile(r"^M([0-7])$"), "PC", {"0":"D37","1":"D36","2":"D35","3":"D34","4":"D33","5":"D32","6":"D31","7":"D30"}),
    (re.compile(r"^M(1[0-5]|8|9)$"), "PL", {"8":"D49","9":"D48","10":"D47","11":"D46","12":"D45","13":"D44","14":"D43","15":"D42"}),
    (re.compile(r"^CW([0-7])$"), "PC", {"0":"D37","1":"D36","2":"D35","3":"D34","4":"D33","5":"D32","6":"D31","7":"D30"}),
    (re.compile(r"^CW(1[0-5]|8|9)$"), "PL", {"8":"D49","9":"D48","10":"D47","11":"D46","12":"D45","13":"D44","14":"D43","15":"D42"}),
    (re.compile(r"^(?:IRB|IS|OB)(\d)$"), "PK", {str(i): f"A{8+i}" for i in range(8)}),
    (re.compile(r"^MDR(\d)$"), "PF", {str(i): f"A{i}" for i in range(8)}),
]
# Pool order: main double-row header first (one-region hookups), then PWM
# header, then COMM header. NEVER: D0/D1 (USB serial), D13 (onboard LED),
# D20/D21 (clone I2C pullups break high-Z release semantics).
POOL = ["PD7/D38","PG2/D39","PG1/D40","PG0/D41","PB3/D50","PB2/D51","PB1/D52",
        "PB0/D53","PE4/D2","PE5/D3","PG5/D4","PE3/D5","PH3/D6","PH4/D7",
        "PH5/D8","PH6/D9","PJ1/D14","PJ0/D15","PH1/D16","PH0/D17",
        "PD3/D18","PD2/D19","PB4/D10","PB5/D11","PB6/D12"]

# Hand-tuned per-module pin assignments: descending Mega pins land on
# physically adjacent DUT points, one contiguous block per chip — grab a
# chip, wire straight down the header. Overrides BOTH the pool and the
# fixed bus rules for the named signals (per-module: other modules keep
# the bus rules). A module MAY borrow fixed-port bus pins (PA/PL/...) it
# doesn't use as a bus; the emitter rejects any within-module
# double-assignment.
PIN_ASSIGN = {
    "control_word": {
        # One UNBROKEN descent D53 -> D22, one block per chip, each
        # block = the chip's driven address pins (1,2,3) then its
        # sampled outputs descending. D21/D20 are banned (clone I2C
        # pullups), so the 33rd wire spills to D19. CW0-8 leave PORTC
        # here so each CW bit sits WITH its decoder; the rig drives
        # them per-pin (settle() dwarfs the cost).
        # D53-D46: U29
        "CW6":              "PB0/D53",   # U29.1 (A0)
        "CW7":              "PB1/D52",   # U29.2 (A1)
        "CW8":              "PB2/D51",   # U29.3 (A2)
        "~{PC_CLEAR}":      "PB3/D50",   # U29.14
        "~{MDR_OUT}":       "PL2/D47",   # U29.11
        "~{REG_OUT_LOAD}":  "PL3/D46",   # U29.9
        # D45-D42: U62
        "COND_FLAG":        "PL5/D44",   # U62.3 (gate 1 input, rig drives)
        "~{PC_LOAD}":       "PL7/D42",   # U62.10
        # D41-D31: U28
        "CW3":              "PG0/D41",   # U28.1 (A0)
        "CW4":              "PG1/D40",   # U28.2 (A1)
        "CW5":              "PG2/D39",   # U28.3 (A2)
        "SRC_ACTIVE":       "PD7/D38",   # U28.15
        "~{ROM_OUT}":       "PC0/D37",   # U28.14
        "~{RAM_OUT}":       "PC1/D36",   # U28.13
        "~{REG_A_OUT}":     "PC2/D35",   # U28.12
        "~{REG_B_OUT}":     "PC3/D34",   # U28.11
        "~{REG_C_OUT}":     "PC4/D33",   # U28.10
        "~{ALU_OUT}":       "PC5/D32",   # U28.9
        # ~{SW_OUT} (was PC6/D31, U28.7) RETIRED 2026-08-25, PHASE E. IN left
        # the ISA and U28.7 is unlanded, so the signal has no contract entry
        # to assign. Deleted rather than repaired: the ATmega rig is retired
        # and CLAUDE.md forbids extending its hookup tables. A dead name here
        # raises at IMPORT and takes every other check in test_kicad_blocks
        # down with it.
        # D30-D22: U30
        "CW0":              "PC7/D30",   # U30.1 (A0)
        "CW1":              "PA7/D29",   # U30.2 (A1)
        "CW2":              "PA6/D28",   # U30.3 (A2)
        "~{REG_A_LOAD}":    "PA5/D27",   # U30.14
        "~{REG_B_LOAD}":    "PA4/D26",   # U30.13
        "~{REG_C_LOAD}":    "PA3/D25",   # U30.12
        "~{MAR_LO_LOAD}":   "PA2/D24",   # U30.11
        "~{MAR_HI_LOAD}":   "PA1/D23",   # U30.10
        "~{IR_LOAD}":       "PA0/D22",   # U30.9
        # D19: the spill
        "~{RAM_LOAD}":      "PD2/D19",   # U30.7
    },
    "mdr": {
        # Control run: ONE unbroken descent D53 -> D40, one contiguous
        # block per gate chip, holes in each chip's own pin order. The
        # three byte buses ride their fixed-port runs (each itself
        # unbroken): W0-7 = PA = D22-D29, MDR0-7 = PF = A0-A7,
        # IRB0-7 = PK = A8-A15.
        # D53-D49: U22 '02, pins 1..5 (D53 = LE_IR probe U22.1,
        # D50 = ~{MDR_EN} probe U22.4)
        "CLK":              "PB1/D52",   # U22.2
        "~{IR_LOAD}":       "PB2/D51",   # U22.3
        "SRC_ACTIVE":       "PL0/D49",   # U22.5
        # D48-D47: U37 '04
        "WRITE_DIR":        "PL1/D48",   # U37.4 (contract OUT)
        "~{MDR_OUT}":       "PL2/D47",   # U37.5
        # D46-D40: U39 '00, pins 1,2,4,6,8,9,10 ascending
        # (D43 = LE_MDR probe U39.6, D42 = BUS_DIR probe U39.8)
        "~{ROM_OUT}":       "PL3/D46",   # U39.1
        "~{RAM_OUT}":       "PL4/D45",   # U39.2
        "~{RAM_LOAD}":      "PL5/D44",   # U39.4 (same net as U37.3)
        "~{ALU_OUT}":       "PG0/D41",   # U39.9
        # ~{SW_OUT} (was PG1/D40) RETIRED 2026-08-25, PHASE E. U39.10 now
        # carries ~{IO_RD}. Not re-assigned -- see the control_word note.
    },
    "alu": {
        # DERIVED FROM THE BOARD (2026-07-26). Strip slots were read off
        # the wired board; the Mega follows with pin = slot + 17, which
        # keeps the existing ribbon (D53 -> slot 36 down to D26 -> slot 9).
        "CW9=SA2"           : "PB0/D53",   # slot 36
        "CW10=SA1"          : "PB1/D52",   # slot 35
        "CW11=SA0"          : "PB2/D51",   # slot 34
        "~{RESET}"          : "PL2/D47",   # slot 30
        "~{CLK}"            : "PL3/D46",   # slot 29
        "CLK"               : "PL4/D45",   # slot 28
        "COND_FLAG"         : "PG0/D41",   # slot 24
        "~{REG_B_LOAD}"     : "PC1/D36",   # slot 19
        "~{REG_A_LOAD}"     : "PC2/D35",   # slot 18
        "~{ALU_OUT}"        : "PC3/D34",   # slot 17
        "W7"                : "PC4/D33",   # slot 16
        "W6"                : "PC5/D32",   # slot 15
        "W5"                : "PC6/D31",   # slot 14
        "W4"                : "PC7/D30",   # slot 13
        "W3"                : "PA7/D29",   # slot 12
        "W2"                : "PA6/D28",   # slot 11
        "W1"                : "PA5/D27",   # slot 10
        "W0"                : "PA4/D26",   # slot 9
    },
    "memory": {
        # BENCH-DRIVEN LAYOUT (Rico, 2026-07-23): both byte buses ride
        # ONE unbroken 24-pin run, D53 -> D30, MDR first then M, each
        # bus ascending — a ribbon per bus, no controls interleaved.
        # Signals follow on D29 -> D22 (+ the D19 spill), U51 in chip
        # pin order. NOTE this abandons the fixed-port bus rule for this
        # module: neither bus is byte-aligned any more, so mod_memory.c
        # drives/samples both PER PIN (address is static per access —
        # settle() dominates, see the module header).
        "MDR0": "PB0/D53", "MDR1": "PB1/D52",
        "MDR2": "PB2/D51", "MDR3": "PB3/D50",
        "MDR4": "PL0/D49", "MDR5": "PL1/D48",
        "MDR6": "PL2/D47", "MDR7": "PL3/D46",
        "M0":  "PL4/D45", "M1":  "PL5/D44", "M2":  "PL6/D43",
        "M3":  "PL7/D42", "M4":  "PG0/D41", "M5":  "PG1/D40",
        "M6":  "PG2/D39", "M7":  "PD7/D38", "M8":  "PC0/D37",
        "M9":  "PC1/D36", "M10": "PC2/D35", "M11": "PC3/D34",
        "M12": "PC4/D33", "M13": "PC5/D32", "M14": "PC6/D31",
        "M15=ROM_EN": "PC7/D30",          # ROM ~CE rides M15
        # D29-D22: U51 '00 in pin order, then the two chip selects
        # (D28/D26/D25/D23 are the four probes — all U51 outputs)
        "WRITE_DIR":  "PA7/D29",          # U51.1 (daisies to .2 and .5)
        "~{CLK}":     "PA5/D27",          # U51.4
        "~{RAM_OUT}": "PA2/D24",          # U51.9 (also U26.22)
        "~{ROM_OUT}": "PA0/D22",          # U24.22 + U19.19
        "~{RAM_EN}":  "PD2/D19",          # U26.20 (spill; D21/D20 banned)
    },
    "mar": {
        # Controls: two short descents, every wire on U60 (the '02) —
        # D53-D50 = U60 pins 1..4, D41-D38 = U60 pins 5,10,11,13.
        # Buses ride fixed ports: W = PA = D22-D29, M0-7 = PC =
        # D37-D30, M8-15 = PL = D49-D42 (CW14 loses PL6 to M14 by the
        # emitter's bus-priority rule and is hand-placed here).
        # (D53 = LE_MAR_LO probe U60.1, D50 = LE_MAR_HI probe U60.4)
        "~{MAR_LO_LOAD}":     "PB1/D52",   # U60.2
        "CLK":                "PB2/D51",   # U60.3
        "~{MAR_HI_LOAD}":     "PG0/D41",   # U60.5
        "~{RAM_EN}":          "PG1/D40",   # U60.10
        "CW14=PC_MAR_MUX":    "PG2/D39",   # U60.11 (rig drives the tap)
        "~{PC_MAR_MUX}":      "PD7/D38",   # U60.13
    },
    "registers": {
        # One unbroken descent D53 -> D39, two chip blocks, holes in
        # chip pin order. Buses ride their fixed ports (MDR = PF =
        # A0-A7, OB = PK = A8-A15), each an unbroken run itself.
        # D53-D45: U57 '02 (all four LE stamps), pins 1..13
        # (D53/D50/D47/D45 = the LE probes, U57 pins 1/4/10/13)
        "~{REG_A_LOAD}":    "PB1/D52",   # U57.2
        "CLK":              "PB2/D51",   # U57.3 (any of the 4 CLK legs)
        "~{REG_B_LOAD}":    "PL0/D49",   # U57.5
        "~{REG_C_LOAD}":    "PL1/D48",   # U57.8
        "~{REG_OUT_LOAD}":  "PL3/D46",   # U57.11
        # D44-D39: U5 '08 (the '245 CE gates), pins 2,3,5,6,8,10
        # (D43/D41/D40 = the EN probes, U5 pins 3/6/8)
        "~{REG_A_OUT}":     "PL5/D44",   # U5.2
        "~{REG_B_OUT}":     "PL7/D42",   # U5.5
        "~{REG_C_OUT}":     "PG2/D39",   # U5.10
    },
}
# Rig-internal probes: nets the rig samples for diagnosis that are NOT
# sheet contracts (they never leave the DUT board). Emitted into the
# module's bundle as ordinary sampled rows, so `pins <mod>` prints EVERY
# wire of the hookup and mod_*.c binds them by name like anything else.
PIN_PROBES = {
    "control_word": [
        ("~{PC_LOAD_JMP}", "PL0/D49"),   # U29.13 -> U62 gate 2 input
        ("~{COND}",        "PL1/D48"),   # U29.12 -> U62 gate 1 input
        ("COND_TAKEN",     "PL4/D45"),   # U62.1  (gate 1 output)
        ("PC_LOAD_JMP",    "PL6/D43"),   # U62.4  (gate 2 output)
    ],
    "mdr": [
        ("LE_IR",     "PB0/D53"),        # U22.1  -> U34.11 (IR latch LE)
        ("~{MDR_EN}", "PB3/D50"),        # U22.4  -> U25.19 (bridge CE)
        ("LE_MDR",    "PL6/D43"),        # U39.6  -> U18.11 (MDR latch LE)
        ("BUS_DIR",   "PL7/D42"),        # U39.8  -> U25.1  (bridge DIR)
    ],
    "alu": [
        ("ALU_CIN"     , "PB3/D50"),   # slot 33
        ("LE_TMP_B"    , "PL0/D49"),   # slot 32
        ("LE_TMP_A"    , "PL1/D48"),   # slot 31
        ("ALU_V"       , "PL5/D44"),   # slot 27
        ("ALU_C"       , "PL6/D43"),   # slot 26
        ("CRY"         , "PL7/D42"),   # slot 25
        ("FLAG_V"      , "PG1/D40"),   # slot 23
        ("FLAG_N"      , "PG2/D39"),   # slot 22
        ("FLAG_C"      , "PD7/D38"),   # slot 21
        ("Z"           , "PC0/D37"),   # slot 20
    ],
    "memory": [
        ("~{WRITE_DIR}",    "PA6/D28"),  # U51.3  -> U21.1  ('245 DIR)
        ("~{RAM_WRITE_EN}", "PA4/D26"),  # U51.6  -> U26.27 (RAM ~WE)
        ("RAM_MDR_DIS",     "PA3/D25"),  # U51.8  -> U51.12/13
        ("~{RAM_MDR_EN}",   "PA1/D23"),  # U51.11 -> U21.19 ('245 CE)
    ],
    "mar": [
        ("LE_MAR_LO", "PB0/D53"),        # U60.1 -> U55.11
        ("LE_MAR_HI", "PB3/D50"),        # U60.4 -> U58.11
    ],
    "registers": [
        ("~{REG_A_LE}",   "PB0/D53"),    # U57.1  -> U31.11 (active HIGH)
        ("~{REG_B_LE}",   "PB3/D50"),    # U57.4  -> U32.11
        ("~{REG_C_LE}",   "PL2/D47"),    # U57.10 -> U33.11
        ("~{REG_OUT_LE}", "PL4/D45"),    # U57.13 -> U35.11
        ("~{A_EN}",       "PL6/D43"),    # U5.3   -> U41.19 ('245 CE)
        ("~{B_EN}",       "PG0/D41"),    # U5.6   -> U42.19
        ("~{C_EN}",       "PG1/D40"),    # U5.8   -> U43.19
    ],
}


def mod_token(sheetpath):
    s = short(sheetpath).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    # match the firmware's module names
    return {"memory_address_regiser": "mar", "memory_data_register": "mdr",
            "microcode_decoder": "microcode", "control_word_module": "control_word",
            "alu_module": "alu", "program_counter": "pc",
            "register_modules": "registers", "output": "io"}.get(s, s)


def expand(label):
    """Expand a compressed numeric range ('W0-7' -> W0..W7). Defensive only:
    build_contracts() emits uncompressed per-bit labels. Alias joins like
    'CW14=PC_MAR_MUX' pass through whole."""
    m = re.match(r"^(.*?)(\d+)-(\d+)$", label)
    if not m:
        return [label]
    base, a, b = m.group(1), int(m.group(2)), int(m.group(3))
    return [f"{base}{i}" for i in range(a, b + 1)]



_PIN_LINE = re.compile(
    r"(\S+)\s+pin\s+(\d+)\s+(\S*)\s*net=(\S+)\s*(?:\[NC\])?\s*(?:->\s*(.*))?$")


def _sheet_files(root):
    """[(sheet_token, path)] for every sub-sheet, root and _-prefixed excluded."""
    import glob as _glob
    out = []
    base = os.path.dirname(root)
    for f in sorted(_glob.glob(os.path.join(base, "*.kicad_sch"))):
        b = os.path.basename(f)
        if b.startswith("_") or f == root:
            continue
        out.append((b[:-len(".kicad_sch")], f))
    return out


def net_pins(root):
    """{netname: [(ref, pin, sheet_token), ...]}, power and anonymous nets
    dropped.

    Extracted so continuity_checklist and alias_splits share ONE collection
    path. Two paths would mean a net could be visible to the guard and
    invisible to the checklist, which is the failure the guard exists to catch.
    """
    from kicad_netlist import build_report
    pins = defaultdict(list)
    for token, f in _sheet_files(root):
        for line in build_report(f)[0]:
            m = _PIN_LINE.match(line)
            if not m:
                continue
            ref, pin, _fn, net = m.group(1), m.group(2), m.group(3), m.group(4)
            if net.startswith("N$anon") or net in ("GND", "+5V"):
                continue
            pins[net].append((ref, int(pin), token))
    # One physical net may carry different label sets on different sheets
    # (microcode: CW12; interrupt: CW12 + END). KiCad joins them through the
    # shared global label, and so does this: keys sharing any label merge,
    # under the sorted union of their labels. (2026-10-30, Rico: the tools
    # follow the schematic as built.)
    parent = {k: k for k in pins}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    owner = {}
    for k in pins:
        for part in k.split("/"):
            if part in owner:
                parent[find(k)] = find(owner[part])
            else:
                owner[part] = k
    groups = defaultdict(list)
    for k in pins:
        groups[find(k)].append(k)
    out = {}
    for ks in groups.values():
        name = "/".join(sorted({p for k in ks for p in k.split("/")}))
        out[name] = [p for k in sorted(ks) for p in pins[k]]
    return out


def alias_splits(net_pins_map):
    """{base_label: [conflicting net keys]} — one physical net carried under
    two different label sets.

    kicad_netlist keys a net on its FULL label set, joined with "/", per
    sheet. A net whose label set differs per sheet gets a different key per
    sheet; net_pins() merges keys that share a label (as KiCad's global labels
    do, since 2026-09-12), so on its output this should be empty. If it is
    not, every key looks single-sheet and continuity_checklist's cross-sheet
    filter drops the whole wire: driven by no test, sampled by no test.

    That is how M15/ROM_EN — the ROM chip-enable — stayed off every checklist
    this tool ever generated while the machine booted from ROM daily. Empty is
    the only acceptable result.
    """
    bases = defaultdict(set)
    for net in net_pins_map:
        for part in net.split("/"):
            bases[part].add(net)
    return {base: sorted(keys) for base, keys in bases.items() if len(keys) > 1}


def unlanded_stubs(root, refs=None):
    """{net: (ref, pin)} for nets with a single pin and nothing to beep against.

    CW16 and CW19-23 are U23 outputs wired to nothing — burned reserve bits with
    no consumer. They must not appear as wires to land (CLAUDE.md: "unwired bits
    emit as plain cw16/cw19-cw23. That is correct, not a failed label"), but
    dropping them without a word makes them indistinguishable from a wire the
    tool forgot. So: reported, in their own bucket.
    """
    refs = set(refs or [])
    out = {}
    for net, ps in sorted(net_pins(root).items()):
        if refs and not any(p[0] in refs for p in ps):
            continue
        if len(ps) == 1:
            out[net] = (ps[0][0], ps[0][1])
    return out


def _pin_state(sheet_paths):
    """{(ref, pin): (net, has_peers)} across the given sheets.

    Unlike net_pins() this keeps GND/+5V/N$anon, because the classifier needs
    them: a pin leaving "+5V" is a lifted strap, and whether an anonymous net
    already had other pins on it is the ONLY thing separating a wire that was
    always there from one that must now be landed.
    """
    from kicad_netlist import build_report
    state = {}
    for _token, path in sheet_paths:
        for line in build_report(path)[0]:
            m = _PIN_LINE.match(line)
            if not m:
                continue
            ref, pin, net, peers = m.group(1), m.group(2), m.group(4), m.group(5)
            peers = (peers or "").strip()
            state[(ref, int(pin))] = (net, bool(peers) and peers != "(nothing)")
    return state


def _sheets_at_rev(root, rev, tmpdir):
    """Materialise every sub-sheet as of `rev` into tmpdir; [(token, path)].

    NOTHING IS STORED. `git show <rev>:<path>` is the baseline and build_report
    takes a path, so the diff is old-parse vs new-parse. A checked-in baseline
    would be one more generated artifact that drifts out of date.
    """
    import subprocess
    d = os.path.dirname(root)
    repo = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=True).stdout.strip()
    reldir = os.path.relpath(d, repo)
    listing = subprocess.run(
        ["git", "-C", repo, "ls-tree", "--name-only", rev, f"{reldir}/"],
        capture_output=True, text=True, check=True).stdout.split()
    root_base = os.path.basename(root)
    out = []
    for rel in sorted(listing):
        b = os.path.basename(rel)
        if not b.endswith(".kicad_sch") or b.startswith("_") or b == root_base:
            continue
        blob = subprocess.run(["git", "-C", repo, "show", f"{rev}:{rel}"],
                              capture_output=True, text=True, check=True).stdout
        p = os.path.join(tmpdir, b)
        with open(p, "w") as fh:
            fh.write(blob)
        out.append((b[:-len(".kicad_sch")], p))
    return out


def pin_net_diff(root, rev):
    """Which pins changed net since `rev`, classified.

    `--continuity <new refs>` filters to nets touching the NEW designators, so
    it structurally cannot show an EXISTING pin whose net moved underneath it.
    In the stack commit that blind spot hid U28.6 and U30.6 going +5V -> the
    bank-select bits: two decoder ENABLES to lift on a working board, the worst
    class under the block law, found only by diffing HEAD by hand.

    Classification is the point. That commit produced 48 pin->net changes and
    44 were annotation — U9/U15/U16/U17 gaining MCA0-11 labels on wires landed
    long before. Unclassified, that is a 48-line scare sheet. Classified, it is
    a 4-line work list.

        new_pin    the pin did not exist at `rev`                U23.12
        new_wire   was anonymous with NOTHING else on the net    U29.7 (was NC)
        annotate   was anonymous but the net already had peers   U9.3
        annotate   old label set is a subset of the new one      U24.20
        copper     anything else — the pin genuinely moved       U28.6

    The two anonymous rules cannot be one rule: U9.3 and U29.7 both read
    "N$anon -> LABEL", and only the peer count tells ink from work.
    """
    import tempfile
    new = _pin_state(_sheet_files(root))
    with tempfile.TemporaryDirectory() as tmp:
        old = _pin_state(_sheets_at_rev(root, rev, tmp))

    buckets = {"copper": [], "new_wire": [], "new_pin": [], "annotate": []}
    for key in sorted(set(old) | set(new)):
        if key not in new:
            continue                      # pin removed; not a landing question
        new_net, _ = new[key]
        if key not in old:
            buckets["new_pin"].append((key[0], key[1], None, new_net))
            continue
        old_net, old_peers = old[key]
        if old_net == new_net:
            continue
        if old_net.startswith("N$anon"):
            which = "annotate" if old_peers else "new_wire"
        elif set(old_net.split("/")) <= set(new_net.split("/")):
            which = "annotate"
        else:
            which = "copper"
        buckets[which].append((key[0], key[1], old_net, new_net))
    return buckets


def print_pin_net_diff(root, rev):
    d = pin_net_diff(root, rev)
    order = [("copper", "COPPER    existing pin moved -- WIRE TO CHANGE"),
             ("new_wire", "NEW_WIRE  was unconnected -- WIRE TO LAND"),
             ("new_pin", "NEW_PIN   chip is new since the rev"),
             ("annotate", "ANNOTATE  label only, wire already there -- no copper")]
    print(f"# pin->net diff vs {rev} -- "
          + ", ".join(f"{k}={len(d[k])}" for k, _ in order))
    for key, title in order:
        if not d[key]:
            continue
        print(f"\n## {title}")
        for ref, pin, old, new in d[key]:
            print(f"  {ref}.{pin:<3d} {str(old):24s} -> {new}")


def continuity_checklist(root, refs=None):
    """Per-net continuity walk: every net that leaves a sheet, with its pin
    endpoints, optionally narrowed to the nets touching `refs`.

    THIS IS THE ARTIFACT THE MAR-LO POST-MORTEM ASKED FOR. That fault was two
    board-to-board runs, nine wires, never landed -- and the reason nothing
    caught it is that a COPPER wire is driven by no test and sampled by no
    test. The fix is not a new test; it is walking the list with a meter
    before power. The list has to come from the netlist, because the failure
    mode is a wire that was never on the hand-written list at all.

    `refs` narrows to newly-added chips: pass the new designators and you get
    exactly the stubs to land and beep, with the existing pins on each net
    shown as the other end to beep against.

    THE CROSS-SHEET FILTER APPLIES ONLY TO THE DEFAULT REPORT. Without `refs`
    the question is "which nets cross a board boundary" — that is what
    dino_sheet_contracts.md consumes, and a sheet-internal net is noise in it.
    With `refs` the question is different: "what do I land for these chips",
    and a new chip's own on-board wiring is most of that work. Measured for the
    twelve stack chips: 41 nets cross a sheet and 38 do not — 62 pins, over
    half the job, invisible.

    ~{TC1} is the case that forces it. Leave U63.15 -> U64.10 unlanded and the
    SP counts correctly for 256 pushes before the low byte wraps; PROG_stack
    passes clean and the bench learns nothing.

    Single-pin nets are excluded either way — see unlanded_stubs().
    """
    refs = set(refs or [])
    pins = net_pins(root)
    out = []
    for net, ps in sorted(pins.items()):
        if refs and not any(p[0] in refs for p in ps):
            continue
        if len(ps) < 2:
            continue
        if not refs and len({p[2] for p in ps}) < 2:
            continue
        new = sorted((r, p) for r, p, _ in ps if r in refs)
        old = sorted((r, p) for r, p, _ in ps if r not in refs)
        out.append((net, new, old))
    return out


def print_continuity(root, refs=None):
    rows = continuity_checklist(root, refs)
    n_new = sum(len(new) for _, new, _ in rows)
    print(f"# continuity checklist -- {len(rows)} nets, {n_new} new pins to land")
    print("# beep each NEW pin against any OTHER pin on the same net, and")
    print("# against its own neighbours (one-hole slips are the common fault).")
    print("# BOARD OFF. In-circuit leg-to-leg on a live board reads clamp diodes.")
    print()
    for net, new, old in rows:
        tag = "  ".join(f"{r}.{p}" for r, p in new) or "-"
        others = "  ".join(f"{r}.{p}" for r, p in old) or "-"
        print(f"{net:22s} NEW: {tag:28s} against: {others}")
    stubs = unlanded_stubs(root, refs)
    if stubs:
        print()
        print(f"# NO-CONNECT -- {len(stubs)} net(s) with a single pin. Nothing to")
        print("# land and nothing to beep against. Listed so they are accounted")
        print("# for: an unwired output is correct here, not a missing wire.")
        for net, (ref, pin) in sorted(stubs.items()):
            print(f"{net:22s} NC:  {ref}.{pin}")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", "..",
                                         "dino_v0_0_2", "dino_v0_0_2.kicad_sch"))
    contracts = build_contracts(root)
    md = render(contracts)
    out = os.path.join(here, "dino_sheet_contracts.md")
    open(out, "w").write(md + "\n")
    print(md)
    print(f"[written to {out}]")
    if "--stamp" in sys.argv:
        stamp(contracts, root)
    if "--continuity" in sys.argv:
        i = sys.argv.index("--continuity")
        refs = [a for a in sys.argv[i + 1:] if not a.startswith("--")]
        print_continuity(root, refs)
    if "--since" in sys.argv:
        i = sys.argv.index("--since")
        rest = [a for a in sys.argv[i + 1:] if not a.startswith("--")]
        print_pin_net_diff(root, rest[0] if rest else "HEAD")
