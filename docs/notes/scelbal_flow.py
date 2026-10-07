#!/usr/bin/env python3
"""scelbal_flow -- control flow and flag analysis of 8008 code (PHASE_BASIC 4a).

The translator (scelbal_xlate.py) asks two questions of every instruction:

  live_out[a]   which 8008 flags (C Z S P) are read after `a` before being
                rewritten -- a DINO macro may clobber only dead flags
  c_pol_in[a]   how DINO's carry relates to the 8008's carry on entry:
                  "T"   same              (after AD/AC, after a rotate)
                  "I"   inverted          (after SU/SB/CP: DINO's '382 gives
                                           NOT-borrow, the 8008 gives borrow)
                  "Z0"  8008 C is 0, DINO C undefined (after ND/XR/OR)
                  "U"   unknown           (entry, a native I/O routine)

THE CALL GRAPH IS EXACT. The 8008's stack is inside the chip and cannot be
read or written, so every CAL returns to the byte after it. A RET belongs
to every procedure that can reach it without following a CAL (tail jumps
into shared code are common in SCELBAL), and its flags flow to the return
points of exactly those procedures' call sites. Context-insensitive, so
conservative: a flag may be reported live where it is not, never the
reverse.

`native` names addresses whose 8008 bodies are REPLACED (CINP, CPRINT):
they are treated as a RET that clobbers every flag.
"""
from collections import deque

import as8

FLAGS = ("C", "Z", "S", "P")
ALL = frozenset(FLAGS)


def classify(mnem):
    """-> (kind, cond) where cond = (flag, sense) or None."""
    m = mnem.upper()
    if m == "JMP":
        return "jmp", None
    if m == "CAL":
        return "cal", None
    if m == "RET":
        return "ret", None
    if m == "HLT":
        return "hlt", None
    if m in ("INP", "OUT"):
        return "io", None
    if m == "RST":
        return "rst", None
    if len(m) == 3 and m[0] in "JCR" and m[1] in "TF" and m[2] in "CZSP":
        return {"J": "jcc", "C": "ccc", "R": "rcc"}[m[0]], (m[2], m[1] == "T")
    return "op", None


def def_use(mnem):
    """8008 flags written and read by a non-control instruction."""
    m = mnem.upper()
    if len(m) == 3 and m[:2] in ("AD", "SU", "ND", "XR", "OR", "CP"):
        return ALL, frozenset()
    if len(m) == 3 and m[:2] in ("AC", "SB"):
        return ALL, frozenset("C")
    if len(m) == 3 and m[:2] in ("IN", "DC") and m[2] in "BCDEHL":
        return frozenset("ZSP"), frozenset()
    if m in ("RLC", "RRC"):
        return frozenset("C"), frozenset()
    if m in ("RAL", "RAR"):
        return frozenset("C"), frozenset("C")
    return frozenset(), frozenset()


LOGIC = ("ND", "XR", "OR")


def is_logic(mnem):
    m = mnem.upper()
    return len(m) == 3 and m[:2] in LOGIC


def c_need(mnem, kind):
    """Carry polarity a carry READER requires: 'T', 'I' or None (either)."""
    m = mnem.upper()
    if len(m) == 3 and m[:2] == "AC" or m in ("RAL", "RAR"):
        return "T"
    if len(m) == 3 and m[:2] == "SB":
        return "I"
    return None


def c_transfer(mnem, pol, norm=None):
    m = mnem.upper()
    if norm and is_logic(m):
        return frozenset({norm})
    if len(m) == 3 and m[:2] in ("AD", "AC"):
        return frozenset({"T"})
    if len(m) == 3 and m[:2] in ("SU", "SB", "CP"):
        return frozenset({"I"})
    if len(m) == 3 and m[:2] in ("ND", "XR", "OR"):
        return frozenset({"Z0"})
    if m in ("RLC", "RRC", "RAL", "RAR"):
        return frozenset({"T"})
    return pol


class Flow:
    def __init__(self, items, symbols, entries, native=()):
        self.sym = {k.upper(): v for k, v in symbols.items()}
        self.items = {it.addr: it for it in items if it.kind == "code"}
        self.native = {self.sym[n.upper()] for n in native}
        self.nxt, self.target, self.kind, self.cond = {}, {}, {}, {}
        for a, it in self.items.items():
            k, c = classify(it.mnem)
            if a in self.native:
                k, c = "native", None
            self.kind[a], self.cond[a] = k, c
            self.nxt[a] = a + it.size
            if k in ("jmp", "jcc", "cal", "ccc"):
                t = self.sym.get(it.operand.upper())
                if t is None:
                    raise ValueError(f"{a:#06x}: target {it.operand!r}")
                self.target[a] = t
        self._rets = {}
        for a in self.items:                    # every target is code
            for t in ([self.target[a]] if a in self.target else []):
                if t not in self.items:
                    raise ValueError(f"{a:#06x}: target {t:#06x} not code")
        self._build()
        self.reached = self._reach([self.sym[e.upper()] for e in entries])
        self._liveness()
        self.c_norm = {}
        self._entries = [self.sym[e.upper()] for e in entries]
        self._polarity(self._entries)
        self._normalize()
        self._constants()
        self._cell_liveness()

    # ---- graph ----------------------------------------------------------
    def intra(self, a):
        """Successors inside one procedure (a call returns to the next)."""
        k = self.kind[a]
        if k == "jmp":
            return [self.target[a]]
        if k == "jcc":
            return [self.target[a], self.nxt[a]]
        if k in ("cal", "ccc", "rcc", "op", "io", "rst"):
            return [self.nxt[a]]
        return []                                   # ret, hlt, native

    def rets(self, entry):
        """RET/Rcc/native nodes reachable from `entry` without a CAL."""
        if entry not in self._rets:
            seen, out, todo = set(), set(), [entry]
            while todo:
                a = todo.pop()
                if a in seen:
                    continue
                if a not in self.items:
                    raise ValueError(f"flow reaches {a:#06x}: not code")
                seen.add(a)
                if self.kind[a] in ("ret", "rcc", "native"):
                    out.add(a)
                todo.extend(self.intra(a))
            self._rets[entry] = frozenset(out)
        return self._rets[entry]

    def body(self, entry):
        """Every node a call to `entry` can execute: intra edges plus the
        bodies of nested calls."""
        if not hasattr(self, "_body"):
            self._body = {}
        if entry not in self._body:
            seen, todo = set(), [entry]
            while todo:
                a = todo.pop()
                if a in seen:
                    continue
                seen.add(a)
                todo.extend(self.intra(a))
                if self.kind[a] in ("cal", "ccc"):
                    todo.append(self.target[a])
            self._body[entry] = frozenset(seen)
        return self._body[entry]

    def defines(self, entry):
        """8008 flags a call to `entry` may change. A procedure that defines
        none of a flag is TRANSPARENT to it: the flag crosses the call
        untouched, per call site."""
        if not hasattr(self, "_defs"):
            self._defs = {}
        if entry not in self._defs:
            d = set()
            for a in self.body(entry):
                d |= self.du(a)[0]
            self._defs[entry] = frozenset(d)
        return self._defs[entry]

    def _build(self):
        # retpts[r] = {(callee entry, return point)} for every RET-like r
        retpts = {a: set() for a in self.items}
        for a, k in self.kind.items():
            if k in ("cal", "ccc"):
                t = self.target[a]
                for r in self.rets(t):
                    retpts[r].add((t, self.nxt[a]))
        self.retpts = retpts
        self.succ = {f: {} for f in FLAGS}
        for f in FLAGS:
            for a, k in self.kind.items():
                self.succ[f][a] = self._succ(a, k, f)
        self.pred = {f: {a: [] for a in self.items} for f in FLAGS}
        for f in FLAGS:
            for a, ss in self.succ[f].items():
                for s_ in ss:
                    if s_ in self.pred[f]:
                        self.pred[f][s_].append(a)

    def _succ(self, a, k, f, defs=None):
        defs = defs or self.defines

        def back(r):
            return sorted(rp for t, rp in self.retpts[r]
                          if f in defs(t))
        if k == "jmp":
            return [self.target[a]]
        if k == "jcc":
            return [self.target[a], self.nxt[a]]
        if k == "cal":
            t = self.target[a]
            return [t] + ([] if f in defs(t) else [self.nxt[a]])
        if k == "ccc":
            return [self.target[a], self.nxt[a]]
        if k in ("ret", "native"):
            return back(a)
        if k == "rcc":
            return [self.nxt[a]] + back(a)
        if k == "hlt":
            return []
        return [self.nxt[a]]

    def _reach(self, entries):
        seen, todo = set(), list(entries)
        while todo:
            a = todo.pop()
            if a in seen:
                continue
            seen.add(a)
            for f in FLAGS:
                todo.extend(self.succ[f][a])
            if self.kind[a] in ("cal", "ccc"):
                todo.append(self.nxt[a])
        return seen

    # ---- flags ----------------------------------------------------------
    def du(self, a):
        k = self.kind[a]
        if k == "native":
            return ALL, frozenset()
        if k in ("jcc", "ccc", "rcc"):
            return frozenset(), frozenset(self.cond[a][0])
        if k == "op":
            return def_use(self.items[a].mnem)
        return frozenset(), frozenset()

    def _liveness(self):
        live = {}
        for f in FLAGS:
            li = {a: False for a in self.items}
            succ, pred = self.succ[f], self.pred[f]
            work = deque(self.items)
            queued = set(work)
            while work:
                a = work.popleft()
                queued.discard(a)
                d, u = self.du(a)
                out = any(li[s_] for s_ in succ[a])
                new = f in u or (out and f not in d)
                if new != li[a]:
                    li[a] = new
                    for p in pred[a]:
                        if p not in queued:
                            work.append(p)
                            queued.add(p)
            live[f] = li
        self.live_in = {a: frozenset(f for f in FLAGS if live[f][a])
                        for a in self.items}
        self.live_out = {a: frozenset(f for f in FLAGS
                                      if any(live[f][s_]
                                             for s_ in self.succ[f][a]))
                         for a in self.items}

    def _polarity(self, entries):
        succ, pred = self.succ["C"], self.pred["C"]
        self.c_pol_in = {a: frozenset() for a in self.items}
        self.c_pol_out = {a: frozenset() for a in self.items}
        for e in entries:
            self.c_pol_in[e] = frozenset({"U"})
        work = deque(self.items)
        queued = set(work)
        while work:
            a = work.popleft()
            queued.discard(a)
            pin = self.c_pol_in[a].union(*(self.c_pol_out[p]
                                           for p in pred[a]))
            self.c_pol_in[a] = pin
            if self.kind[a] == "native":
                out = frozenset({"U"})
            elif self.kind[a] == "op":
                out = c_transfer(self.items[a].mnem, pin, self.c_norm.get(a))
            else:
                out = pin
            if out != self.c_pol_out[a]:
                self.c_pol_out[a] = out
                for s_ in succ[a]:
                    if s_ not in queued:
                        work.append(s_)
                        queued.add(s_)

    def _normalize(self):
        """A logic op clears the 8008 carry but leaves DINO's undefined.
        Where that carry is live, pick the polarity its readers need (the
        translator emits ADI 0 for T, CPI 0 for I) and re-run polarity."""
        uses = {a for a in self.items if "C" in self.du(a)[1]}
        for a in sorted(self.reached):
            it = self.items[a]
            if self.kind[a] != "op" or not is_logic(it.mnem) \
                    or "C" not in self.live_out[a]:
                continue
            need, seen, todo = set(), set(), list(self.succ["C"][a])
            while todo:
                n = todo.pop()
                if n in seen:
                    continue
                seen.add(n)
                if n in uses:
                    r = c_need(self.items[n].mnem, self.kind[n])
                    if r:
                        need.add(r)
                if "C" in self.du(n)[0]:
                    continue
                todo.extend(self.succ["C"][n])
            if len(need) > 1:
                raise ValueError(f"{a:#06x}: carry readers need {need}")
            self.c_norm[a] = need.pop() if need else "T"
        if self.c_norm:
            self._polarity(self._entries)

    # ---- register constants (for the translator's M fusion) ----------------
    VREGS = "BCDEHL"

    def reg_writes(self, a):
        """8008 registers B-L an instruction writes."""
        if self.kind[a] != "op":
            return frozenset()
        m = self.items[a].mnem.upper()
        if len(m) == 3 and m[0] == "L" and m[1] in self.VREGS:
            return frozenset(m[1])
        if len(m) == 3 and m[:2] in ("IN", "DC") and m[2] in self.VREGS:
            return frozenset(m[2])
        return frozenset()

    def writes(self, entry):
        if not hasattr(self, "_wr"):
            self._wr = {}
        if entry not in self._wr:
            w = set()
            for a in self.body(entry):
                w |= self.reg_writes(a)
            self._wr[entry] = frozenset(w)
        return self._wr[entry]

    def _constants(self):
        """consts[a] = {reg: value or None} on ENTRY to a, for H and L
        (B-E are tracked too, so LHD can carry D's constant). A callee that
        never writes a register passes the caller's value across the call."""
        R = self.VREGS
        BOT = object()
        edges = {a: [] for a in self.items}          # a -> [(dest, mask)]
        allr = frozenset(R)
        for a, k in self.kind.items():
            if k in ("cal", "ccc"):
                t = self.target[a]
                edges[a].append((t, allr))
                edges[a].append((self.nxt[a], allr - self.writes(t)))
                for r in self.rets(t):
                    edges[r].append((self.nxt[a], self.writes(t)))
            elif k in ("ret", "native", "hlt"):
                pass
            else:
                for d in self.intra(a):
                    edges[a].append((d, allr))
            if k == "rcc":
                pass                                    # nxt via intra()
        st_in = {a: {r: BOT for r in R} for a in self.items}
        for e in self._entries:
            st_in[e] = {r: None for r in R}

        def join(x, y):
            if x is BOT:
                return y
            if y is BOT or x == y:
                return x
            return None

        def step(a, st):
            st = dict(st)
            if self.kind[a] != "op":
                return st
            m = self.items[a].mnem.upper()
            if len(m) == 3 and m[0] == "L" and m[1] in R:
                d = m[1]
                if m[2] == "I":
                    st[d] = as8.value(self.items[a].operand, self.sym) & 0xFF
                elif m[2] in R:
                    v = st[m[2]]
                    st[d] = None if v is BOT else v
                else:
                    st[d] = None
            elif len(m) == 3 and m[:2] in ("IN", "DC") and m[2] in R:
                v = st[m[2]]
                st[m[2]] = (None if v is None or v is BOT
                            else (v + (1 if m[:2] == "IN" else -1)) & 0xFF)
            return st

        work = deque(self._entries)
        queued = set(work)
        while work:
            a = work.popleft()
            queued.discard(a)
            out = step(a, st_in[a])
            for d, mask in edges[a]:
                if d not in st_in:
                    continue
                cur = st_in[d]
                new = dict(cur)
                for r in mask:
                    new[r] = join(cur[r], out[r])
                if new != cur:
                    st_in[d] = new
                    if d not in queued:
                        work.append(d)
                        queued.add(d)
        self.consts = {a: {r: (None if st_in[a][r] is BOT else st_in[a][r])
                           for r in "HL"} for a in self.items}
        self.consts_all = st_in

    # ---- liveness of the translator's register cells -------------------
    # The DINO port keeps 8008 B-L in RAM cells, H twice: VH (its value)
    # and PH (the RAM page it selects). A store to a cell no one reads
    # before the next store is dead and the translator drops it. A FUSED
    # memory access (H and L both constant: an absolute LDA/STA/MVI/LDB)
    # reads neither VL nor PH -- which is what kills most LLI stores.
    CELLS = ("VB", "VC", "VD", "VE", "VL", "VH", "PH")
    _CELL_OF = {"B": ("VB",), "C": ("VC",), "D": ("VD",), "E": ("VE",),
                "L": ("VL",), "H": ("VH", "PH")}

    def fused(self, a):
        """True when the translator turns this M access into an absolute
        address. Must agree with scelbal_xlate.macro (test pinned)."""
        m = self.items[a].mnem.upper()
        c = self.consts[a]
        if c["H"] is None or c["L"] is None:
            return False
        return (m in ("LAM", "LMA", "LMI")
                or (len(m) == 3 and m[2] == "M" and m[:2] in
                    ("AD", "AC", "SU", "SB", "ND", "XR", "OR", "CP")))

    def cell_du(self, a):
        """(cells written, cells read) by one instruction."""
        if self.kind[a] == "io":
            # peekpoke.as8's pseudo-ports address DINO memory through D:E
            port = as8.value(self.items[a].operand, self.sym)
            if port in (1, 9):
                return frozenset(), frozenset(("VD", "VE"))
            return frozenset(), frozenset()
        if self.kind[a] != "op":
            return frozenset(), frozenset()
        m = self.items[a].mnem.upper()
        R = self.VREGS
        d, u = set(), set()

        def read(r):
            if r == "H":
                u.add("VH")
            elif r in R:
                u.update(self._CELL_OF[r])
            elif r == "M" and not self.fused(a):
                u.update(("VL", "PH"))
        if (len(m) == 3 and m[0] == "L" and m[1] in "HL" and m[2] == "I"
                and self.consts[a][m[1]] ==
                as8.value(self.items[a].operand, self.sym) & 0xFF):
            return frozenset(), frozenset()     # redundant: emits nothing
        if len(m) == 3 and m[0] == "L" and m[1] == m[2]:
            return frozenset(), frozenset()     # LBB etc: emits nothing
        if len(m) == 3 and m[0] == "L" and m[1] in R + "AM":
            if m[2] == "I":
                read("M") if m[1] == "M" else None
            else:
                read(m[2])
                if m[1] == "M":
                    read("M")
            if m[1] in R:
                d.update(self._CELL_OF[m[1]])
        elif len(m) == 3 and m[:2] in ("AD", "AC", "SU", "SB", "ND", "XR",
                                       "OR", "CP"):
            if m[2] != "I":
                read(m[2])
        elif len(m) == 3 and m[:2] in ("IN", "DC") and m[2] in R:
            read(m[2])
            d.update(self._CELL_OF[m[2]])
        return frozenset(d), frozenset(u)

    def cell_writes(self, entry):
        out = set()
        for r in self.writes(entry):
            out.update(self._CELL_OF[r])
        return frozenset(out)

    def _cell_liveness(self):
        live = {}
        for cell in self.CELLS:
            succ = {a: self._succ(a, self.kind[a], cell, self.cell_writes)
                    for a in self.items}
            pred = {a: [] for a in self.items}
            for a, ss in succ.items():
                for s_ in ss:
                    if s_ in pred:
                        pred[s_].append(a)
            li = {a: False for a in self.items}
            work = deque(self.items)
            queued = set(work)
            while work:
                a = work.popleft()
                queued.discard(a)
                d, u = self.cell_du(a)
                out = any(li[s_] for s_ in succ[a])
                new = cell in u or (out and cell not in d)
                if new != li[a]:
                    li[a] = new
                    for p in pred[a]:
                        if p not in queued:
                            work.append(p)
                            queued.add(p)
            live[cell] = (li, succ)
        self.cell_live_in = {a: frozenset(c for c in self.CELLS
                                          if live[c][0][a])
                             for a in self.items}
        self.cell_live_out = {a: frozenset(c for c in self.CELLS
                                           if any(live[c][0][s_]
                                                  for s_ in live[c][1][a]))
                              for a in self.items}
