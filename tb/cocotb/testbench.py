"""Primary cocotb test module for spi_flash_ctrl (MODULE=testbench).

Provides ``SpiFlashDUT``, a thin wrapper around the cocotb DUT handle that
maps APB slave and SPI master ports to named Python attributes and offers a
shared ``reset()`` coroutine. No behavioral flash model is required here.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from flash_model import (
    CMD_WRITE_ENABLE,
    MEMORY_SIZE,
    FlashState,
    SpiNorFlash,
    SR_WEL,
)


def _start_clock(signal, period_ns=10):
    """Start a free-running clock; support cocotb ``unit=`` and legacy ``units=``."""
    try:
        clock = Clock(signal, period_ns, unit="ns")
    except TypeError:  # pragma: no cover - older cocotb
        clock = Clock(signal, period_ns, units="ns")
    cocotb.start_soon(clock.start())


async def _timer_ns(duration_ns):
    try:
        await Timer(duration_ns, unit="ns")
    except TypeError:  # pragma: no cover - older cocotb
        await Timer(duration_ns, units="ns")


class SpiFlashDUT:
    """Wrapper around the ``spi_flash_ctrl`` cocotb handle.

    Maps APB slave and SPI master signals to Python attributes for easy access.
    RTL port names are lowercase (``clk``, ``rst_n``, ``perror``, ``cs_n``);
    conventional APB aliases (``PCLK``, ``PRESETN``, ``PSLVERR``, ``CSN``) are
    also exposed for readability in stimulus code.
    """

    def __init__(self, dut):
        self.dut = dut

        # Clock / reset (APB PCLK / PRESETN equivalents on this IP)
        self.pclk = dut.clk
        self.presetn = dut.rst_n
        self.clk = dut.clk
        self.rst_n = dut.rst_n

        # APB3 slave
        self.psel = dut.psel
        self.penable = dut.penable
        self.pwrite = dut.pwrite
        self.paddr = dut.paddr
        self.pwdata = dut.pwdata
        self.prdata = dut.prdata
        self.pready = dut.pready
        # RTL uses ``perror`` for the APB slave error response (PSLVERR)
        self.pslverr = dut.perror
        self.perror = dut.perror

        # Interrupt
        self.irq = dut.irq

        # SPI master
        self.sclk = dut.sclk
        self.mosi = dut.mosi
        self.miso = dut.miso
        self.csn = dut.cs_n
        self.cs_n = dut.cs_n

        # Uppercase aliases matching classic APB/SPI naming from the story
        self.PCLK = self.pclk
        self.PRESETN = self.presetn
        self.PSEL = self.psel
        self.PENABLE = self.penable
        self.PWRITE = self.pwrite
        self.PADDR = self.paddr
        self.PWDATA = self.pwdata
        self.PRDATA = self.prdata
        self.PREADY = self.pready
        self.PSLVERR = self.pslverr
        self.SCLK = self.sclk
        self.MOSI = self.mosi
        self.MISO = self.miso
        self.CSN = self.csn

    def idle_host_inputs(self):
        """Drive APB host and SPI MISO inputs to a safe idle state."""
        self.psel.value = 0
        self.penable.value = 0
        self.pwrite.value = 0
        self.paddr.value = 0
        self.pwdata.value = 0
        self.miso.value = 0

    async def reset(self, cycles=11):
        """Assert active-low reset for ``cycles`` clock edges (must be >10).

        Host inputs are held idle while reset is asserted. Reset is then
        deasserted and one extra rising edge is waited so the DUT samples
        the released reset.
        """
        if cycles <= 10:
            raise ValueError("reset must be held for more than 10 cycles")

        self.presetn.value = 0
        self.idle_host_inputs()

        for _ in range(cycles):
            await RisingEdge(self.pclk)

        self.presetn.value = 1
        await RisingEdge(self.pclk)


@cocotb.test()
async def test_reset(dut):
    """Compile/smoke harness: clock + DUT wrapper reset, check SPI/APB idle."""
    tb = SpiFlashDUT(dut)
    _start_clock(tb.pclk)

    # Allow the clock to start before driving a multi-cycle reset.
    await _timer_ns(20)
    await tb.reset(cycles=11)

    for _ in range(5):
        await RisingEdge(tb.pclk)

    assert int(tb.csn.value) == 1, "SPI CS should idle high after reset"
    assert int(tb.pready.value) == 1, "APB pready should be ready after reset"
    assert int(tb.irq.value) == 0, "IRQ should be clear after reset"


@cocotb.test()
async def test_flash_model_unit(dut):
    """Unit-test SpiNorFlash memory array, WEL latch, and SPI state machine.

    Exercises the behavioral model directly (no SPI bit-banging yet). The DUT
    is only brought out of reset so the cocotb+Icarus harness stays valid.
    """
    tb = SpiFlashDUT(dut)
    _start_clock(tb.pclk)
    await _timer_ns(20)
    await tb.reset(cycles=11)

    flash = SpiNorFlash()

    # --- memory array -------------------------------------------------------
    assert isinstance(flash.memory, (bytearray, bytes))
    assert len(flash.memory) == MEMORY_SIZE == 128 * 1024
    assert flash.wel == 0
    assert flash.state is FlashState.IDLE

    flash.write_byte(0x0000, 0xA5)
    flash.write_byte(0x0100, 0x5A)
    assert flash.read_byte(0x0000) == 0xA5
    assert flash.read_byte(0x0100) == 0x5A

    payload = bytes([0x11, 0x22, 0x33, 0x44])
    flash.write_bytes(0x2000, payload)
    assert bytes(flash.read_bytes(0x2000, 4)) == payload

    # Address wrap within 128 KiB
    flash.write_byte(MEMORY_SIZE + 7, 0x77)
    assert flash.read_byte(7) == 0x77

    # --- WEL latch ----------------------------------------------------------
    assert flash.status_register() & SR_WEL == 0
    assert not flash.write_enabled()

    flash.set_write_enable()
    assert flash.wel == 1
    assert flash.write_enabled()
    assert flash.status_register() & SR_WEL

    flash.clear_write_enable()
    assert flash.wel == 0
    assert not flash.write_enabled()

    flash.apply_write_enable_command()
    assert flash.wel == 1
    assert flash.command == CMD_WRITE_ENABLE

    # --- SPI status state machine -------------------------------------------
    flash.reset_transaction()
    assert flash.state is FlashState.IDLE

    flash.begin_transaction()
    assert flash.state is FlashState.COMMAND

    flash.command = 0x03
    flash.advance_to_address()
    assert flash.state is FlashState.ADDRESS

    flash.advance_to_data(dummy_cycles=0)
    assert flash.state is FlashState.DATA
    assert flash.dummy_cycles_remaining == 0

    flash.reset_transaction()
    flash.begin_transaction()
    flash.command = 0x0B
    flash.advance_to_address()
    flash.advance_to_data(dummy_cycles=8)
    assert flash.state is FlashState.DATA
    assert flash.dummy_cycles_remaining == 8

    flash.reset_transaction()
    assert flash.state is FlashState.IDLE
    # WEL is independent of CSN / transaction reset
    assert flash.wel == 1

    for _ in range(2):
        await RisingEdge(tb.pclk)
