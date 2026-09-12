#!/usr/bin/env python3
"""Take dino_v0_0_2's ERC warnings down to the ones the peripheral bus
will consume. No wire moves; see test_erc_cleanup.py for the inventory.

    python3 docs/notes/erc_cleanup.py --write
    python3 docs/notes/erc_cleanup.py --append <erc-report.json>   merge keys
                      from a report the GUI saved (its ERC finds markers
                      kicad-cli does not)

Four edits:
  1. rehome_symbols   the four symbols KiCad 10's libraries no longer carry
                      (74LS244N, AT28C64B, AT28C256, MCM60256AP) move, byte
                      for byte, into the project library `dino`
  2. delete           a 1.27 mm stub wire and a no-connect flag on the
                      root sheet that sit on nothing
  3. exclusions       one KiCad ERC exclusion per by-design warning:
                      pin_to_pin ('245 B side on counter Q), the alias
                      stubs (multiple_net_names), and the documentation
                      labels on unconsumed pins (isolated_pin_label),
                      except RESET_B and ~{IO_WR}, which the bus sheet
                      consumes and which stay visible until it does
  4. (nothing else)   rule severities and the pin matrix are untouched, so
                      every check that found something today still runs

Exclusion key format, found empirically against kicad-cli 10.0.4:

    type|x|y|main_uuid|aux_uuid|sheet|main_item_sheet|aux_item_sheet

x, y in schematic IU (the JSON report writes positions through the PCB
scale, so its numbers are IU / 1e6). Per kind:

    pin_to_pin           x,y = item 0; item sheets = the sheet each pin's
                         SYMBOL is on (the 16 cross-sheet pairs differ)
    multiple_net_names   x,y = item 1; item sheets = the marker's sheet
    isolated_pin_label   x,y = item 0; aux = the null uuid; item sheets
                         EMPTY
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from footprint_gen import sheets  # noqa: E402

KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
LIB = "dino"
LIB_FILE = "dino_v0_0_2.kicad_sym"
ORPHANS = {
    "74xx:74LS244N": "74LS244N",
    "Memory_EEPROM:AT28C64B": "AT28C64B",
    "Memory_EEPROM:AT28C256": "AT28C256",
    "Memory_RAM:MCM60256AP": "MCM60256AP",
}
EXCLUDE_KINDS = ("pin_to_pin", "multiple_net_names", "isolated_pin_label")
KEEP_VISIBLE = ("RESET_B", "~{IO_WR}")          # the bus sheet consumes these
STUB_WIRE_UUID = "9a8e0246-c382-4aee-a8c4-af23ec003b1f"


# --- 1. project library -------------------------------------------------------

def embedded_block(src, lib_id):
    """Text of `\\t\\t(symbol "<lib_id>" ...)` inside lib_symbols, or None."""
    head = f'\t\t(symbol "{lib_id}"\n'
    i = src.find(head)
    if i < 0:
        return None
    j = src.find('\n\t\t(symbol "', i + len(head))
    end_libs = src.find("\n\t)\n", i)
    j = end_libs if j < 0 or end_libs < j else j
    return src[i:j + 1]


def rehome_symbols(proj):
    """Move ORPHANS into <proj>/dino_v0_0_2.kicad_sym and repoint lib_ids."""
    blocks = {}
    for p in sheets(proj):
        with open(p) as f:
            src = f.read()
        for lib_id, name in ORPHANS.items():
            blk = embedded_block(src, lib_id)
            if blk and name not in blocks:
                blocks[name] = blk
    lib_path = os.path.join(proj, LIB_FILE)
    if blocks:
        body = ""
        for name, blk in sorted(blocks.items()):
            blk = blk.replace(f'(symbol "{next(k for k, v in ORPHANS.items() if v == name)}"',
                              f'(symbol "{name}"', 1)
            body += "\n".join(l[1:] if l.startswith("\t") else l
                              for l in blk.splitlines()) + "\n"
        with open(lib_path, "w") as f:
            f.write("(kicad_symbol_lib\n\t(version 20251024)\n"
                    '\t(generator "kicad_symbol_editor")\n'
                    '\t(generator_version "10.0")\n' + body + ")\n")
    changed = 0
    for p in sheets(proj):
        with open(p) as f:
            src = f.read()
        new = src
        for lib_id, name in ORPHANS.items():
            new = new.replace(f'(symbol "{lib_id}"', f'(symbol "{LIB}:{name}"')
            new = new.replace(f'(lib_id "{lib_id}")', f'(lib_id "{LIB}:{name}")')
        if new != src:
            changed += 1
            with open(p, "w") as f:
                f.write(new)
    table = os.path.join(proj, "sym-lib-table")
    with open(table) as f:
        t = f.read()
    if f'(name "{LIB}")' not in t:
        row = (f'\t(lib (name "{LIB}") (type "KiCad") '
               f'(uri "${{KIPRJMOD}}/{LIB_FILE}") (options "") (descr ""))\n')
        t = t.replace("\n)", "\n" + row + ")", 1) if t.rstrip().endswith(")") else t + row
        with open(table, "w") as f:
            f.write(t)
    return changed


# --- 2. the two cosmetic items ------------------------------------------------

_BLOCK = r"\t\({kind}\n(?:\t\t.*\n)*?\t\t\(uuid \"{uuid}\"\)\n\t\)\n"


def delete_by_uuid(path, kind, uuid):
    with open(path) as f:
        src = f.read()
    new, n = re.subn(_BLOCK.format(kind=kind, uuid=re.escape(uuid)), "", src)
    if n:
        with open(path, "w") as f:
            f.write(new)
    return n


def _erc(proj, extra=()):
    out = tempfile.mktemp(suffix=".json")
    subprocess.run([KICAD_CLI, "sch", "erc", "--format", "json", "-o", out,
                    os.path.join(proj, "dino_v0_0_2.kicad_sch"), *extra],
                   capture_output=True)
    with open(out) as f:
        rep = json.load(f)
    os.remove(out)
    return rep


def _count(rep, kind):
    return sum(1 for s in rep["sheets"] for v in s["violations"] if v["type"] == kind)


def delete_dangling_nc(proj):
    """KiCad reports a dangling no-connect under a uuid that is not in the
    file, so find it by elimination: drop each root-sheet NC on a copy and
    keep the one whose absence clears the warning."""
    root = os.path.join(proj, "dino_v0_0_2.kicad_sch")
    if _count(_erc(proj), "no_connect_dangling") == 0:
        return None
    with open(root) as f:
        src = f.read()
    uuids = re.findall(r"\t\(no_connect\n\t\t\(at [^\n]*\n\t\t\(uuid \"([^\"]+)\"\)", src)
    for u in uuids:
        tmp = tempfile.mkdtemp()
        try:
            for p in os.listdir(proj):
                s = os.path.join(proj, p)
                (shutil.copytree if os.path.isdir(s) else shutil.copy)(s, os.path.join(tmp, p))
            delete_by_uuid(os.path.join(tmp, "dino_v0_0_2.kicad_sch"), "no_connect", u)
            if _count(_erc(tmp), "no_connect_dangling") == 0:
                delete_by_uuid(root, "no_connect", u)
                return u
        finally:
            shutil.rmtree(tmp)
    raise RuntimeError("no single no-connect clears the warning")


# --- 3. exclusions ------------------------------------------------------------

NIL_UUID = "00000000-0000-0000-0000-000000000000"
_REF = re.compile(r"^Symbol (\S+) Pin ")


def key(kind, sheet_path, items, ref_sheet=None):
    """One exclusion key. `ref_sheet` maps a symbol reference to the uuid
    path of the sheet it sits on; needed for cross-sheet pin pairs."""
    ref_sheet = ref_sheet or {}

    def sheet_of(item):
        m = _REF.match(item["description"])
        return ref_sheet.get(m.group(1), sheet_path) if m else sheet_path

    if kind == "multiple_net_names":
        pos, main, aux = items[1]["pos"], items[0]["uuid"], items[1]["uuid"]
        p1 = p2 = sheet_path
    elif len(items) > 1:
        pos, main, aux = items[0]["pos"], items[0]["uuid"], items[1]["uuid"]
        p1, p2 = sheet_of(items[0]), sheet_of(items[1])
    else:
        pos, main, aux = items[0]["pos"], items[0]["uuid"], NIL_UUID
        p1 = p2 = ""
    x, y = int(round(pos["x"] * 1e6)), int(round(pos["y"] * 1e6))
    return f"{kind}|{x}|{y}|{main}|{aux}|{sheet_path}|{p1}|{p2}"


def ref_sheets(proj):
    """symbol reference -> uuid path of its sheet, off KiCad's netlist."""
    from pcb_gen import export_netlist, read_netlist
    net = os.path.join(tempfile.mkdtemp(), "x.net")
    comps, _ = read_netlist(export_netlist(proj, net))
    os.remove(net)
    with open(os.path.join(proj, "dino_v0_0_2.kicad_sch")) as f:
        root_uuid = re.search(r'\(uuid "([^"]+)"\)', f.read()).group(1)
    # the netlist writes "/" for the root and "/<sheet>/" below it; the ERC
    # report writes "/<root>" and "/<root>/<sheet>"
    out = {}
    for c in comps:
        sub = c.path.rsplit("/", 1)[0].strip("/")
        out[c.ref] = "/" + root_uuid + ("/" + sub if sub else "")
    return out


def label_sheets(proj):
    """label uuid -> uuid path of the sheet it is drawn on. The report files
    every isolated GLOBAL label under the root sheet; the marker KiCad
    matches against lives on the label's own sheet."""
    root_path = os.path.join(proj, "dino_v0_0_2.kicad_sch")
    with open(root_path) as f:
        root = f.read()
    root_uuid = re.search(r'\(uuid "([^"]+)"\)', root).group(1)
    file_sheet = {os.path.basename(root_path): "/" + root_uuid}
    for m in re.finditer(r'\t\(sheet\n(?:\t\t.*\n)*?\t\t\(uuid "([^"]+)"\)\n'
                         r'(?:\t\t.*\n)*?\t\t\(property "Sheetfile" "([^"]+)"', root):
        file_sheet[m.group(2)] = "/" + root_uuid + "/" + m.group(1)
    out = {}
    for p in sheets(proj):
        with open(p) as f:
            src = f.read()
        sp = file_sheet.get(os.path.basename(p))
        for m in re.finditer(r'\t\((?:global_)?label "[^"]*"\n(?:\t\t.*\n)*?\t\t\(uuid "([^"]+)"\)', src):
            out[m.group(1)] = sp
    return out


def exclusions(rep, ref_sheet=None, label_sheet=None):
    keys = []
    label_sheet = label_sheet or {}
    for s in rep["sheets"]:
        for v in s["violations"]:
            if v["type"] not in EXCLUDE_KINDS:
                continue
            if any(f"'{k}'" in i["description"] for i in v["items"] for k in KEEP_VISIBLE):
                continue
            sp = s["uuid_path"]
            if len(v["items"]) == 1:
                sp = label_sheet.get(v["items"][0]["uuid"], sp)
            keys.append(key(v["type"], sp, v["items"], ref_sheet))
    return keys


def write_exclusions(proj, keys):
    pro = os.path.join(proj, "dino_v0_0_2.kicad_pro")
    with open(pro) as f:
        d = json.load(f)
    d.setdefault("erc", {})["erc_exclusions"] = keys
    with open(pro, "w") as f:
        json.dump(d, f, indent=2)
        f.write("\n")


def append_report(proj, report_path):
    """Merge exclusion keys from a saved ERC report (the GUI's Save... in
    JSON, same schema as kicad-cli's) into the project. Returns how many
    were new. 2026-09-12: the GUI's ERC places a second marker on ten alias
    pairs where kicad-cli places one, on the sheet where the CW bit is
    consumed; those markers exist only in the GUI run."""
    with open(report_path) as f:
        rep = json.load(f)
    root = os.path.join(proj, "dino_v0_0_2.kicad_sch")
    have_sch = os.path.exists(root)
    keys = exclusions(rep,
                      ref_sheets(proj) if have_sch and os.path.exists(KICAD_CLI) else {},
                      label_sheets(proj) if have_sch else {})
    pro = os.path.join(proj, "dino_v0_0_2.kicad_pro")
    with open(pro) as f:
        d = json.load(f)
    have = d.setdefault("erc", {}).setdefault("erc_exclusions", [])
    new = [k for k in keys if k not in have]
    if new:
        have.extend(new)
        with open(pro, "w") as f:
            json.dump(d, f, indent=2)
            f.write("\n")
    return len(new)


# --- the pass -----------------------------------------------------------------

def run(proj):
    rehomed = rehome_symbols(proj)
    root = os.path.join(proj, "dino_v0_0_2.kicad_sch")
    wire = delete_by_uuid(root, "wire", STUB_WIRE_UUID)
    nc = delete_dangling_nc(proj)
    keys = exclusions(_erc(proj), ref_sheets(proj), label_sheets(proj))
    write_exclusions(proj, keys)
    return {"rehomed_sheets": rehomed, "stub_wire": wire, "no_connect": nc,
            "exclusions": len(keys)}


def main(argv):
    proj = os.path.join(HERE, "..", "..", "dino_v0_0_2")
    if "--append" in argv:
        print(f"{append_report(proj, argv[argv.index('--append') + 1])} exclusions added")
        return 0
    if "--write" not in argv:
        print(__doc__)
        return 2
    print(run(proj))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
