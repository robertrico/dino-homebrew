#!/usr/bin/env python3
"""dinoload -- load an assembled .asm into DINO's RAM over the monitor, and
run it.

    python3 docs/notes/dinoload.py asm/ram/hello.asm            # load
    make monitor                                                 # then, in
    > G 8100                                                     # minicom
    python3 docs/notes/dinoload.py asm/ram/hello.asm --go       # or: G too
    DINO_PORT=/dev/cu.usbserial-XXXX ...   or   --port /dev/cu.x

The far end is asm/monitor.asm, at the prompt. The protocol is the
monitor's own language and nothing else -- everything here can be typed
by hand at minicom, which is the point:

    host  ->  \\r                    sync: expect "> " back
    host  ->  L 8100,<len>\\r         the echo and CRLF come back first
    host  ->  115A5F34...            hex text, two digits a byte, sent 16
                                     digits at a time; each chunk's echo
                                     is read back before the next goes
    DINO  ->  \\r\\n0x<sum>\\r\\n> "      the 8-bit sum of what LANDED
    host  ->  G 8100\\r               --go only; whatever the program
                                     prints follows, then "> " if it RETs

The sum is the witness, the same shape as W's read-back: it is computed
from the bytes the monitor wrote through STAX, not from the bytes the
host meant to send. A mismatch is a LoadError naming both sums; a wrong
echo is a LoadError naming the chunk.

A loadable program: `.org 0x8100` or above, ends with RET (HALT stays
halted; RESET recovers), never touches 0x80E0-0x80FF -- the monitor's
cells and the stack the RET needs. check_placement() refuses both ROM
addresses and that page. Monitor subroutines (putc, puthex, puts, crlf)
are callable by ROM address; `make listing-monitor` prints them.

Port handling is serprobe_host's: stdlib termios, 9600 8N1, raw.
"""
import os
import select
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asm                                                    # noqa: E402
from serprobe_host import open_port                           # noqa: E402

DEFAULT_PORT = os.environ.get("DINO_PORT", "/dev/cu.usbserial-AB0JK5WC")
RAM_BASE = 0x8000
MON_LO, MON_HI = 0x80E0, 0x80FF         # the monitor's cells and stack
PROMPT = b"> "
CHUNK = 16                              # the 16550's RX FIFO depth


class LoadError(Exception):
    pass


# ---- framing, pure ------------------------------------------------------
def load_line(origin, code):
    return b"L %04X,%X\r" % (origin, len(code))


def go_line(origin):
    return b"G %04X\r" % origin


def csum(code):
    return sum(code) & 0xFF


def hexed(code):
    """The payload as the monitor wants it: two upper-case digits per
    byte, nothing between them."""
    return bytes(code).hex().upper().encode()


def check_placement(code, origin):
    end = origin + len(code) - 1
    if origin < RAM_BASE:
        raise LoadError(f"origin {origin:#06x} is below RAM ({RAM_BASE:#06x}):"
                        " use .org 0x8100")
    if end > 0xFFFF:
        raise LoadError(f"{len(code)} bytes at {origin:#06x} run off the end"
                        " of memory")
    if origin <= MON_HI and end >= MON_LO:
        raise LoadError(f"{origin:#06x}-{end:#06x} overlaps the monitor's own"
                        f" cells and stack at {MON_LO:#06x}-{MON_HI:#06x}")


def assemble_file(path):
    r = asm.assemble_text(open(path).read())
    return r.code, r.origin


# ---- the session --------------------------------------------------------
def _expect(port, want, what, timeout=2.0):
    got = port.read_until(want, timeout)
    if not got.endswith(want):
        raise LoadError(f"{what}: expected {want!r}, got {got!r}")
    return got


def sync(port, tries=4):
    """A bare CR at the prompt reprompts. The FTDI buffer can hold a stray
    byte from the burn or a prior run in front of the banner (minicom
    flushes on open; open_port does too, but bytes arrive after that), so
    drain first and send CR up to `tries` times, each ending a possibly
    partial line. `read_until` returns the tail through the FIRST prompt,
    so a leading 0x81 is swallowed, not fatal."""
    if hasattr(port, "flush_input"):
        port.flush_input()
    last = b""
    for _ in range(tries):
        port.write(b"\r")
        got = port.read_until(PROMPT, 1.0)
        if got.endswith(PROMPT):
            return
        last = got
    raise LoadError(f"sync: no prompt after {tries} CRs -- is the monitor "
                    f"in the socket and at its prompt? last saw {last!r}")


def load(port, code, origin):
    """Send `code` to `origin` as hex text; return the sum the monitor
    answered. Each chunk's echo is read back before the next is sent: that
    is the pacing (the monitor echoes at line rate) and a per-chunk check
    that the digits arrived as sent."""
    check_placement(code, origin)
    sync(port)
    line = load_line(origin, code)
    port.write(line)
    _expect(port, line[:-1] + b"\r\n", "L line echo")
    text = hexed(code)
    for i in range(0, len(text), CHUNK):
        chunk = text[i:i + CHUNK]
        port.write(chunk)
        got = port.read_until(chunk, 2.0)
        if got != chunk:
            raise LoadError(f"echo at byte {i // 2} of {len(code)}: sent "
                            f"{chunk!r}, monitor echoed {got!r}")
    reply = _expect(port, PROMPT, "sum reply")
    body = reply[:-len(PROMPT)].strip()
    try:
        got = int(body, 16)
    except ValueError:
        raise LoadError(f"sum reply unreadable: {reply!r}")
    want = csum(code)
    if got != want:
        raise LoadError(f"sum mismatch: monitor {got:#04x}, host {want:#04x}"
                        f" -- {len(code)} bytes at {origin:#06x} did not land"
                        " as sent")
    return got


def go(port, origin, timeout=5.0):
    """G origin. Returns what the program printed before the prompt came
    back, or None if no prompt did (the program HALTed, or is still
    running)."""
    line = go_line(origin)
    port.write(line)
    _expect(port, line[:-1] + b"\r\n", "G line echo")
    out = port.read_until(PROMPT, timeout)
    if out.endswith(PROMPT):
        return out[:-len(PROMPT)]
    if out:
        sys.stdout.write(out.decode("ascii", "replace"))
    return None


# ---- the real port ------------------------------------------------------
class FdPort:
    def __init__(self, path):
        self.fd = open_port(path)

    def flush_input(self, settle=0.2):
        """Drop whatever is queued: the burn's noise, a banner from a
        reset, an unfinished line's echo. Wait `settle` first so bytes in
        the adapter's pipe make it into the queue we are dropping."""
        time.sleep(settle)
        import termios
        termios.tcflush(self.fd, termios.TCIFLUSH)

    def write(self, data):
        data = bytes(data)
        while data:
            n = os.write(self.fd, data)
            data = data[n:]

    def read_until(self, delim, timeout=1.0):
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return bytes(buf)
            r, _, _ = select.select([self.fd], [], [], left)
            if not r:
                continue
            b = os.read(self.fd, 256)
            if not b:
                continue
            buf += b
            if delim in buf:
                i = buf.find(delim) + len(delim)
                # anything past the delimiter belongs to the next read;
                # the monitor never speaks unprompted, so there is none
                return bytes(buf[:i])

    def close(self):
        os.close(self.fd)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    src, run, port_path = None, False, DEFAULT_PORT
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--go":
            run = True
        elif a == "--port":
            port_path = argv[i + 1]
            i += 1
        elif a.startswith("-"):
            print(f"unknown option {a!r}")
            return 2
        else:
            src = a
        i += 1
    if src is None:
        print("no source given")
        return 2
    try:
        code, origin = assemble_file(src)
    except asm.AsmError as e:
        print(f"{src}: {e}", file=sys.stderr)
        return 1
    print(f"{src}: {len(code)} bytes at {origin:#06x}, sum {csum(code):#04x}")
    try:
        check_placement(code, origin)
    except LoadError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    if not os.path.exists(port_path):
        print(f"no such port {port_path} (ls /dev/cu.usbserial*; kill minicom"
              " first: make kill-monitor)", file=sys.stderr)
        return 1
    port = FdPort(port_path)
    try:
        got = load(port, code, origin)
        print(f"  loaded, monitor sum {got:#04x} OK")
        if not run:
            print(f"  now: make monitor, then type   G {origin:04X}")
        if run:
            print(f"  G {origin:04X}")
            out = go(port, origin)
            if out is None:
                print("  no prompt back: the program HALTed or is still"
                      " running")
            else:
                sys.stdout.write(out.decode("ascii", "replace"))
                print("  returned to the prompt")
    except LoadError as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        return 1
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
