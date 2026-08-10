import cocotb
from cocotb.triggers import Timer


@cocotb.test()
async def bus_hands_off_between_drivers(dut):
    dut.a_val.value = 0x55
    dut.b_val.value = 0xAA
    dut.en_a_n.value = 0
    dut.en_b_n.value = 1
    await Timer(10, units="ns")
    assert dut.y.value == 0x55, f"driver A enabled: y={dut.y.value} not 0x55"
    dut.en_a_n.value = 1
    dut.en_b_n.value = 0
    await Timer(10, units="ns")
    assert dut.y.value == 0xAA, f"driver B enabled: y={dut.y.value} not 0xAA"
