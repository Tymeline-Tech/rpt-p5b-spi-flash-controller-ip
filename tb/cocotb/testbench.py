"""Primary cocotb test module for spi_flash_ctrl (MODULE=testbench).

Directly drives the RTL top-level ports (APB slave + SPI master) without a
behavioral flash model. Detailed DUT wrapper / signal-mapping helpers are
added in a follow-on story.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


def _start_clock(dut, period_ns=10):
    """Start a free-running clock; support cocotb ``unit=`` and legacy ``units=``."""
    try:
        clock = Clock(dut.clk, period_ns, unit="ns")
    except TypeError:  # pragma: no cover - older cocotb
        clock = Clock(dut.clk, period_ns, units="ns")
    cocotb.start_soon(clock.start())


async def _timer_ns(duration_ns):
    try:
        await Timer(duration_ns, unit="ns")
    except TypeError:  # pragma: no cover - older cocotb
        await Timer(duration_ns, units="ns")


def _idle_host_inputs(dut):
    """Drive APB/SPI host-side inputs to a safe idle/reset state."""
    dut.psel.value = 0
    dut.penable.value = 0
    dut.pwrite.value = 0
    dut.paddr.value = 0
    dut.pwdata.value = 0
    dut.miso.value = 0


@cocotb.test()
async def test_reset(dut):
    """Compile/smoke harness: clock + reset release, check SPI/APB idle."""
    _start_clock(dut)

    dut.rst_n.value = 0
    _idle_host_inputs(dut)

    await _timer_ns(50)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)

    for _ in range(5):
        await RisingEdge(dut.clk)

    assert int(dut.cs_n.value) == 1, "SPI CS should idle high after reset"
    assert int(dut.pready.value) == 1, "APB pready should be ready after reset"
    assert int(dut.irq.value) == 0, "IRQ should be clear after reset"
