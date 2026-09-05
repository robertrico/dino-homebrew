#!/usr/bin/env python3
"""Host-side probe for PROG_serrx / serrx0. Sends one byte at a time and
prints EVERY byte that comes back, in hex, with the gap since the send.
No terminal rendering in the way: a 0x1F is printed as 1f, a 0xC6 as c6.

  python3 docs/notes/serprobe_host.py                 # walk the pattern set
  python3 docs/notes/serprobe_host.py 62 5b 0d        # these bytes, in order
  python3 docs/notes/serprobe_host.py --hold [bytes]  # open the port FIRST,
        # wait for Enter, then walk. Reproduces "port open at DINO power-up".
  DINO_PORT=/dev/cu.usbserial-XXXX ...                # another adapter

Stdlib only (termios). 9600 8N1, no flow control, raw."""
import os, sys, time, termios, select

PORT = os.environ.get("DINO_PORT", "/dev/cu.usbserial-AB0JK5WC")
# Walk: rails, alternating, nibbles, walking 1 and walking 0, then the
# keystrokes that misbehaved.
DEFAULT = ([0x00, 0xFF, 0x55, 0xAA, 0x0F, 0xF0]
           + [1 << i for i in range(8)] + [0xFF ^ (1 << i) for i in range(8)]
           + [0x41, 0x42, 0x5B, 0x5D, 0x0D, 0x35, 0x61, 0x62])

def open_port(path):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attr = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attr
    iflag = 0; oflag = 0; lflag = 0
    cflag = termios.CS8 | termios.CREAD | termios.CLOCAL   # 8N1, no CRTSCTS
    cc[termios.VMIN] = 0; cc[termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW,
                      [iflag, oflag, cflag, lflag, termios.B9600, termios.B9600, cc])
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd

def drain(fd, quiet_ms=150, t0=None):
    got = []
    last = time.monotonic()
    while True:
        r, _, _ = select.select([fd], [], [], quiet_ms / 1000)
        if not r:
            if time.monotonic() - last > quiet_ms / 1000:
                break
            continue
        b = os.read(fd, 64)
        if not b:
            break
        now = time.monotonic()
        for x in b:
            got.append((x, (now - t0) * 1000 if t0 else 0))
        last = now
    return got

def main(argv):
    hold = "--hold" in argv
    argv = [a for a in argv if a != "--hold"]
    seq = [int(a, 16) for a in argv] if argv else DEFAULT
    fd = open_port(PORT)
    print(f"port {PORT} 9600 8N1 raw; {len(seq)} bytes")
    if hold:
        print("PORT IS OPEN AND DRIVING TX. Power DINO up now, wait for the"
              " poison on OB, then press Enter here.")
        sys.stdin.readline()
    junk = drain(fd, 300)
    if junk:
        print("  unsolicited before start:", " ".join(f"{x:02x}" for x, _ in junk))
    bad = 0
    for v in seq:
        t0 = time.monotonic()
        os.write(fd, bytes([v]))
        got = drain(fd, 150, t0)
        back = " ".join(f"{x:02x}@{ms:.1f}ms" for x, ms in got) or "(nothing)"
        ok = len(got) == 1 and got[0][0] == v
        bad += not ok
        mark = "  " if ok else "!!"
        diff = f"  xor {got[-1][0] ^ v:02x}" if got else ""
        print(f"{mark} sent {v:02x}  got {back}{diff}")
    print(f"{bad}/{len(seq)} wrong")
    os.close(fd)
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
