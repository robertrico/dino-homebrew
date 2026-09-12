#!/usr/bin/env python3
"""global_labels.py: make KiCad join the sheets the way the repo's tools
already do -- by label name.

2026-09-12. Every cross-sheet net in dino_v0_0_2 is a plain (sheet-local)
label repeated on each sheet. KiCad joins nothing between sheets that way,
so its netlist had 122 base names split into per-sheet fragments, ERC saw
90 inputs with no driver, and the PCB draft's ratsnest stopped at every
sheet boundary. The repo's `kicad_contracts.py` joins by name and was
right all along; this pass makes KiCad agree with it.

Two edits, both mechanical:
  * every label whose name appears on two or more sheets becomes a
    global label, same anchor, same name
  * the AT28C64B / AT28C256 symbols type their I/O pins `input`; the
    microcode ROMs DRIVE CW0-23, so those pins become `tri_state`

The proof is KiCad's own netlist after the edit: it must partition the
pins exactly as a name-join of its netlist BEFORE the edit does, once the
Control Word sheet's alias stubs (`CW12 END`, ...) are folded in.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import global_labels as gl  # noqa: E402
import footprint_gen as fg  # noqa: E402
import kicad_contracts as kc  # noqa: E402
from kicad_netlist import tokenize, parse, children, child  # noqa: E402

PROJ = os.path.join(HERE, "..", "..", "dino_v0_0_2")
KICAD_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
HAVE_KICAD = os.path.exists(KICAD_CLI)


def copy_project(dst):
    for f in fg.sheets(PROJ) + [os.path.join(PROJ, "dino_v0_0_2.kicad_pro"),
                                os.path.join(PROJ, "fp-lib-table"),
                                os.path.join(PROJ, "sym-lib-table")]:
        shutil.copy(f, dst)
    shutil.copytree(os.path.join(PROJ, "74F382PC"), os.path.join(dst, "74F382PC"))


def labels(path):
    with open(path) as f:
        tree = parse(tokenize(f.read()))
    out = {"label": [], "global_label": []}
    for kind in out:
        for l in children(tree, kind):
            at = child(l, "at")
            out[kind].append((l[1], float(at[1]), float(at[2])))
    return out


class TestNames(unittest.TestCase):
    def test_cross_sheet_names_are_the_ones_repeated_on_two_sheets(self):
        names = gl.cross_sheet_names(fg.sheets(PROJ))
        for n in ("CLK", "M15", "W0", "END", "HALT", "CW[0..23]", "~{IO_RD_Q}"):
            self.assertIn(n, names)
        for n in ("IS0", "SWITCH_EN", "MAR[15..0]", "SD0"):
            self.assertNotIn(n, names)

    def test_autosave_files_are_not_sheets(self):
        d = tempfile.mkdtemp()
        copy_project(d)
        open(os.path.join(d, "_autosave-dino_v0_0_2.kicad_sch"), "w").write("")
        self.assertEqual([f for f in fg.sheets(d) if "autosave" in f], [])
        shutil.rmtree(d)


class TestConvert(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        copy_project(self.tmp)
        self.before = {f: labels(f) for f in fg.sheets(self.tmp)}
        self.names = gl.cross_sheet_names(fg.sheets(self.tmp))
        gl.convert(self.tmp)
        self.after = {f: labels(f) for f in fg.sheets(self.tmp)}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_every_cross_sheet_label_is_global_at_the_same_anchor(self):
        # holds whether the project on disk is converted already or not
        for f in self.before:
            want = sorted([l for l in self.before[f]["label"] if l[0] in self.names]
                          + self.before[f]["global_label"])
            got = sorted(self.after[f]["global_label"])
            self.assertEqual(got, want, f)
        self.assertGreater(sum(len(v["global_label"]) for v in self.after.values()), 600)

    def test_sheet_local_labels_are_untouched(self):
        for f in self.before:
            want = sorted(l for l in self.before[f]["label"] if l[0] not in self.names)
            self.assertEqual(sorted(self.after[f]["label"]), want, f)

    def test_convert_is_idempotent(self):
        snap = {f: open(f).read() for f in fg.sheets(self.tmp)}
        gl.convert(self.tmp)
        self.assertEqual({f: open(f).read() for f in fg.sheets(self.tmp)}, snap)

    def test_rom_io_pins_drive(self):
        for sheet, sym in (("microcode.kicad_sch", "Memory_EEPROM:AT28C64B"),
                           ("memory.kicad_sch", "Memory_EEPROM:AT28C256")):
            with open(os.path.join(self.tmp, sheet)) as f:
                tree = parse(tokenize(f.read()))
            for s in children(child(tree, "lib_symbols"), "symbol"):
                if s[1] != sym:
                    continue
                types = {child(p, "name")[1]: p[1]
                         for sub in children(s, "symbol") for p in children(sub, "pin")
                         if child(p, "name")[1].startswith("I/O")}
                self.assertEqual(set(types.values()), {"tri_state"}, (sym, types))


def _nets(path):
    with open(path) as f:
        tree = parse(tokenize(f.read()))
    out = {}
    for n in children(child(tree, "nets"), "net"):
        out[child(n, "name")[1]] = {(child(x, "ref")[1], child(x, "pin")[1])
                                    for x in children(n, "node")}
    return out


def _base(name):
    return name.rsplit("/", 1)[-1] if name.startswith("/") else name


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


@unittest.skipUnless(HAVE_KICAD, "KiCad 10 not installed")
class TestKiCadAgrees(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        copy_project(cls.tmp)
        sch = os.path.join(cls.tmp, "dino_v0_0_2.kicad_sch")
        cls.pre = os.path.join(cls.tmp, "pre.net")
        subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format",
                        "kicadsexpr", "-o", cls.pre, sch], check=True,
                       capture_output=True)
        cls.aliases = gl.alias_pairs(os.path.join(cls.tmp, "control_word.kicad_sch"))
        gl.convert(cls.tmp)
        cls.post = os.path.join(cls.tmp, "post.net")
        subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format",
                        "kicadsexpr", "-o", cls.post, sch], check=True,
                       capture_output=True)
        cls.erc = os.path.join(cls.tmp, "erc.json")
        subprocess.run([KICAD_CLI, "sch", "erc", "--format", "json", "-o",
                        cls.erc, sch], capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_kicad_contracts_reads_the_same_contracts_off_global_labels(self):
        # 2026-09-12: build_contracts took each node's sheet from the net
        # NAME's /Sheet/ prefix. Global nets have none, so every node fell on
        # the root, nothing crossed, and dino_sheet_contracts.md came out
        # empty. The landing lists (--continuity, --since) are built on this.
        # The committed contracts doc was rendered from the local-label
        # schematic; the same doc must come back off the global-label one.
        after = kc.build_contracts(os.path.join(self.tmp, "dino_v0_0_2.kicad_sch"))
        with open(os.path.join(HERE, "dino_sheet_contracts.md")) as f:
            committed = f.read().rstrip("\n")
        self.assertEqual(kc.render(after).rstrip("\n"), committed)

    def test_alias_pairs_read_off_the_control_word_sheet(self):
        self.assertIn(("CW12", "END"), self.aliases)
        self.assertIn(("CW15", "HALT"), self.aliases)
        self.assertIn(("CW9", "SA2"), self.aliases)
        self.assertIn(("CW17", "~{SRC_BANK}"), self.aliases)
        self.assertEqual(len(self.aliases), 15)

    def test_kicad_partitions_pins_exactly_as_a_name_join_of_its_old_netlist(self):
        pre, post = _nets(self.pre), _nets(self.post)
        uf = _UF()
        for name, pins in pre.items():
            key = _base(name)
            for p in pins:
                uf.union(("pin",) + p, ("net", key))
        for a, b in self.aliases:
            uf.union(("net", a), ("net", b))
        want = {}
        for name, pins in pre.items():
            for p in pins:
                want.setdefault(uf.find(("pin",) + p), set()).add(p)
        want = {frozenset(v) for v in want.values()}
        got = {frozenset(v) for v in post.values()}
        self.assertEqual({p for s in got for p in s}, {p for s in want for p in s})
        self.assertEqual(sorted(map(sorted, got - want)), [])
        self.assertEqual(sorted(map(sorted, want - got)), [])

    def test_no_net_is_split_by_sheet_any_more(self):
        post = _nets(self.post)
        split = {}
        for name in post:
            if name.startswith("/") and not name.startswith("/unconnected"):
                split.setdefault(_base(name), []).append(name)
        self.assertEqual({k: v for k, v in split.items() if len(v) > 1}, {})

    def test_erc_has_no_undriven_inputs_and_no_floating_labels(self):
        with open(self.erc) as f:
            rep = json.load(f)
        bad = [(s["path"], v["type"], [i["description"] for i in v["items"]])
               for s in rep["sheets"] for v in s["violations"]
               if v["type"] in ("pin_not_driven", "label_dangling")]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
