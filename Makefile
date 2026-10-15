# SPI Flash Controller IP — top-level toolchain entry points
# Tools: Verilator (lint), Icarus + cocotb (simulate), Yosys (synth)
#
# Self-check / platform gate:
#   make lint      → artifacts/lint.log
#   make simulate  → artifacts/simulation.log (+ functional_coverage_report.md)
#   make synth     → artifacts/synth.log
# Cocotb vars: SIM=icarus TOPLEVEL=spi_flash_ctrl MODULE=<comma-separated tests>
# Each target is independently runnable in its toolchain container.

ROOT        := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
RTL_DIR     := $(ROOT)/rtl
TB_DIR      := $(ROOT)/tb
TB_COCOTB   := $(TB_DIR)/cocotb
SYNTH_DIR   := $(ROOT)/synth
ARTIFACTS   := $(ROOT)/artifacts
SIM_DIR     := $(ARTIFACTS)/sim

TOP         := spi_flash_ctrl
RTL_FILES   := $(wildcard rtl/*.sv)
RTL_SRCS    := $(abspath $(RTL_FILES))

# Cocotb defaults (Icarus). Override on the command line, e.g. TESTCASE=test_reset.
# Default MODULE: full functional regression (all SPI cmds × Modes 0/3 + FIFO/IRQ).
SIM         ?= icarus
TOPLEVEL    ?= spi_flash_ctrl
MODULE      ?= test_read_status_commands,test_program_erase,test_fifo_interrupt_stress
TESTCASE    ?=
COVERAGE_REPORT := $(ARTIFACTS)/functional_coverage_report.md
COVERAGE_SCRIPT := $(ROOT)/scripts/generate_coverage_report.py

.PHONY: all lint simulate simulate-verilator synth clean clean-sim-artifacts \
	coverage-report help self-check

all: lint simulate synth

help:
	@echo "Targets: lint | simulate | synth | coverage-report | self-check | clean"
	@echo "simulate uses cocotb+Icarus: TOPLEVEL=$(TOPLEVEL) MODULE=$(MODULE)"
	@echo "Artifacts: artifacts/lint.log, artifacts/simulation.log,"
	@echo "           artifacts/functional_coverage_report.md, artifacts/synth.log"

# ---------------------------------------------------------------------------
# lint — Verilator lint-only (hdl_sim / verilator container)
# Lints every SystemVerilog source under rtl/; log → artifacts/lint.log
# ---------------------------------------------------------------------------
lint:
	@mkdir -p artifacts
	bash -o pipefail -c 'verilator --lint-only -Wall -sv --top-module $(TOP) $(RTL_FILES) 2>&1 | tee artifacts/lint.log'
	@test -f artifacts/lint.log
	@echo "lint: PASS (artifacts/lint.log)"

# ---------------------------------------------------------------------------
# simulate — cocotb + Icarus Verilog (hdl_sim container)
# Cleans stale artifacts first so the run is falsifiable end-to-end.
# TOPLEVEL=spi_flash_ctrl, MODULE=testbench under tb/cocotb/.
# Results: artifacts/simulation.log (+ artifacts/sim/results.xml when cocotb emits it).
# ---------------------------------------------------------------------------
simulate: clean-sim-artifacts
	@mkdir -p $(ARTIFACTS) $(SIM_DIR)
	@# PATH may need ~/.local/bin when cocotb was installed with --user (dev agents).
	@# PYTHONPATH: tb/ (command tests) + tb/cocotb/ (DUT wrapper + flash model).
	bash -o pipefail -c '\
		export PATH="$$HOME/.local/bin:$$PATH"; \
		export PYTHONPATH="$(TB_DIR):$(TB_COCOTB):$$PYTHONPATH"; \
		$(MAKE) -C $(TB_COCOTB) \
			SIM=$(SIM) \
			TOPLEVEL_LANG=verilog \
			TOPLEVEL=$(TOPLEVEL) \
			COCOTB_TOPLEVEL=$(TOPLEVEL) \
			MODULE=$(MODULE) \
			COCOTB_TEST_MODULES=$(MODULE) \
			TESTCASE="$(TESTCASE)" \
			COCOTB_TESTCASE="$(TESTCASE)" \
			VERILOG_SOURCES="$(RTL_SRCS)" \
			COCOTB_RESULTS_FILE=$(SIM_DIR)/results.xml \
			SIM_BUILD=$(SIM_DIR)/sim_build \
			PYTHONPATH="$(TB_DIR):$(TB_COCOTB):$$PYTHONPATH" \
		2>&1 | tee $(ARTIFACTS)/simulation.log'
	@cp -f $(ARTIFACTS)/simulation.log $(ARTIFACTS)/sim.log
	@test -f $(ARTIFACTS)/simulation.log
	@# Prefer cocotb results.xml when present; otherwise require a PASS marker in the log.
	@if [ -f $(SIM_DIR)/results.xml ]; then \
		grep -q 'testcase' $(SIM_DIR)/results.xml; \
		if grep -q 'failures=' $(SIM_DIR)/results.xml; then grep -q 'failures="0"' $(SIM_DIR)/results.xml; fi; \
		if grep -q 'errors=' $(SIM_DIR)/results.xml; then grep -q 'errors="0"' $(SIM_DIR)/results.xml; fi; \
		! grep -E '<failure|<error' $(SIM_DIR)/results.xml; \
	else \
		grep -Eq 'PASS|passed|tests=.*fail=0|0\.00ns.*PASS' $(ARTIFACTS)/simulation.log; \
	fi
	@# Normalize coverage artifact to repo root when present (exactly one coverage*.xml).
	@if [ -f $(TB_DIR)/coverage.xml ]; then mv -f $(TB_DIR)/coverage.xml $(ROOT)/coverage.xml; fi
	@if [ -f $(TB_COCOTB)/coverage.xml ]; then mv -f $(TB_COCOTB)/coverage.xml $(ROOT)/coverage.xml; fi
	@if [ -f $(SIM_DIR)/coverage.xml ]; then mv -f $(SIM_DIR)/coverage.xml $(ROOT)/coverage.xml; fi
	@if [ -f $(SIM_DIR)/sim_build/coverage.xml ]; then mv -f $(SIM_DIR)/sim_build/coverage.xml $(ROOT)/coverage.xml; fi
	@$(MAKE) coverage-report
	@test -f $(COVERAGE_REPORT)
	@echo "simulate: PASS (artifacts/simulation.log + functional_coverage_report.md)"

# ---------------------------------------------------------------------------
# coverage-report — parse cocotb logs → artifacts/functional_coverage_report.md
# Requires artifacts/simulation*.log from a prior (or just-finished) simulate.
# ---------------------------------------------------------------------------
coverage-report:
	@mkdir -p $(ARTIFACTS)
	@test -f $(COVERAGE_SCRIPT)
	python3 $(COVERAGE_SCRIPT) --artifacts $(ARTIFACTS) --output $(COVERAGE_REPORT) --require-100
	@test -f $(COVERAGE_REPORT)
	@echo "coverage-report: PASS ($(COVERAGE_REPORT))"

clean-sim-artifacts:
	# Delete stale sim logs, VCDs, ELF/build products so the next run is fresh.
	rm -rf $(SIM_DIR)
	rm -f $(ARTIFACTS)/sim.log $(ARTIFACTS)/simulation.log \
		$(ARTIFACTS)/results.xml $(ARTIFACTS)/coverage.xml \
		$(ARTIFACTS)/functional_coverage_report.md \
		$(ROOT)/coverage.xml $(ROOT)/results.xml
	rm -rf $(ROOT)/sim_build $(TB_DIR)/sim_build $(TB_COCOTB)/sim_build
	rm -f $(TB_DIR)/*.vcd $(TB_DIR)/*.fst $(TB_DIR)/*.vvp \
		$(TB_COCOTB)/*.vcd $(TB_COCOTB)/*.fst $(TB_COCOTB)/*.vvp \
		$(ARTIFACTS)/*.vcd $(ARTIFACTS)/*.fst

# ---------------------------------------------------------------------------
# synth — Yosys synthesis of the RTL hierarchy (hdl_synth / yosys container)
# Reads every rtl/*.sv (top: spi_flash_ctrl) via synth/top_synth.tcl;
# log → artifacts/synth.log, netlist → artifacts/synth_out.v
# ---------------------------------------------------------------------------
synth:
	@mkdir -p artifacts
	bash -o pipefail -c 'yosys synth/top_synth.tcl 2>&1 | tee artifacts/synth.log'
	@test -f artifacts/synth.log
	@test -f artifacts/synth_out.v
	@echo "synth: PASS (artifacts/synth.log)"

# Local end-to-end regression (not used by the platform gate; each gate
# command still runs independently in its own toolchain container).
self-check: lint simulate synth
	@test -f artifacts/lint.log
	@test -f artifacts/sim.log
	@test -f artifacts/synth.log
	@echo "self-check: PASS (lint + simulate + synth)"

# Verilator self-checking stub smoke (assertions on; not part of the gate).
simulate-verilator:
	@mkdir -p $(ARTIFACTS)/vl_obj
	verilator --binary --assert --trace -Wall -sv --timing --top-module tb_stub_smoke \
		-Mdir $(ARTIFACTS)/vl_obj -o Vtb_stub_smoke $(RTL_FILES) $(TB_DIR)/tb_stub_smoke.sv
	$(ARTIFACTS)/vl_obj/Vtb_stub_smoke

clean: clean-sim-artifacts
	rm -rf $(ARTIFACTS)/$(TOP)_netlist.v $(ARTIFACTS)/$(TOP)_synth.json \
		$(ARTIFACTS)/synth_out.v \
		$(ARTIFACTS)/lint.log $(ARTIFACTS)/synth.log
	@# Keep artifacts/.gitkeep
	@touch $(ARTIFACTS)/.gitkeep
