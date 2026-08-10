import cocotb
from cocotb.triggers import Timer
from cocotb.types import LogicArray

RELEASE = LogicArray("ZZZZZZZZ")


@cocotb.test()
async def xcvr_drives_both_directions(dut):
    # a -> b direction: dir='1' selects a as the input side.
    dut.oe_n.value = 0
    dut.dir.value = 1
    dut.a.value = 0x3C
    await Timer(10, units="ns")
    assert dut.b.value == 0x3C, f"dir=1: b={dut.b.value} not 0x3C"

    # Release our drive on 'a' before the RTL takes over driving it,
    # or the testbench's stale poke fights the real driver.
    dut.a.value = RELEASE
    await Timer(10, units="ns")

    # b -> a direction: dir='0' selects b as the input side.
    dut.dir.value = 0
    dut.b.value = 0xC3
    await Timer(10, units="ns")
    assert dut.a.value == 0xC3, f"dir=0: a={dut.a.value} not 0xC3"
