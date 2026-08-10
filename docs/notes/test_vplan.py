"""Host test for docs/notes/dino_fpga_vplan.md. Run:
    ~/.venvs/dino-fpga/bin/python -m pytest docs/notes/test_vplan.py -q
(plain python3 on this machine has no pytest installed).

This is the VPLAN's own drift guard, mirroring the 8008 precedent's own
VPLAN discipline: a table that nobody re-checks is worse than no table.
Things this file proves about docs/notes/dino_fpga_vplan.md:

1. every cited artifact PATH actually EXISTS on disk;
2. every cited FUNCTION (`path::name` citations) actually exists in that
   file, not just a plausible-looking name -- a path can exist while the
   function inside it does not, so this file mechanically checks
   function-level citations too, not just path-level ones;
3. every row's Status cell starts with one of the four legal keywords
   (COVERED-EXHAUSTIVE / COVERED-DIRECTED / COVERED-INCIDENTAL / GAP);
4. every COVERED-* row cites at least one artifact path -- INV-12 is the
   SOLE, EXPLICIT exception (a derived row, see ALLOWED_PATHLESS_COVERED
   below); a GAP row is exempt by definition;
5. KNOWN_GAPS below is a literal, hand-maintained set that must equal the
   table's actual GAP rows exactly. Adding a new GAP row to the table
   WITHOUT updating this literal fails the test -- the whole point
   (CLAUDE.md's "the gate is the gate" spirit applied to an audit
   document: it must not be able to silently rot wider).

Also includes test_assert_crc_guard_catches_content_mismatch and
test_prepare_roms_integration_does_not_raise_against_real_roms -- host
tests for fpga/sim/conftest_helpers.py's CRC guard (RES-06 in the VPLAN
table): content-verifies roms/*.bin on every prepare_roms() call, not
just when the mtime heuristic thinks a regeneration is due.

Finally, two "checker self-test" functions (test_checker_catches_*) RED-
check the two new guard clauses (2 and 4 above) against synthetic,
throwaway markdown text -- never mutating the real committed file --
proving the checker itself can fail, per CLAUDE.md's own "mutation-test
every checker" doctrine.
"""
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
VPLAN_MD = os.path.join(HERE, "dino_fpga_vplan.md")

# ---- KNOWN_GAPS: hand-maintained, must equal the table's real GAP set ----
# Adding a GAP row to dino_fpga_vplan.md without adding its ID here fails
# test_gap_set_matches_known_gaps below -- that IS the guard.
KNOWN_GAPS = frozenset({
    "ROM-07",   # src==dst register self-transfer: printed WARNING only
    "ROM-08",   # PC_UP-count-vs-byte-length mismatch: printed WARNING only
    "SYN-08",   # zero-inferred-latches: printed warning only, never parsed
    "RES-02",   # LDCI/NOP: no bench silicon ground truth
    "RES-07",   # fuzz_gen._MENU keeping NOP/LDCI: unenforced
})

# The ONE row allowed a COVERED-* status with zero path citations: INV-12
# is a DERIVED claim (the union of the surviving INV-01..INV-10 rows,
# stated in its own Check artifact cell as having no independent artifact).
# Every other COVERED-* row must cite >=1 real path.
ALLOWED_PATHLESS_COVERED = frozenset({"INV-12"})

LEGAL_STATUS_PREFIXES = (
    "COVERED-EXHAUSTIVE",
    "COVERED-DIRECTED",
    "COVERED-INCIDENTAL",
    "GAP",
)
# Order matters for prefix matching: none of these are prefixes of each
# other EXCEPT the trivial case (a status cell literally starting with
# one keyword, then optional trailing annotation like " (derived)" text)
# -- so first-match-wins is unambiguous.
_STATUS_RE = re.compile(
    r"^(" + "|".join(re.escape(p) for p in LEGAL_STATUS_PREFIXES) + r")\b")

_ROW_ID_RE = re.compile(r"^[A-Z]+-\d+$")

# Real repo-root top-level directories a citation might reasonably point
# into (the KiCad project dir and the burned-ROM dir included, not just
# fpga/docs/tests).
_PATH_ROOTS = ("fpga", "docs", "tests", "roms", "microcode", "dino_v0_0_2")
# Captures an optional trailing `::identifier` (a specific function/def
# inside the cited file) as its own group, so callers can verify it
# separately against the file's real content.
_PATH_RE = re.compile(
    r"\b(?:" + "|".join(_PATH_ROOTS) + r")/[A-Za-z0-9_./-]+"
    r"(?:::([A-Za-z_][A-Za-z0-9_]*))?")

_DEF_RE_TEMPLATE = r"^\s*(?:async\s+)?def\s+{name}\s*\("


def _split_row(line):
    """A markdown table data row -> list of stripped cells (no leading/
    trailing empty cells from the outer pipes). None of this table's
    cells contain a literal '|', so a naive split is safe -- verified by
    inspection (no `|` appears inside any cell in dino_fpga_vplan.md)."""
    parts = line.strip().split("|")
    # leading/trailing empty strings come from the row's outer pipes
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def _parse_rows(text):
    """Every real data row in the row table: (id, cells) pairs, in file
    order. Skips header rows ("| ID | ... |") and separator rows
    ("|----|...|") by requiring cell[0] to match _ROW_ID_RE -- neither
    "ID" nor "----" does."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = _split_row(line)
        if len(cells) < 7:
            continue
        if not _ROW_ID_RE.match(cells[0]):
            continue
        rows.append((cells[0], cells))
    return rows


def _extract_citations(artifact_cell):
    """artifact_cell -> list of (path_token, func_or_None), path_token
    with any trailing sentence punctuation stripped. func is the group
    captured after '::' (verified to exist as a def in that file by
    _check_citations below), or None if the citation is path-only."""
    out = []
    for m in _PATH_RE.finditer(artifact_cell):
        full = m.group(0)
        func = m.group(1)
        path_token = full[:-(len(func) + 2)] if func else full
        path_token = path_token.rstrip(".,;)")
        out.append((path_token, func))
    return out


def _check_citations(rows):
    """Core checker logic, factored out of the pytest test functions so
    test_checker_catches_* (below) can exercise it directly against
    synthetic rows without touching the real file. Returns
    (missing_paths, bad_functions, pathless_covered) -- three lists of
    (row_id, detail) findings; empty lists mean everything checked out."""
    missing_paths = []
    bad_functions = []
    pathless_covered = []
    for rid, cells in rows:
        status = cells[6]
        artifact_cell = cells[5]
        citations = _extract_citations(artifact_cell)
        for path_token, func in citations:
            full = os.path.join(REPO_ROOT, path_token)
            if not os.path.exists(full):
                missing_paths.append((rid, path_token))
                continue
            if func is not None:
                if not path_token.endswith(".py"):
                    bad_functions.append(
                        (rid, f"{path_token}::{func} -- '::name' citations "
                               f"are only meaningful for .py files"))
                    continue
                with open(full, encoding="utf-8") as f:
                    content = f.read()
                pat = re.compile(_DEF_RE_TEMPLATE.format(name=re.escape(func)),
                                  re.MULTILINE)
                if not pat.search(content):
                    bad_functions.append(
                        (rid, f"{path_token}::{func} -- no 'def {func}(' "
                               f"(or 'async def {func}(') found in {path_token}"))
        m = _STATUS_RE.match(status)
        is_covered = bool(m) and m.group(1) != "GAP"
        if is_covered and not citations and rid not in ALLOWED_PATHLESS_COVERED:
            pathless_covered.append((rid, status))
    return missing_paths, bad_functions, pathless_covered


@pytest.fixture(scope="module")
def vplan_text():
    with open(VPLAN_MD, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def rows(vplan_text):
    parsed = _parse_rows(vplan_text)
    assert parsed, f"no rows parsed out of {VPLAN_MD} -- table format changed?"
    return parsed


def test_row_ids_are_unique(rows):
    ids = [rid for rid, _ in rows]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate row IDs in dino_fpga_vplan.md: {sorted(dupes)}"


def test_every_row_has_a_legal_status(rows):
    bad = []
    for rid, cells in rows:
        status = cells[6]
        if not _STATUS_RE.match(status):
            bad.append((rid, status))
    assert not bad, (
        "rows with an illegal Status cell (must start with one of "
        f"{LEGAL_STATUS_PREFIXES}): {bad}")


def test_every_cited_artifact_path_exists(rows):
    missing, _, _ = _check_citations(rows)
    assert not missing, (
        "rows cite artifact paths that do not exist on disk: " + repr(missing))


def test_every_cited_function_exists(rows):
    """A `path::name` citation must resolve to a real `def name(...)` (or
    `async def name(...)`, cocotb's own decorator style) inside that
    file -- catches a citation naming a function that was never written,
    which the old path-only checker could not have caught (the FILE
    existed; the FUNCTION did not)."""
    _, bad_functions, _ = _check_citations(rows)
    assert not bad_functions, (
        "rows cite a function that does not exist in the named file: "
        + repr(bad_functions))


def test_every_covered_row_cites_at_least_one_path(rows):
    """A COVERED-* row with ZERO artifact citations is exactly as
    unfalsifiable as a mislabeled GAP -- the only sanctioned exception is
    INV-12 (ALLOWED_PATHLESS_COVERED), a derived row that says so
    explicitly in its own Check artifact cell."""
    _, _, pathless = _check_citations(rows)
    assert not pathless, (
        "COVERED-* rows with no artifact citation at all (add one, or add "
        f"the row ID to ALLOWED_PATHLESS_COVERED with a stated reason like "
        f"INV-12's): {pathless}")


def _gap_row_ids(rows):
    out = set()
    for rid, cells in rows:
        status = cells[6]
        m = _STATUS_RE.match(status)
        if m and m.group(1) == "GAP":
            out.add(rid)
    return out


def test_gap_set_matches_known_gaps(rows):
    actual_gaps = _gap_row_ids(rows)
    extra = actual_gaps - KNOWN_GAPS
    missing = KNOWN_GAPS - actual_gaps
    assert not extra, (
        f"dino_fpga_vplan.md has GAP row(s) not listed in this file's "
        f"KNOWN_GAPS: {sorted(extra)} -- add them to KNOWN_GAPS (this is "
        f"the guard working as intended: a new GAP cannot go unnoticed)")
    assert not missing, (
        f"KNOWN_GAPS lists row(s) that are no longer GAP in "
        f"dino_fpga_vplan.md (or were removed): {sorted(missing)} -- "
        f"update KNOWN_GAPS to match")


def test_header_gap_count_matches_table(vplan_text, rows):
    m = re.search(r"GAP count:\s*(\d+)", vplan_text)
    assert m, "dino_fpga_vplan.md header is missing a 'GAP count: N' line"
    header_count = int(m.group(1))
    actual = len(_gap_row_ids(rows))
    assert header_count == actual, (
        f"header says 'GAP count: {header_count}' but {actual} rows are "
        f"actually GAP -- header drifted from the table")
    assert header_count == len(KNOWN_GAPS), (
        f"header GAP count ({header_count}) != len(KNOWN_GAPS) "
        f"({len(KNOWN_GAPS)}) -- keep all three in lockstep")


def test_row_count_matches_header_claim(vplan_text, rows):
    m = re.search(r"of (\d+) rows", vplan_text)
    assert m, "dino_fpga_vplan.md header is missing an 'of N rows' claim"
    claimed = int(m.group(1))
    assert claimed == len(rows), (
        f"header claims {claimed} rows, but {len(rows)} were parsed out "
        f"of the actual table -- header drifted from the table")


# ---- checker self-tests: RED-check the two new guard clauses -------------
# CLAUDE.md's own doctrine ("NO BLIND COUNTERS", "mutation-test every
# checker; a checker that can't fail is a liability") applied to this
# file's own two guard clauses -- against SYNTHETIC markdown text only,
# never the real committed dino_fpga_vplan.md.
def test_checker_catches_bad_function_citation():
    fake_rows = [("ZZZ-01", [
        "ZZZ-01", "spec cite", "assertion", "conditions", "check type",
        "docs/notes/test_vplan.py::this_function_does_not_exist_anywhere",
        "COVERED-DIRECTED",
    ])]
    _, bad_functions, _ = _check_citations(fake_rows)
    assert bad_functions and bad_functions[0][0] == "ZZZ-01", (
        "checker failed to catch a citation naming a function that does "
        "not exist")

    # and the positive control: a real function must NOT be flagged
    fake_rows_good = [("ZZZ-02", [
        "ZZZ-02", "spec cite", "assertion", "conditions", "check type",
        "docs/notes/test_vplan.py::test_row_ids_are_unique",
        "COVERED-DIRECTED",
    ])]
    _, bad_functions_good, _ = _check_citations(fake_rows_good)
    assert not bad_functions_good, (
        f"checker false-flagged a function that genuinely exists: "
        f"{bad_functions_good}")


def test_checker_catches_covered_row_without_path():
    fake_rows = [("ZZZ-03", [
        "ZZZ-03", "spec cite", "assertion", "conditions", "check type",
        "no artifact citation here at all, just prose",
        "COVERED-DIRECTED",
    ])]
    _, _, pathless = _check_citations(fake_rows)
    assert pathless and pathless[0][0] == "ZZZ-03", (
        "checker failed to catch a COVERED-* row with zero path citations")

    # a GAP row with no citation must NOT be flagged (GAP is exempt)
    fake_rows_gap = [("ZZZ-04", [
        "ZZZ-04", "spec cite", "assertion", "conditions", "check type",
        "no artifact citation here either", "GAP",
    ])]
    _, _, pathless_gap = _check_citations(fake_rows_gap)
    assert not pathless_gap, (
        f"checker false-flagged a GAP row for having no path citation "
        f"(GAP rows are exempt by definition): {pathless_gap}")

    # the one sanctioned exception must also NOT be flagged
    fake_rows_exempt = [("INV-12", [
        "INV-12", "spec cite", "assertion", "conditions", "check type",
        "no artifact citation here, exempt by name",
        "COVERED-DIRECTED (derived)",
    ])]
    _, _, pathless_exempt = _check_citations(fake_rows_exempt)
    assert not pathless_exempt, (
        f"checker false-flagged the explicitly-sanctioned INV-12 exemption: "
        f"{pathless_exempt}")


# ---- RES-06: prepare_roms CRC guard ---------------------------------------
def test_assert_crc_guard_catches_content_mismatch(tmp_path):
    """Direct, isolated test of fpga/sim/conftest_helpers._assert_crc --
    never touches the real committed roms/ directory (CLAUDE.md rule 4:
    Rico burns the ROMs, this rig never hand-patches one). Confirms both
    halves: a matching file passes silently, a mismatched one raises a
    loud AssertionError naming the guard, per _assert_crc's own
    docstring contract. Also confirms a missing file raises a LABELED
    AssertionError, not a bare unlabeled FileNotFoundError."""
    pytest.importorskip("cocotb", reason="conftest_helpers.py imports cocotb")
    fpga_sim = os.path.join(REPO_ROOT, "fpga", "sim")
    if fpga_sim not in sys.path:
        sys.path.insert(0, fpga_sim)
    import conftest_helpers as ch

    good = b"\x01\x02\x03\x04\x05"
    p = tmp_path / "sample.bin"
    p.write_bytes(good)

    # matching content: no raise
    ch._assert_crc(str(p), good, ch.microcode_gen.crc16, "sample (match)")

    # mismatched content: raises, names the guard and the file
    corrupted_expectation = b"\x01\x02\x03\x04\x06"
    with pytest.raises(AssertionError, match="prepare_roms CRC guard"):
        ch._assert_crc(str(p), corrupted_expectation, ch.microcode_gen.crc16,
                        "sample (mismatch)")

    # missing file: a LABELED AssertionError, not a bare FileNotFoundError
    missing = tmp_path / "does_not_exist.bin"
    with pytest.raises(AssertionError, match="prepare_roms CRC guard"):
        ch._assert_crc(str(missing), good, ch.microcode_gen.crc16,
                        "sample (missing)")


def test_prepare_roms_integration_does_not_raise_against_real_roms():
    """Smoke-integration check: the CRC guard's addition to prepare_roms()
    does not break the real, normal path -- the actually-committed
    roms/*.bin must currently agree with a fresh in-memory rebuild (they
    do; nothing regenerates them out from under Rico's burned chips
    between commits). This is the same prepare_roms() call every
    fpga/sim/test_core_*.py and fpga/sim/test_module_*.py already makes
    as a fixture step -- idempotent, side-effect-only, safe to call here
    too."""
    pytest.importorskip("cocotb", reason="conftest_helpers.py imports cocotb")
    fpga_sim = os.path.join(REPO_ROOT, "fpga", "sim")
    if fpga_sim not in sys.path:
        sys.path.insert(0, fpga_sim)
    import conftest_helpers as ch

    ch.prepare_roms(tags=("real", "in"))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
