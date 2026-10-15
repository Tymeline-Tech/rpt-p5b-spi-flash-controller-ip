"""Minimal cocotb smoke test — proves simulate entry point against RTL."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

try:
    from cocotb_coverage.coverage import CoverPoint, coverage_db

    @CoverPoint("smoke.rst_released", xf=lambda rst_n: int(rst_n.value), bins=[0, 1])
    def sample_rst(rst_n):
        pass

    HAVE_COVERAGE = True
except ImportError:  # pragma: no cover - optional in some environments
    def sample_rst(rst_n):
        pass

    HAVE_COVERAGE = False


def _start_clock(dut, period_ns=10):
    """Start a clock; support both cocotb ``unit=`` and legacy ``units=``."""
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


@cocotb.test()
async def test_reset_and_idle(dut):
    """Start clock, apply reset, then check an idle SPI/APB signal."""
    _start_clock(dut)

    dut.rst_n.value = 0
    dut.psel.value = 0
    dut.penable.value = 0
    dut.pwrite.value = 0
    dut.paddr.value = 0
    dut.pwdata.value = 0
    dut.miso.value = 0

    await _timer_ns(50)
    sample_rst(dut.rst_n)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    sample_rst(dut.rst_n)

    for _ in range(5):
        await RisingEdge(dut.clk)

    assert int(dut.cs_n.value) == 1, "SPI CS should idle high"
    assert int(dut.pready.value) == 1, "APB pready should be ready"
    assert int(dut.irq.value) == 0, "IRQ should be clear at idle"

    if HAVE_COVERAGE:
        # Exactly one coverage*.xml for gates that scan the repo root.
        coverage_db.export_to_xml(filename="../coverage.xml")
