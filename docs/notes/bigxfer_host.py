#!/usr/bin/env python3
"""The serial settle test, run N times: load asm/ram/bigxfer.asm through
the monitor's L, run it with G, and check that what it streams back is,
byte for byte, what was sent. Both directions, ~2.2K each way, per run.

  python3 docs/notes/bigxfer_host.py               # 3 runs
  python3 docs/notes/bigxfer_host.py --runs 10
  DINO_PORT=/dev/cu.usbserial-XXXX ...

Per run, one line:

  run 1  load OK (1 try)  stream 2233/2233 MATCH  S 0x.... X 0x..  OK
  run 2  load OK (2 tries) stream 2233/2233 diff at 1187  ...      FAIL

Then a tally. A wire that has settled passes every run. `make kill-monitor`
first if minicom holds the port."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dinoload                                               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "asm", "ram", "bigxfer.asm")
PROMPT = dinoload.PROMPT
ROW = 32


def render(code):
    """What a perfect run prints after the G echo, prompt included. The
    parser's reference, and the program's answer key in one place."""
    code = bytes(code)
    out = bytearray()
    for i in range(0, len(code), ROW):
        out += code[i:i + ROW].hex().upper().encode() + b"\r\n"
    x = 0
    for b in code:
        x ^= b
    out += b"S %04X X %02X\r\n" % (sum(code) & 0xFFFF, x)
    out += PROMPT
    return bytes(out)


def parse(out, code):
    """out: bytes the program printed (after the G echo). Returns what
    matched and what did not; never raises on garbage."""
    code = bytes(code)
    rep = {"ok": False, "n": 0, "first_diff": None, "sum16": None,
           "xor": None, "tail": b""}
    text = bytes(out)
    i = text.find(b"\r\nS ")
    if i < 0:
        i = text.find(b"S ")
    hexpart = text[:i] if i >= 0 else text     # no S line: grade what came
    digits = bytes(c for c in hexpart if c in b"0123456789ABCDEFabcdef")
    got = bytearray()
    for j in range(0, len(digits) - 1, 2):
        got.append(int(digits[j:j + 2], 16))
    rep["n"] = len(got)
    for j, (a, b) in enumerate(zip(got, code)):
        if a != b:
            rep["first_diff"] = j
            break
    if rep["first_diff"] is None and len(got) != len(code):
        rep["first_diff"] = min(len(got), len(code))
    line = text[i:].lstrip(b"\r\n").split(b"\r\n", 1)[0] if i >= 0 else b""
    parts = line.split()
    try:
        if len(parts) >= 4 and parts[0] == b"S" and parts[2] == b"X":
            rep["sum16"] = int(parts[1], 16)
            rep["xor"] = int(parts[3], 16)
    except ValueError:
        pass
    rep["tail"] = text[-40:]
    rep["ok"] = rep["sum16"] is not None and rep["xor"] is not None
    return rep


def one_run(port, code, origin, k):
    tries = []
    try:
        got = dinoload.load(port, code, origin, log=lambda s: tries.append(s))
    except dinoload.LoadError:
        for t in tries:                       # every attempt's own reason
            print("      " + t.strip())
        raise
    load_txt = f"load OK ({len(tries) + 1} tr{'y' if not tries else 'ies'})"
    # not dinoload.go(): that returns None when no prompt comes back and
    # drops what DID arrive, and what arrived is the evidence.
    dinoload._type(port, dinoload.go_line(origin), "G line")
    t0 = time.monotonic()
    out = port.read_until(PROMPT, 90.0)
    dt = time.monotonic() - t0
    back = out.endswith(PROMPT)
    rep = parse(out, code)
    want16 = sum(code) & 0xFFFF
    wx = 0
    for b in code:
        wx ^= b
    stream = (f"stream {rep['n']}/{len(code)} "
              + ("MATCH" if rep["first_diff"] is None else f"diff at {rep['first_diff']}"))
    sums = (f"S {rep['sum16']:#06x} X {rep['xor']:#04x}" if rep["ok"]
            else f"no S line, tail {rep['tail']!r}")
    ok = (back and got == dinoload.csum(code) and rep["first_diff"] is None
          and rep["sum16"] == want16 and rep["xor"] == wx)
    ret = f"prompt after {dt:.1f}s" if back else f"NO PROMPT in {dt:.0f}s, read OB"
    print(f"run {k}  {load_txt}  {stream}  {sums}  {ret}  {'OK' if ok else 'FAIL'}")
    if not back and rep["n"]:
        print(f"       stopped after byte {rep['n']}: page {origin + rep['n']:#06x}, "
              f"line {rep['n'] // ROW}, {rep['n'] % ROW} bytes into it; "
              f"tail {out[-24:]!r}")
    return ok, len(tries) == 0


def main(argv):
    runs, port_path = 3, dinoload.DEFAULT_PORT
    it = iter(argv)
    for a in it:
        if a == "--runs":
            runs = int(next(it))
        elif a == "--port":
            port_path = next(it)
        else:
            print(f"unknown arg {a}", file=sys.stderr)
            return 2
    code, origin = dinoload.assemble_file(SRC)
    dinoload.check_placement(code, origin)
    print(f"bigxfer: {len(code)} bytes at {origin:#06x}, host sum "
          f"{dinoload.csum(code):#04x}, {runs} runs on {port_path}")
    port = dinoload.FdPort(port_path)
    passed, first_try = 0, 0
    t0 = time.monotonic()
    for k in range(1, runs + 1):
        try:
            ok, clean = one_run(port, code, origin, k)
        except dinoload.LoadError as e:
            print(f"run {k}  {e}  FAIL")
            ok, clean = False, False
        passed += ok
        first_try += clean
    dt = time.monotonic() - t0
    print(f"\n{passed}/{runs} runs passed, {first_try}/{runs} loads clean "
          f"first try, {dt / runs:.0f}s per run")
    return 0 if passed == runs else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
