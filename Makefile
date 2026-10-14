# SPI Flash Controller IP — top-level toolchain entry points
# Tools: Verilator (lint), Icarus + cocotb (simulate), Yosys (synth)

ROOT        := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
RTL_DIR     := $(ROOT)/rtl
TB_DIR      := $(ROOT)/tb
SYNTH_DIR   := $(ROOT)/synth
ARTIFACTS   := $(ROOT)/artifacts
SIM_DIR     := $(ARTIFACTS)/sim

TOP         := spi_flash_ctrl
RTL_FILES   := $(wildcard rtl/*.sv)
RTL_SRCS    := $(RTL_DIR)/$(TOP).sv

.PHONY: all lint simulate synth clean clean-sim-artifacts help

all: lint simulate synth

help:
	@echo "Targets: lint | simulate | synth | clean"

# ---------------------------------------------------------------------------
# lint — Verilator lint-only (hdl_sim / verilator container)
# Lints every SystemVerilog source under rtl/; log → artifacts/lint.log
# ---------------------------------------------------------------------------
lint:
	@mkdir -p artifacts
	bash -o pipefail -c 'verilator --lint-only --top-module $(TOP) $(RTL_FILES) 2>&1 | tee artifacts/lint.log'

# ---------------------------------------------------------------------------
# simulate — cocotb + Icarus Verilog smoke (hdl_sim container)
# Cleans stale artifacts first so the run is falsifiable end-to-end.
# Results: artifacts/sim/results.xml (fail the build if Python tests fail).
# ---------------------------------------------------------------------------
simulate: clean-sim-artifacts
	@mkdir -p $(SIM_DIR)
	$(MAKE) -C $(TB_DIR) \
		SIM=icarus \
		TOPLEVEL_LANG=verilog \
		TOPLEVEL=tb_spi_flash_ctrl \
		COCOTB_TEST_MODULES=test_smoke \
		MODULE=test_smoke \
		VERILOG_SOURCES="$(RTL_SRCS) $(TB_DIR)/tb_spi_flash_ctrl.sv" \
		COCOTB_RESULTS_FILE=$(SIM_DIR)/results.xml \
		SIM_BUILD=$(SIM_DIR)/sim_build
	@test -f $(SIM_DIR)/results.xml
	@# Normalize coverage artifact to repo root when present.
	@if [ -f $(TB_DIR)/coverage.xml ]; then mv -f $(TB_DIR)/coverage.xml $(ROOT)/coverage.xml; fi
	@if [ -f $(SIM_DIR)/coverage.xml ]; then mv -f $(SIM_DIR)/coverage.xml $(ROOT)/coverage.xml; fi
	@if [ -f $(SIM_DIR)/sim_build/coverage.xml ]; then mv -f $(SIM_DIR)/sim_build/coverage.xml $(ROOT)/coverage.xml; fi

clean-sim-artifacts:
	# Delete stale sim logs, VCDs, ELF/build products so the next run is fresh.
	rm -rf $(SIM_DIR)
	rm -f $(ARTIFACTS)/results.xml $(ARTIFACTS)/coverage.xml \
		$(ROOT)/coverage.xml $(ROOT)/results.xml
	rm -rf $(ROOT)/sim_build $(TB_DIR)/sim_build
	rm -f $(TB_DIR)/*.vcd $(TB_DIR)/*.fst $(TB_DIR)/*.vvp \
		$(ARTIFACTS)/*.vcd $(ARTIFACTS)/*.fst

# ---------------------------------------------------------------------------
# synth — Yosys synthesis of stub RTL (hdl_synth / yosys container)
# Reads rtl/spi_flash_ctrl_stub.sv via synth/top_synth.tcl;
# log → artifacts/synth.log, netlist → artifacts/synth_out.v
# ---------------------------------------------------------------------------
synth:
	@mkdir -p artifacts
	bash -o pipefail -c 'yosys synth/top_synth.tcl 2>&1 | tee artifacts/synth.log'

clean: clean-sim-artifacts
	rm -rf $(ARTIFACTS)/$(TOP)_netlist.v $(ARTIFACTS)/$(TOP)_synth.json \
		$(ARTIFACTS)/synth_out.v \
		$(ARTIFACTS)/lint.log $(ARTIFACTS)/synth.log
	@# Keep artifacts/.gitkeep
	@touch $(ARTIFACTS)/.gitkeep
