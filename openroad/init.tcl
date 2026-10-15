# OpenROAD design initialization for spi_flash_ctrl (sky130_fd_sc_hd)
# Run from the repository root after `make synth`:
#   openroad openroad/init.tcl
#
# Requires PDK_ROOT pointing at the open_pdks / sky130 install root so that:
#   $PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/...
# is available. Liberty/LEF are never committed to this repository.
#
# ---------------------------------------------------------------------------
# Expected netlist path (from `make synth`)
# ---------------------------------------------------------------------------
# Makefile target `synth` runs: yosys -c synth/synth_skylake.tcl
# That script ends with:
#   write_verilog -noattr artifacts/spi_flash_ctrl_mapped.v
# so the OpenROAD-consumable gate-level netlist is always:
#   artifacts/spi_flash_ctrl_mapped.v
# (relative to the repository root). Do not point at synth.ilang or
# artifacts/spi_flash_ctrl_netlist.v (legacy synth.ys name — unused by make).
# Cells in that netlist must be sky130_fd_sc_hd__* for link_design to succeed
# against the liberty/LEF loaded below.

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
# Path: artifacts/spi_flash_ctrl_mapped.v  (see header comment)
set netlist "artifacts/spi_flash_ctrl_mapped.v"
set top     "spi_flash_ctrl"
set sky130_cell_prefix "sky130_fd_sc_hd__"

foreach f [list $sky130_tech_lef $sky130_cell_lef $sky130_lib $netlist] {
	if {![file isfile $f]} {
		error "required file not found: $f"
	}
}

# ---------------------------------------------------------------------------
# Netlist ↔ sky130 cell-library compatibility check (pre-link)
# ---------------------------------------------------------------------------
# Manual / scripted verification that Yosys mapped to sky130_fd_sc_hd and
# left no generic $_* cells that would fail OpenROAD link_design.
set netlist_fh [open $netlist r]
set netlist_txt [read $netlist_fh]
close $netlist_fh

set sky130_hits [regexp -all -- {sky130_fd_sc_hd__[A-Za-z0-9_]+} $netlist_txt]
set generic_hits [regexp -all -- {\$_[A-Za-z0-9_]+} $netlist_txt]

if {$sky130_hits < 1} {
	error "netlist compatibility: no $sky130_cell_prefix cells in $netlist \
(re-run `make synth` with PDK_ROOT sky130 liberty mapping)"
}
if {$generic_hits > 0} {
	error "netlist compatibility: found $generic_hits generic Yosys \$_* cell \
reference(s) in $netlist — not fully mapped to sky130_fd_sc_hd"
}

puts "OpenROAD init: netlist OK — $sky130_hits sky130_fd_sc_hd cell ref(s) in $netlist"

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
