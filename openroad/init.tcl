# OpenROAD design initialization for spi_flash_ctrl (sky130_fd_sc_hd)
# Run from the repository root after `make synth`:
#   openroad openroad/init.tcl
#
# Requires PDK_ROOT pointing at the open_pdks / sky130 install root so that:
#   $PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/...
# is available. Liberty/LEF are never committed to this repository.

if {![info exists ::env(PDK_ROOT)] || $::env(PDK_ROOT) eq ""} {
	error "PDK_ROOT is unset or empty; point it at the sky130 PDK root"
}

set PDK_ROOT $::env(PDK_ROOT)
set SKY130_SC_HD "$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd"

# Technology LEF (routing layers / sites) then cell LEF
set sky130_tech_lef "$SKY130_SC_HD/techlef/sky130_fd_sc_hd__nom.tlef"
set sky130_cell_lef "$SKY130_SC_HD/lef/sky130_fd_sc_hd.lef"
# Timing / power library (TT corner — matches Yosys mapping)
set sky130_lib      "$SKY130_SC_HD/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"

# Gate-level netlist from `make synth` (Yosys → sky130_fd_sc_hd)
set netlist "artifacts/spi_flash_ctrl_mapped.v"
set top     "spi_flash_ctrl"

foreach f [list $sky130_tech_lef $sky130_cell_lef $sky130_lib $netlist] {
	if {![file isfile $f]} {
		error "required file not found: $f"
	}
}

# ---------------------------------------------------------------------------
# Load sky130 technology (LEF) and liberty (LIB)
# ---------------------------------------------------------------------------
read_lef $sky130_tech_lef
read_lef $sky130_cell_lef
read_liberty $sky130_lib

# ---------------------------------------------------------------------------
# Read Yosys-mapped gate-level netlist and link the top design
# ---------------------------------------------------------------------------
read_verilog $netlist
link_design $top

puts "OpenROAD init: linked design '$top' (sky130_fd_sc_hd)"
# Floorplanning / SDC loading belong to subsequent P&R steps.
