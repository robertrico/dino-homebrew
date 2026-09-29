#!/usr/bin/env python3
"""RET fetched from RAM HALTs on silicon when the instruction before it ends
at T >= 2. The oracle cannot see it (it has no timing); this file pins the
bench results as truth and checks one rule against every one of them.

2026-09-28. bigxfer streamed 2233/2233 and then did not return; the machine
sat on a HALT row (T0 frozen, ~RD flat). Cut down to `callret` -- CALL
CRLF; RET -- it still halts, with or without the 22 pF on U103.28. The
2026-09-08 staircase had already named "OUT immediately before RET from
RAM"; the widening is that a RET from ROM before it does the same, and
that what OUT and that RET share is where they END, not what they do.

SILICON ROW COUNTS ARE NOT main's. The sockets hold U9 0xC52B / U15 0x45F9
/ U23 0xCB8E: dbd5e78~1's microcode plus the 2026-09-08 OUT settle patch
(OUT, the register OUT_ family and the ALU OUT_ family: last row loses END,
SETTLE appended, the builder's FILL ends it -- T3). Rebuilt and CRC-matched
2026-09-28. main's OUT is one row (the interrupt burn reverts the settle),
so every "ends at" below comes from SILICON_END_T, not from main's table.

The oracle trace names each executed instruction; this test looks up where
that instruction ends ON SILICON and applies the rule to every RET fetched
from RAM. A rule that disagrees with any bench row fails here.

    python3 docs/notes/test_ramret.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import asm                                                    # noqa: E402
import dinoload                                               # noqa: E402
import microcode_gen as mg                                    # noqa: E402
import progrom_gen as pg                                      # noqa: E402

FAILS = []


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# ---- silicon microcode ---------------------------------------------------
# The 2026-09-08 settle patch, as burned (U15 0x45F9). T0 is the implicit
# FETCH, so an instruction with n rows ENDS at Tn.
_SETTLED = {"OUT", "OUTB", "OUTC", "OUTSPL", "OUTSPH", "OUTPCL", "OUTPCH",
            "OUTADD", "OUTSUB", "OUTBSUB", "OUTAND", "OUTOR", "OUTXOR"}


def silicon_end_t(name):
    """The T-state whose row carries END, on the microcode in the sockets."""
    n = len(mg.INSTRUCTIONS[name][1])
    return 3 if name in _SETTLED else n


def test_silicon_out_ends_at_t3_and_main_at_t1():
    check(len(mg.INSTRUCTIONS["OUT"][1]) == 1, "main: OUT is one row (T1)")
    check(silicon_end_t("OUT") == 3, "silicon: OUT ends at T3 (settle patch)")
    check(silicon_end_t("RET") == 13, "RET ends at T13")
    check(silicon_end_t("NOP") == 1 and silicon_end_t("LDAI") == 1,
          "NOP and LDAI end at T1")


# ---- the oracle trace ------------------------------------------------------
def test_trace_records_each_instruction():
    """simulate(trace=[]) appends one (pc, name) per instruction, in order,
    with pc the address the opcode was FETCHED from."""
    r = asm.assemble_text(".org 0x0000\nLDAI 0x22\nNOP\nOUT\nHALT\n")
    tr = []
    pg.simulate(None, image=pg.build_image_from_bytes(r.code, r.origin),
                serial=False, trace=tr)
    check([(e["pc"], e["op"]) for e in tr] ==
          [(0x0000, "LDAI"), (0x0002, "NOP"), (0x0003, "OUT"),
           (0x0004, "HALT")],
          f"trace is fetch-pc + name per instruction: {tr}")


# ---- the bench, as truth ---------------------------------------------------
MON = os.path.join(ROOT, "asm", "monitor.asm")
_MON_IMG = None


def monitor_image():
    global _MON_IMG
    if _MON_IMG is None:
        r = asm.assemble_text(open(MON).read())
        _MON_IMG = pg.build_image_from_bytes(r.code, r.origin)
    return _MON_IMG


def run_in_monitor(path):
    """Load `path` through the monitor's L and run it with G, exactly as
    dinoload does, all inside the oracle. Returns (result, trace)."""
    code, org = dinoload.assemble_file(path)
    script = (b"\r" + dinoload.load_line(org, code) + dinoload.hexed(code)
              + dinoload.go_line(org))
    tr = []
    res = pg.simulate(None, image=monitor_image(), serial_in=script,
                      max_steps=20_000_000, trace=tr)
    return res, tr


def ram_rets(tr):
    """Every RET fetched from RAM, with the instruction executed before it."""
    return [(tr[i - 1], tr[i]) for i in range(1, len(tr))
            if tr[i]["op"] == "RET" and tr[i]["pc"] >= 0x8000]


def rule_halts(tr):
    """RULE A -- FALSIFIED 2026-09-28 by rethlsp (see below): a RET fetched
    from RAM halts when the instruction before it ENDS at T >= 2."""
    return any(silicon_end_t(prev["op"]) >= 2 for prev, _ in ram_rets(tr))


def rule_b_halts(tr):
    """RULE B -- FALSIFIED 2026-09-28 by retjmp (JMP ends T3, returned x2):
    the END before a RAM RET clears T through 2+ changing bits."""
    return any(bin(silicon_end_t(p["op"])).count("1") >= 2
               for p, _ in ram_rets(tr))


# (program, bench outcome, source). "halt" = no prompt, T frozen; "return" =
# prompt back. Only runs with a recorded outcome are here.
BENCH = [
    ("step2",    "halt",   "2026-09-08 make go-step2 at 1.024 MHz"),
    ("step2ram", "halt",   "2026-09-08 go-step2ram, OB 0x2B"),
    ("step2a",   "return", "2026-09-08 go-step2a, OB 0x22"),
    ("step2b",   "return", "2026-09-08 go-step2b"),
    ("step2g",   "return", "2026-09-08 go-step2g; again 2026-09-28"),
    ("step2jmp", "return", "2026-09-08 go-step2jmp, OB 0x2D"),
    ("callret",  "halt",   "2026-09-28, 22 pF out"),
    ("retcrlf",  "halt",   "2026-09-28, 22 pF in AND out, OB 0x5A"),
    ("bigxfer",  "halt",   "2026-09-28 x3: 2233/2233 MATCH, S 3329 X 13, "
                           "then no prompt"),
    ("rethlsp",  "return", "2026-09-28: HLSP (ends T2) -> RAM RET, prompt "
                           "back. FALSIFIES rule A"),
    ("retmvi",   "halt",   "2026-09-28: MVI (ends T5 = 0101) -> RAM RET. "
                           "Rule B PREDICTED this before the run"),
    ("retpop",   "return", "2026-09-28, 22 pF in: PUSHA; POPA (T4) -> RET"),
    ("retjmp",   "return", "2026-09-28 x2, 22 pF in: JMP (T3 = 0011) -> RET. "
                           "FALSIFIES rule B"),
    ("retlda",   "halt",   "2026-09-28 x2: LDA (T3) -> RET. Halted, DMM: "
                           "IR 0xFF, PC 0x8104, MAR 0x8200, T1 -- the FETCH "
                           "of RET at 0x8103 delivered 0xFF; RET never ran"),
    ("popout",   "return", "2026-09-28: OUT; POPA read CLEAN (OB 0x5A); final "
                           "RET after NOP"),
]

# Programs whose RAM RET follows a predecessor the bench has not yet run.
# No rule is trusted to predict them (A and B are both dead); they are data.
UNRUN = ["retinr", "retldam"]


def test_the_oracle_returns_from_every_bench_program():
    """The oracle has no timing, so it returns from all of them -- including
    the ones that halt on silicon. That blindness is why this file exists."""
    for name, _, _ in BENCH:
        res, _ = run_in_monitor(os.path.join(ROOT, "asm", "ram", name + ".asm"))
        if name == "step2ram":          # returns RAM->RAM, then HALTs by design
            check(res.get("halted") and res.get("out") == 0x2A,
                  "oracle: step2ram returns from sub and HALTs on OB 0x2A")
            continue
        check(res.get("idle") and not res.get("halted"),
              f"oracle: {name} returns to the prompt")


def test_rule_b_is_falsified_by_retjmp_and_fits_everything_else():
    """RULE B ("the END clears T through 2+ changing bits") predicted
    retmvi's HALT correctly and retjmp's HALT WRONGLY: JMP ends at T3 like
    OUT and its RAM RET returned, twice. OUT and JMP share the T-clear, so
    what the predecessor's last rows DO matters, not only where they end.
    Kept, and asserted wrong exactly on retjmp, so no fix of B can quietly
    hide the counter-example. The real rule is OPEN."""
    for name, bench, src in BENCH:
        _, tr = run_in_monitor(os.path.join(ROOT, "asm", "ram", name + ".asm"))
        pairs = ram_rets(tr)
        why = ", ".join(f"{p['op']}(T{silicon_end_t(p['op'])}="
                        f"{silicon_end_t(p['op']):04b})->RET@{r['pc']:#06x}"
                        for p, r in pairs) or "no RAM RET"
        got = "halt" if rule_b_halts(tr) else "return"
        if name == "retjmp":
            check(got == "halt" and bench == "return",
                  f"retjmp: B says halt, bench RETURNED -> B falsified [{why}]")
            continue
        check(got == bench, f"{name}: rule B says {got}, bench {bench} "
                            f"[{why}] ({src})")


def test_rule_a_is_falsified_by_rethlsp():
    """Rule A ("ends at T >= 2") fit the first nine bench rows and predicted
    rethlsp would HALT. On silicon it RETURNED (2026-09-28). Kept so the
    dead rule cannot quietly come back."""
    _, tr = run_in_monitor(os.path.join(ROOT, "asm", "ram", "rethlsp.asm"))
    check(rule_halts(tr) and not rule_b_halts(tr),
          "rethlsp: A says halt (bench: return -> A falsified), B says return")


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print(f"\n{len(FAILS)} FAILED" if FAILS else "\nALL OK")
    sys.exit(1 if FAILS else 0)
