# =============================================================================
# OpenROAD Flow Scripts (ORFS) design configuration — spi_flash_ctrl / sky130HD
# =============================================================================
# Consumed by ORFS as DESIGN_CONFIG (from repository root), e.g.:
#   make DESIGN_CONFIG=$(PWD)/pr_flow/config.mk
#
# Timing: the ONLY SDC in this repository is constraints/spi_flash_ctrl.sdc
# (50 MHz / period 20.0 ns). Do not point ORFS at any other .sdc.
#
# Floorplan: CORE_UTILIZATION=40 matches the project key parameter
# core_utilization=40. Cell area estimate (~18214 um^2 from make synth /
# sky130_fd_sc_hd tt_025C_1v80) implies ~45535 um^2 core at 40% fill.
# =============================================================================

export DESIGN_NICKNAME = spi_flash_ctrl
export DESIGN_NAME     = spi_flash_ctrl
export PLATFORM        = sky130hd

# Gate-level netlist produced by `make synth` (Yosys → sky130_fd_sc_hd).
# Path is relative to the repository root (same as openroad/init.tcl).
export VERILOG_FILES = ./artifacts/spi_flash_ctrl_mapped.v

# Sole project timing constraints (create_clock -period 20.0 on clk).
export SDC_FILE = ./constraints/spi_flash_ctrl.sdc

# Floorplan sizing from estimated cell area @ 40% core utilization.
export CORE_UTILIZATION  = 40
export CORE_ASPECT_RATIO = 1
export CORE_MARGIN       = 2

# Placement density headroom for sky130HD routing (ORFS default-friendly).
export PLACE_DENSITY_LB_ADDON = 0.20
