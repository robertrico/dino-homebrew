#!/usr/bin/env bash
# run_cocotb_ladder.sh -- `make -C fpga verify` (below) never ran the
# cocotb testbench ladder (fpga/ttl/test_*.py's 18 chip models,
# fpga/sim/test_module_*.py's 9 sheet models, test_core_milestone.py's 2
# whole-core cases, test_core_coverage.py's 8 coverage-image cases -- 37
# `make` invocations total). There is no all-models target in
# fpga/ttl/Makefile or fpga/sim/Makefile (each `make` runs exactly one
# MODEL/MODULE_UNDER_TEST/TESTCASE combination, and dino_core's ROM
# content is a GHDL generic fixed at elaboration -- see
# test_core_fuzz.py's own header for why -- so each TESTCASE needs its
# own invocation with the matching DINO_PROG_HEX). This script IS that
# missing all-models loop.
#
# TTL_MODELS is derived from the actual fpga/ttl/*.vhd files on disk (no
# hand-kept list to drift) -- CLAUDE.md: "everything is generated,
# nothing is retyped" applies to a shell loop's inputs too, not just
# Python. SIM_MODULES hand-mirrors fpga/synth/check_images.py's own
# GEN_SHEETS list -- the same "no Python in this script's critical path"
# convention fpga/Makefile, fpga/postsynth/Makefile, and fpga/sim/Makefile
# already use for the identical list.
#
# Fails LOUD at the first red step (`|| exit 1` per item, not
# collect-and-report) -- read the failing invocation's own results.xml
# (fpga/ttl/results.xml or fpga/sim/results.xml) for the specific
# failure, same as every other cocotb stage in this repo.
#
# Usage: fpga/run_cocotb_ladder.sh
# (no flags; run from anywhere, this script cd's for you, same
# convention as every other run_*.sh in this repo)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"      # fpga/
TOOLS="$HOME/oss-cad-suite/bin"
VENV="$HOME/.venvs/dino-fpga/bin"
export PATH="$VENV:$TOOLS:$PATH"

cd "$HERE"

# 18 TTL chip models -- every fpga/ttl/*.vhd file, stripped of the ttl/
# prefix and .vhd suffix. Globbing the real directory instead of a
# hand-kept list means this loop can never silently fall behind an added
# or removed model.
TTL_MODELS=$(cd ttl && for f in *.vhd; do basename "$f" .vhd; done)

# 9 sheet models -- fpga/synth/check_images.py's own GEN_SHEETS list (the
# same 9 entities dino_core.vhd instantiates; hand-mirrored here per this
# repo's existing convention for shell contexts with no Python in their
# critical path -- see fpga/Makefile's own GEN_SHEETS comment).
SIM_MODULES="alu control_word input_output mar mdr memory microcode program_counter registers_a_b"

n=0
echo "=== cocotb ladder: 18 TTL models ==="
for model in $TTL_MODELS; do
    n=$((n+1))
    echo "--- [$n] ttl MODEL=$model ---"
    make -C ttl MODEL="$model" || { echo "COCOTB LADDER FAILED: ttl MODEL=$model" >&2; exit 1; }
done

echo "=== cocotb ladder: 9 sheet modules ==="
for mod in $SIM_MODULES; do
    n=$((n+1))
    echo "--- [$n] sim MODULE_UNDER_TEST=$mod ---"
    make -C sim MODULE_UNDER_TEST="$mod" || { echo "COCOTB LADDER FAILED: sim MODULE_UNDER_TEST=$mod" >&2; exit 1; }
done

echo "=== cocotb ladder: whole-core milestone (2 cases) ==="
n=$((n+1))
echo "--- [$n] dino_core milestone_free_runs_to_4d ---"
make -C sim MODULE_UNDER_TEST=dino_core MODULE=test_core_milestone \
    TESTCASE=milestone_free_runs_to_4d || {
    echo "COCOTB LADDER FAILED: milestone_free_runs_to_4d" >&2; exit 1; }
n=$((n+1))
echo "--- [$n] dino_core in_tracks_switches ---"
make -C sim MODULE_UNDER_TEST=dino_core MODULE=test_core_milestone \
    TESTCASE=in_tracks_switches DINO_PROG_HEX=hex/PROG_in.hex || {
    echo "COCOTB LADDER FAILED: in_tracks_switches" >&2; exit 1; }

echo "=== cocotb ladder: whole-core coverage (8 tags) ==="
# tag:testcase pairs -- test_core_coverage.py's own @cocotb.test() names,
# each against its matching hex/PROG_<tag>.hex (conftest_helpers.
# prepare_roms() regenerates every progrom_gen.COVERAGE tag's hex up
# front, so every one of these exists before this loop runs).
COVERAGE_CASES="alu:alu_covers_every_sa_code mem:mem_witnesses_mar_as_a_latch \
flow:flow_takes_the_jump_and_falls_through loop:loop_takes_the_jnz_branch \
adda:adda_isolates_tmp_a addb:addb_isolates_tmp_b \
mardisc:mardisc_discriminates_mar_lo pads:pads_lands_the_jmp_at_the_named_pad"
for pair in $COVERAGE_CASES; do
    tag="${pair%%:*}"
    testcase="${pair##*:}"
    n=$((n+1))
    echo "--- [$n] dino_core coverage tag=$tag testcase=$testcase ---"
    make -C sim MODULE_UNDER_TEST=dino_core MODULE=test_core_coverage \
        TESTCASE="$testcase" DINO_PROG_HEX="hex/PROG_${tag}.hex" || {
        echo "COCOTB LADDER FAILED: coverage tag=$tag testcase=$testcase" >&2
        exit 1; }
done

echo "=== cocotb ladder: ALL $n invocations GREEN (18 ttl + 9 sim + 2 milestone + 8 coverage) ==="
