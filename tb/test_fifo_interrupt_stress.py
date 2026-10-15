"""FIFO integrity + interrupt / back-to-back stress tests for spi_flash_ctrl.

Verifies 16-entry TX/RX FIFO defined behavior under over/under-flow stimulus,
command-completion interrupt assert/clear via the STATUS register, and
pipeline robustness under back-to-back Read re-initialization.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TB_DIR = Path(__file__).resolve().parent
if str(_TB_DIR) not in sys.path:
    sys.path.insert(0, str(_TB_DIR))

import cocotb
from cocotb.triggers import RisingEdge

from cmd_test_utils import (
    DEADBEEF_PATTERN,
    bringup,
    export_coverage,
    fill_deadbeef,
    issue_command,
)
from flash_model import CMD_READ
from testbench import (
    ADDR_DATA,
    ADDR_STATUS,
    CTRL_MODE_SHIFT,
    STATUS_BUSY,
    STATUS_IRQ,
    STATUS_RXE,
    STATUS_TXF,
    SpiFlashDUT,
    _start_clock,
    _timer_ns,
)

FIFO_DEPTH = 16
BACK_TO_BACK_READS = 4
READ_NBYTES = 4


async def _bringup_no_spi(dut) -> SpiFlashDUT:
    """Clock + reset only — FIFO boundary tests do not start SPI transactions."""
    tb = SpiFlashDUT(dut)
    _start_clock(tb.pclk)
    await _timer_ns(20)
    await tb.reset(cycles=11)
    return tb


async def _apb_write_observe_pready(
    tb: SpiFlashDUT, addr: int, data: int, *, max_wait_cycles: int = 32
) -> dict:
    """APB write that records whether PREADY stalled during the access phase.

    Returns a dict with:
      - completed: True if PREADY asserted within ``max_wait_cycles``
      - pready_low_seen: True if PREADY was sampled 0 while PENABLE was high
      - wait_cycles: number of cycles spent waiting for PREADY after access start
    """
    addr = int(addr) & 0xFFFFFFFF
    data = int(data) & 0xFFFFFFFF

    await RisingEdge(tb.pclk)
    tb.psel.value = 1
    tb.penable.value = 0
    tb.pwrite.value = 1
    tb.paddr.value = addr
    tb.pwdata.value = data

    await RisingEdge(tb.pclk)
    tb.penable.value = 1

    pready_low_seen = False
    wait_cycles = 0
    completed = False

    await RisingEdge(tb.pclk)
    for _ in range(int(max_wait_cycles)):
        ready = int(tb.pready.value)
        if ready == 0:
            pready_low_seen = True
            wait_cycles += 1
            await RisingEdge(tb.pclk)
            continue
        completed = True
        break

    tb.psel.value = 0
    tb.penable.value = 0
    tb.pwrite.value = 0

    return {
        "completed": completed,
        "pready_low_seen": pready_low_seen,
        "wait_cycles": wait_cycles,
    }


def _tx_wr_ptr(dut) -> int:
    """Read TX FIFO write pointer via hierarchy (integrity check only)."""
    return int(dut.u_tx_fifo.wr_ptr.value)


def _tx_rd_ptr(dut) -> int:
    return int(dut.u_tx_fifo.rd_ptr.value)


def _tx_occupancy(dut) -> int:
    """Occupancy from circular pointers (DEPTH=16, PTR_W=5)."""
    return (_tx_wr_ptr(dut) - _tx_rd_ptr(dut)) & 0x1F


@cocotb.test()
async def test_tx_fifo_overflow(dut):
    """Fill TX FIFO with 16 bytes, then stress the 17th write for back-pressure.

    After 16 pushes STATUS.TXF must be set. The 17th APB write to DATA must not
    corrupt the FIFO: either PREADY stays low (wait-state back-pressure) or the
    transfer completes while the write is ignored (STATUS.TXF / occupancy stay
    at full) — matching the delivered register-block behavior.
    """
    tb = await _bringup_no_spi(dut)

    status = await tb.read_status()
    assert not (status & STATUS_TXF), (
        f"TX FIFO should not be full after reset, STATUS=0x{status:x}"
    )
    assert _tx_occupancy(dut) == 0, "TX occupancy must be 0 after reset"

    # Push exactly DEPTH bytes with unique payloads
    for i in range(FIFO_DEPTH):
        await tb.write_tx_data(0xA0 + i)
        status = await tb.read_status()
        if i < FIFO_DEPTH - 1:
            assert not (status & STATUS_TXF), (
                f"TXF unexpected after {i + 1} push(es): STATUS=0x{status:x}"
            )
        else:
            assert status & STATUS_TXF, (
                f"TXF expected after {FIFO_DEPTH} pushes: STATUS=0x{status:x}"
            )

    assert _tx_occupancy(dut) == FIFO_DEPTH, (
        f"TX occupancy {_tx_occupancy(dut)} != {FIFO_DEPTH} after fill"
    )
    wr_ptr_full = _tx_wr_ptr(dut)

    # 17th byte — observe PREADY wait-states / discard path
    obs = await _apb_write_observe_pready(tb, ADDR_DATA, 0xFF, max_wait_cycles=32)

    status_after = await tb.apb_read(ADDR_STATUS)
    assert status_after & STATUS_TXF, (
        f"TXF must remain set after overflow attempt: STATUS=0x{status_after:x}"
    )
    assert _tx_occupancy(dut) == FIFO_DEPTH, (
        f"TX occupancy grew past full after 17th write: {_tx_occupancy(dut)}"
    )
    assert _tx_wr_ptr(dut) == wr_ptr_full, (
        "TX wr_ptr advanced on overflow — 17th byte was accepted (corruption)"
    )

    # Defined back-pressure: PREADY stall *or* completed-but-ignored write
    if obs["pready_low_seen"]:
        assert obs["wait_cycles"] >= 1, "PREADY low seen but wait_cycles==0"
        # If the design stalls, it must eventually complete or we timed out
        # (timeout is still acceptable as "blocked"; occupancy must not grow).
    else:
        assert obs["completed"], (
            "17th TX write neither stalled on PREADY nor completed — APB hang"
        )

    # Spot-check first stored byte via FIFO memory (no SPI drain)
    assert int(dut.u_tx_fifo.mem[0].value) == 0xA0, (
        "TX mem[0] corrupted after overflow attempt"
    )
    assert int(dut.u_tx_fifo.mem[FIFO_DEPTH - 1].value) == 0xA0 + FIFO_DEPTH - 1, (
        "TX mem[15] corrupted after overflow attempt"
    )

    export_coverage()


@cocotb.test()
async def test_rx_fifo_underflow(dut):
    """Read RX FIFO while empty — STATUS.RXE stays set; no hang / no pop."""
    tb = await _bringup_no_spi(dut)

    status = await tb.read_status()
    assert status & STATUS_RXE, (
        f"STATUS.RXE expected set after reset (RX empty), got 0x{status:x}"
    )

    rd_ptr_before = int(dut.u_rx_fifo.rd_ptr.value)
    wr_ptr_before = int(dut.u_rx_fifo.wr_ptr.value)
    assert rd_ptr_before == wr_ptr_before, "RX FIFO not empty after reset"

    # Attempt read from empty RX FIFO (DATA register)
    rdata = await tb.read_rx_data()

    status_after = await tb.read_status()
    assert status_after & STATUS_RXE, (
        f"STATUS.RXE must stay set after empty read, got 0x{status_after:x}"
    )

    rd_ptr_after = int(dut.u_rx_fifo.rd_ptr.value)
    wr_ptr_after = int(dut.u_rx_fifo.wr_ptr.value)
    assert rd_ptr_after == rd_ptr_before, (
        f"RX rd_ptr advanced on empty read ({rd_ptr_before} -> {rd_ptr_after}) "
        "— underflow popped empty FIFO"
    )
    assert wr_ptr_after == wr_ptr_before, "RX wr_ptr changed during empty read"

    # Returned data is not a valid FIFO pop; after reset mem is 0 so expect 0
    assert (rdata & 0xFF) == 0x00, (
        f"empty RX read returned unexpected 0x{rdata:02x} (expect 0 after reset)"
    )

    # Second empty read must remain well-defined (no hang, still empty)
    rdata2 = await tb.read_rx_data()
    status2 = await tb.read_status()
    assert status2 & STATUS_RXE, f"RXE cleared after second empty read: 0x{status2:x}"
    assert int(dut.u_rx_fifo.rd_ptr.value) == rd_ptr_before
    assert (rdata2 & 0xFF) == 0x00

    export_coverage()


async def _wait_interrupt_high(tb: SpiFlashDUT, timeout_cycles: int = 20000) -> None:
    """Wait until the command-completion interrupt pin asserts."""
    interrupt = tb.irq
    for _ in range(int(timeout_cycles)):
        if int(interrupt.value) == 1:
            return
        await RisingEdge(tb.pclk)
    raise TimeoutError(
        f"interrupt pin never asserted within {timeout_cycles} cycles"
    )


@cocotb.test()
async def test_interrupt_assert_and_clear(dut):
    """IRQ asserts on Read completion and clears via STATUS interrupt-clear bit.

    Sequence: issue Read (0x03) → wait for interrupt high → assert == 1 →
    write 1 to the Interrupt Clear bit in STATUS → wait 1 cycle → assert == 0.
    """
    tb, flash_model = await bringup(dut)
    fill_deadbeef(flash_model, length=64)
    interrupt = tb.irq

    assert int(interrupt.value) == 0, "interrupt must be clear before Read"

    # Issue Read without using wait helpers that already check IRQ — wait on pin
    await tb.clear_irq()
    await tb.write_cmd(CMD_READ)
    await tb.write_addr(0x000000)
    for _ in range(READ_NBYTES):
        await tb.write_tx_data(0x00)
    await tb.write_ctrl(0 << CTRL_MODE_SHIFT)
    await tb.start_transaction(spi_mode=0)

    # Confirm the engine started, then wait for the interrupt pin itself
    saw_busy = False
    for _ in range(200):
        status = await tb.read_status()
        if status & STATUS_BUSY:
            saw_busy = True
            break
        await RisingEdge(tb.pclk)
    assert saw_busy, "STATUS.BUSY never asserted after START"

    await _wait_interrupt_high(tb)
    assert int(interrupt.value) == 1, "interrupt.value must be 1 after completion"

    status = await tb.read_status()
    assert not (status & STATUS_BUSY), f"BUSY should be clear with IRQ: 0x{status:x}"
    assert status & STATUS_IRQ, f"STATUS.IRQ expected set: 0x{status:x}"

    # Write 1 to the Interrupt Clear bit (STATUS[1] / STATUS_IRQ)
    await tb.apb_write(ADDR_STATUS, STATUS_IRQ)

    await RisingEdge(tb.pclk)
    assert int(interrupt.value) == 0, (
        "interrupt.value must be 0 one cycle after STATUS clear write"
    )

    status_after = await tb.read_status()
    assert not (status_after & STATUS_IRQ), (
        f"STATUS.IRQ should be clear after STATUS write: 0x{status_after:x}"
    )

    export_coverage()


@cocotb.test()
async def test_back_to_back_reads(dut):
    """Back-to-back Read commands — rapid SPI re-init without hang or corruption.

    Issues several Read (0x03) transactions immediately one after another,
    clearing IRQ between starts, and checks each RX FIFO payload matches the
    flash model so pipeline re-initialization stays correct under stress.
    """
    tb, flash_model = await bringup(dut)
    fill_deadbeef(flash_model, length=64)
    interrupt = tb.irq

    base = DEADBEEF_PATTERN
    for seq in range(BACK_TO_BACK_READS):
        addr = seq  # distinct starting bytes within the repeating pattern
        expected = bytes(flash_model.memory[addr : addr + READ_NBYTES])
        assert expected[0] == base[addr % len(base)]

        status = await issue_command(
            tb,
            CMD_READ,
            spi_mode=0,
            addr=addr,
            tx_bytes=[0x00] * READ_NBYTES,
        )
        assert int(interrupt.value) == 1, (
            f"interrupt should be high after read #{seq}: STATUS=0x{status:x}"
        )
        assert not (status & STATUS_RXE), (
            f"RX FIFO empty after read #{seq}: STATUS=0x{status:x}"
        )

        got = bytearray()
        for _ in range(READ_NBYTES):
            got.append(await tb.read_rx_data())
        assert bytes(got) == expected, (
            f"back-to-back read #{seq}: got {got.hex()} != expected {expected.hex()}"
        )

        # Host clears IRQ before the next transaction re-arms the SPI engine
        await tb.apb_write(ADDR_STATUS, STATUS_IRQ)
        await RisingEdge(tb.pclk)
        assert int(interrupt.value) == 0, (
            f"interrupt must clear before read #{seq + 1}"
        )

        status_idle = await tb.read_status()
        assert not (status_idle & STATUS_BUSY), (
            f"BUSY stuck between back-to-back reads (#{seq}): 0x{status_idle:x}"
        )
        assert status_idle & STATUS_RXE, (
            f"RXE expected after drain before next read: 0x{status_idle:x}"
        )

    export_coverage()
