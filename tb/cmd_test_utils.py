"""Shared helpers for SPI flash command verification cocotb tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow importing the cocotb DUT wrapper / flash model under tb/cocotb/
_COCOTB_DIR = Path(__file__).resolve().parent / "cocotb"
if str(_COCOTB_DIR) not in sys.path:
    sys.path.insert(0, str(_COCOTB_DIR))

import cocotb
from cocotb.triggers import RisingEdge

from flash_model import (
    CMD_FAST_READ,
    CMD_PAGE_PROGRAM,
    CMD_READ,
    CMD_READ_STATUS,
    CMD_SECTOR_ERASE,
    CMD_WRITE_ENABLE,
    SECTOR_SIZE,
    SpiNorFlash,
    SR_WEL,
)
from testbench import (
    CTRL_MODE_SHIFT,
    STATUS_BUSY,
    STATUS_IRQ,
    STATUS_RXE,
    SpiFlashDUT,
    _start_clock,
    _timer_ns,
    spi_flash_bridge,
)

try:
    from cocotb_coverage.coverage import CoverPoint, coverage_db

    @CoverPoint("cmd.spi_mode", xf=lambda mode: int(mode), bins=[0, 3])
    def _sample_spi_mode(mode):
        pass

    @CoverPoint(
        "cmd.opcode",
        xf=lambda op: int(op),
        bins=[
            CMD_READ,
            CMD_FAST_READ,
            CMD_PAGE_PROGRAM,
            CMD_SECTOR_ERASE,
            CMD_READ_STATUS,
            CMD_WRITE_ENABLE,
        ],
    )
    def _sample_opcode(op):
        pass

    HAVE_COVERAGE = True
except ImportError:  # pragma: no cover

    def _sample_spi_mode(mode):
        pass

    def _sample_opcode(op):
        pass

    HAVE_COVERAGE = False
    coverage_db = None


# Pattern used by Read / Fast Read cohort tests (big-endian word stream)
DEADBEEF_PATTERN = bytes([0xDE, 0xAD, 0xBE, 0xEF])

# Page Program payload (story: data 0x12345678 at address 0)
PP_WORD = 0x12345678
PP_BYTES = bytes([(PP_WORD >> 24) & 0xFF, (PP_WORD >> 16) & 0xFF,
                  (PP_WORD >> 8) & 0xFF, PP_WORD & 0xFF])


def export_coverage(filename: str = "../coverage.xml") -> None:
    """Write the single functional-coverage XML artifact when available."""
    if HAVE_COVERAGE and coverage_db is not None:
        coverage_db.export_to_xml(filename=filename)


async def bringup(dut, flash_model: SpiNorFlash | None = None):
    """Clock, reset, optional SPI↔flash bridge. Returns (tb, flash_model)."""
    tb = SpiFlashDUT(dut)
    if flash_model is None:
        flash_model = SpiNorFlash()
    _start_clock(tb.pclk)
    cocotb.start_soon(spi_flash_bridge(tb, flash_model))
    await _timer_ns(20)
    await tb.reset(cycles=11)
    await tb.write_cfg(0x01)
    return tb, flash_model


async def wait_command_done(tb: SpiFlashDUT, timeout_cycles: int = 20000) -> int:
    """Wait until STATUS.BUSY asserts then clears; require completion IRQ."""
    saw_busy = False
    for _ in range(200):
        status = await tb.read_status()
        if status & STATUS_BUSY:
            saw_busy = True
            break
        await RisingEdge(tb.pclk)
    assert saw_busy, "STATUS.BUSY never asserted after START"

    status = await tb.wait_not_busy(timeout_cycles=timeout_cycles)
    assert not (status & STATUS_BUSY), f"BUSY still set: 0x{status:x}"
    assert status & STATUS_IRQ, f"IRQ pending expected after completion: 0x{status:x}"
    assert int(tb.irq.value) == 1, "irq pin should follow STATUS.IRQ"
    return status


async def issue_command(
    tb: SpiFlashDUT,
    opcode: int,
    *,
    spi_mode: int = 0,
    addr: int | None = None,
    tx_bytes=(),
):
    """Program CMD(/ADDR)/TX FIFO, pulse START for ``spi_mode``, wait done."""
    _sample_spi_mode(spi_mode)
    _sample_opcode(opcode)

    await tb.clear_irq()
    await tb.write_cmd(opcode)
    if addr is not None:
        await tb.write_addr(addr)
    for byte in tx_bytes:
        await tb.write_tx_data(int(byte) & 0xFF)
    # Latch mode bits without START, then pulse START (matches story CFG flow)
    await tb.write_ctrl((int(spi_mode) & 0x3) << CTRL_MODE_SHIFT)
    await tb.start_transaction(spi_mode=spi_mode)
    return await wait_command_done(tb)


async def write_enable(tb: SpiFlashDUT, flash_model: SpiNorFlash, spi_mode: int = 0):
    """Issue Write Enable (0x06) and assert the model's WEL latch is set."""
    flash_model.clear_write_enable()
    assert flash_model.wel == 0
    await issue_command(tb, CMD_WRITE_ENABLE, spi_mode=spi_mode)
    assert flash_model.wel == 1, "WEL should be 1 after Write Enable (0x06)"
    assert flash_model.status_register() & SR_WEL


def fill_deadbeef(flash_model: SpiNorFlash, length: int = 64) -> None:
    """Fill flash model memory with a repeating 0xDEADBEEF pattern."""
    pattern = DEADBEEF_PATTERN
    for i in range(length):
        flash_model.memory[i] = pattern[i % len(pattern)]


def memory_word_be(flash_model: SpiNorFlash, addr: int = 0) -> int:
    """Read a big-endian 32-bit word from ``flash_model.memory[addr:addr+4]``."""
    return int.from_bytes(bytes(flash_model.memory[addr : addr + 4]), "big")
