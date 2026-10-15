# =============================================================================
# System Design Constraints (SDC) — spi_flash_ctrl
# =============================================================================
# Target frequency : 50 MHz  (period 20.0 ns)
# Purpose          : OpenROAD / ORFS timing analysis during place & route
# Top module       : spi_flash_ctrl
#
# Primary ports (must match rtl/spi_flash_ctrl.sv exactly):
#   Clock / reset : clk, rst_n
#   APB slave     : psel, penable, pwrite, paddr[31:0], pwdata[31:0]
#                   → pready, prdata[31:0], perror
#   Interrupt     : irq
#   SPI master    : sclk, mosi, cs_n ← miso
# =============================================================================

# -----------------------------------------------------------------------------
# Clock definition — 50 MHz on port clk (period exactly 20.0 ns)
# -----------------------------------------------------------------------------
create_clock -name clk -period 20.0 [get_ports clk]

# -----------------------------------------------------------------------------
# Input delays relative to clk
# Covers every non-clock, non-async primary input:
#   APB: psel, penable, pwrite, paddr, pwdata
#   SPI: miso
# clk is excluded (clock root). rst_n is excluded (async; false-pathed below).
# max 2.0 ns ≈ 10% of period for SoC / board integration margin.
# min 0.0 ns provides a defined hold external delay (avoids unset-min warnings).
# -----------------------------------------------------------------------------
set_input_delay -clock clk -max 2.0 \
  [get_ports {psel penable pwrite paddr[*] pwdata[*] miso}]
set_input_delay -clock clk -min 0.0 \
  [get_ports {psel penable pwrite paddr[*] pwdata[*] miso}]

# -----------------------------------------------------------------------------
# Output delays relative to clk
# Covers every primary output:
#   APB: pready, prdata, perror
#   IRQ: irq
#   SPI: sclk, mosi, cs_n
# -----------------------------------------------------------------------------
set_output_delay -clock clk -max 2.0 \
  [get_ports {pready prdata[*] perror irq sclk mosi cs_n}]
set_output_delay -clock clk -min 0.0 \
  [get_ports {pready prdata[*] perror irq sclk mosi cs_n}]

# -----------------------------------------------------------------------------
# Asynchronous reset — rst_n is async active-low throughout the design.
# False path avoids spurious STA on the reset tree; no I/O delay on rst_n.
# -----------------------------------------------------------------------------
set_false_path -from [get_ports rst_n]
