# Integration Guide — SPI Flash Controller IP (`spi_flash_ctrl`)

This guide is for the hardware engineer putting `spi_flash_ctrl` into a RISC-V
microcontroller, and for the software engineer driving it. It is the entry
point to the IP's documentation:

| Document | Contents |
| --- | --- |
| This guide | System integration, reset, the APB handshake, the resource and timing summary, and known limits |
| [`register_map.md`](register_map.md) (+ [`register_map.json`](register_map.json)) | Every register, field, access type, reset value and side effect |
| [`spi_configuration_guide.md`](spi_configuration_guide.md) | SPI mode and clock setup, FIFO use, and step-by-step sequences with C code for all six commands |
| [`synthesis_report.md`](synthesis_report.md) | Full Yosys + sky130 synthesis report, including the cell breakdown |

Contents:

1. [Overview](#1-overview)
2. [System Integration](#2-system-integration)
3. [Reset and power-on](#3-reset-and-power-on)
4. [APB handshake](#4-apb-handshake)
5. [FIFOs: polling the full and empty flags](#5-fifos-polling-the-full-and-empty-flags)
6. [Resource & Timing Summary](#6-resource--timing-summary)
7. [Verification status](#7-verification-status)
8. [Known limits and integration cautions](#8-known-limits-and-integration-cautions)

## 1. Overview

- An APB3 slave with six 32-bit registers.
- A single-lane SPI master for SPI NOR flash, supporting Mode 0 and Mode 3.
- 16-byte TX and RX FIFOs.
- A level-high completion interrupt.
- Supported flash commands: Read (0x03), Fast Read (0x0B), Page Program (0x02),
  Sector Erase (0x20), Read Status (0x05), Write Enable (0x06).
- One clock domain (`clk`). SCLK is divided from `clk`; there is no second
  clock.

```
            APB3 (PCLK = clk)                               SPI NOR flash
  RISC-V  ───────────────────►  spi_reg_block ─┬─► spi_tx_fifo ─┐
  APB     ◄───────────────────    (6 regs, IRQ)│                ├─► spi_master ─► sclk, cs_n, mosi
  bridge                              irq ◄────┘◄─ spi_rx_fifo ◄┘              ◄─ miso
```

## 2. System Integration

### 2.1 Ports

| Port | Dir | Width | Connect to |
| --- | --- | --- | --- |
| `clk` | in | 1 | APB clock (PCLK). Also the SPI engine clock |
| `rst_n` | in | 1 | APB reset (PRESETn), active low. See §3 |
| `psel` | in | 1 | APB bridge select for this slave |
| `penable` | in | 1 | PENABLE |
| `pwrite` | in | 1 | PWRITE |
| `paddr` | in | 32 | PADDR. Only `[7:0]` select a register; `[31:8]` must be 0 at the slave, so pass a local (offset) address. See §2.3 |
| `pwdata` | in | 32 | PWDATA |
| `pready` | out | 1 | PREADY (always 1) |
| `prdata` | out | 32 | PRDATA |
| `perror` | out | 1 | PSLVERR |
| `irq` | out | 1 | An interrupt input of the RISC-V core or its interrupt controller (PLIC/CLIC). Level-high |
| `sclk` | out | 1 | Flash SCK pad |
| `cs_n` | out | 1 | Flash CS# pad |
| `mosi` | out | 1 | Flash SI / IO0 pad |
| `miso` | in | 1 | Flash SO / IO1 pad |

The IP has no parameters at the top level. The FIFOs are 16 deep. On a
quad-capable flash, tie WP# (IO2) and HOLD#/RESET# (IO3) high on the board,
because this controller drives only IO0 and IO1.

### 2.2 Instantiation

```systemverilog
// Example: one APB slave slot of a RISC-V SoC's APB bridge.
module spi_flash_ctrl_wrapper (
    input  logic        pclk,
    input  logic        presetn,          // synchronous de-assertion, see §3

    // APB slave port from the SoC bridge
    input  logic        psel_spif,
    input  logic        penable,
    input  logic        pwrite,
    input  logic [31:0] paddr,            // full system address
    input  logic [31:0] pwdata,
    output logic        pready_spif,
    output logic [31:0] prdata_spif,
    output logic        pslverr_spif,

    output logic        irq_spif,         // to PLIC/CLIC source

    // Flash pins
    output logic        flash_sck,
    output logic        flash_cs_n,
    output logic        flash_io0,        // MOSI
    input  logic        flash_io1         // MISO
);

    // The controller decodes paddr[7:0] and requires paddr[31:8] == 0.
    // Pass the offset within its 256-byte window, not the system address.
    logic [31:0] paddr_local;
    assign paddr_local = {24'h0, paddr[7:0]};

    spi_flash_ctrl u_spi_flash_ctrl (
        .clk     (pclk),
        .rst_n   (presetn),
        .psel    (psel_spif),
        .penable (penable),
        .pwrite  (pwrite),
        .paddr   (paddr_local),
        .pwdata  (pwdata),
        .pready  (pready_spif),
        .prdata  (prdata_spif),
        .perror  (pslverr_spif),
        .irq     (irq_spif),
        .sclk    (flash_sck),
        .mosi    (flash_io0),
        .miso    (flash_io1),
        .cs_n    (flash_cs_n)
    );

endmodule
```

### 2.3 Address map

Give the controller a 256-byte (or larger) window on the APB bus, for example
`0x4001_0000–0x4001_00FF`. Inside the window:

- Offsets 0x00–0x14 are the six registers.
- Every other offset answers with PSLVERR (`perror = 1`).

If the bridge passes full system addresses, keep only `paddr[7:0]` as shown
above. A full address would have non-zero `paddr[31:8]`, and every access would
return PSLVERR.

## 3. Reset and power-on

- **Polarity:** `rst_n` is active low.
- **Assertion:** asynchronous. Every flop in the IP resets on `negedge rst_n`
  (`always_ff @(posedge clk or negedge rst_n)`), so no clock is needed while
  reset is applied.
- **De-assertion:** must be synchronous to `clk`. The IP has no internal reset
  synchronizer. Drive `rst_n` from the SoC's reset synchronizer (the same one
  that produces PRESETn), so that release meets recovery and removal timing.
- **Minimum assertion time:** none is required by the logic, because
  assertion is asynchronous. Holding reset for at least two `clk` cycles is
  recommended so the release goes through the SoC's synchronizer cleanly. The
  regression holds it for 11 cycles.
- **Pins while reset is asserted and after it is released:**
  - `cs_n` is 1 (flash deselected).
  - `sclk` is 0 (Mode 0 idle level).
  - `mosi` is 0.
  - `irq` is 0.
- **Registers after reset:**
  - CTRL = 0 (Mode 0).
  - STATUS = 0x18: RX and TX FIFOs empty, not busy, no IRQ.
  - CMD = 0, ADDR = 0, CLKDIV = 0 (SCLK = clk/2).
  - Both FIFOs are emptied.

Power-on sequence for software:

1. Release reset (hardware).
2. Program CLKDIV for your flash's maximum SCLK, then write CTRL with the mode
   and no START. See `spi_configuration_guide.md` §1.
3. Optionally read the flash status with Read Status (0x05) and wait for WIP
   = 0. A flash that was mid-erase when the SoC reset keeps working on its own.
4. Enable the `irq` source in the interrupt controller if you use interrupts.

The SPI engine does not reset the flash, and the IP has no flash-reset
command.

## 4. APB handshake

The slave follows APB3 with zero wait states.

| Phase | Signals | Slave behaviour |
| --- | --- | --- |
| Setup | `psel = 1`, `penable = 0` | Nothing happens. Address and data are only sampled in the access phase |
| Access | `psel = 1`, `penable = 1` | Write: registers update at the next `clk` edge. Read: `prdata` is valid in this cycle. `pready = 1`, so every transfer completes in this single access cycle |
| Error | access to an unmapped offset, or `paddr[31:8] != 0` | `perror = 1` in the access phase. A write has no effect, a read returns 0 |

Side effects that happen in the access phase:

- A read of DATA (0x10) pops one byte from the RX FIFO.
- A write of DATA pushes one byte to the TX FIFO.
- Any write of STATUS clears the interrupt.
- A write of CTRL with bit 0 = 1 starts a transaction.

The DATA side effects happen once per access phase. A bridge must not issue
speculative or repeated reads of DATA (for example, a cache or prefetch over
the APB window). Map the window as device or uncached memory.

`pready` is a constant 1, so the IP never inserts wait states. A transaction
that is still running on the SPI side never stalls the APB bus.

## 5. FIFOs: polling the full and empty flags

The TX and RX FIFOs are 16 bytes deep, and the hardware does not protect
against misuse:

> **Warning.** A write to DATA while `STATUS.TXF = 1` (TX full) is dropped
> without an error. A read from DATA while `STATUS.RXE = 1` (RX empty) returns
> stale data and pops nothing. Software must poll the FIFO flags in STATUS:
> TXF bit 2, RXE bit 3, TXE bit 4, RXF bit 5.

Practical rules:

| Situation | Check | Why |
| --- | --- | --- |
| Before pushing a Page Program payload or read dummies | `TXF = 0`, and keep the transaction to 16 bytes or fewer | A 17th byte is lost silently |
| Before starting Read, Fast Read or Read Status | `RXE = 1` (drain first) | With RX full (`RXF = 1`) the data phase is skipped and the command reports done |
| Before Sector Erase, Write Enable or Read Status | `TXE = 1` | Leftover TX bytes would become the next command's payload or dummies |
| Before reading DATA | `RXE = 0` | Avoid stale data |
| Before starting Read or Fast Read | At least one dummy in TX | A read with an empty TX FIFO never completes and needs a reset |

Transfers of more than 16 bytes need software to service the FIFOs while BUSY
is 1. Only transfers of up to 16 bytes are covered by the regression (§7).

## 6. Resource & Timing Summary

### 6.1 Area (from the Yosys synthesis report)

From [`synthesis_report.md`](synthesis_report.md): `make synth`, which runs
Yosys mapping to `sky130_fd_sc_hd`, typical corner tt_025C_1v80.

| Metric | Value |
| --- | --- |
| Standard cells | 1,423 |
| Cell area | 18,213.7 µm² (≈ 0.018 mm²) |
| Flip-flops | 412 (`dfrtp_1`, async-reset D flip-flop) |
| 2:1 muxes | 346 (`mux2_1`) |
| Memories (SRAM macros) | 0. Both FIFOs are built from flip-flops |

The cell area excludes placement density and routing. A typical 60–70% core
utilization gives a placed block of roughly 0.026–0.030 mm².

Most of the area is FIFO storage. The 32 FIFO entries hold 256 bits of
flip-flops plus their read muxes, which accounts for most of the 412 flops and
346 muxes.

The numbers depend slightly on the Yosys version:

| Yosys | Cells | Area | Where |
| --- | --- | --- | --- |
| 0.33 | 1,423 | 18,213.7 µm² | Committed report (coding agent's environment) |
| 0.23 | 1,384 | 18,093.6 µm² | The project's verification runner, which re-ran `make synth` at review |

Both runs map to the real sky130 liberty. The difference is about 0.7%.

### 6.2 Timing (static timing analysis, pre-layout)

Yosys reports area only. For timing, the mapped netlist
(`artifacts/spi_flash_ctrl_mapped.v`) was analysed with OpenSTA against the
sky130_fd_sc_hd liberty at three corners. Setup:

- 20 ns clock (50 MHz) on `clk`.
- Inputs and outputs budgeted at 4 ns each, with inputs driven by
  `sky130_fd_sc_hd__buf_2` and outputs loaded with 10 fF.
- Ideal clock, no wire parasitics.

| Corner | Worst flop-to-flop path | Pre-layout f_max (flop to flop) | Worst setup slack at 50 MHz (all paths) | Worst hold slack |
| --- | --- | --- | --- | --- |
| ss_100C_1v60 (slow) | 7.29 ns + 0.19 ns setup | ≈ 134 MHz | +9.59 ns | +0.90 ns |
| tt_025C_1v80 (typical) | 3.73 ns + 0.09 ns setup | ≈ 262 MHz | +10.85 ns | +0.44 ns |
| ff_n40C_1v95 (fast) | 2.27 ns + 0.04 ns setup | ≈ 433 MHz | — | — |

Reading these numbers:

- The design meets 50 MHz with a large margin at every corner. The critical
  path runs from the SPI engine's FSM state (`state[2]`) to its byte counter
  (`byte_cnt[6]`).
- The APB read path is combinational: `paddr` passes through the register
  decode and read mux to `prdata` (about 1.15 ns of logic at tt). Budget it
  inside the APB bridge's read timing.
- These are pre-layout estimates. Clock-tree skew, wire load and the
  place-and-route utilisation will reduce them. Re-run STA on the routed design
  at the SoC's own corners and with its SDC before sign-off.
- SPI interface timing (flash setup and hold relative to SCLK) depends on the
  pads and board. It is not covered here. At CLKDIV ≥ 1 there is at least one
  `clk` period between SCLK edges.

## 7. Verification status

From the cocotb regression (`make simulate`; Icarus Verilog with a SPI NOR
flash model), as reported in `artifacts/functional_coverage_report.md`:

- **All 16 tests pass:** six commands in each of Mode 0 and Mode 3 (12
  pass/fail points), plus four FIFO and interrupt cases:
  - TX FIFO overflow on a 17th write;
  - RX FIFO underflow on a read when empty;
  - interrupt raise and clear;
  - back-to-back reads.
- **What "100% functional coverage" means here:** each of those 16 cases has a
  passing test. It is a pass/fail matrix, not code coverage and not
  bin-by-bin functional coverage.
- **Not covered by the regression:**
  - Modes 1 and 2;
  - transfers of more than 16 bytes;
  - CLKDIV values other than 1;
  - the two read hazards in §8.
- **Lint:** `make lint` (Verilator `-Wall`) is clean.
- **Synthesis:** `make synth` reports no warnings. Two classes of
  informational messages are demoted on purpose:
  - "Replacing memory" for the FIFO arrays, documented in
    `synth_issue_tracker.md`;
  - "Found unsupported expression" for sky130 scan-cell `next_state`
    formulas, documented in the comments of `synth/synth_skylake.tcl`.

## 8. Known limits and integration cautions

| # | Item | Impact | Mitigation |
| --- | --- | --- | --- |
| 1 | Read or Fast Read with an empty TX FIFO never completes | BUSY stays 1, no IRQ; only reset recovers | Always push ≥ 1 dummy byte before START. Candidate RTL fix: default to a 1-byte read |
| 2 | Read with a full RX FIFO skips its data phase | Command reports done with no data | Drain RX (RXE = 1) before reads |
| 3 | TX full / RX empty accesses fail silently | Lost or stale bytes, no PSLVERR | Poll TXF/RXE (§5) |
| 4 | No internal reset synchronizer | Release must be synchronous to `clk` | Drive `rst_n` from the SoC reset synchronizer (§3) |
| 5 | Single lane, 24-bit address, six opcodes | No dual/quad I/O, no 4-byte addressing (flashes > 16 MB) | — |
| 6 | No automatic WIP polling | Software must poll Read Status after Program/Erase | `spi_wait_wip_clear()` in the configuration guide |
| 7 | `sclk` and `cs_n` are decoded combinationally from the engine's registered state | Glitch-free pad outputs are not verified | Register them at the pad, or check with gate-level simulation of the final netlist |
| 8 | ABC picked `lpflow_inputiso1p` / `lpflow_isobufsrc` (low-power isolation cells) for 12 instances | These cells are meant for power-gated domains; most sky130 place-and-route flows mark `lpflow*` don't-use | Add `lpflow*` to the don't-use list before abc / P&R |
| 9 | APB read data path is combinational from `paddr` | Counts against the bridge's read timing | Budget about 1.2 ns (tt) plus wiring |

Items 1 and 2 were confirmed in simulation when this guide was written. Items 7
and 8 come from reading the RTL and the mapped netlist; they were not seen to
fail.
