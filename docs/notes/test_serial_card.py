#!/usr/bin/env python3
"""Phase G, step 1 -- the PAPER WITNESS for the serial card schematic.
Run: python3 test_serial_card.py            (checks dino_serial/dino_serial.kicad_sch)
     DINO_SERIAL_SCH=<path> python3 test_serial_card.py   (check another file)

Every assertion here is `.git/sdd/PHASE_G.md` SECTION 1, line for line,
netlist-extracted from the card project by kicad_netlist.build_report.
Nothing is read off the drawing by eye -- CLAUDE.md rule 4.

Pin numbers are the PC16550D datasheet's (section 7.0 connection diagram),
which is also what KiCad's Interface_UART:16550 symbol carries. The traps
the spec names are each a separate test so a failure names the wire:

    A0 is pin 28 and A2 is pin 26 -- the register selects run DESCENDING.
    ~RD is pin 21, RD (active-high dual) is pin 22 and is tied LOW.
    ~WR is pin 18, WR (active-high dual) is pin 19 and is tied LOW.
    DIR comes from DDIS (pin 23), card-internal. NOT from ~{IO_RD_Q}.
    O0 of the '138 is card zero's. It must not be landed.

The card is a separate KiCad project, so nothing joins it to the core but
a human reading both. That is why the edge labels are checked CHARACTER
FOR CHARACTER against the spellings the core sheets use, and why the
NOT-TAKEN list is checked too: a label that looks right but is not on
SECTION 1's list is a wire nobody planned.
"""
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from kicad_netlist import build_report, parse, tokenize, children, child  # noqa: E402
from kicad_contracts import alias_splits, _PIN_LINE  # noqa: E402

SCH = os.environ.get("DINO_SERIAL_SCH") or os.path.normpath(
    os.path.join(HERE, "..", "..", "dino_serial", "dino_serial.kicad_sch"))

# SECTION 1 -- the edge. Spelled exactly as dino_v0_0_2/*.kicad_sch spells
# them (grep-verified 2026-09-01: every one of these appears as a (label ..)
# on at least one core sheet).
EDGE_TAKEN = (
    {f"W{i}" for i in range(8)}
    | {"M0", "M1", "M2", "M11", "M12", "M13"}
    | {"~{IO_SEL}", "~{IO_RD_Q}", "~{IO_WR}", "RESET_B"}
)
EDGE_NOT_TAKEN = (
    {f"M{i}" for i in range(3, 11)} | {"M14", "M15", "CLK", "~{CLK}", "~{IO_RD}"}
    | {f"MDR{i}" for i in range(8)}
)
POWER = {"+5V", "GND"}

# The three ICs, and nothing else with a U prefix.
ICS = {"U101": "74LS138", "U102": "74LS245", "U103": "16550"}

# U103 outputs that are FORBIDDEN to leave the card (CARD-2), by pin.
U103_NC = {"30": "INTR", "24": "~{TXRDY}", "29": "~{RXRDY}",
           "34": "~{OUT1}", "31": "~{OUT2}", "32": "~{RTS}", "33": "~{DTR}"}


# --------------------------------------------------------------- extraction
class Card:
    """One parse of the card sheet, indexed three ways."""

    def __init__(self, path):
        self.path = path
        assert os.path.exists(path), f"no such schematic: {path}"
        lines, self.lint = build_report(path)
        self.net = {}      # (ref, pin) -> net key ("A/B" joined label set, or N$anon...)
        self.name = {}     # (ref, pin) -> pin name
        self.nc = set()    # (ref, pin) marked with a no-connect flag
        self.pins = defaultdict(list)   # net key -> [(ref, pin)]
        for ln in lines:
            m = _PIN_LINE.match(ln)
            assert m, f"unparseable build_report line: {ln!r}"
            ref, pin, fn, net = m.group(1), m.group(2), m.group(3), m.group(4)
            self.net[(ref, pin)] = net
            self.name[(ref, pin)] = fn
            if "[NC]" in ln:
                self.nc.add((ref, pin))
            if not net.startswith("N$anon"):
                self.pins[net].append((ref, pin))
            else:
                # anonymous nets are unique per pin group only through the
                # '-> others' tail; keep them keyed by the pin itself so
                # `others()` still works.
                self.pins[("anon", ref, pin)].append((ref, pin))
        self._others = {}
        for ln in lines:
            m = _PIN_LINE.match(ln)
            tail = m.group(5) or ""
            self._others[(m.group(1), m.group(2))] = {
                re.match(r"(\S+?)\.(\d+)\(", t).groups()
                for t in tail.split(", ") if t and t != "(nothing)"}
        root = parse(tokenize(open(path).read()))
        self.value = {}
        self.lib = {}
        for s in children(root, "symbol"):
            props = {p[1]: p[2] for p in children(s, "property")}
            r = props.get("Reference", "?")
            self.value[r] = props.get("Value", "")
            self.lib[r] = child(s, "lib_id")[1]
        self.labels = set()
        for kind in ("label", "global_label", "hierarchical_label"):
            for l in children(root, kind):
                self.labels.add(l[1])

    def _have(self, ref, pin):
        assert (ref, pin) in self.net, (
            f"{ref} pin {pin} is not on the sheet -- is {ref} placed and "
            f"annotated as {ref}? Refs on the sheet: {sorted(r for r in self.value if not r.startswith('#'))}")

    def labels_on(self, ref, pin):
        """The label set of the net at (ref, pin); empty if anonymous."""
        self._have(ref, pin)
        n = self.net[(ref, pin)]
        return set() if n.startswith("N$anon") else set(n.split("/"))

    def others(self, ref, pin):
        """{(ref, pin)} sharing a net with (ref, pin), by build_report."""
        self._have(ref, pin)
        return self._others[(ref, pin)]


_CARD = None


def card():
    global _CARD
    if _CARD is None:
        _CARD = Card(SCH)
    return _CARD


def _on(c, ref, pin, label):
    c._have(ref, pin)
    got = c.labels_on(ref, pin)
    assert label in got, (
        f"{ref}.{pin} ({c.name[(ref, pin)]}) must be on {label}; "
        f"labels there: {sorted(got) or 'none (anonymous)'}")


def _rail(c, ref, pin, rail):
    c._have(ref, pin)
    got = c.labels_on(ref, pin)
    assert rail in got, (
        f"{ref}.{pin} ({c.name[(ref, pin)]}) must be tied to {rail}; "
        f"got {sorted(got) or 'nothing -- FLOATING'}")


def _joined(c, a, b):
    c._have(*a)
    c._have(*b)
    assert b in c.others(*a) or a in c.others(*b), (
        f"{a[0]}.{a[1]} ({c.name[a]}) must be wired to "
        f"{b[0]}.{b[1]} ({c.name[b]}); it reaches {sorted(c.others(*a)) or 'nothing'}")


# ------------------------------------------------------------------- tests
def test_three_ics_and_their_designators():
    c = card()
    us = {r for r in c.value if r.startswith("U")}
    assert us == set(ICS), (
        f"the card is U101 '138, U102 '245, U103 16550 and nothing else; "
        f"found {sorted(us)}. Designators are the spec's: they must not "
        f"look like core ones (U1..U80 are spoken for).")
    for r, v in ICS.items():
        assert v in c.value[r], f"{r} should be a {v}, Value is {c.value[r]!r}"


def test_u101_decode():
    """A0-A2 <- M11-M13; E1 <- ~{IO_SEL}; E2 <- GND; E3 <- +5V."""
    c = card()
    _on(c, "U101", "1", "M11")
    _on(c, "U101", "2", "M12")
    _on(c, "U101", "3", "M13")
    _on(c, "U101", "4", "~{IO_SEL}")     # E1 = ~G2A, the window term
    _rail(c, "U101", "5", "GND")         # E2 = ~G2B
    _rail(c, "U101", "6", "+5V")         # E3 = G1


def test_u101_o1_is_the_tap_and_o0_is_card_zeros():
    c = card()
    # O1 (pin 14) -> ~{SER_SEL} -> U102 ~CE (19) and U103 ~CS2 (14)
    _on(c, "U101", "14", "~{SER_SEL}")
    _joined(c, ("U101", "14"), ("U102", "19"))
    _joined(c, ("U101", "14"), ("U103", "14"))
    # O0 (pin 15) is card zero's slot. NOTHING may land on it.
    assert not c.others("U101", "15") and not c.labels_on("U101", "15"), (
        f"U101.15 (O0) is card zero's slot and must be left unlanded; "
        f"it reaches {sorted(c.others('U101', '15'))} / "
        f"labels {sorted(c.labels_on('U101', '15'))}")
    # O0, O2-O7 carry an NC flag so ERC does not nag and nobody wires them.
    for pin in ("15", "13", "12", "11", "10", "9", "7"):
        assert ("U101", pin) in c.nc, (
            f"U101.{pin} ({c.name[('U101', pin)]}) must be marked NC")


def test_u102_a_side_is_w():
    c = card()
    # '245 A0..A7 = pins 2..9
    for i in range(8):
        _on(c, "U102", str(2 + i), f"W{i}")


def test_u102_b_side_is_uart_data():
    c = card()
    # '245 B0..B7 = pins 18..11 (descending); 16550 D0..D7 = pins 1..8
    for i in range(8):
        _joined(c, ("U102", str(18 - i)), ("U103", str(1 + i)))


def test_u102_dir_is_ddis_and_card_internal():
    """DIR (1) <- U103 DDIS (23). NOT ~{IO_RD_Q}. NOT an edge label."""
    c = card()
    _joined(c, ("U102", "1"), ("U103", "23"))
    labs = c.labels_on("U102", "1")
    leaked = labs & (EDGE_TAKEN | EDGE_NOT_TAKEN | POWER)
    assert not leaked, (
        f"DIR must be a card-internal net; it carries edge/power label(s) "
        f"{sorted(leaked)}. ~{{IO_RD_Q}} on DIR points the '245 into a live "
        f"UART driver for up to tHZ=100ns on every read (PHASE_G GOTCHA).")


def test_u102_ce_is_ser_sel():
    c = card()
    _on(c, "U102", "19", "~{SER_SEL}")


def test_u103_register_select_descends():
    """A0 is pin 28, A1 pin 27, A2 pin 26. M0 -> 28."""
    c = card()
    _on(c, "U103", "28", "M0")
    _on(c, "U103", "27", "M1")
    _on(c, "U103", "26", "M2")


def test_u103_chip_selects():
    c = card()
    _rail(c, "U103", "12", "+5V")        # CS0
    _rail(c, "U103", "13", "+5V")        # CS1
    _on(c, "U103", "14", "~{SER_SEL}")   # ~CS2


def test_u103_strobes_active_low_pins():
    """~RD is 21, ~WR is 18. Landing ~{IO_RD_Q} on 22 builds a card that never reads."""
    c = card()
    _on(c, "U103", "21", "~{IO_RD_Q}")
    _on(c, "U103", "18", "~{IO_WR}")


def test_u103_active_high_duals_tied_low():
    """RD (22) and WR (19) <- GND. Datasheet sec 6.0: tie the unused dual."""
    c = card()
    _rail(c, "U103", "22", "GND")
    _rail(c, "U103", "19", "GND")


def test_u103_ads_low_mr_is_reset_b():
    c = card()
    _rail(c, "U103", "25", "GND")        # ~ADS: address is static
    _on(c, "U103", "35", "RESET_B")      # MR, ACTIVE HIGH, not inverted


def test_u103_modem_inputs_tied_and_drawn():
    """~CTS ~DSR ~DCD ~RI (36-39): either rail, but DRAWN, and one rail."""
    c = card()
    rails = set()
    for pin in ("36", "37", "38", "39"):
        got = c.labels_on("U103", pin) & POWER
        assert got, (f"U103.{pin} ({c.name[('U103', pin)]}) is an input and "
                     f"must be tied to +5V or GND; it is floating")
        rails |= got
    assert len(rails) == 1, f"tie all four modem inputs to ONE rail; found {sorted(rails)}"


def test_u103_baudout_feeds_rclk():
    c = card()
    _joined(c, ("U103", "15"), ("U103", "9"))


def test_u103_forbidden_outputs_unconnected():
    """CARD-2: INTR, ~TXRDY, ~RXRDY, ~OUT1, ~OUT2, ~RTS, ~DTR give back nothing."""
    c = card()
    for pin, nm in U103_NC.items():
        assert ("U103", pin) in c.nc, f"U103.{pin} ({nm}) must carry an NC flag"
        assert not c.others("U103", pin) and not c.labels_on("U103", pin), (
            f"U103.{pin} ({nm}) must reach nothing; it reaches "
            f"{sorted(c.others('U103', pin))} / labels {sorted(c.labels_on('U103', pin))}")


def test_u103_serial_pins_labelled():
    """SIN (10) and SOUT (11) go to the host adapter; each needs a label."""
    c = card()
    for pin in ("10", "11"):
        labs = c.labels_on("U103", pin)
        assert labs and not (labs & (EDGE_TAKEN | EDGE_NOT_TAKEN | POWER)), (
            f"U103.{pin} ({c.name[('U103', pin)]}) needs its own label to the "
            f"host adapter; got {sorted(labs) or 'nothing'}")


def test_clock_source():
    """Datasheet sec 6.0/8.2: EITHER a crystal network on XIN/XOUT (RP across,
    RX2 in series with XOUT, crystal XIN -> RX2 node, C to GND at both) OR an
    off-chip oscillator into XIN with XOUT left unused (NC-flagged). The
    sheet as of 2026-09-01 carries a CXO_DIP8 can, Y1, 3.6864MHz."""
    c = card()
    xin, xout = ("U103", "16"), ("U103", "17")
    ys = {r for r in c.value if r.startswith("Y")}
    assert ys, "no Y* part on the sheet: no crystal and no oscillator"
    on_xin = c.others(*xin)
    y_pins = {(r, p) for (r, p) in c.net if r in ys}
    y_on_xin = {(r, p) for (r, p) in on_xin if r in ys}
    assert y_on_xin, (
        f"nothing from {sorted(ys)} reaches XIN (U103.16); XIN reaches "
        f"{sorted(on_xin) or 'nothing'}"
        + (" and is NC-flagged -- remove the flag and wire the oscillator OUT to it"
           if xin in c.nc else ""))
    (y_ref, y_pin), = sorted(y_on_xin)[:1]
    y_names = {p: c.name[(y_ref, p)] for (r, p) in y_pins if r == y_ref}
    if "OUT" in y_names.values():
        # ---- can oscillator ----
        assert y_names[y_pin] == "OUT", (
            f"{y_ref}.{y_pin} ({y_names[y_pin]}) is on XIN; the oscillator's "
            f"OUT pin must be the one that lands there")
        assert xout in c.nc and not c.others(*xout) and not c.labels_on(*xout), (
            "with an off-chip clock XOUT (U103.17) is unused: NC-flag it and "
            f"land nothing; it reaches {sorted(c.others(*xout))}")
        for p, nm in y_names.items():
            if nm.upper() in ("VCC", "VDD", "V+"):
                _rail(c, y_ref, p, "+5V")
            elif nm.upper() == "GND":
                _rail(c, y_ref, p, "GND")
            elif nm.upper() in ("EN", "OE", "ST", "~{OE}", "~{ST}"):
                got = c.labels_on(y_ref, p) & POWER
                assert got, (f"{y_ref}.{p} ({nm}) is the oscillator's enable "
                             f"and must be tied, not floated")
        return
    # ---- crystal network ----
    rs = {r for r in c.value if r.startswith("R")}
    cs = {r for r in c.value if r.startswith("C")}
    on_xout = c.others(*xout)
    rp = {r for (r, p) in on_xin if r in rs} & {r for (r, p) in on_xout if r in rs}
    assert rp, f"no resistor spans XIN and XOUT (RP); XIN reaches {sorted(on_xin)}, XOUT {sorted(on_xout)}"
    rx2 = {r for (r, p) in on_xout if r in rs} - rp
    assert rx2, f"no series resistor on XOUT (RX2); XOUT reaches {sorted(on_xout)}"
    rx2_ref = sorted(rx2)[0]
    rx2_far = {c.net[k] for k in c.net if k[0] == rx2_ref} - {c.net[xout]}
    y_far = {c.net[k] for k in c.net if k[0] == y_ref} - {c.net[xin]}
    assert rx2_far and rx2_far == y_far, (
        f"{rx2_ref}'s far side {sorted(rx2_far)} and {y_ref}'s far side "
        f"{sorted(y_far)} must be one node")
    (node,) = rx2_far

    def cap_to_gnd(netkey):
        for cr in cs:
            nets = {c.net[k] for k in c.net if k[0] == cr}
            if netkey in nets and any("GND" in n.split("/") for n in nets):
                return cr
        return None
    assert cap_to_gnd(c.net[xin]), "no capacitor from XIN to GND (C1 of the network)"
    assert cap_to_gnd(node), f"no capacitor from the crystal/RX2 node ({node}) to GND (C2)"


def test_power_pins():
    c = card()
    for ref, vcc, gnd in (("U101", "16", "8"), ("U102", "20", "10"), ("U103", "40", "20")):
        _rail(c, ref, vcc, "+5V")
        _rail(c, ref, gnd, "GND")


def test_edge_labels_spelled_like_the_core():
    """Every SECTION 1 edge label present, character for character."""
    c = card()
    missing = EDGE_TAKEN - c.labels
    assert not missing, f"edge labels missing or misspelled: {sorted(missing)}"


def test_nothing_not_taken_is_taken():
    c = card()
    extra = EDGE_NOT_TAKEN & c.labels
    assert not extra, (
        f"labels on the card that SECTION 1 says the card does NOT take: "
        f"{sorted(extra)}")


def test_nothing_given_back():
    """No card OUTPUT lands on a net carrying an edge label (CARD-2)."""
    c = card()
    outputs = [("U103", p) for p in ("11", "15", "17", "23") + tuple(U103_NC)]
    outputs += [("U101", str(p)) for p in (15, 14, 13, 12, 11, 10, 9, 7)]
    for k in outputs:
        leak = c.labels_on(*k) & EDGE_TAKEN
        assert not leak, (
            f"{k[0]}.{k[1]} ({c.name[k]}) is a card output on edge net(s) "
            f"{sorted(leak)} -- pulling the card would leave a core input floating")


def test_no_alias_splits():
    c = card()
    net_pins_map = {n: ps for n, ps in c.pins.items() if isinstance(n, str)}
    splits = alias_splits(net_pins_map)
    assert not splits, f"one physical net under two label sets: {splits}"


def test_no_driverless_anon_nets():
    c = card()
    assert not c.lint, "\n".join(c.lint)


if __name__ == "__main__":
    # ENUMERATED, not a hand-written sequence. Guarded by test_suite_reachability.py.
    print(f"serial card: {SCH}")
    _failed = []
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        try:
            _fn()
            print(f"ok  {_name}")
        except AssertionError as _e:
            _failed.append(_name)
            print(f"FAIL {_name}: {_e}")
    if _failed:
        print(f"\n{len(_failed)} FAILED")
        sys.exit(1)
    print("\nserial card step 1 paper witness: OK")
