"""Minimal cocotb smoke test — proves simulate entry point and emits coverage."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_coverage.coverage import CoverPoint, coverage_db


@CoverPoint("smoke.rst_released", xf=lambda rst_n: int(rst_n.value), bins=[0, 1])
def sample_rst(rst_n):
    pass


@cocotb.test()
async def test_reset_and_idle(dut):
    """Drive clock/reset and confirm stub idle outputs."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    dut.rst_n.value = 0
    dut.psel.value = 0
    dut.penable.value = 0
    dut.pwrite.value = 0
    dut.paddr.value = 0
    dut.pwdata.value = 0
    dut.miso.value = 0

    await Timer(50, unit="ns")
    sample_rst(dut.rst_n)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    sample_rst(dut.rst_n)

    for _ in range(5):
        await RisingEdge(dut.clk)

    assert int(dut.cs_n.value) == 1, "SPI CS should idle high"
    assert int(dut.pready.value) == 1, "APB pready should be ready in stub"
    assert int(dut.irq.value) == 0, "IRQ should be clear at idle"

    # Emit exactly one coverage*.xml at repo root for the verification gate.
    coverage_db.export_to_xml(filename="../coverage.xml")
