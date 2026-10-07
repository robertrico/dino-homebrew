#!/usr/bin/env python3
"""scelbal_ref -- the ORIGINAL SCELBAL on i8008.py, behind a scripted terminal.

    python3 docs/notes/scelbal_ref.py 'PRINT 2/3'      # prints the transcript

PHASE_BASIC's answer key. The image is as8's assembly of the vendored
upstream source (byte-identical to upstream's sc1fast.bin, test_as8.py),
started at EXEC. The bit-banged serial routines are replaced by hooks:

    CINP    next scripted byte, OR 0x80 (SCELBAL is mark parity), echoed
            -- the original echoes bit by bit as it samples (NEXBIT)
    CPRINT  A AND 0x7F to the transcript

When the script runs dry while SCELBAL waits for input, the session ends:
that is the "idle at the prompt" condition, not an error.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import as8                                                    # noqa: E402
import i8008                                                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "asm", "scelbal", "upstream",
                   "sc1fast.asm")


PATCHES = [os.path.join(HERE, "..", "..", "asm", "scelbal", n)
           for n in ("udf.as8", "peekpoke.as8")]

# Anchored substitutions in upstream: (whole line, replacement lines).
# Each anchor must occur exactly once, or source() refuses.
_I = "           "
SUBST = [
    ("UDEFX:\tHLT", ["UDEFX:\tJMP UDF8"]),
    # keyword scan starts at the extended table in page 061 ...
    (_I + "LHI \\HB\\OLDPG27        ;** Set H to point to start of KEYWORD TABLE.",
     [_I + "LHI \\HB\\KEYTB"]),
    (_I + "LLI 000                ;Set L to point to start of KEYWORD TABLE.",
     [_I + "LLI \\LB\\KEYTB"]),
    # ... and tries 15 entries, not 12 (POKE is token 017)
    (_I + "CPI 015                ;See if have tested all entries in the keyword table.",
     [_I + "CPI 020"]),
    (_I + "JFZ SYNERR             ;If not, then assume a syntax error condition.",
     [_I + "JFZ POKCHK"]),
    # function table: 8-byte slots in page 061, nine entries
    (_I + "LCI 002                ;Initialize C to a value of two for future ops",
     [_I + "LCI 003"]),
    (_I + "LLI 274                ;Load L with starting address (less four) of FUNCTION",
     [_I + "LLI \\LB\\FUNM8"]),
    (_I + "LHI \\HB\\OLDPG26        ;** LOOK-UP TABLE. Set H to table page.",
     [_I + "LHI \\HB\\FUNM8"]),
    (_I + "CPI 010                ;Possible functions in the table.",
     [_I + "CPI 011"]),
    (_I + "JTZ UDEFX              ;# Function. If so, perform the User DEfined Function",
     [_I + "JTZ UDEFX", _I + "CPI 011", _I + "JTZ PEEKX"]),
]
SW_PORT, LED_PORT = 0, 8          # INP 0 = SW1, OUT 010 = OB (udf.as8)
PEEK_PORT, POKE_PORT = 1, 9        # INP 1 / OUT 011 = DINO [D:E] (peekpoke)


class _Dry(Exception):
    pass


def source(src_path=SRC):
    """Upstream with the DINO patch: UDEFX jumps to udf.as8's UDF8.
    The upstream file itself is never edited."""
    with open(src_path) as f:
        lines = f.read().split("\n")
    for old, new in SUBST:
        hits = [i for i, l in enumerate(lines) if l == old]
        assert len(hits) == 1, f"anchor {old.strip()!r} found {len(hits)}x"
        lines[hits[0]:hits[0] + 1] = new
    text = "\n".join(lines)
    for p in PATCHES:
        with open(p) as f:
            text += "\n" + f.read()
    return text


def image():
    return as8.assemble(source())


def session(script, max_steps=50_000_000, m_seen=None, switches=0x00,
            leds=None, dmem=None):
    """`dmem` (dict) stands in for DINO memory behind PEEK/POKE's pseudo-
    ports: POKE writes it, PEEK reads it; 0x4000 reads `switches`."""
    """Run SCELBAL from EXEC on `script` (bytes). -> transcript (str).
    `m_seen=set()` collects every address read or written through M."""
    img, sym = image()
    cpu = i8008.CPU(img, pc=sym["EXEC"])
    cpu.m_seen = m_seen
    out = bytearray()
    feed = list(script)

    def cinp(c):
        if not feed:
            raise _Dry
        ch = feed.pop(0)
        out.append(ch & 0x7F)
        c.a = ch | 0x80

    def cprint(c):
        out.append(c.a & 0x7F)

    dmem = {} if dmem is None else dmem

    def peek(c):
        a = (c.d << 8) | c.e
        return switches if a == 0x4000 else dmem.get(a, 0)

    def poke(c, v):
        dmem[(c.d << 8) | c.e] = v

    cpu.inp[PEEK_PORT] = peek
    cpu.out[POKE_PORT] = poke
    cpu.inp[SW_PORT] = lambda c: switches
    cpu.out[LED_PORT] = lambda c, v: (leds.append(v) if leds is not None
                                      else None)
    cpu.hooks[sym["CINP"]] = cinp
    cpu.hooks[sym["CPRINT"]] = cprint
    try:
        if not cpu.run(max_steps):
            raise RuntimeError(f"no idle after {max_steps} steps at "
                               f"{cpu.pc:#06x}")
        raise RuntimeError(f"HLT at {cpu.pc:#06x}")
    except _Dry:
        pass
    session.steps = cpu.steps
    return out.decode("ascii", "replace")


if __name__ == "__main__":
    text = "\r".join(sys.argv[1:]) + ("\r" if sys.argv[1:] else "")
    print(session(text.encode()).replace("\r", ""))
    print(f"[{session.steps} 8008 instructions]")
