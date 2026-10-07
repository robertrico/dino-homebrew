#!/usr/bin/env python3
"""i8008 -- an Intel 8008 emulator, PHASE_BASIC's answer key.

It runs the ORIGINAL SCELBAL image (as8.py's output, pinned against
upstream's sc1fast.bin) so the DINO translation has something exact to be
compared with. It is not a DINO tool and never models DINO timing.

Semantics (Intel 8008 datasheet; test_i8008.py pins each family):
    ALU      C Z S P from the result; ND/XR/OR clear C; SU/SB/CP set C on
             BORROW. CP leaves A alone.
    INr/DCr  Z S P only -- C survives.
    rotates  C only.
    P        1 = even parity.
    stack    seven return addresses in a circular file; an eighth CAL
             overwrites the oldest, as on silicon (`wraps` counts them).
             SCELBAL's error exits depend on it.
    HLT      000, 001, 377: run() returns.

Ports: `cpu.inp[p] = fn(cpu) -> byte`, `cpu.out[p] = fn(cpu, byte)`;
an unhooked INP/OUT raises.

Hooks: `cpu.hooks[addr] = fn` makes `addr` a native subroutine: when the
PC reaches it, fn(cpu) runs and the CPU executes a RET. SCELBAL's
bit-banged CINP/CPRINT are replaced this way.
"""

REG = "abcdehl"             # 8008 codes 0..6; 7 is M


class Halted(Exception):
    pass


def _parity_even(v):
    return bin(v).count("1") % 2 == 0


class CPU:
    def __init__(self, image, pc=0):
        self.mem = bytearray(image) + bytearray(max(0, 0x4000 - len(image)))
        self.a = self.b = self.c = self.d = self.e = self.h = self.l = 0
        self.cy = self.z = self.s = self.p = False
        self.pc = pc
        self.stack = []
        self.hooks = {}
        self.inp = {}               # port -> fn(cpu) -> byte
        self.out = {}               # port -> fn(cpu, byte)
        self.halted = False
        self.steps = 0
        self.wraps = 0              # CALs that overwrote the oldest return
        self.m_seen = None          # set() to record every M address

    # ---- register file ------------------------------------------------
    @property
    def hl(self):
        return ((self.h & 0x3F) << 8) | self.l

    def get(self, r):
        if r == 7:
            if self.m_seen is not None:
                self.m_seen.add(self.hl)
            return self.mem[self.hl]
        return getattr(self, REG[r])

    def put(self, r, v):
        v &= 0xFF
        if r == 7:
            if self.m_seen is not None:
                self.m_seen.add(self.hl)
            self.mem[self.hl] = v
        else:
            setattr(self, REG[r], v)

    def _fetch(self):
        v = self.mem[self.pc]
        self.pc = (self.pc + 1) & 0x3FFF
        return v

    def _szp(self, v):
        self.z = v == 0
        self.s = bool(v & 0x80)
        self.p = _parity_even(v)

    def _cond(self, cc):
        return (self.cy, self.z, self.s, self.p)[cc]

    def _call(self, target):
        self.stack.append(self.pc)
        if len(self.stack) > 7:                 # circular: oldest is lost
            self.stack.pop(0)
            self.wraps += 1
        self.pc = target

    def _ret(self):
        self.pc = self.stack.pop()

    def _alu(self, op, x):
        a = self.a
        if op in (0, 1):                        # AD, AC
            r = a + x + (1 if op == 1 and self.cy else 0)
            self.cy = r > 0xFF
        elif op in (2, 3, 7):                   # SU, SB, CP
            r = a - x - (1 if op == 3 and self.cy else 0)
            self.cy = r < 0
        elif op == 4:
            r, self.cy = a & x, False
        elif op == 5:
            r, self.cy = a ^ x, False
        else:
            r, self.cy = a | x, False
        r &= 0xFF
        self._szp(r)
        if op != 7:
            self.a = r

    # ---- one instruction ---------------------------------------------
    def step(self):
        if self.pc in self.hooks:
            self.hooks[self.pc](self)
            self._ret()
            return
        self.steps += 1
        op = self._fetch()
        hi, mid, lo = op >> 6, (op >> 3) & 7, op & 7
        if op in (0x00, 0x01, 0xFF):
            self.pc = (self.pc - 1) & 0x3FFF
            self.halted = True
            raise Halted
        if hi == 3:                             # Lds
            self.put(mid, self.get(lo))
        elif hi == 2:                           # ALU r
            self._alu(mid, self.get(lo))
        elif hi == 0:
            if lo == 0:                         # INr
                v = (self.get(mid) + 1) & 0xFF
                self.put(mid, v)
                self._szp(v)
            elif lo == 1:                       # DCr
                v = (self.get(mid) - 1) & 0xFF
                self.put(mid, v)
                self._szp(v)
            elif lo == 2:                       # rotates
                a = self.a
                if mid == 0:
                    self.cy = bool(a & 0x80)
                    self.a = ((a << 1) | (a >> 7)) & 0xFF
                elif mid == 1:
                    self.cy = bool(a & 1)
                    self.a = (a >> 1) | ((a & 1) << 7)
                elif mid == 2:
                    c = 1 if self.cy else 0
                    self.cy = bool(a & 0x80)
                    self.a = ((a << 1) | c) & 0xFF
                elif mid == 3:
                    c = 0x80 if self.cy else 0
                    self.cy = bool(a & 1)
                    self.a = (a >> 1) | c
                else:
                    raise ValueError(f"illegal {op:#04o} at {self.pc - 1:#06x}")
            elif lo == 3:                       # Rcc
                if self._cond(mid & 3) == bool(mid & 4):
                    self._ret()
            elif lo == 4:                       # ALU imm
                self._alu(mid, self._fetch())
            elif lo == 5:                       # RST
                self._call(mid << 3)
            elif lo == 6:                       # LrI
                self.put(mid, self._fetch())
            else:                               # RET
                self._ret()
        else:                                   # hi == 1
            if lo & 1:                          # INP / OUT, flags untouched
                port = (op >> 1) & 0x1F
                if port < 8 and port in self.inp:
                    self.a = self.inp[port](self) & 0xFF
                    return
                if port >= 8 and port in self.out:
                    self.out[port](self, self.a)
                    return
                raise ValueError(f"I/O {op:#04o} at {self.pc - 1:#06x} unhooked")
            lo_b = self._fetch()
            target = ((self._fetch() & 0x3F) << 8) | lo_b
            kind = lo & 6
            if kind == 4:                       # JMP
                self.pc = target
            elif kind == 6:                     # CAL
                self._call(target)
            elif kind == 0:                     # Jcc
                if self._cond(mid & 3) == bool(mid & 4):
                    self.pc = target
            else:                               # Ccc
                if self._cond(mid & 3) == bool(mid & 4):
                    self._call(target)

    def run(self, max_steps=10_000_000):
        try:
            for _ in range(max_steps):
                self.step()
        except Halted:
            return True
        return False
