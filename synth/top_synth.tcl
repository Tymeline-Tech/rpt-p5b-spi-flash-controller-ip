# Yosys synthesis of the spi_flash_ctrl hierarchy (sky130-oriented baseline)
# Invoked from repository root:
#   yosys synth/top_synth.tcl 2>&1 | tee artifacts/synth.log
yosys -import
foreach f [lsort [glob rtl/*.sv]] {
    read_verilog -sv $f
}
hierarchy -check -top spi_flash_ctrl
synth -top spi_flash_ctrl
stat
write_verilog artifacts/synth_out.v
