# Yosys Tcl synthesis flow for spi_flash_ctrl → sky130
# Invoked from repository root (log captured by Makefile tee / -l):
#   yosys -l artifacts/synth.log -c synth/synth_skylake.tcl
#   yosys synth/synth_skylake.tcl 2>&1 | tee artifacts/synth.log

yosys -import

# Task alias: read_lib → Yosys read_liberty (sky130 .lib technology mapping)
proc read_lib {args} {
	uplevel 1 [list read_liberty {*}$args]
}

file mkdir artifacts

# FIFO DEPTH=16 mem[] → register-list elaborations are expected (SYN-001).
# Demote them so the clean-slate quality gate can assert No warnings / No errors.
logger -nowarn "Replacing memory"

# ---------------------------------------------------------------------------
# Technology library (sky130 standard cells) for mapping / area estimation
# ---------------------------------------------------------------------------
set sky130_lib "synth/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
read_lib -lib $sky130_lib

# ---------------------------------------------------------------------------
# RTL sources (every SystemVerilog file under rtl/)
# ---------------------------------------------------------------------------
foreach f [lsort [glob rtl/*.sv]] {
	read_verilog -sv $f
}

# ---------------------------------------------------------------------------
# Top module + optimization passes
# ---------------------------------------------------------------------------
prep -top spi_flash_ctrl
synth -top spi_flash_ctrl
opt
check -assert

# Resource / area summary (liberty areas apply once cells are mapped)
stat -liberty $sky130_lib

# ---------------------------------------------------------------------------
# Netlist dump (RTLIL / ilang) → artifacts/
# ---------------------------------------------------------------------------
write_ilang artifacts/synth.ilang
