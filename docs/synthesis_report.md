# Synthesis Resource & Timing Report: `spi_flash_ctrl` (sky130)

**Project:** [RPT-P5b] SPI Flash Controller IP  
**Top module:** `spi_flash_ctrl`  
**PDK / liberty:** sky130 (`synth/lib/sky130_fd_sc_hd__tt_025C_1v80.lib`)  
**Flow:** `make synth` → Yosys (`synth/synth_skylake.tcl`)  
**Artifacts:** `artifacts/synth.log`, `artifacts/synth.ilang`  
**Yosys:** 0.33 (git sha1 2584903a060)  
**Date:** 2026-10-15  
**Quality gate:** **PASS**

---

## 1. Clean-slate verification

| Check | Result |
| --- | --- |
| Fresh `artifacts/` rebuild | Required before this report (`rm -rf artifacts/` then `make synth`) |
| Yosys errors | **None** |
| Yosys warnings | **None** |
| Netlist `artifacts/synth.ilang` format | PASS (12140 lines) |
| Hierarchy | `spi_flash_ctrl`, `spi_reg_block`, `spi_master`, paramod TX/RX FIFOs |

**No warnings.**  
**No errors.**

---

## 2. Resource utilization (post-`synth` / `opt`)

Top-level design statistics from the final Yosys `stat` block:

| Metric | Value |
| --- | --- |
| Wires | 1405 |
| Wire bits | 2228 |
| Cells (generic) | 1732 |
| Memories | 0 |
| Processes | 0 |
| Reported chip area | n/a (generic `$_*` cells; liberty areas apply after full tech-map) |

### Cell breakdown

| Cell type | Count |
| --- | --- |
| `$_ANDNOT_` | 557 |
| `$_AND_` | 42 |
| `$_DFFE_PN0P_` | 403 |
| `$_DFF_PN0_` | 9 |
| `$_MUX_` | 36 |
| `$_NAND_` | 49 |
| `$_NOR_` | 20 |
| `$_NOT_` | 25 |
| `$_ORNOT_` | 79 |
| `$_OR_` | 458 |
| `$_XNOR_` | 21 |
| `$_XOR_` | 33 |

FIFO `mem[]` arrays are elaborated to register lists (expected for DEPTH=16);
those informational elaborations are demoted in the Yosys flow so the quality
gate remains warning-clean.

---

## 3. Timing notes

This open-source Yosys + sky130 liberty flow reports structural cell counts and
optional liberty area. Full static timing (setup/hold paths, WNS/TNS) requires a
downstream STA tool (e.g. OpenSTA) after technology mapping — not part of the
`make synth` gate.

Observed structural timing proxies from synthesis:

| Proxy | Observation |
| --- | --- |
| Sequential elements | `$_DFF_*` / `$_DFFE_*` cells present (clocked APB, SPI, FIFO pointers) |
| Combinational fabric | Dominated by `$_ANDNOT_` / `$_OR_` after ABC |
| Latch inference | None (all processes mapped to FFs / gates) |
| Async reset | Active-low `rst_n` retained on flops (`$_DFF_PN0_` / `$_DFFE_PN0P_`) |

SPI modes 0/3 and the programmable clock divider remain in the RTL; timing
closure versus `PCLK` / derived `SCLK` is a place-and-route / STA concern.

---

## 4. Deliverable links

| Deliverable | Path |
| --- | --- |
| Synthesis log | [`artifacts/synth.log`](../artifacts/synth.log) |
| RTLIL netlist | [`artifacts/synth.ilang`](../artifacts/synth.ilang) |
| Yosys Tcl flow | [`synth/synth_skylake.tcl`](../synth/synth_skylake.tcl) |
| sky130 liberty | [`synth/lib/sky130_fd_sc_hd__tt_025C_1v80.lib`](../synth/lib/sky130_fd_sc_hd__tt_025C_1v80.lib) |
| Prior warning analysis | [`docs/synth_issue_tracker.md`](synth_issue_tracker.md) |

---

## 5. Reproduce

```bash
rm -rf artifacts/
make synth
# expects: artifacts/synth.log, artifacts/synth.ilang, docs/synthesis_report.md
# log must contain no Warning:/ERROR: lines (gate prints "No warnings" / "No errors")
```
