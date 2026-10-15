# [RPT-P5b] SPI Flash Controller IP

Synthesizable SystemVerilog SPI NOR flash controller with an APB3 slave host
interface and a single-lane SPI master. Targets sky130 with an open-source
toolchain (Verilator, Icarus/cocotb, Yosys).

## Build

```bash
make lint       # Verilator --lint-only -Wall
make simulate   # Verilator --binary --assert --trace smoke test
make synth      # Yosys → artifacts/netlist.v
```

## RTL layout

| Module            | Role                                      |
|-------------------|-------------------------------------------|
| `spi_flash_ctrl`  | Top-level integration                     |
| `spi_reg_block`   | APB3 slave register stub                  |
| `spi_master`      | SPI master engine stub (CS_N high, SCLK low) |
| `spi_tx_fifo`     | 16-entry TX FIFO stub                     |
| `spi_rx_fifo`     | 16-entry RX FIFO stub                     |
