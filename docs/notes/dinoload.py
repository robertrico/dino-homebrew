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
    host  ->  L 8100,<len>\\r         typed one character at a time, each
                                     echo read back before the next goes
    host  ->  115A5F34...            hex text, two digits a byte, the same
                                     way: one digit, its echo, the next
    DINO  ->  \\r\\n0x<sum>\\r\\n> "      the 8-bit sum of what LANDED
    host  ->  G 8100\\r               --go only; whatever the program
                                     prints follows, then "> " if it RETs

ONE CHARACTER AT A TIME IS THE POINT. The machine drops characters that
arrive back-to-back (2026-09-07: the burst loader lost one in nine, a
150 ms-paced serprobe lost none), so the loader types like a person and
never has more than one character in flight. A wrong echo, or a wrong
sum, restarts the whole load from the prompt, up to three times; every
byte lands again, so a partial pass is overwritten, not patched.

The sum is the witness, the same shape as W's read-back: it is computed
from the bytes the monitor wrote through STAX, not from the bytes the
host meant to send. A mismatch is a LoadError naming both sums; a wrong
echo is a LoadError naming the character.

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


def _drain(port):
    """Swallow anything still queued after a prompt (a second prompt from
    a recovery, a stray byte). Short timeout: nothing is expected."""
    port.read_until(PROMPT, 0.3)


def sync(port, tries=4):
    """Get the monitor to a prompt from wherever it is. A bare CR at the
    prompt reprompts; a CR mid-line ends the line with `?`. But a CR
    inside an L payload is SKIPPED, so the last tries send `Z` first: a
    non-hex character aborts a payload with `?`, and as a command letter
    it draws the same `?`. Either way a prompt comes back. The FTDI
    buffer can hold a stray byte from the burn in front of the banner, so
    the queue is dropped first; `read_until` runs through the FIRST prompt,
    so a leading 0x81 is swallowed, not fatal."""
    if hasattr(port, "flush_input"):
        port.flush_input()
    last = b""
    for i in range(tries):
        port.write(b"\r" if i < tries // 2 else b"Z\r")
        got = port.read_until(PROMPT, 1.0)
        if got.endswith(PROMPT):
            _drain(port)
            return
        last = got
    raise LoadError(f"sync: no prompt after {tries} tries -- is the monitor "
                    f"in the socket and running? last saw {last!r}")


ROW = 32                                # payload bytes per progress row


def _type(port, data, what, view=None):
    """Type `data` the way a person does: one character, wait for its
    echo, the next. CR echoes as CRLF. That is the pacing -- the machine
    drops characters that arrive back-to-back and never drops paced ones
    (2026-09-07, serprobe vs the burst loader) -- and a per-character
    check that each digit arrived as sent. A wrong echo names the
    position. `view` sees every echo as it lands: the live picture."""
    for i, b in enumerate(bytes(data)):
        ch = bytes([b])
        want = b"\r\n" if ch == b"\r" else ch
        port.write(ch)
        got = port.read_until(want, 1.0)
        if view and got:
            view(got)
        if got != want:
            raise LoadError(f"{what}: char {i} sent {ch!r}, monitor echoed "
                            f"{got!r}")


def _load_once(port, code, origin, view=None):
    _type(port, load_line(origin, code), "L line", view)
    text = hexed(code)
    for row in range(0, len(code), ROW):
        _type(port, text[2 * row:2 * (row + ROW)], "payload", view)
        done = min(row + ROW, len(code))
        if view and done < len(code):
            view(b"\n  %d/%d " % (done, len(code)))
    reply = _expect(port, PROMPT, "sum reply")
    if view:
        view(reply)
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


def load(port, code, origin, tries=3, log=None, view=None):
    """Send `code` to `origin` as hex text; return the sum the monitor
    answered. A dropped character anywhere (the line, the payload) or a
    wrong sum is retried from the top, up to `tries` times, after getting
    the monitor back to its prompt. Every byte lands again on a retry --
    the L is whole-image, so a partial first pass is simply overwritten.
    `log` gets one line per failed attempt; `view` gets the echo stream,
    the sum line and a `done/total` counter every 32 bytes."""
    check_placement(code, origin)
    sync(port)
    last = None
    for attempt in range(1, tries + 1):
        try:
            return _load_once(port, code, origin, view)
        except LoadError as e:
            last = e
            if log:
                log(f"\n  attempt {attempt}: {e}")
            sync(port)
    raise LoadError(f"{last} -- gave up after {tries} attempts")


def go(port, origin, timeout=5.0, view=None):
    """G origin. Returns what the program printed before the prompt came
    back, or None if no prompt did (the program HALTed, or is still
    running). `view` sees the G line's echo and the program's output."""
    _type(port, go_line(origin), "G line", view)
    out = port.read_until(PROMPT, timeout)
    if view and out:
        view(out)
    if out.endswith(PROMPT):
        return out[:-len(PROMPT)]
    return None


class FdPort:
    """The adapter. Bytes arrive in whatever clumps USB delivers them, so
    a read for one delimiter can bring the NEXT reply along with it: the
    last payload digit's echo and the whole sum line came in one read on
    the bench (2026-09-07) and the reply was dropped on the floor. What
    arrives past the delimiter is kept in `self.buf` for the next call."""

    def __init__(self, path=None, fd=None):
        self.fd = open_port(path) if fd is None else fd
        self.buf = bytearray()

    def flush_input(self, settle=0.2):
        """Drop whatever is queued: the burn's noise, a banner from a
        reset, an unfinished line's echo. Wait `settle` first so bytes in
        the adapter's pipe make it into the queue we are dropping."""
        time.sleep(settle)
        self.buf.clear()
        try:
            import termios
            termios.tcflush(self.fd, termios.TCIFLUSH)
        except (termios.error, OSError):
            pass                                  # a pipe, not a tty
        while True:                               # whatever is left
            r, _, _ = select.select([self.fd], [], [], 0)
            if not r or not os.read(self.fd, 256):
                break

    def write(self, data):
        data = bytes(data)
        while data:
            n = os.write(self.fd, data)
            data = data[n:]

    def _take(self, delim):
        i = self.buf.find(delim)
        if i < 0:
            return None
        i += len(delim)
        out, self.buf = bytes(self.buf[:i]), self.buf[i:]
        return out

    def read_until(self, delim, timeout=1.0):
        got = self._take(delim)
        if got is not None:
            return got
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                out, self.buf = bytes(self.buf), bytearray()
                return out
            r, _, _ = select.select([self.fd], [], [], left)
            if not r:
                continue
            b = os.read(self.fd, 256)
            if not b:
                continue
            self.buf += b
            got = self._take(delim)
            if got is not None:
                return got

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

    def view(b):                       # what the monitor sends, verbatim
        sys.stdout.write(b.decode("ascii", "replace"))
        sys.stdout.flush()
    try:
        got = load(port, code, origin, log=print, view=view)
        print(f"\nloaded {len(code)} bytes at {origin:#06x}, monitor sum "
              f"{got:#04x} OK")
        if not run:
            print(f"  now: make monitor, then type   G {origin:04X}")
        if run:
            out = go(port, origin, view=view)
            if out is None:
                print("\n  no prompt back: the program HALTed or is still"
                      " running")
            else:
                print("\n  returned to the prompt")
    except LoadError as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        return 1
    finally:
        port.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
