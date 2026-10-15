"""FIFO integrity stress tests — TX overflow and RX underflow boundaries.

Verifies 16-entry TX/RX FIFO defined behavior under over/under-flow stimulus:
back-pressure via STATUS.TXF (and optional PREADY wait-states) on TX full, and
STATUS.RXE / non-popping reads on RX empty. Interrupt stress sequences belong
to a later story step and are not implemented here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TB_DIR = Path(__file__).resolve().parent
if str(_TB_DIR) not in sys.path:
    sys.path.insert(0, str(_TB_DIR))

import cocotb
from cocotb.triggers import RisingEdge

from cmd_test_utils import export_coverage
from testbench import (
    ADDR_DATA,
    ADDR_STATUS,
    STATUS_RXE,
    STATUS_TXF,
    SpiFlashDUT,
    _start_clock,
    _timer_ns,
)

FIFO_DEPTH = 16


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
