import os
import re

import pytest

import fpga_gen

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", "dino_v0_0_2", "dino_v0_0_2.kicad_sch"))
GEN_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "..", "fpga", "gen"))

def test_normalize_type_folds_families():
    assert fpga_gen.normalize_type("74xx:7400", "74LS00") == "74LS00"
    assert fpga_gen.normalize_type("74xx:74LS244N", "74LS244") == "74LS244"
    # the alu sheet contains BOTH value variants of the '382 — fold both
    assert fpga_gen.normalize_type("2026-07-13_03-50-17:74F382PC", "74F382PC") == "74F382"
    assert fpga_gen.normalize_type("2026-07-13_03-50-17:74F382PC", "74F382N") == "74F382"

def test_gate_pinmaps_complete():
    # every pin mapped exactly once per part's real pin count; power pins
    # named vcc/gnd. The five plain gates share the DIP-14 gnd@7/vcc@14
    # layout; the four MSI types (Task 3) use their own DIP-16/DIP-20
    # power-pin positions (all netlist-derived, see PIN_MAP comments).
    specs = {
        "74LS00": (14, 7, 14), "74LS02": (14, 7, 14), "74LS04": (14, 7, 14),
        "74HC14": (14, 7, 14), "74LS08": (14, 7, 14),
        "74LS138": (16, 8, 16), "74LS157": (16, 8, 16),
        "74LS244": (20, 10, 20), "74LS245": (20, 10, 20),
        "74F382": (20, 10, 20),
        "74LS74": (14, 7, 14), "74LS163": (16, 8, 16),
        "74LS193": (16, 8, 16), "74LS273": (20, 10, 20),
        "74LS373": (20, 10, 20),
        "AT28C64B": (28, 14, 28), "AT28C256": (28, 14, 28),
        "MCM60256AP": (28, 14, 28),
    }
    for t, (n, gnd_pin, vcc_pin) in specs.items():
        pm = fpga_gen.PIN_MAP[t]
        assert set(pm.keys()) == set(range(1, n + 1)), f"{t}: pins {sorted(pm)} not 1..{n}"
        assert pm[gnd_pin] == "gnd" and pm[vcc_pin] == "vcc", f"{t}: power pins misnamed"

def test_vhdl_entities_match_pinmap():
    # parse each ttl/*.vhd entity port list; must equal PIN_MAP names minus vcc/gnd
    # (plus "clk_sys" for CLK_SYS_TYPES members -- the hidden fabric clock
    # every clk_sys-sampling model reads against, per task-5-brief.md /
    # synth-rework-brief.md item 2; it has no netlist pin and so no
    # PIN_MAP entry). PIN_MAP itself keeps the real (undecorated) datasheet
    # pin name as the stem (synth-rework-brief.md item 1) -- a pin that
    # is genuinely bidirectional at the VHDL level (ttl_74ls245's a/b,
    # ttl_mcm60256's dq) is no longer declared `inout`; it's split into a
    # `<stem>_i : in` + `<stem>_o : out` pair instead (ghdl-yosys-plugin
    # silently severs internal nets touching a sub-instance `inout` port
    # at synthesis import), so this check accepts EITHER the plain stem OR
    # its exact `_i`/`_o` pair, whichever the model actually declares.
    import re, pathlib
    for t, fname in [("74LS00","ttl_74ls00.vhd"), ("74LS02","ttl_74ls02.vhd"),
                     ("74LS04","ttl_74ls04.vhd"), ("74HC14","ttl_74hc14.vhd"),
                     ("74LS08","ttl_74ls08.vhd"), ("74LS138","ttl_74ls138.vhd"),
                     ("74LS157","ttl_74ls157.vhd"), ("74LS244","ttl_74ls244.vhd"),
                     ("74LS245","ttl_74ls245.vhd"), ("74F382","ttl_74f382.vhd"),
                     ("74LS74","ttl_74ls74.vhd"), ("74LS163","ttl_74ls163.vhd"),
                     ("74LS193","ttl_74ls193.vhd"), ("74LS273","ttl_74ls273.vhd"),
                     ("74LS373","ttl_74ls373.vhd"),
                     ("AT28C64B","ttl_at28c64b.vhd"), ("AT28C256","ttl_at28c256.vhd"),
                     ("MCM60256AP","ttl_mcm60256.vhd")]:
        src = (pathlib.Path(__file__).parents[2] / "fpga/ttl" / fname).read_text()
        # Scope the port scan to the entity's own "port (...)" clause, not
        # the whole file -- '382 (Task 4) is the first model with a local
        # procedure inside the architecture body whose parameter list also
        # has "name : out ..." tokens (e.g. "f_v : out unsigned(...)"); a
        # whole-file scan would false-positive-match those as entity ports.
        # Task 6's memory models add a "generic (init_file : string;
        # addr_bits : positive)" clause ABOVE the port clause -- confirmed
        # the regex still only matches the "port (...)" text (generics use
        # a different keyword, "generic", so they're never captured here)
        # and that init_file's ": string" doesn't false-positive as a port
        # (it isn't inside the port(...) capture group at all).
        entity_block = re.search(r"\bport\s*\((.*?)\)\s*;\s*end\s+entity",
                                  src, re.S)
        assert entity_block, f"{t}: no \"port (...); end entity\" found in {fname}"
        ports = set(re.findall(r"^\s*(\w+)\s*:\s*(?:in|out|inout)\b",
                                entity_block.group(1), re.M))
        assert "inout" not in re.findall(r":\s*(inout)\b", entity_block.group(1)), \
            f"{t}: {fname} still declares a literal inout port"
        # "nc" (Task 6: AT28C64B pins 1/26, physically unconnected on the
        # 8K part) gets no port, same as vcc/gnd -- a pin with nothing to
        # wire needs nothing to declare.
        want = {n for p, n in fpga_gen.PIN_MAP[t].items() if n not in ("vcc", "gnd", "nc")}
        if t in fpga_gen.CLK_SYS_TYPES:
            want = want | {"clk_sys"}
        want_expanded = set()
        for n in want:
            if n in ports:
                want_expanded.add(n)
                continue
            assert f"{n}_i" in ports and f"{n}_o" in ports, (
                f"{t}: PIN_MAP pin {n!r} is neither a plain port nor a "
                f"split _i/_o pair in {fname} (got {sorted(ports)})")
            want_expanded.add(f"{n}_i")
            want_expanded.add(f"{n}_o")
        assert ports == want_expanded, f"{t}: VHDL ports {ports} != PIN_MAP-derived {want_expanded}"

def test_bin2hex_roundtrip(tmp_path):
    # Round-trip through bin2hex(): every byte 0x00-0xff (both endpoints,
    # not just "typical" mid-range values -- 0x00 and 0xff are exactly the
    # values a naive off-by-one in the %02x formatting would mangle) twice
    # over, to also confirm line order is preserved (a byte-reversal bug
    # would still pass a single 0..255 pass since it's a palindrome-free
    # sequence forwards or backwards only at the boundary).
    src = tmp_path / "sample.bin"
    payload = bytes(range(256)) + bytes(reversed(range(256)))
    src.write_bytes(payload)
    dst = tmp_path / "sample.hex"

    n = fpga_gen.bin2hex(str(src), str(dst))
    assert n == 512, f"bin2hex returned {n}, want 512 (byte count)"

    lines = dst.read_text().splitlines()
    assert len(lines) == 512, f"{len(lines)} lines written, want one per byte (512)"
    for i, line in enumerate(lines):
        assert line == f"{payload[i]:02x}", (
            f"line {i}: {line!r}, want lowercase two-digit hex {payload[i]:02x}"
        )

    # Round trip: reparse the hex text back into bytes and compare against
    # the exact source bytes, in the SAME order they were written (mirror-
    # witness rule doesn't strictly apply to a pure format-conversion
    # round-trip, but re-deriving bytes from the hex text independently of
    # bin2hex's own byte-iteration is still the honest check here).
    recovered = bytes(int(l, 16) for l in lines)
    assert recovered == payload, "round-trip through bin2hex()'s hex text did not reproduce the source bytes"

def test_stateful_types_membership():
    # task-5-brief.md line 8: the exact five-part-plus-RAM set Task 8's
    # emitter threads clk_sys to. '74LS169' joined 2026-08-10 -- the stack
    # pointer's counter, U63-U66, which samples CP through the same clk_sys
    # edge-detect every other member uses.
    assert fpga_gen.STATEFUL_TYPES == {
        "74LS74", "74LS163", "74LS169", "74LS193", "74LS273", "74LS373",
        "MCM60256AP",
    }

def test_load_design_groups_units_and_assigns_sheets():
    d = fpga_gen.load_design(ROOT)
    u1 = d.instances["U1"]                      # PC counter, program_counter sheet
    assert u1.type == "74LS193"
    assert u1.sheet == "program_counter"
    assert u1.pins[4] == "+5V"                  # DOWN clock strapped high (verified)
    # a multi-unit gate chip appears ONCE with all 14 pins merged
    gates = [i for i in d.instances.values() if i.type == "74LS02"]
    assert gates, "no 74LS02 instances found -- part-type normalization or grouping broke"
    assert all(set(g.pins) <= set(range(1, 15)) and len(g.pins) >= 12 for g in gates), \
        "a 74LS02 instance is missing unit pins - units not merged by reference"

def test_every_chip_on_exactly_one_sheet():
    d = fpga_gen.load_design(ROOT)
    assert d.instances, "load_design returned no instances"
    for ref, inst in d.instances.items():
        assert inst.sheet in fpga_gen.SHEETS, f"{ref} landed on unknown sheet {inst.sheet!r}"

def test_sheets_constant_has_eleven_entries():
    # The root schematic plus the ten sub-sheets it owns (dino_v0_0_2/
    # *.kicad_sch, one per module). Was nine sub-sheets until 2026-08-10,
    # when stack_pointer.kicad_sch landed.
    assert len(fpga_gen.SHEETS) == 11
    assert len(set(fpga_gen.SHEETS)) == 11, "SHEETS has a duplicate token"
    assert "stack_pointer" in fpga_gen.SHEETS

def test_every_sheet_has_at_least_one_instance():
    # a sheet with zero instances would mean load_design silently dropped a
    # whole board's worth of chips instead of erroring.
    d = fpga_gen.load_design(ROOT)
    seen = {inst.sheet for inst in d.instances.values()}
    assert seen == set(fpga_gen.SHEETS), \
        f"sheets with no instances: {set(fpga_gen.SHEETS) - seen}"

def test_sheet_ports_shape():
    # Design.sheet_ports: dict[sheet, list[PortSig]] -- every sheet that has
    # boundary signals at all keys into a known sheet token, and every entry
    # is a real (name, direction, width) triple a VHDL port clause can use.
    d = fpga_gen.load_design(ROOT)
    assert d.sheet_ports, "load_design returned no sheet_ports"
    for sheet, ports in d.sheet_ports.items():
        assert sheet in fpga_gen.SHEETS, f"sheet_ports has unknown sheet {sheet!r}"
        assert ports, f"sheet_ports[{sheet!r}] is empty -- every real module has a boundary"
        for p in ports:
            assert p.direction in ("in", "out", "inout"), \
                f"{sheet}/{p.name}: bad direction {p.direction!r}"
            assert p.width >= 1, f"{sheet}/{p.name}: width {p.width} < 1"
    # program_counter drives QA-QD (its count) onto the shared bus and
    # consumes CLR/LOAD/UP/DOWN -- known contract facts (dino_sheet_contracts
    # .md), so this sheet must show both directions represented.
    pc_dirs = {p.direction for p in d.sheet_ports["program_counter"]}
    assert "out" in pc_dirs and "in" in pc_dirs

def test_sa_field_composite_labels_keep_their_bit_number():
    # CW9=SA2/CW10=SA1/CW11=SA0 are build_contracts's cross-sheet alias
    # labels for the SA field (microcode ROM's SA bits, routed straight to
    # the ALU bypassing control_word's own decode -- this is the exact
    # signal family that bit the bench once already: the SA field was
    # packed bit-reversed and every ADD silently ran as AND, see
    # CLAUDE.md's "What is proven" section). A naive bus-grouping regex
    # applied uniformly would strip the trailing SA-bit digit (0/1/2) as if
    # it were a bus index, collapsing all three into indistinguishable
    # width-1 ports named "CW9=SA"/"CW10=SA"/"CW11=SA" with the bit number
    # gone -- silently correct here only because no OTHER label happens to
    # collide post-truncation. Pin the exact verbatim names so a future
    # "helpfully" generalized bus-grouping regex can't reintroduce that.
    d = fpga_gen.load_design(ROOT)
    names = {p.name for p in d.sheet_ports["alu"]}
    for want in ("CW9=SA2", "CW10=SA1", "CW11=SA0"):
        assert want in names, (
            f"{want} missing verbatim from alu sheet_ports (got {sorted(names)}) "
            f"-- composite alias label got bus-grouped and its bit digit stripped"
        )
    # and each is its own width-1 port, not merged with anything else
    by_name = {p.name: p for p in d.sheet_ports["alu"]}
    for want in ("CW9=SA2", "CW10=SA1", "CW11=SA0"):
        assert by_name[want].width == 1, f"{want}: width {by_name[want].width} != 1"


# --- Task 8: emitter ---------------------------------------------------

def _ref_label(ref):
    # Every ref except SWITCH-GATE1 (input_output) is already a legal VHDL
    # label (UxxNN); the one exception goes through the same net-name
    # sanitizer the emitter itself uses for its instance label, since a
    # literal '-' is not legal in a VHDL identifier. Netlist-verified
    # (rule 5) this is the ONLY offending ref in the whole 154-component
    # design -- see test_only_switch_gate1_needs_ref_sanitizing below.
    return ref if re.match(r"^[A-Za-z]\w*$", ref) else fpga_gen._sanitize_name(ref)


def test_only_switch_gate1_needs_ref_sanitizing():
    d = fpga_gen.load_design(ROOT)
    bad = [ref for ref in d.instances if not re.match(r"^[A-Za-z]\w*$", ref)]
    assert bad == ["SWITCH-GATE1"], (
        f"expected exactly one non-VHDL-legal ref (SWITCH-GATE1), got {bad}")


def test_type_alias_7400_folds_to_74ls00():
    # Task 7's report flagged U36/U51 (Value "7400", no PIN_MAP entry) --
    # netlist-verified (rule 5) same DIP-14 quad-NAND pinout as 74LS00.
    assert fpga_gen.normalize_type("74xx:7400", "7400") == "74LS00"
    d = fpga_gen.load_design(ROOT)
    assert d.instances["U36"].type == "74LS00"
    assert d.instances["U51"].type == "74LS00"


def test_emit_every_chip_once_every_net_somewhere(tmp_path):
    fpga_gen.emit(ROOT, tmp_path)
    src = "".join(p.read_text() for p in tmp_path.glob("*.vhd"))
    d = fpga_gen.load_design(ROOT)
    for ref, inst in d.instances.items():
        if inst.type in fpga_gen.EXCLUDED_TYPES:
            continue
        label = _ref_label(ref)
        n = len(re.findall(rf"\b{re.escape(label)}\s*:\s*entity work\.ttl_", src))
        assert n == 1, f"{ref} (label {label!r}) instantiated {n} times"


def test_clk_sys_threaded_to_every_stateful_instance(tmp_path):
    fpga_gen.emit(ROOT, tmp_path)
    texts = {p.name: p.read_text() for p in tmp_path.glob("*.vhd")}
    # every generated file declares clk_sys
    for fname, text in texts.items():
        assert re.search(r"\bclk_sys\s*:\s*in\s+std_logic", text), \
            f"{fname}: no clk_sys port declared"
    src = "".join(texts.values())
    d = fpga_gen.load_design(ROOT)
    for ref, inst in d.instances.items():
        if inst.type not in fpga_gen.STATEFUL_TYPES:
            continue
        label = _ref_label(ref)
        m = re.search(
            rf"\b{re.escape(label)}\s*:\s*entity work\.ttl_\w+.*?port map \((.*?)\);",
            src, re.S)
        assert m, f"{ref}: instantiation not found"
        assert "clk_sys => clk_sys" in m.group(1), \
            f"{ref} ({inst.type}): clk_sys not threaded into its port map"


def test_no_hand_edit_marker(tmp_path):
    fpga_gen.emit(ROOT, tmp_path)
    files = sorted(tmp_path.glob("*.vhd"))
    assert len(files) == 11, f"expected 10 sheet entities + dino_core.vhd, got {len(files)}"
    for p in files:
        first_line = p.read_text().splitlines()[0]
        assert first_line == "-- GENERATED by fpga_gen.py - DO NOT EDIT", \
            f"{p.name}: missing/wrong DO-NOT-EDIT marker: {first_line!r}"


def test_boundary_table_covers_all_excluded_refs():
    # Every excluded component's every pin is either a power tie (GND/+5V),
    # claimed by BOUNDARY_INPUTS/INPUT_OUTPUT_EXTRA_PORT, shared with a
    # real (non-excluded) instance elsewhere in the design (so the net
    # survives on its own), or one of the 16 known-dead LED-anode pins
    # (Net-(D1-A)..Net-(D8-A), each touched by both the dropped 330R
    # limiter AND the dropped LED itself, netlist-verified (rule 5) to
    # have NO other consumer -- see task-8-report.md). Anything else is a
    # hard failure naming the exact ref.pin, so a future schematic edit
    # that orphans a NEW net can't silently slip through unreviewed.
    known_dead = {f"Net-(D{n}-A)" for n in range(1, 9)}
    d = fpga_gen.load_design(ROOT)
    boundary_claimed = set()
    for _name, _width, locs in fpga_gen.BOUNDARY_INPUTS:
        boundary_claimed.update(locs)
    boundary_claimed.update(fpga_gen.INPUT_OUTPUT_EXTRA_PORT[3])
    non_excluded_nets = set()
    for inst in d.instances.values():
        if inst.type not in fpga_gen.EXCLUDED_TYPES:
            non_excluded_nets.update(inst.pins.values())
    unaccounted = []
    for ref, inst in d.instances.items():
        if inst.type not in fpga_gen.EXCLUDED_TYPES:
            continue
        for pin, net in inst.pins.items():
            if net in ("GND", "+5V"):
                continue
            if net in boundary_claimed or net in non_excluded_nets:
                continue
            if net in known_dead:
                continue
            unaccounted.append(f"{ref}.{pin} (net {net!r})")
    assert not unaccounted, "unaccounted excluded-component pins: " + ", ".join(unaccounted)


def test_nc_allowed_covers_every_unconnected_model_input():
    # An unconnected model INPUT with no NC_ALLOWED tie is a hard error at
    # emit() time -- prove emit() actually succeeds (it would raise
    # ValueError otherwise) AND that NC_ALLOWED has no stale/unused entries
    # left over from a schematic that's since been rewired.
    d = fpga_gen.load_design(ROOT)
    used = set()
    for ref, inst in d.instances.items():
        if inst.type in fpga_gen.EXCLUDED_TYPES:
            continue
        dirs = fpga_gen._ttl_port_dirs(inst.type)
        pin_map = fpga_gen.PIN_MAP[inst.type]
        for pin, net in inst.pins.items():
            if not net.startswith("unconnected-"):
                continue
            pin_name = pin_map.get(pin)
            if pin_name is None or pin_name in ("vcc", "gnd", "nc"):
                continue
            if dirs.get(pin_name) == "out":
                continue  # unconnected OUTPUT -- fine as `open`, no tie needed
            used.add((ref, pin))
    assert used == set(fpga_gen.NC_ALLOWED), (
        f"NC_ALLOWED out of sync with the real unconnected-input set: "
        f"missing={used - set(fpga_gen.NC_ALLOWED)} "
        f"stale={set(fpga_gen.NC_ALLOWED) - used}")


def test_emit_raises_loudly_on_unconnected_input_with_no_tie(tmp_path, monkeypatch):
    monkeypatch.setattr(fpga_gen, "NC_ALLOWED", {})
    with pytest.raises(ValueError, match="unconnected"):
        fpga_gen.emit(ROOT, tmp_path)


def test_ports_shared_through_a_real_inout_pin_are_inout(tmp_path):
    # Review finding: build_contracts's OWN IN/OUT/BIDIR classification is
    # blind to a sheet that reads a bus back through one of its OWN '245s
    # in the opposite direction from where ANOTHER of its own '245s drives
    # it (KiCad draws every '245 pin "tri_state" regardless of DIR, so
    # build_contracts's has_in check never sees it as a reader). The real
    # ttl_74ls245.vhd/ttl_mcm60256.vhd models declare those pins bidirectional
    # (split `_i`/`_o` pairs since the Task-13 rework, item 1 -- ghdl-yosys-
    # plugin severs internal nets touching a sub-instance `inout` port at
    # synthesis import) -- that is ground truth. Five real cases in this
    # design (the JMP/JNZ path through program_counter's own M bus and the
    # M15=ROM_EN tap, the STA/LDA path through memory's and registers_a_b's
    # own MDR, and mar's own M -- its '245s are wired dir-tied-always-A->B
    # in practice, but the MODEL pin is still bidirectional, so the entity
    # port must be split too for the same association-legality reason).
    fpga_gen.emit(ROOT, tmp_path)
    expect_split = {
        "program_counter.vhd": ["m", "m15_eq_rom_en"],
        "memory.vhd": ["mdr"],
        "registers_a_b.vhd": ["mdr"],
        "mar.vhd": ["m", "m15_eq_rom_en"],
    }
    for fname, ports in expect_split.items():
        text = (tmp_path / fname).read_text()
        assert not re.search(r"\binout\b", text), \
            f"{fname}: no port should be declared inout any more"
        for port in ports:
            assert re.search(rf"\b{port}_i\s*:\s*in\b", text), \
                f"{fname}: expected port {port}_i to be in"
            assert re.search(rf"\b{port}_o\s*:\s*out\b", text), \
                f"{fname}: expected port {port}_o to be out"


def test_flag_z_stays_out_not_over_flagged_inout(tmp_path):
    # Regression guard for the FIRST (over-broad) version of the inout fix:
    # alu's FLAG_Z is driven once by a plain `out` register pin (U49 q1)
    # and merely READ locally by a plain `in` mux-select pin (U48 i1b) --
    # a normal single-driver fanout, legally `out` under VHDL-2008 (which
    # lifted the VHDL-93 restriction on reading a mode-out port from
    # within its own architecture). No `inout`-mode model pin is involved,
    # so this must NOT flip -- if it does, the detection rule regressed to
    # "any local read" instead of "a genuinely bidirectional model pin".
    fpga_gen.emit(ROOT, tmp_path)
    text = (tmp_path / "alu.vhd").read_text()
    assert re.search(r"\bflag_z\s*:\s*out\b", text), \
        "alu.vhd: flag_z should stay `out` (single real driver, VHDL-2008 " \
        "permits the local internal read) -- got something else"
    assert not re.search(r"\bflag_z\s*:\s*inout\b", text)


def test_sanitizer_rules():
    s = fpga_gen._sanitize_name
    assert s("~{RESET}") == "n_reset"
    assert s("CW9=SA2") == "cw9_eq_sa2"
    assert s("Net-(D1-A)") == "net_d1_a"
    assert s("3STATE") == "n_3state"


def test_sanitizer_collision_fails_loudly():
    scope = fpga_gen._Scope()
    scope.name("~{FOO}")
    with pytest.raises(ValueError, match="collision"):
        # "FOO" alone and "~{FOO}" both sanitize differently in general,
        # but two genuinely different raw names that DO collide must raise
        # -- construct one directly: "A=B" and "A_eq_B" both sanitize to
        # "a_eq_b".
        scope.name("A=B")
        scope.name("A_eq_B")


def test_gated_clocks_txt_nonempty_and_nets_exist(tmp_path):
    fpga_gen.emit(ROOT, tmp_path)
    lines = (tmp_path / "gated_clocks.txt").read_text().splitlines()
    assert lines, "gated_clocks.txt is empty"
    src = "".join(p.read_text() for p in tmp_path.glob("*.vhd"))
    for net in lines:
        assert net, "blank line in gated_clocks.txt"
        assert re.search(rf"\b{re.escape(net)}\b", src), \
            f"gated_clocks.txt lists {net!r}, not found as an identifier in generated VHDL"
    # "clk" (the sanitized machine clock net "CLK") must never appear --
    # gated_clocks.txt is specifically the DERIVED/gated signals, not the
    # reference clock itself. "n_clk" (the DIFFERENT net "~{CLK}") is a
    # real, expected entry and must NOT be excluded by this check.
    assert "clk" not in lines


def test_memory_instances_get_generic_maps(tmp_path):
    fpga_gen.emit(ROOT, tmp_path)
    microcode = (tmp_path / "microcode.vhd").read_text()
    memory = (tmp_path / "memory.vhd").read_text()
    core = (tmp_path / "dino_core.vhd").read_text()
    for text, refs in ((microcode, ("u9", "u15")), (memory, ("u24", "u26"))):
        for ref in refs:
            assert f"{ref}_init_file : string" in text, f"{ref}_init_file generic missing"
            assert f"{ref}_addr_bits : positive" in text, f"{ref}_addr_bits generic missing"
    for ref in ("u9", "u15", "u24", "u26"):
        assert f"{ref}_init_file : string" in core
        assert f"{ref}_addr_bits : positive" in core


def test_dino_core_boundary_ports(tmp_path):
    fpga_gen.emit(ROOT, tmp_path)
    text = (tmp_path / "dino_core.vhd").read_text()
    for port, direction, width in (
            ("clk_sys", "in", 1), ("clk4m_y1", "in", 1),
            ("dip_sw", "in", 8), ("btn_reset_n", "in", 1),
            ("ob_led", "out", 8), ("halt", "out", 1)):
        if width == 1:
            pat = rf"\b{port}\s*:\s*{direction}\s+std_logic\b"
        else:
            pat = rf"\b{port}\s*:\s*{direction}\s+std_logic_vector\({width - 1} downto 0\)"
        assert re.search(pat, text), f"dino_core: port {port} ({direction}, width {width}) not found"


def test_mar_golden_file(tmp_path):
    # Runs the REAL emit() into a fresh tmp_path and compares the freshly
    # generated mar.vhd against the eye-reviewed golden -- catches a
    # regression in the generator itself, not just drift of the checked-in
    # copy (a prior version of this test compared fpga/gen/mar.vhd against
    # fpga/gen/mar.vhd.golden directly, which never ran emit() at all and
    # so could not fail even if emit() were broken, only if someone hand-
    # edited the committed file).
    fpga_gen.emit(ROOT, tmp_path)
    golden_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "..", "fpga", "gen", "mar.vhd.golden")
    with open(golden_path) as f:
        golden = f.read()
    actual = (tmp_path / "mar.vhd").read_text()
    assert actual == golden, (
        "emit()'s mar.vhd no longer matches the eye-reviewed golden "
        "(fpga/gen/mar.vhd.golden) -- regenerate + re-review + update the "
        "golden if the change is intentional")


def test_committed_gen_matches_emit_output_no_drift(tmp_path):
    # Guards fpga/gen/*.vhd (the committed artifacts-of-record) against
    # silently drifting out of sync with what fpga_gen.py's emit() ACTUALLY
    # produces today -- e.g. a hand-edit of a committed file, or a
    # generator change that was tested via a tmp_path run but never used to
    # regenerate fpga/gen/ itself. Every generated file, byte for byte.
    # ALL emitted files, not just *.vhd -- emit() also writes
    # fpga/gen/gated_clocks.txt (the invariant monitor's own source of
    # identifiers, per that function's own docstring), and a glob that
    # only matched *.vhd would let it drift silently, the exact class of
    # bug this test exists to catch.
    fpga_gen.emit(ROOT, tmp_path)
    fresh = sorted(p.name for p in tmp_path.iterdir() if p.is_file())
    committed = sorted(p.name for p in os.scandir(GEN_DIR)
                        if p.is_file() and p.name.endswith((".vhd", ".txt")))
    assert fresh == committed, f"file set mismatch: fresh={fresh} committed={committed}"
    mismatched = []
    for name in fresh:
        fresh_text = (tmp_path / name).read_text()
        committed_text = open(os.path.join(GEN_DIR, name)).read()
        if fresh_text != committed_text:
            mismatched.append(name)
    assert not mismatched, (
        f"fpga/gen/ has drifted from emit()'s current output for: "
        f"{mismatched} -- regenerate and recommit fpga/gen/")


def test_missing_pin_map_entry_is_a_hard_failure(tmp_path, monkeypatch):
    # Final-review fix: a netlist pin with no PIN_MAP entry used to
    # `continue` past silently (a dropped pin is a dropped net, and the
    # generated VHDL would just be missing a wire with no error anywhere).
    # "A missing mapping is a hard failure, not a warning" -- delete one
    # real PIN_MAP entry (74LS00, pin 1 -- used throughout the design) and
    # confirm emit() raises, naming the offending pin, instead of quietly
    # continuing to produce output.
    pm = dict(fpga_gen.PIN_MAP["74LS00"])
    del pm[1]
    monkeypatch.setitem(fpga_gen.PIN_MAP, "74LS00", pm)
    with pytest.raises(ValueError, match=r"74LS00.*pin.*1"):
        fpga_gen.emit(ROOT, tmp_path)
