# =============================================================================
# System Design Constraints (SDC) — spi_flash_ctrl
# =============================================================================
# Target frequency : 50 MHz  (period 20.0 ns)
# Purpose          : OpenROAD / ORFS timing analysis during place & route
# Top module       : spi_flash_ctrl
#
# Ports constrained (see rtl/spi_flash_ctrl.sv):
#   Clock / reset : clk, rst_n
#   APB slave     : psel, penable, pwrite, paddr, pwdata → pready, prdata, perror
#   Interrupt     : irq
#   SPI master    : sclk, mosi, cs_n ← miso
# =============================================================================

# -----------------------------------------------------------------------------
# Clock definition — 50 MHz on port clk
# -----------------------------------------------------------------------------
create_clock -name clk -period 20.0 [get_ports clk]

# -----------------------------------------------------------------------------
# Input delays relative to clk (APB inputs + SPI MISO)
# 2.0 ns max allows typical SoC / board integration margin (10% of period).
# -----------------------------------------------------------------------------
set_input_delay -clock clk -max 2.0 [all_inputs]

# -----------------------------------------------------------------------------
# Output delays relative to clk (APB outs, irq, SPI master outs)
# -----------------------------------------------------------------------------
set_output_delay -clock clk -max 2.0 [all_outputs]

# -----------------------------------------------------------------------------
# Asynchronous reset — rst_n is async active-low throughout the design.
# Mark as false path so STA does not report spurious timing on reset trees.
# -----------------------------------------------------------------------------
set_false_path -from [get_ports rst_n]
