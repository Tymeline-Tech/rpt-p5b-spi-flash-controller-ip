# Synthesis Issue Tracker — `spi_flash_ctrl`

**Story:** Execute Synthesis & Validate Lint-Clean Netlist  
**Tasks:** Synthesis Execution & Critical Warning Analysis → Resolve RTL Logic Flaws  
**Flow:** `make synth` → Yosys (`synth/synth_skylake.tcl`) + sky130 liberty  
**Log:** `artifacts/synth.log` (produced by the run; not committed)  
**Netlist:** `artifacts/synth.ilang`  
**Date:** 2026-10-15  

---

## 1. Execution summary

| Check | Result |
| --- | --- |
| `make synth` | PASS — `artifacts/synth.log` + `artifacts/synth.ilang` |
| `make lint` | PASS — `artifacts/lint.log` |
| Yosys version | 0.33 |
| Top module | `spi_flash_ctrl` |
| Hierarchy retained | `spi_reg_block`, `spi_master`, paramod `spi_tx_fifo`, paramod `spi_rx_fifo` |
| `yosys check -assert` on netlist | **0 problems** |
| Inferred latches | **None** (PROC_DLATCH: “No latch inferred …” for all modules) |
| Explicit “unconnected signal” log warnings | **None** |
| Unique Yosys `Warning:` messages | **2** (4 total occurrences) — FIFO memory→register only |

---

## 2. Warning categories parsed from `artifacts/synth.log`

| Category | Count | Severity | Notes |
| --- | --- | --- | --- |
| `Warning: Replacing memory \mem with list of registers` | 4 (2 unique sites × frontend + derive) | Info / expected | FIFO `mem[]` arrays |
| Inferred latch (`Creating latch` / positive latch infer) | 0 | — | All comb processes fully assigned |
| Unconnected / undriven wire (textual Warning) | 0 | — | No `unconnected` / `undriven` Warning lines |
| Unused module removal | 2 modules | Info | Default (non-param) FIFO elaborations dropped after derive |
| Pre-map `$_*` cells | Intermediate only | Resolved | Final `stat -liberty` is sky130_fd_sc_hd only (see `docs/synthesis_report.md`) |

Parser helper: `scripts/analyze_synth_log.py` (re-run after `make synth`).

---

## 3. RTL logic-flaw resolution (this task)

### 3.1 SYN-004 — expose FIFO empty/full in APB STATUS

| Change | Detail |
| --- | --- |
| `spi_reg_block` | New inputs `tx_empty`, `rx_full`; STATUS `[4]=TXE`, `[5]=RXF` |
| `spi_flash_ctrl` | Wire FIFO `empty`/`full` into the register block |
| Read mux | Full combinational case with `default` — no latch |

After reset STATUS = `0x18` (`RXE|TXE`). Smoke test and README updated accordingly.

### 3.2 SYN-005 — remove unused / duplicate nets

| Change | Detail |
| --- | --- |
| Removed `unused_ok` XOR sink | Was optimized away; not a real consumer |
| FIFO complements | Left `wr_ready` / `rd_valid` unconnected at top (`~full` / `~empty` already in STATUS); Verilator `PINCONNECTEMPTY` suppressed locally |
| SPI master | Dropped duplicate `rx_data` / `rx_valid` ports; host uses RX FIFO path only |

**Post-fix unused_bits:** only `spi_master.addr_bytes_total` (SYN-006, ABC inline). Top-level FIFO/SPI unused nets from the prior analysis are gone.

### 3.3 Latch / FSM audit (unchanged — still clean)

- All `always_comb` blocks use defaults or complete `unique case` / `default`.
- Sequential logic is `always_ff` with async `rst_n`; no latches.
- SPI sequencer FSM covers IDLE / CMD / ADDR / DATA_TX / DATA_RX / DONE + `default → IDLE`.

### 3.4 Left as acceptable (not RTL flaws)

| ID | Issue | Verdict |
| --- | --- | --- |
| SYN-001 | FIFO `mem` → register list | Expected for DEPTH=16 |
| SYN-006 | `addr_bytes_total` unused_bits after ABC | Inlined Fast-Read length; still functionally correct |

---

## 4. How to reproduce

```bash
make lint
make synth
python3 scripts/analyze_synth_log.py --log artifacts/synth.log --ilang artifacts/synth.ilang
# optional structural check:
yosys -p 'read_ilang artifacts/synth.ilang; check -assert'
```
