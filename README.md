# [RPT-P5b] SPI Flash Controller IP

Synthesizable SystemVerilog SPI NOR flash controller with an APB3 slave host
interface and a single-lane SPI master. Targets sky130 with an open-source
toolchain (Verilator, Icarus/cocotb, Yosys).

## Epic status

| Epic | Status |
|------|--------|
| Yosys Synthesis & Resource Validation | **Ready for PM review** / **Synthesis Passed** |

Epic status: [`docs/epic_status.md`](docs/epic_status.md).  
Synthesis resource & timing report: [`docs/synthesis_report.md`](docs/synthesis_report.md)
(real sky130_fd_sc_hd cell counts and tt_025C_1v80 area from `make synth`).  
Warning / issue analysis: [`docs/synth_issue_tracker.md`](docs/synth_issue_tracker.md).

## Build

```bash
make lint       # Verilator --lint-only -Wall
make simulate   # Icarus + cocotb functional regression
make synth      # Yosys + sky130 → artifacts/synth.log + docs/synthesis_report.md
                # Requires PDK_ROOT (sky130_fd_sc_hd__tt_025C_1v80.lib)
```

## RTL layout

| Module            | Role                                      |
|-------------------|-------------------------------------------|
| `spi_flash_ctrl`  | Top-level integration                     |
| `spi_reg_block`   | APB3 slave register block + IRQ           |
| `spi_master`      | SPI master engine stub (CS_N high, SCLK low) |
| `spi_tx_fifo`     | 16-entry TX FIFO                          |
| `spi_rx_fifo`     | 16-entry RX FIFO                          |

## Register map (`spi_reg_block`)

| Offset | Name   | Access | Description |
|--------|--------|--------|-------------|
| 0x00   | CTRL   | RW     | [0]=START (W1P), [2:1]=SPI mode |
| 0x04   | STATUS | R/W1C  | [0]=busy, [1]=irq_pending (clear on write), [2]=tx_full, [3]=rx_empty, [4]=tx_empty, [5]=rx_full |
| 0x08   | CMD    | RW     | [7:0] SPI command byte |
| 0x0C   | ADDR   | RW     | [23:0] flash address |
| 0x10   | DATA   | RW     | Write pushes TX FIFO; read pops RX FIFO |
| 0x14   | CLKDIV | RW     | [7:0] SPI clock divider |
