# SPI Flash Controller IP — top-level build
# Toolchain split (verification containers):
#   make lint     / make simulate  → verilator container (verilator, iverilog, cocotb)
#   make synth                    → yosys container

RTL_DIR      := rtl
TB_DIR       := tb
ART_DIR      := artifacts

TOP          := spi_flash_ctrl
TB           := tb_spi_flash_ctrl

RTL_SRCS     := \
	$(RTL_DIR)/spi_master.sv \
	$(RTL_DIR)/spi_reg_block.sv \
	$(RTL_DIR)/spi_tx_fifo.sv \
	$(RTL_DIR)/spi_rx_fifo.sv \
	$(RTL_DIR)/spi_flash_ctrl.sv

TB_SRCS      := $(TB_DIR)/tb_spi_flash_ctrl.sv

LINT_LOG     := $(ART_DIR)/lint.log
SIM_LOG      := $(ART_DIR)/simulate.log
SYNTH_LOG    := $(ART_DIR)/synth.log
NETLIST      := $(ART_DIR)/netlist.v
SIM_BIN_DIR  := $(ART_DIR)/sim_obj
SIM_BIN      := $(SIM_BIN_DIR)/V$(TB)

VERILATOR    ?= verilator
YOSYS        ?= yosys

.PHONY: all lint simulate synth clean dirs

all: lint simulate synth

dirs:
	@mkdir -p $(ART_DIR) $(SIM_BIN_DIR)

# ---------------------------------------------------------------------------
# Lint (Verilator) — must run in the verilator/sim container
# ---------------------------------------------------------------------------
lint: dirs
	@echo "lint: $(VERILATOR) --lint-only -Wall -sv $(RTL_SRCS)"
	@$(VERILATOR) --lint-only -Wall -sv --top-module $(TOP) $(RTL_SRCS) \
		> $(LINT_LOG) 2>&1; \
	ec=$$?; \
	if [ $$ec -ne 0 ]; then \
		echo "error: verilator lint failed (exit $$ec); see $(LINT_LOG)"; \
		cat $(LINT_LOG); \
		exit $$ec; \
	fi
	@echo "lint: OK" | tee -a $(LINT_LOG)

# ---------------------------------------------------------------------------
# Simulate (Verilator --binary + --assert + VCD)
# ---------------------------------------------------------------------------
simulate: dirs
	@echo "simulate: building $(TB) with Verilator --binary --assert"
	@$(VERILATOR) --binary --assert --trace -Wall -sv --timing \
		--top-module $(TB) \
		-Mdir $(SIM_BIN_DIR) \
		-o V$(TB) \
		$(RTL_SRCS) $(TB_SRCS) \
		> $(SIM_LOG) 2>&1; \
	ec=$$?; \
	if [ $$ec -ne 0 ]; then \
		echo "error: verilator build failed (exit $$ec); see $(SIM_LOG)"; \
		cat $(SIM_LOG); \
		exit $$ec; \
	fi
	@echo "simulate: running $(SIM_BIN)"
	@$(SIM_BIN) >> $(SIM_LOG) 2>&1; \
	ec=$$?; \
	if [ $$ec -ne 0 ]; then \
		echo "error: simulation failed (exit $$ec); see $(SIM_LOG)"; \
		cat $(SIM_LOG); \
		exit $$ec; \
	fi
	@grep -q "PASS" $(SIM_LOG) || (echo "error: PASS not found in $(SIM_LOG)"; cat $(SIM_LOG); exit 1)
	@echo "simulate: OK"

# ---------------------------------------------------------------------------
# Synth (Yosys) — must run in the yosys container
# ---------------------------------------------------------------------------
synth: dirs
	@echo "synth: yosys → $(NETLIST)"
	@$(YOSYS) -q -p "\
		read_verilog -sv $(RTL_SRCS); \
		hierarchy -check -top $(TOP); \
		proc; opt; fsm; opt; memory; opt; \
		techmap; opt; \
		write_verilog -noattr $(NETLIST); \
		stat" \
		> $(SYNTH_LOG) 2>&1; \
	ec=$$?; \
	if [ $$ec -ne 0 ]; then \
		echo "error: yosys synth failed (exit $$ec); see $(SYNTH_LOG)"; \
		cat $(SYNTH_LOG); \
		exit $$ec; \
	fi
	@test -f $(NETLIST) || (echo "error: missing $(NETLIST)"; exit 1)
	@echo "synth: OK" | tee -a $(SYNTH_LOG)

clean:
	rm -rf $(ART_DIR) $(SIM_BIN_DIR)
