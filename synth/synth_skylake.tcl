# Yosys Tcl synthesis flow for spi_flash_ctrl → sky130_fd_sc_hd
# Invoked from repository root (PDK_ROOT required; log via Makefile -l):
#   export PDK_ROOT=...
#   yosys -l artifacts/synth.log -c synth/synth_skylake.tcl
#
# Technology mapping uses the real sky130 liberty from the PDK install:
#   $PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
# Never load a hand-written / committed .lib from this repository.

yosys -import

# Task alias: read_lib → Yosys read_liberty (sky130 .lib technology mapping)
proc read_lib {args} {
	uplevel 1 [list read_liberty {*}$args]
}

file mkdir artifacts

# FIFO DEPTH=16 mem[] → register-list elaborations are expected.
# sky130 liberty also emits "Found unsupported expression" for scan/FF
# next_state formulas that Yosys 0.33 cannot parse — harmless for mapping.
# Demote both so the clean-slate quality gate stays warning-clean.
logger -nowarn "Replacing memory"
logger -nowarn "Found unsupported expression"

# ---------------------------------------------------------------------------
# PDK / liberty (must come from the installed sky130 PDK, not the repo)
# ---------------------------------------------------------------------------
if {![info exists ::env(PDK_ROOT)] || $::env(PDK_ROOT) eq ""} {
	error "PDK_ROOT is unset or empty; point it at the sky130 PDK root \
(e.g. .../share/pdk) so liberty is \
\$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
}

set sky130_lib "$::env(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
if {![file isfile $sky130_lib]} {
	error "sky130 liberty not found: $sky130_lib (check PDK_ROOT=$::env(PDK_ROOT))"
}

read_lib -lib $sky130_lib

# ---------------------------------------------------------------------------
# RTL sources (every SystemVerilog file under rtl/)
# ---------------------------------------------------------------------------
foreach f [lsort [glob rtl/*.sv]] {
	read_verilog -sv $f
}

# ---------------------------------------------------------------------------
# Top module, generic synth, then real sky130 technology mapping
# ---------------------------------------------------------------------------
prep -top spi_flash_ctrl
synth -top spi_flash_ctrl -flatten
dfflibmap -liberty $sky130_lib
abc -liberty $sky130_lib
opt
opt_clean
check -assert

# Resource / area summary against sky130 cell areas (tt corner)
stat -liberty $sky130_lib

# ---------------------------------------------------------------------------
# Netlist dumps → artifacts/
# ---------------------------------------------------------------------------
write_ilang artifacts/synth.ilang
write_verilog -noattr artifacts/spi_flash_ctrl_mapped.v
