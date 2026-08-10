import cocotb
import itertools
from cocotb.triggers import Timer

# One test per gate-function package (all in this one file, per brief step
# 5), each exhaustive over every gate instance in the package and every
# input combination. The Makefile selects which single test runs for a
# given MODEL via COCOTB_TEST_FILTER (COCOTB_TESTCASE is deprecated in
# cocotb 2.x and its DeprecationWarning would make the run output non
# -pristine, so the Makefile sets the non-deprecated filter var instead).
# '04 and 'HC14 share identical port names and digital behavior (the
# Schmitt trigger's hysteresis is analog, out of scope for this structural
# model), so one inverter_truth_table test covers both entities.


@cocotb.test()
async def nand_truth_table(dut):
    for n in (1, 2, 3, 4):
        a = getattr(dut, f"a{n}")
        b = getattr(dut, f"b{n}")
        y = getattr(dut, f"y{n}")
        for av, bv in itertools.product((0, 1), repeat=2):
            a.value = av
            b.value = bv
            await Timer(1, unit="ns")
            exp = int(not (av and bv))
            assert y.value == exp, f"y{n}: a{n}={av} b{n}={bv} -> {y.value}, want {exp}"


@cocotb.test()
async def nor_truth_table(dut):
    for n in (1, 2, 3, 4):
        a = getattr(dut, f"a{n}")
        b = getattr(dut, f"b{n}")
        y = getattr(dut, f"y{n}")
        for av, bv in itertools.product((0, 1), repeat=2):
            a.value = av
            b.value = bv
            await Timer(1, unit="ns")
            exp = int(not (av or bv))
            assert y.value == exp, f"y{n}: a{n}={av} b{n}={bv} -> {y.value}, want {exp}"


@cocotb.test()
async def and_truth_table(dut):
    for n in (1, 2, 3, 4):
        a = getattr(dut, f"a{n}")
        b = getattr(dut, f"b{n}")
        y = getattr(dut, f"y{n}")
        for av, bv in itertools.product((0, 1), repeat=2):
            a.value = av
            b.value = bv
            await Timer(1, unit="ns")
            exp = int(av and bv)
            assert y.value == exp, f"y{n}: a{n}={av} b{n}={bv} -> {y.value}, want {exp}"


@cocotb.test()
async def inverter_truth_table(dut):
    for n in range(1, 7):
        a = getattr(dut, f"a{n}")
        y = getattr(dut, f"y{n}")
        for av in (0, 1):
            a.value = av
            await Timer(1, unit="ns")
            exp = int(not av)
            assert y.value == exp, f"y{n}: a{n}={av} -> {y.value}, want {exp}"
