# SPI Flash Controller IP — top-level toolchain entry points
# Tools: Verilator (lint), Icarus + cocotb (simulate), Yosys (synth)

ROOT        := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
RTL_DIR     := $(ROOT)/rtl
TB_DIR      := $(ROOT)/tb
SYNTH_DIR   := $(ROOT)/synth
ARTIFACTS   := $(ROOT)/artifacts

TOP         := spi_flash_ctrl
RTL_SRCS    := $(RTL_DIR)/$(TOP).sv

.PHONY: all lint simulate synth clean help

all: lint simulate synth

help:
	@echo "Targets: lint | simulate | synth | clean"

# ---------------------------------------------------------------------------
# lint — Verilator lint-only (hdl_sim container)
# ---------------------------------------------------------------------------
lint:
	@mkdir -p $(ARTIFACTS)
	verilator --lint-only -Wall $(RTL_SRCS)

# ---------------------------------------------------------------------------
# simulate — cocotb + Icarus Verilog smoke (hdl_sim container)
# Cleans stale artifacts first so the run is falsifiable end-to-end.
# ---------------------------------------------------------------------------
simulate: clean-sim-artifacts
	@mkdir -p $(ARTIFACTS)
	$(MAKE) -C $(TB_DIR) \
		SIM=icarus \
		TOPLEVEL_LANG=verilog \
		TOPLEVEL=tb_spi_flash_ctrl \
		COCOTB_TEST_MODULES=test_smoke \
		MODULE=test_smoke \
		VERILOG_SOURCES="$(RTL_SRCS) $(TB_DIR)/tb_spi_flash_ctrl.sv" \
		COCOTB_RESULTS_FILE=$(ARTIFACTS)/results.xml \
		SIM_BUILD=$(ARTIFACTS)/sim_build
	@# Normalize coverage artifact to repo root (verification scans for coverage*.xml)
	@if [ -f $(TB_DIR)/coverage.xml ]; then mv -f $(TB_DIR)/coverage.xml $(ROOT)/coverage.xml; fi
	@if [ -f $(ARTIFACTS)/sim_build/coverage.xml ]; then mv -f $(ARTIFACTS)/sim_build/coverage.xml $(ROOT)/coverage.xml; fi
	@test -f $(ROOT)/coverage.xml

clean-sim-artifacts:
	rm -rf $(ARTIFACTS)/sim_build $(ARTIFACTS)/results.xml \
		$(ARTIFACTS)/coverage.xml $(ROOT)/coverage.xml \
		$(ARTIFACTS)/*.vcd $(ARTIFACTS)/*.fst \
		$(ROOT)/results.xml $(ROOT)/sim_build

# ---------------------------------------------------------------------------
# synth — Yosys synthesis to artifacts netlist (hdl_synth container)
# ---------------------------------------------------------------------------
synth:
	@mkdir -p $(ARTIFACTS)
	yosys -s $(SYNTH_DIR)/synth.ys

clean: clean-sim-artifacts
	rm -rf $(ARTIFACTS)/$(TOP)_netlist.v $(ARTIFACTS)/$(TOP)_synth.json \
		$(ARTIFACTS)/lint.log $(ARTIFACTS)/synth.log
	@# Keep artifacts/.gitkeep
	@touch $(ARTIFACTS)/.gitkeep
