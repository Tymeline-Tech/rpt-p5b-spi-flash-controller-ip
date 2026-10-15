# Synthesis Issue Tracker — `spi_flash_ctrl`

**Story:** Execute Synthesis & Validate Lint-Clean Netlist  
**Task:** Synthesis Execution & Critical Warning Analysis  
**Flow:** `make synth` → Yosys (`synth/synth_skylake.tcl`) + sky130 liberty  
**Log:** `artifacts/synth.log` (produced by the run; not committed)  
**Netlist:** `artifacts/synth.ilang`  
**Date:** 2026-10-15  

---

## 1. Execution summary

| Check | Result |
| --- | --- |
| `make synth` | PASS — `artifacts/synth.log` + `artifacts/synth.ilang` |
| Yosys version | 0.33 |
| Top module | `spi_flash_ctrl` |
| Hierarchy retained | `spi_reg_block`, `spi_master`, paramod `spi_tx_fifo`, paramod `spi_rx_fifo` |
| `yosys check -assert` on netlist | **0 problems** |
| Inferred latches | **None** (PROC_DLATCH: “No latch inferred …” for all modules) |
| Explicit “unconnected signal” log warnings | **None** |
| Unique Yosys `Warning:` messages | **2** (4 total occurrences) — FIFO memory→register only |

Post-synth cell count (generic `$_*` after `synth`/`opt`): **1726** cells, including **412** flops (`$_DFFE_PN0P_` + `$_DFF_PN0_`).

---

## 2. Warning categories parsed from `artifacts/synth.log`

| Category | Count | Severity | Notes |
| --- | --- | --- | --- |
| `Warning: Replacing memory \mem with list of registers` | 4 (2 unique sites × frontend + derive) | Info / expected | FIFO `mem[]` arrays |
| Inferred latch (`Creating latch` / positive latch infer) | 0 | — | All comb processes fully assigned |
| Unconnected / undriven wire (textual Warning) | 0 | — | No `unconnected` / `undriven` Warning lines |
| Unused module removal | 2 modules | Info | Default (non-param) FIFO elaborations dropped after derive |
| `unused_bits` on final netlist wires | 7 signals | Review | Yosys attribute = bits never read after opt (see §4) |
| Liberty area for `$_*` cells unknown | Several `stat` lines | Flow note | Generic cells not tech-mapped to sky130; not an RTL flaw |

Parser helper: `scripts/analyze_synth_log.py` (re-run after `make synth`).

---

## 3. Module mapping (APB / FIFO / SPI Master / Top)

### 3.1 FIFO — `spi_tx_fifo` / `spi_rx_fifo`

| Finding | RTL | Assessment |
| --- | --- | --- |
| Memory `\mem` replaced with register list | `rtl/spi_tx_fifo.sv:63`, `rtl/spi_rx_fifo.sv:63` | **Acceptable.** 16×8 circular buffers are small; Yosys maps them to flops rather than macro RAM. Expected for this depth. |
| Non-parameterized module removed after hierarchy | Default `spi_tx_fifo` / `spi_rx_fifo` | **Acceptable.** Top instantiates `#(.DEPTH(16), .WIDTH(8))`; only `$paramod$…` copies remain. |
| PROC_DLATCH: no latch on `rd_data` / mem read addr/data | Comb `always_comb rd_data = mem[rd_idx]` | **Clean.** Fall-through read is fully combinational. |

### 3.2 APB — `spi_reg_block`

| Finding | RTL | Assessment |
| --- | --- | --- |
| No latch on `prdata`, `dec_hit` | `always_comb` case muxes with `default` | **Clean.** Full case coverage; no inferred latch. |
| No unconnected Warning | APB decode / STATUS / DATA paths | **Clean** at Yosys Warning level. STATUS exposes `busy`, IRQ, `tx_full`, `rx_empty` only. |

### 3.3 SPI Master — `spi_master`

| Finding | RTL | Assessment |
| --- | --- | --- |
| No latch on `next_state`, `load_data`, `addr_byte_data`, `more_bytes_needed`, `has_*` | Comb FSM / decode | **Clean.** Defaults / unique case present. |
| `unused_bits "0 1 2"` on `addr_bytes_total` | `rtl/spi_master.sv:78` (`assign` at :128) | **Acceptable optimization artifact.** Consumers (`phase_addr_done`, `more_bytes_needed`) remain; ABC inlined the Fast-Read 3-vs-4 byte compare and left the intermediate wire unread. `cmd_r` / `byte_cnt` still heavily used in the netlist. **Not a functional disconnect of Fast Read.** |

### 3.4 Top interconnect — `spi_flash_ctrl`

| Finding | RTL | Assessment |
| --- | --- | --- |
| No latch on `unused_ok` | `rtl/spi_flash_ctrl.sv:171-174` | Comb XOR sink; no latch. |
| `unused_ok` absent from netlist | same | Optimized away (sink never read). |
| `unused_bits` on FIFO / SPI status nets | see §4 | **Review for follow-on RTL cleanup** (do not treat as latch/hazard). |

---

## 4. Unconnected / unused signal deep-dive (`unused_bits`)

Yosys did not emit a textual “unconnected signal” Warning. After `opt`, the netlist tags these top-level wires with `attribute \unused_bits` (bits driven but never read by remaining logic). The prior `unused_ok` XOR sink was eliminated, so these nets are effectively **functionally unconnected at the top level**.

| Signal | Module | Source | Bits unused | Likely intent | Verdict |
| --- | --- | --- | --- | --- | --- |
| `tx_wr_ready` | Top ← TX FIFO | `spi_flash_ctrl.sv:62` | `[0]` | Complement of `tx_full` (APB already uses `tx_full`) | **Acceptable** complementary status; optional cleanup |
| `tx_empty` | Top ← TX FIFO | `spi_flash_ctrl.sv:60` | `[0]` | Not in APB STATUS map | **Review** — expose in STATUS or intentional omission |
| `rx_full` | Top ← RX FIFO | `spi_flash_ctrl.sv:66` | `[0]` | Not in APB STATUS map | **Review** — expose in STATUS or intentional omission |
| `rx_rd_valid` | Top ← RX FIFO | `spi_flash_ctrl.sv:68` | `[0]` | Complement of `rx_empty` | **Acceptable** complementary status |
| `spi_rx_byte` | Top ← SPI Master | `spi_flash_ctrl.sv:71` | `[7:0]` | Engine-local byte; host uses RX FIFO | **Acceptable** with FIFO datapath (duplicate of FIFO write data path) |
| `spi_rx_valid` | Top ← SPI Master | `spi_flash_ctrl.sv:72` | `[0]` | Engine-local pulse; host uses FIFO `rd_valid`/`empty` | **Acceptable** with FIFO datapath |
| `addr_bytes_total` | SPI Master | `spi_master.sv:78` | `[2:0]` | Intermediate for Fast Read dummy folding | **Acceptable** (inlined; see §3.3) |

### Design-flaw vs acceptable-feature summary

| ID | Issue | Flaw? | Recommended owner |
| --- | --- | --- | --- |
| SYN-001 | FIFO `mem` → register list warnings | No — expected for DEPTH=16 | None (document only) |
| SYN-002 | Inferred latches | No — none found | None |
| SYN-003 | Textual unconnected-signal Warnings | No — none found | None |
| SYN-004 | Top-level `tx_empty` / `rx_full` unused after synth | Possibly incomplete STATUS visibility, not a latch/hazard | Later task: Resolve RTL Logic Flaws |
| SYN-005 | Top-level `spi_rx_*` / ready/valid complements unused | Acceptable with FIFO+STATUS design; `unused_ok` is a lint sink only | Later task may tidy (formal `/* unused */` / drop ports) |
| SYN-006 | `addr_bytes_total` unused_bits after opt | No — inlined Fast Read length logic | None |

---

## 5. Latch audit (PROC_DLATCH excerpt)

Yosys explicitly reported **no latch** for:

- FIFO: `rd_data`, mem2reg read ADDR/DATA (`spi_tx_fifo`, `spi_rx_fifo`)
- APB: `prdata`, `dec_hit` (`spi_reg_block`)
- SPI Master: `load_data`, `addr_byte_data`, `more_bytes_needed`, `next_state`, `has_addr`, `has_tx`, `has_rx`
- Top: `unused_ok`

**Conclusion:** No synthesis-inferred latch defects in the current RTL.

---

## 6. Follow-ups (out of scope for this task)

Deferred to **Resolve RTL Logic Flaws Identified in Synthesis**:

1. Decide whether APB STATUS should surface `tx_empty` / `rx_full` (SYN-004) or keep the lean STATUS bitmap.
2. Replace `unused_ok` XOR sink with intentional unused handling if signals remain host-invisible (SYN-005).
3. Do **not** change FIFO memory style solely to silence mem→reg warnings (SYN-001).

---

## 7. How to reproduce

```bash
make synth
python3 scripts/analyze_synth_log.py --log artifacts/synth.log --ilang artifacts/synth.ilang
# optional structural check:
yosys -p 'read_ilang artifacts/synth.ilang; check -assert'
```
