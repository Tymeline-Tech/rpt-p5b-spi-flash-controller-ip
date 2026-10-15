"""Primary cocotb test module for spi_flash_ctrl (MODULE=testbench).

Provides ``SpiFlashDUT``, a thin wrapper around the cocotb DUT handle that
maps APB slave and SPI master ports to named Python attributes and offers a
shared ``reset()`` coroutine. No behavioral flash model is required here.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from flash_model import (
    CMD_FAST_READ,
    CMD_PAGE_PROGRAM,
    CMD_READ,
    CMD_READ_STATUS,
    CMD_SECTOR_ERASE,
    CMD_WRITE_ENABLE,
    FAST_READ_DUMMY_CYCLES,
    MEMORY_SIZE,
    SECTOR_SIZE,
    FlashState,
    SpiNorFlash,
    SR_WEL,
)


def _spi_transfer_byte(flash: SpiNorFlash, byte_val: int) -> None:
    """Drive eight MOSI bits MSB-first, sampling on rising SCLK (Mode 0/3)."""
    for i in range(7, -1, -1):
        bit = (int(byte_val) >> i) & 1
        flash.process_sclk_mosi(0, bit)
        flash.process_sclk_mosi(1, bit)


def _spi_dummy_clocks(flash: SpiNorFlash, n: int, mosi: int = 0) -> None:
    """Toggle SCLK ``n`` times (rising-edge samples) without meaningful MOSI."""
    for _ in range(int(n)):
        flash.process_sclk_mosi(0, mosi)
        flash.process_sclk_mosi(1, mosi)


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

    # --- process_sclk_mosi: Write Enable (0x06) -----------------------------
    flash.clear_write_enable()
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_WRITE_ENABLE)
    assert flash.wel == 1
    assert flash.command == CMD_WRITE_ENABLE
    assert flash.state is FlashState.COMMAND
    flash.reset_transaction()

    # --- process_sclk_mosi: Read Status (0x05) → DATA -----------------------
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_READ_STATUS)
    assert flash.command == CMD_READ_STATUS
    assert flash.state is FlashState.DATA
    flash.reset_transaction()

    # --- process_sclk_mosi: Read (0x03) Command → Address → Data ------------
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_READ)
    assert flash.state is FlashState.ADDRESS
    _spi_transfer_byte(flash, 0x00)
    _spi_transfer_byte(flash, 0x12)
    assert flash.addr_byte_count == 2
    _spi_transfer_byte(flash, 0x34)
    assert flash.address == 0x001234
    assert flash.state is FlashState.DATA
    assert flash.dummy_cycles_remaining == 0
    flash.reset_transaction()

    # --- process_sclk_mosi: Fast Read (0x0B) with dummy cycles --------------
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_FAST_READ)
    _spi_transfer_byte(flash, 0x00)
    _spi_transfer_byte(flash, 0x00)
    _spi_transfer_byte(flash, 0x10)
    assert flash.state is FlashState.DATA
    assert flash.dummy_cycles_remaining == FAST_READ_DUMMY_CYCLES
    _spi_dummy_clocks(flash, FAST_READ_DUMMY_CYCLES)
    assert flash.dummy_cycles_remaining == 0
    flash.reset_transaction()

    # --- process_sclk_mosi: Page Program (0x02) requires WEL ----------------
    # Without WEL: memory must not change.
    prog_addr = 0x3000
    flash.write_byte(prog_addr, 0xFF)
    flash.clear_write_enable()
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_PAGE_PROGRAM)
    _spi_transfer_byte(flash, (prog_addr >> 16) & 0xFF)
    _spi_transfer_byte(flash, (prog_addr >> 8) & 0xFF)
    _spi_transfer_byte(flash, prog_addr & 0xFF)
    assert flash.state is FlashState.DATA
    _spi_transfer_byte(flash, 0xA5)
    assert flash.read_byte(prog_addr) == 0xFF
    assert flash.wel == 0
    flash.reset_transaction()

    # With WEL: program ANDs data into memory and clears WEL.
    flash.write_byte(prog_addr, 0xFF)
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_WRITE_ENABLE)
    flash.reset_transaction()
    assert flash.wel == 1

    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_PAGE_PROGRAM)
    _spi_transfer_byte(flash, (prog_addr >> 16) & 0xFF)
    _spi_transfer_byte(flash, (prog_addr >> 8) & 0xFF)
    _spi_transfer_byte(flash, prog_addr & 0xFF)
    _spi_transfer_byte(flash, 0xA5)
    assert flash.read_byte(prog_addr) == 0xA5
    assert flash.wel == 0
    flash.reset_transaction()

    # --- process_sclk_mosi: Sector Erase (0x20) requires WEL ----------------
    erase_addr = 0x4000
    sector_base = erase_addr & ~(SECTOR_SIZE - 1)
    flash.write_bytes(sector_base, bytes([0x5A] * 16))
    flash.clear_write_enable()
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_SECTOR_ERASE)
    _spi_transfer_byte(flash, (erase_addr >> 16) & 0xFF)
    _spi_transfer_byte(flash, (erase_addr >> 8) & 0xFF)
    _spi_transfer_byte(flash, erase_addr & 0xFF)
    # WEL was clear — sector must remain unchanged.
    assert flash.read_byte(sector_base) == 0x5A
    flash.reset_transaction()

    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_WRITE_ENABLE)
    flash.reset_transaction()
    assert flash.wel == 1

    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_SECTOR_ERASE)
    _spi_transfer_byte(flash, (erase_addr >> 16) & 0xFF)
    _spi_transfer_byte(flash, (erase_addr >> 8) & 0xFF)
    _spi_transfer_byte(flash, erase_addr & 0xFF)
    assert flash.read_byte(sector_base) == 0xFF
    assert flash.read_byte(sector_base + 15) == 0xFF
    assert flash.wel == 0

    for _ in range(2):
        await RisingEdge(tb.pclk)
