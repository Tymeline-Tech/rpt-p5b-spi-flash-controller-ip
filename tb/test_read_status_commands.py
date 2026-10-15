"""Read / Fast Read / Read Status / Write Enable verification — Modes 0 and 3."""

from __future__ import annotations

import sys
from pathlib import Path

_TB_DIR = Path(__file__).resolve().parent
if str(_TB_DIR) not in sys.path:
    sys.path.insert(0, str(_TB_DIR))

import cocotb

from cmd_test_utils import (
    DEADBEEF_PATTERN,
    bringup,
    export_coverage,
    fill_deadbeef,
    issue_command,
    write_enable,
)
from flash_model import (
    CMD_FAST_READ,
    CMD_READ,
    CMD_READ_STATUS,
    CMD_WRITE_ENABLE,
    SR_WEL,
)
from testbench import STATUS_RXE


async def _read_cmd(dut, opcode: int, spi_mode: int, nbytes: int = 4):
    """Fill 0xDEADBEEF pattern, issue Read/Fast Read, compare RX FIFO bytes."""
    tb, flash_model = await bringup(dut)
    fill_deadbeef(flash_model, length=max(64, nbytes))

    expected = bytes(flash_model.memory[0:nbytes])
    assert expected[:4] == DEADBEEF_PATTERN[: min(4, nbytes)]

    # One TX dummy per RX beat (SPI master length control for Read/Fast Read)
    tx_dummies = [0x00] * nbytes
    status = await issue_command(
        tb,
        opcode,
        spi_mode=spi_mode,
        addr=0x000000,
        tx_bytes=tx_dummies,
    )
    assert not (status & STATUS_RXE), (
        f"RX FIFO should hold {nbytes} byte(s), STATUS=0x{status:x}"
    )

    got = bytearray()
    for i in range(nbytes):
        byte = await tb.read_rx_data()
        got.append(byte)

    assert bytes(got) == expected, (
        f"RX FIFO {got.hex()} != flash model {expected.hex()} "
        f"(opcode=0x{opcode:02x} mode={spi_mode})"
    )

    status_after = await tb.read_status()
    assert status_after & STATUS_RXE, (
        f"RXE expected after draining RX FIFO, got 0x{status_after:x}"
    )


async def _write_enable_check(dut, spi_mode: int):
    """Issue 0x06 and verify flash model WEL=1."""
    tb, flash_model = await bringup(dut)
    flash_model.clear_write_enable()
    assert flash_model.wel == 0

    await issue_command(tb, CMD_WRITE_ENABLE, spi_mode=spi_mode)

    assert flash_model.wel == 1, "flash model WEL must be 1 after Write Enable"
    assert flash_model.status_register() & SR_WEL


async def _read_status_check(dut, spi_mode: int, *, set_wel: bool):
    """Issue 0x05 and compare RX FIFO byte to flash_model.status_register()."""
    tb, flash_model = await bringup(dut)

    if set_wel:
        await write_enable(tb, flash_model, spi_mode=spi_mode)
    else:
        flash_model.clear_write_enable()

    expected_sr = flash_model.status_register()

    status = await issue_command(tb, CMD_READ_STATUS, spi_mode=spi_mode)
    assert not (status & STATUS_RXE), (
        f"RX FIFO should hold status byte, STATUS=0x{status:x}"
    )

    rx_byte = await tb.read_rx_data()
    assert rx_byte == expected_sr, (
        f"RX FIFO 0x{rx_byte:02x} != flash status 0x{expected_sr:02x} "
        f"(mode={spi_mode})"
    )


@cocotb.test()
async def test_read_cmd_mode0(dut):
    """Read (0x03) in SPI Mode 0 — RX FIFO matches 0xDEADBEEF pattern."""
    await _read_cmd(dut, CMD_READ, spi_mode=0)


@cocotb.test()
async def test_read_cmd_mode3(dut):
    """Read (0x03) in SPI Mode 3 — CPOL/CPHA via CTRL mode bits."""
    await _read_cmd(dut, CMD_READ, spi_mode=3)


@cocotb.test()
async def test_fast_read_cmd_mode0(dut):
    """Fast Read (0x0B) in SPI Mode 0 — RX FIFO matches flash model."""
    await _read_cmd(dut, CMD_FAST_READ, spi_mode=0)


@cocotb.test()
async def test_fast_read_cmd_mode3(dut):
    """Fast Read (0x0B) in SPI Mode 3 — CPOL/CPHA via CTRL mode bits."""
    await _read_cmd(dut, CMD_FAST_READ, spi_mode=3)


@cocotb.test()
async def test_write_enable_mode0(dut):
    """Write Enable (0x06) in SPI Mode 0 sets flash model WEL=1."""
    await _write_enable_check(dut, spi_mode=0)


@cocotb.test()
async def test_write_enable_mode3(dut):
    """Write Enable (0x06) in SPI Mode 3 sets flash model WEL=1."""
    await _write_enable_check(dut, spi_mode=3)


@cocotb.test()
async def test_read_status_mode0(dut):
    """Read Status (0x05) Mode 0 — RX matches model (WEL cleared)."""
    await _read_status_check(dut, spi_mode=0, set_wel=False)


@cocotb.test()
async def test_read_status_mode3(dut):
    """Read Status (0x05) Mode 3 — RX matches model after Write Enable."""
    await _read_status_check(dut, spi_mode=3, set_wel=True)
    export_coverage()
