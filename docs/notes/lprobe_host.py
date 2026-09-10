#!/usr/bin/env python3
"""Raw probe of the monitor's L path: serprobe's honesty on the loader's
bytes. Types an L line and a hex payload one character at a time, prints
EVERY byte that comes back in hex, names each wrong echo by position, and
never retries. One pass, one verdict, nothing hidden.

  python3 docs/notes/lprobe_host.py                  # 32-byte pattern, gap 0
  python3 docs/notes/lprobe_host.py --gap 150        # serprobe's pacing
  python3 docs/notes/lprobe_host.py --bytes 128      # longer payload
  python3 docs/notes/lprobe_host.py --pattern 00 ff 55 aa
  DINO_PORT=/dev/cu.usbserial-XXXX ...

  --gap MS   milliseconds of silence AFTER each echo before the next
             character goes. 0 = the loader's pacing (next char ~1ms after
             the echo). 150 = serprobe's (it waits 150ms of quiet). The
             two tools disagreed on the fail rate on 2026-09-08 and this
             switch is the only difference between them.

Reading the output:

  !! sent 33 got 00           echo was 0x00: the byte the CPU read
  !! sent 33 got (nothing)    no echo in 1s: the character vanished
  !! sent 33 got 33 3f ...    echoed right, then `?`: hexval rejected it
                              (cannot happen for a hex digit -- would mean
                              A changed between putc and hexval)
  ?? at payload N             the monitor aborted; nothing after N was sent

The sum line is the witness the monitor computes from what it STORED, and
is compared with the host's sum of what it MEANT to send."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dinoload                                               # noqa: E402

PORT = os.environ.get("DINO_PORT", "/dev/cu.usbserial-AB0JK5WC")
PROMPT = dinoload.PROMPT

# serprobe's walk, as payload bytes
DEFAULT = ([0x00, 0xFF, 0x55, 0xAA, 0x0F, 0xF0]
           + [1 << i for i in range(8)] + [0xFF ^ (1 << i) for i in range(8)]
           + [0x41, 0x42, 0x5B, 0x5D, 0x0D, 0x35, 0x61, 0x62]
           + [0x30, 0x31])


def l_line(origin, n):
    return f"L {origin:04X},{n:X}\r".encode()


def hx(b):
    return " ".join(f"{x:02x}" for x in b) or "(nothing)"


def _type(port, data, what, gap, out):
    """One character, its echo, the next. Returns (wrong, positions,
    wrong_bytes, abort_at). CR echoes as CRLF. `?` in an echo is the
    monitor aborting; stop there."""
    wrong, positions, wrong_bytes, abort_at = 0, [], {}, None
    for i, b in enumerate(bytes(data)):
        ch = bytes([b])
        want = b"\r\n" if ch == b"\r" else ch
        t0 = time.monotonic()
        port.write(ch)
        got = port.read_until(want, 1.0)
        ms = (time.monotonic() - t0) * 1000
        ok = got == want
        if not ok:
            wrong += 1
            positions.append(i)
            for x in got:
                wrong_bytes[x] = wrong_bytes.get(x, 0) + 1
        out(f"{'  ' if ok else '!!'} {what} {i:3d} sent {b:02x}  "
            f"got {hx(got)}@{ms:.1f}ms")
        if b"?" in got or (not ok and b"\n?" in port.read_until(b"?", 0.3)):
            abort_at = i
            out(f"?? at {what} {i}: the monitor aborted, nothing more sent")
            break
        if gap:
            time.sleep(gap / 1000)
    return wrong, positions, wrong_bytes, abort_at


def sync(port, out=print):
    """A bare CR draws a prompt. The banner carries one too, so keep
    reading until no prompt is pending; a leftover would land in the first
    echo and be reported as a wrong byte that never was."""
    port.write(b"\r")
    got = port.read_until(PROMPT, 1.0)
    out(f"   sync got {hx(got)}")
    for _ in range(4):
        more = port.read_until(PROMPT, 0.3)
        if not more:
            break
        out(f"   sync also {hx(more)}")


def probe(port, code, origin, gap=0.0, out=print):
    code = bytes(code)
    want_sum = dinoload.csum(code)
    sync(port, out)
    line = l_line(origin, len(code))
    wl, pl, bl, al = _type(port, line, "line", gap, out)
    wp, pp, bp, ap = 0, [], {}, None
    sum_got = None
    if al is None:
        wp, pp, bp, ap = _type(port, dinoload.hexed(code), "payload", gap, out)
        if ap is None:
            reply = port.read_until(PROMPT, 2.0)
            out(f"   reply got {hx(reply)}")
            i = reply.find(b"0x")
            if i >= 0:
                try:
                    sum_got = int(reply[i + 2:i + 4], 16)
                except ValueError:
                    sum_got = None
    wrong_bytes = dict(bl)
    for k, v in bp.items():
        wrong_bytes[k] = wrong_bytes.get(k, 0) + v
    out(f"{wl}/{len(line)} line wrong, {wp}/{len(code) * 2} payload wrong"
        + (f", aborted at payload {ap}" if ap is not None else "")
        + (f", aborted at line {al}" if al is not None else ""))
    if wrong_bytes:
        out("   wrong bytes came back as: "
            + ", ".join(f"{k:02x} x{v}" for k, v in sorted(wrong_bytes.items())))
    if sum_got is not None:
        out(f"   sum monitor {sum_got:#04x} host {want_sum:#04x} "
            + ("MATCH" if sum_got == want_sum else "MISMATCH"))
    return {"wrong_line": wl, "wrong_payload": wp, "positions": pl + pp,
            "wrong_bytes": wrong_bytes, "abort_at": ap if ap is not None else al,
            "sum_got": sum_got, "sum_want": want_sum}


def main(argv):
    gap, n, origin, pattern = 0.0, None, 0x8100, None
    it = iter(argv)
    for a in it:
        if a == "--gap":
            gap = float(next(it))
        elif a == "--bytes":
            n = int(next(it))
        elif a == "--origin":
            origin = int(next(it), 16)
        elif a == "--pattern":
            pattern = [int(x, 16) for x in it]
        else:
            print(f"unknown arg {a}", file=sys.stderr)
            return 2
    code = pattern or DEFAULT
    if n:
        code = (code * (n // len(code) + 1))[:n]
    port = dinoload.FdPort(PORT)
    print(f"port {PORT} 9600 8N1 raw; {len(code)} payload bytes at "
          f"{origin:#06x}, gap {gap:g}ms, host sum {dinoload.csum(code):#04x}")
    port.flush_input()
    r = probe(port, code, origin, gap=gap)
    return 1 if (r["wrong_line"] or r["wrong_payload"]
                 or r["sum_got"] != r["sum_want"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
