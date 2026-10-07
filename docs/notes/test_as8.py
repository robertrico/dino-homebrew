#!/usr/bin/env python3
"""Host tests for as8.py -- the 8008 assembler for SCELBAL's source.

PHASE_BASIC step 2. The answer key is upstream's own assembled image,
asm/scelbal/upstream/sc1fast.bin (willegal.net, fetched 2026-10-06): the
source assembled by this file must reproduce it BYTE FOR BYTE. The
translator reads labels and the code/data split out of as8, so an as8 that
drifts from the published binary would translate a program nobody ran.

Run: python3 test_as8.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as8                                                    # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(HERE, "..", "..", "asm", "scelbal", "upstream")
SRC = os.path.join(UP, "sc1fast.asm")
BIN = os.path.join(UP, "sc1fast.bin")
BIN_BASE = 0o000100             # the .bin starts at the first ORG, 000#100


def _ref():
    with open(BIN, "rb") as f:
        return f.read()


def test_encodings_one_of_each_family():
    """Octal, as the 8008 book writes them."""
    cases = {
        "LAB": [0o301], "LMA": [0o370], "LAM": [0o307],
        "LAI 104": [0o006, 0o104], "LMI 001": [0o076, 0o001],
        "INB": [0o010], "DCL": [0o061],
        "ADB": [0o201], "ACM": [0o217], "SUI 001": [0o024, 0o001],
        "NDA": [0o240], "XRA": [0o250], "ORB": [0o261], "CPI 260": [0o074, 0o260],
        "RLC": [0o002], "RRC": [0o012], "RAL": [0o022], "RAR": [0o032],
        "RET": [0o007], "RFZ": [0o013], "RTC": [0o043], "RTS": [0o063],
        "JMP 001#002": [0o104, 0o002, 0o001],
        "JFZ 002#000": [0o110, 0o000, 0o002],
        "JTS 002#000": [0o160, 0o000, 0o002],
        "CAL 003#004": [0o106, 0o004, 0o003],
        "CTZ 003#004": [0o152, 0o004, 0o003],
        "INP 5": [0o113], "OUT 16": [0o135], "RST 1": [0o015],
    }
    for text, want in cases.items():
        img, _ = as8.assemble("\tORG 000#000\n\t" + text + "\n")
        assert list(img[:len(want)]) == want, (text, list(img[:len(want)]), want)


def test_hb_and_equ():
    img, sym = as8.assemble("PG: EQU 027#000\n\tORG 000#000\n\tLHI \\HB\\PG\n")
    assert sym["PG"] == 0o27 * 256
    assert list(img[:2]) == [0o056, 0o027]


def test_strings_are_mark_parity_and_star_is_decimal():
    img, _ = as8.assemble('\tORG 000#000\n\tDATA "AB"\n\tDATA *10\n\tDATA 7\n')
    assert list(img[:2]) == [0xC1, 0xC2]
    assert img[12] == 7                     # *10 reserved ten bytes


def test_reproduces_upstream_binary():
    with open(SRC) as f:
        img, sym = as8.assemble(f.read())
    ref = _ref()
    diffs = [BIN_BASE + i for i in range(len(ref))
             if img[BIN_BASE + i] != ref[i]]
    assert not diffs, (f"{len(diffs)} bytes differ; first at "
                       f"{diffs[0]:#06x}: got {img[diffs[0]]:#04x} "
                       f"want {ref[diffs[0] - BIN_BASE]:#04x}")
    assert sym["CINP"] == 0o103 and sym["EXEC"] == 0x08B6


def test_code_data_split_covers_every_byte_once():
    """The translator needs to know which bytes are instructions."""
    with open(SRC) as f:
        src = f.read()
    _, _ = as8.assemble(src)
    items = as8.parse(src)
    seen = {}
    for it in items:
        for a in range(it.addr, it.addr + it.size):
            assert a not in seen, f"{a:#06x} emitted twice"
            seen[a] = it.kind
    assert {"code", "data"} <= set(seen.values())


# ---- runner: ENUMERATED (test_suite_reachability.py) -------------------
if __name__ == "__main__":
    _failed = []
    for _name, _fn in sorted(
            (kv for kv in list(globals().items())
             if kv[0].startswith("test_") and callable(kv[1]))):
        try:
            _fn()
            print(f"  ok   {_name}")
        except Exception as _e:                   # noqa: BLE001
            _failed.append((_name, _e))
            print(f"  FAIL {_name}: {type(_e).__name__}: {_e}")
    if _failed:
        print(f"\n{len(_failed)} FAILED")
        sys.exit(1)
    print("OK test_as8")
