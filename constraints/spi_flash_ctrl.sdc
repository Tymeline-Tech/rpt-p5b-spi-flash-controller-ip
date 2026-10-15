# =============================================================================
# Project SDC for spi_flash_ctrl — 50 MHz (20.0 ns)
# Kept in sync with constraints/design.sdc (OpenROAD flow entry).
# =============================================================================

create_clock -period 20.0 [get_ports clk]

set_false_path -from [get_ports rst_n]

set_input_delay  -clock [get_clocks clk] -max 4.0 \
  [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_input_delay  -clock [get_clocks clk] -min 0.0 \
  [remove_from_collection [all_inputs] [get_ports {clk rst_n}]]
set_output_delay -clock [get_clocks clk] -max 4.0 [all_outputs]
set_output_delay -clock [get_clocks clk] -min 0.0 [all_outputs]
