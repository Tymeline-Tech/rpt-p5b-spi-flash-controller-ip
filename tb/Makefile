# cocotb simulation makefile (invoked from repository root via `make simulate`)
SIM             ?= icarus
TOPLEVEL_LANG   ?= verilog
TOPLEVEL        ?= tb_spi_flash_ctrl
MODULE          ?= test_smoke
VERILOG_SOURCES ?=

export COCOTB_REDUCED_LOG_FMT ?= 1

include $(shell cocotb-config --makefiles)/Makefile.sim
