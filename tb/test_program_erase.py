"""Page Program (0x02) and Sector Erase (0x20) verification — SPI Modes 0 and 3.

Strictly enforces the Write Enable (0x06) prerequisite before program/erase,
then checks the behavioral flash model's memory updates.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure sibling helpers and tb/cocotb are importable when MODULE is this file.
_TB_DIR = Path(__file__).resolve().parent
if str(_TB_DIR) not in sys.path:
    sys.path.insert(0, str(_TB_DIR))

import cocotb

from cmd_test_utils import (
    PP_BYTES,
    PP_WORD,
    bringup,
    export_coverage,
    issue_command,
    memory_word_be,
    write_enable,
)
from flash_model import CMD_PAGE_PROGRAM, CMD_SECTOR_ERASE, SECTOR_SIZE


async def _page_program(dut, spi_mode: int):
    """WREN → Page Program 0x02 @0x000000 with data 0x12345678 → check memory."""
    tb, flash_model = await bringup(dut)

    # Initialize flash model memory to erased state (0xFF).
    for i in range(len(flash_model.memory)):
        flash_model.memory[i] = 0xFF

    await write_enable(tb, flash_model, spi_mode=spi_mode)

    await issue_command(
        tb,
        CMD_PAGE_PROGRAM,
        spi_mode=spi_mode,
        addr=0x000000,
        tx_bytes=PP_BYTES,
    )

    # Story: fail if flash_model.memory[0] is not 0x12345678 (32-bit BE word).
    programmed = memory_word_be(flash_model, 0)
    assert programmed == PP_WORD, (
        f"flash_model.memory[0] word is 0x{programmed:08x}, expected 0x{PP_WORD:08x} "
        f"(bytes={list(flash_model.memory[0:4])})"
    )
    assert bytes(flash_model.memory[0:4]) == PP_BYTES
    # WEL clears after a successful program
    assert flash_model.wel == 0, "WEL should clear after Page Program"


async def _sector_erase(dut, spi_mode: int):
    """Prefill sector with 0x00 → WREN → Sector Erase 0x20 → all bytes 0xFF."""
    tb, flash_model = await bringup(dut)

    sector_end = SECTOR_SIZE  # 0x000000 .. 0x000FFF
    for i in range(sector_end):
        flash_model.memory[i] = 0x00
    # Neighbor sector must stay untouched (sanity)
    flash_model.memory[SECTOR_SIZE] = 0xA5

    await write_enable(tb, flash_model, spi_mode=spi_mode)

    await issue_command(
        tb,
        CMD_SECTOR_ERASE,
        spi_mode=spi_mode,
        addr=0x000000,
    )

    for i in range(sector_end):
        byte = flash_model.memory[i]
        assert byte == 0xFF, (
            f"sector byte[{i:#06x}]=0x{byte:02x} after erase, expected 0xFF"
        )
    assert flash_model.memory[SECTOR_SIZE] == 0xA5, "adjacent sector must be unchanged"
    assert flash_model.wel == 0, "WEL should clear after Sector Erase"


@cocotb.test()
async def test_page_program_mode0(dut):
    """Page Program (0x02) in SPI Mode 0 after Write Enable."""
    await _page_program(dut, spi_mode=0)


@cocotb.test()
async def test_page_program_mode3(dut):
    """Page Program (0x02) in SPI Mode 3 after Write Enable."""
    await _page_program(dut, spi_mode=3)


@cocotb.test()
async def test_sector_erase_mode0(dut):
    """Sector Erase (0x20) in SPI Mode 0 after Write Enable."""
    await _sector_erase(dut, spi_mode=0)


@cocotb.test()
async def test_sector_erase_mode3(dut):
    """Sector Erase (0x20) in SPI Mode 3 after Write Enable."""
    await _sector_erase(dut, spi_mode=3)
    export_coverage()
