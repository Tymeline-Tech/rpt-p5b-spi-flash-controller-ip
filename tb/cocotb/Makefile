# Cocotb + Icarus Verilog harness for spi_flash_ctrl
# Invoked from the repository root via `make simulate`.
#
# Required cocotb variables:
#   SIM / TOPLEVEL_LANG / TOPLEVEL / MODULE / VERILOG_SOURCES

SIM                  ?= icarus
TOPLEVEL_LANG        ?= verilog
TOPLEVEL             ?= spi_flash_ctrl
COCOTB_TOPLEVEL      ?= $(TOPLEVEL)
MODULE               ?= testbench
COCOTB_TEST_MODULES  ?= $(MODULE)

# Absolute paths preferred when invoked from a nested make.
ROOT                 ?= $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
RTL_DIR              ?= $(ROOT)/rtl
VERILOG_SOURCES      ?= $(wildcard $(RTL_DIR)/*.sv)

# Optional: select a single cocotb test (e.g. TESTCASE=test_reset).
TESTCASE             ?=
COCOTB_TESTCASE      ?= $(TESTCASE)

export COCOTB_REDUCED_LOG_FMT ?= 1
export SIM

# Ensure the Python test module in this directory is importable.
export PYTHONPATH := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))):$(PYTHONPATH)

include $(shell cocotb-config --makefiles)/Makefile.sim
