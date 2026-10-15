"""Primary cocotb test module for spi_flash_ctrl (MODULE=testbench).

Provides ``SpiFlashDUT``, a thin wrapper around the cocotb DUT handle that
maps APB slave and SPI master ports to named Python attributes, offers a
shared ``reset()`` coroutine, and an APB3 master driver (``apb_write`` /
``apb_read``) with register-map helpers. Instantiates ``SpiNorFlash`` and a
SPI pin bridge for end-to-end host↔flash smoke tests.
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

# ---------------------------------------------------------------------------
# Register map (byte offsets on PADDR) — matches rtl/spi_reg_block.sv
# ---------------------------------------------------------------------------
ADDR_CTRL = 0x00
ADDR_STATUS = 0x04
ADDR_CMD = 0x08
ADDR_ADDR = 0x0C
ADDR_DATA = 0x10  # TX FIFO write (APB write) / RX FIFO read (APB read)
ADDR_CLKDIV = 0x14

# Host-facing aliases (story / verification plan naming)
REG_CTRL = ADDR_CTRL
REG_STATUS = ADDR_STATUS
REG_CMD = ADDR_CMD
REG_ADDR = ADDR_ADDR
REG_TX_DATA = ADDR_DATA
REG_RX_DATA = ADDR_DATA
REG_CFG = ADDR_CLKDIV
REG_CLKDIV = ADDR_CLKDIV

# CTRL bits: [0]=START, [2:1]=MODE
CTRL_START = 0x1
CTRL_MODE_SHIFT = 1

# STATUS bits: [0]=BUSY, [1]=IRQ, [2]=TXF, [3]=RXE
STATUS_BUSY = 0x1
STATUS_IRQ = 0x2
STATUS_TXF = 0x4
STATUS_RXE = 0x8


def _spi_transfer_byte(flash: SpiNorFlash, byte_val: int) -> None:
    """Drive eight MOSI bits MSB-first, sampling on rising SCLK (Mode 0/3)."""
    for i in range(7, -1, -1):
        bit = (int(byte_val) >> i) & 1
        flash.process_sclk_mosi(0, bit)
        flash.process_sclk_mosi(1, bit)


def _spi_transfer_byte_miso(flash: SpiNorFlash, byte_val: int = 0) -> int:
    """Drive eight MOSI bits and capture the MISO byte (MSB-first).

    Samples ``get_miso()`` after each rising SCLK edge, matching Mode 0/3
    master sampling of the flash model's shift-out.
    """
    miso_byte = 0
    for i in range(7, -1, -1):
        bit = (int(byte_val) >> i) & 1
        flash.process_sclk_mosi(0, bit)
        flash.process_sclk_mosi(1, bit)
        miso_byte = ((miso_byte << 1) | flash.get_miso()) & 0xFF
    return miso_byte


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

    # ------------------------------------------------------------------
    # APB3 master driver (PSEL / PENABLE / PWRITE setup → wait PREADY)
    # ------------------------------------------------------------------
    async def apb_write(self, addr: int, data: int) -> None:
        """APB 3.0 write transfer to ``addr`` with ``data``.

        Setup phase: PSEL=1, PENABLE=0, PWRITE=1, drive PADDR/PWDATA.
        Access phase: PENABLE=1, wait until PREADY, then return to idle.
        """
        addr = int(addr) & 0xFFFFFFFF
        data = int(data) & 0xFFFFFFFF

        await RisingEdge(self.pclk)
        self.psel.value = 1
        self.penable.value = 0
        self.pwrite.value = 1
        self.paddr.value = addr
        self.pwdata.value = data

        await RisingEdge(self.pclk)
        self.penable.value = 1

        await RisingEdge(self.pclk)
        while int(self.pready.value) == 0:
            await RisingEdge(self.pclk)

        self.psel.value = 0
        self.penable.value = 0
        self.pwrite.value = 0

    async def apb_read(self, addr: int) -> int:
        """APB 3.0 read transfer from ``addr``; return captured PRDATA.

        Setup phase: PSEL=1, PENABLE=0, PWRITE=0, drive PADDR.
        Access phase: PENABLE=1, wait until PREADY, sample PRDATA, idle.
        """
        addr = int(addr) & 0xFFFFFFFF

        await RisingEdge(self.pclk)
        self.psel.value = 1
        self.penable.value = 0
        self.pwrite.value = 0
        self.paddr.value = addr
        self.pwdata.value = 0

        await RisingEdge(self.pclk)
        self.penable.value = 1

        await RisingEdge(self.pclk)
        while int(self.pready.value) == 0:
            await RisingEdge(self.pclk)

        data = int(self.prdata.value) & 0xFFFFFFFF

        self.psel.value = 0
        self.penable.value = 0
        return data

    # ------------------------------------------------------------------
    # Register helpers (CTRL / STATUS / CMD / ADDR / TX / RX / CFG)
    # ------------------------------------------------------------------
    async def write_ctrl(self, data: int) -> None:
        """Write the CTRL register (START / MODE)."""
        await self.apb_write(ADDR_CTRL, data)

    async def write_cmd(self, cmd: int) -> None:
        """Write the CMD register (SPI opcode)."""
        await self.apb_write(ADDR_CMD, int(cmd) & 0xFF)

    async def write_addr(self, addr: int) -> None:
        """Write the ADDR register (24-bit flash address)."""
        await self.apb_write(ADDR_ADDR, int(addr) & 0xFFFFFF)

    async def write_tx_data(self, data: int) -> None:
        """Push one byte into the TX FIFO via the DATA register."""
        await self.apb_write(REG_TX_DATA, int(data) & 0xFF)

    async def write_cfg(self, clk_div: int) -> None:
        """Write the CFG / CLKDIV register."""
        await self.apb_write(REG_CFG, int(clk_div) & 0xFF)

    async def write_clkdiv(self, clk_div: int) -> None:
        """Alias for ``write_cfg`` (matches RTL ``ADDR_CLKDIV``)."""
        await self.write_cfg(clk_div)

    async def read_status(self) -> int:
        """Read the STATUS register."""
        return await self.apb_read(ADDR_STATUS)

    async def read_ctrl(self) -> int:
        """Read the CTRL register."""
        return await self.apb_read(ADDR_CTRL)

    async def read_cmd(self) -> int:
        """Read the CMD register."""
        return await self.apb_read(ADDR_CMD)

    async def read_addr(self) -> int:
        """Read the ADDR register."""
        return await self.apb_read(ADDR_ADDR)

    async def read_rx_data(self) -> int:
        """Pop one byte from the RX FIFO via the DATA register."""
        return await self.apb_read(REG_RX_DATA) & 0xFF

    async def read_cfg(self) -> int:
        """Read the CFG / CLKDIV register."""
        return await self.apb_read(REG_CFG)

    async def clear_irq(self) -> None:
        """Clear the pending interrupt by writing STATUS."""
        await self.apb_write(ADDR_STATUS, 0xFFFFFFFF)

    async def start_transaction(self, spi_mode: int = 0) -> None:
        """Pulse CTRL.START with the given SPI mode (0 or 3)."""
        mode = int(spi_mode) & 0x3
        await self.write_ctrl(CTRL_START | (mode << CTRL_MODE_SHIFT))

    async def wait_not_busy(self, timeout_cycles: int = 5000) -> int:
        """Poll STATUS until BUSY clears; return the final STATUS value."""
        status = await self.read_status()
        for _ in range(int(timeout_cycles)):
            if not (status & STATUS_BUSY):
                return status
            await RisingEdge(self.pclk)
            status = await self.read_status()
        raise TimeoutError(
            f"STATUS.BUSY stuck set after {timeout_cycles} polls "
            f"(last STATUS=0x{status:x})"
        )


async def spi_flash_bridge(tb: SpiFlashDUT, flash_model: SpiNorFlash):
    """Bridge DUT SPI pins to ``SpiNorFlash`` (monitor SCLK/MOSI/CSN, drive MISO).

    Samples the DUT each PCLK rising edge (after RTL NBA updates), feeds
    ``process_sclk_mosi``, and drives ``miso`` from ``get_miso()``. On CSN
    assert/deassert the model begins/resets a transaction.

    When the model enters DATA for a MISO-producing command, the first status
    / memory bit is primed immediately so it is valid before the DUT's next
    rising-SCLK sample (Mode 0/3 master samples on the rising edge; the
    behavioral model advances MISO on that same edge, one half-cycle late if
    only driven from Python after the NBA region).
    """
    prev_csn = 1
    while True:
        await RisingEdge(tb.pclk)

        try:
            csn = int(tb.csn.value)
            sclk = int(tb.sclk.value)
            mosi = int(tb.mosi.value)
        except ValueError:
            # X/Z during early reset — hold MISO idle
            tb.miso.value = 0
            continue

        if prev_csn == 1 and csn == 0:
            flash_model.begin_transaction()
            # Sync edge detector to the Mode 0/3 idle level so the first
            # real SCLK edge is not missed or double-detected (Mode 3 idles high).
            flash_model._prev_sclk = sclk
        elif prev_csn == 0 and csn == 1:
            flash_model.reset_transaction()

        if csn == 0:
            prev_state = flash_model.state
            prev_dummy = flash_model.dummy_cycles_remaining
            flash_model.process_sclk_mosi(sclk, mosi)

            # Prime first MISO bit when a MISO-producing DATA phase becomes
            # ready: either on COMMAND/ADDRESS → DATA (Read/RDSR), or when
            # Fast Read dummy clocks count down to zero.
            entered_data = (
                prev_state is not FlashState.DATA
                and flash_model.state is FlashState.DATA
            )
            dummy_done = (
                prev_dummy > 0 and flash_model.dummy_cycles_remaining == 0
            )
            if (
                flash_model.command
                in (CMD_READ, CMD_FAST_READ, CMD_READ_STATUS)
                and flash_model.state is FlashState.DATA
                and flash_model.dummy_cycles_remaining == 0
                and (entered_data or dummy_done)
            ):
                flash_model._clock_miso()

            tb.miso.value = flash_model.get_miso()
        else:
            tb.miso.value = 0

        prev_csn = csn


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
async def test_apb_driver(dut):
    """Exercise APB3 master driver against the register block.

    Writes/reads CTRL, STATUS, CMD, ADDR, TX DATA, and CFG via
    ``apb_write`` / ``apb_read`` and the register helpers. Does not
    start an SPI transaction or require the flash model.
    """
    tb = SpiFlashDUT(dut)
    _start_clock(tb.pclk)
    await _timer_ns(20)
    await tb.reset(cycles=11)

    # STATUS after reset: RX empty, TX not full, IRQ clear, not busy
    status = await tb.read_status()
    assert status & STATUS_RXE, f"STATUS.RXE expected set after reset, got 0x{status:x}"
    assert not (status & STATUS_BUSY), f"STATUS.BUSY unexpected after reset: 0x{status:x}"
    assert not (status & STATUS_IRQ), f"STATUS.IRQ unexpected after reset: 0x{status:x}"
    assert not (status & STATUS_TXF), f"STATUS.TXF unexpected after reset: 0x{status:x}"

    # Program CMD / ADDR / CFG and read back through apb_read helpers
    await tb.write_cmd(0x03)
    await tb.write_addr(0xABCDEF)
    await tb.write_cfg(0x04)
    await tb.write_ctrl(0x2 << CTRL_MODE_SHIFT)  # mode=2, no START

    assert await tb.read_cmd() == 0x03
    assert await tb.read_addr() == 0xABCDEF
    assert await tb.read_cfg() == 0x04
    ctrl = await tb.read_ctrl()
    assert (ctrl >> CTRL_MODE_SHIFT) & 0x3 == 0x2, f"CTRL.MODE mismatch: 0x{ctrl:x}"

    # TX FIFO push via DATA register; STATUS should still show not-full
    await tb.write_tx_data(0xA5)
    status = await tb.apb_read(ADDR_STATUS)
    assert not (status & STATUS_TXF), f"TX FIFO should not be full after one push: 0x{status:x}"

    # Clear IRQ path (no pending interrupt expected)
    await tb.clear_irq()
    assert int(tb.irq.value) == 0


@cocotb.test()
async def test_flash_model_unit(dut):
    """Unit-test SpiNorFlash memory, decode, and MISO shift-out.

    Instantiates the behavioral model directly (no RTL SPI) and drives
    synthetic SPI frames to verify memory updates and ``get_miso()`` output.
    The DUT is only brought out of reset so the cocotb+Icarus harness stays
    valid.
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
    assert flash.get_miso() == 0

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

    # --- MISO: Read Status (0x05) shifts status register --------------------
    flash.clear_write_enable()
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_READ_STATUS)
    assert flash.command == CMD_READ_STATUS
    assert flash.state is FlashState.DATA
    assert flash.status_register() == 0x00
    assert _spi_transfer_byte_miso(flash, 0x00) == 0x00
    flash.reset_transaction()

    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_WRITE_ENABLE)
    flash.reset_transaction()
    assert flash.wel == 1
    assert flash.status_register() & SR_WEL

    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_READ_STATUS)
    # Continuous status stream: WEL set → 0x02 on MISO
    assert _spi_transfer_byte_miso(flash, 0x00) == SR_WEL
    assert _spi_transfer_byte_miso(flash, 0x00) == SR_WEL
    flash.reset_transaction()
    assert flash.get_miso() == 0

    # --- MISO: Read (0x03) queues memory bytes onto MISO --------------------
    read_addr = 0x001000
    read_data = bytes([0xDE, 0xAD, 0xBE, 0xEF])
    flash.write_bytes(read_addr, read_data)
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_READ)
    assert flash.state is FlashState.ADDRESS
    _spi_transfer_byte(flash, (read_addr >> 16) & 0xFF)
    _spi_transfer_byte(flash, (read_addr >> 8) & 0xFF)
    _spi_transfer_byte(flash, read_addr & 0xFF)
    assert flash.state is FlashState.DATA
    assert flash.dummy_cycles_remaining == 0
    assert flash.address == read_addr
    got = bytes(
        _spi_transfer_byte_miso(flash, 0x00) for _ in range(len(read_data))
    )
    assert got == read_data
    # Memory unchanged by Read
    assert bytes(flash.read_bytes(read_addr, 4)) == read_data
    flash.reset_transaction()

    # --- process_sclk_mosi: Read address framing (no MISO yet) --------------
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

    # --- MISO: Fast Read (0x0B) after dummy cycles --------------------------
    fast_addr = 0x002000
    fast_data = bytes([0x11, 0x22, 0x33, 0x44])
    flash.write_bytes(fast_addr, fast_data)
    flash.begin_transaction()
    _spi_transfer_byte(flash, CMD_FAST_READ)
    _spi_transfer_byte(flash, (fast_addr >> 16) & 0xFF)
    _spi_transfer_byte(flash, (fast_addr >> 8) & 0xFF)
    _spi_transfer_byte(flash, fast_addr & 0xFF)
    assert flash.state is FlashState.DATA
    assert flash.dummy_cycles_remaining == FAST_READ_DUMMY_CYCLES
    _spi_dummy_clocks(flash, FAST_READ_DUMMY_CYCLES)
    assert flash.dummy_cycles_remaining == 0
    got_fast = bytes(
        _spi_transfer_byte_miso(flash, 0x00) for _ in range(len(fast_data))
    )
    assert got_fast == fast_data
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


@cocotb.test()
async def test_smoke_read_status(dut):
    """End-to-end smoke: APB Read Status (0x05) ↔ SpiNorFlash ↔ RX FIFO.

    Sequence: Reset → CTRL Mode 0 → CMD 0x05 → START → wait completion →
    read RX_DATA and compare against the flash model's status register.
    """
    tb = SpiFlashDUT(dut)
    flash_model = SpiNorFlash()
    _start_clock(tb.pclk)
    cocotb.start_soon(spi_flash_bridge(tb, flash_model))

    await _timer_ns(20)
    await tb.reset(cycles=11)

    # Known status: WEL/WIP cleared after model construction / reset path
    expected_sr = flash_model.status_register()
    assert expected_sr == 0x00, f"flash status should be 0 after reset, got 0x{expected_sr:x}"

    # Configure SPI Mode 0 (no START yet)
    await tb.write_ctrl(0 << CTRL_MODE_SHIFT)
    # Optional divider: 1 keeps SCLK slow enough for clean edge sampling
    await tb.write_cfg(0x01)

    # Issue Read Status (0x05) then pulse START with Mode 0
    await tb.write_cmd(CMD_READ_STATUS)
    await tb.start_transaction(spi_mode=0)

    # Wait for BUSY to assert (START is registered one cycle after the APB write)
    saw_busy = False
    for _ in range(100):
        status = await tb.read_status()
        if status & STATUS_BUSY:
            saw_busy = True
            break
        await RisingEdge(tb.pclk)
    assert saw_busy, "STATUS.BUSY never asserted after START"

    # Wait until the engine drops BUSY (txn complete; IRQ should also assert)
    status = await tb.wait_not_busy(timeout_cycles=10000)
    assert not (status & STATUS_BUSY), f"BUSY still set: 0x{status:x}"
    assert status & STATUS_IRQ, f"IRQ pending expected after completion: 0x{status:x}"
    assert not (status & STATUS_RXE), (
        f"RX FIFO should hold status byte (RXE clear), STATUS=0x{status:x}"
    )
    assert int(tb.irq.value) == 1, "irq pin should follow STATUS.IRQ"

    # Pop RX FIFO and compare with the behavioral flash status register
    rx_byte = await tb.read_rx_data()
    assert rx_byte == expected_sr, (
        f"RX FIFO 0x{rx_byte:02x} != flash status 0x{expected_sr:02x}"
    )

    # STATUS should show RX empty again after the pop
    status_after = await tb.read_status()
    assert status_after & STATUS_RXE, (
        f"RXE expected after draining RX FIFO, got 0x{status_after:x}"
    )
