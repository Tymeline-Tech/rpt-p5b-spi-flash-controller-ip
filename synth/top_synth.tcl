# Yosys synthesis script for spi_flash_ctrl_stub (sky130-oriented baseline)
# Invoked from repository root:
#   yosys synth/top_synth.tcl 2>&1 | tee artifacts/synth.log
yosys -import
read_verilog rtl/spi_flash_ctrl_stub.sv
hierarchy -top spi_flash_ctrl_stub
synth
stat
write_verilog artifacts/synth_out.v
