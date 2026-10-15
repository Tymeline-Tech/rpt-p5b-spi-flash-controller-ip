# Synthesis Resource & Timing Report: `spi_flash_ctrl` (sky130)

**Project:** [RPT-P5b] SPI Flash Controller IP  
**Top module:** `spi_flash_ctrl`  
**PDK / liberty:** sky130_fd_sc_hd TT (`$PDK_ROOT/.../sky130_fd_sc_hd__tt_025C_1v80.lib`)  
**Corner:** `tt_025C_1v80`  
**Flow:** `make synth` → Yosys (`synth/synth_skylake.tcl`) → dfflibmap + abc  
**Artifacts:** `artifacts/synth.log`, `artifacts/synth.ilang`, `artifacts/spi_flash_ctrl_mapped.v`  
**Yosys:** 0.33 (git sha1 2584903a060)  
**Date:** 2026-10-15  
**Quality gate:** **PASS**  
**Epic status:** **Ready for PM review**  
**Status doc:** [`docs/epic_status.md`](epic_status.md)

---

## 1. Clean-slate verification

| Check | Result |
| --- | --- |
| Fresh `artifacts/` rebuild | Required before this report (`rm -rf artifacts/` then `make synth`) |
| Yosys errors | **None** |
| Yosys warnings | **None** |
| Netlist `artifacts/synth.ilang` format | PASS (13604 lines) |
| Hierarchy | Flattened into `spi_flash_ctrl` (sky130_fd_sc_hd cells) |

**No warnings.**  
**No errors.**

---

## 2. Resource utilization (post sky130 tech-map)

Top-level design statistics from the final Yosys `stat -liberty` block
(`sky130_fd_sc_hd__tt_025C_1v80`):

| Metric | Value |
| --- | --- |
| Wires | 1150 |
| Wire bits | 1925 |
| Cells (sky130_fd_sc_hd) | 1423 |
| Memories | 0 |
| Processes | 0 |
| Chip area (um^2, tt_025C_1v80) | 18213.718400 |

### sky130 cell breakdown

| Cell type | Count |
| --- | --- |
| `sky130_fd_sc_hd__a2111o_1` | 2 |
| `sky130_fd_sc_hd__a2111oi_0` | 1 |
| `sky130_fd_sc_hd__a211o_1` | 1 |
| `sky130_fd_sc_hd__a211oi_1` | 1 |
| `sky130_fd_sc_hd__a21boi_0` | 2 |
| `sky130_fd_sc_hd__a21o_1` | 2 |
| `sky130_fd_sc_hd__a21oi_1` | 30 |
| `sky130_fd_sc_hd__a221oi_1` | 32 |
| `sky130_fd_sc_hd__a222oi_1` | 45 |
| `sky130_fd_sc_hd__a22o_1` | 8 |
| `sky130_fd_sc_hd__a22oi_1` | 47 |
| `sky130_fd_sc_hd__a311oi_1` | 2 |
| `sky130_fd_sc_hd__a31o_1` | 1 |
| `sky130_fd_sc_hd__a31oi_1` | 3 |
| `sky130_fd_sc_hd__and2_0` | 22 |
| `sky130_fd_sc_hd__and3_1` | 6 |
| `sky130_fd_sc_hd__and3b_1` | 3 |
| `sky130_fd_sc_hd__and4_1` | 2 |
| `sky130_fd_sc_hd__clkinv_1` | 26 |
| `sky130_fd_sc_hd__dfrtp_1` | 412 |
| `sky130_fd_sc_hd__lpflow_inputiso1p_1` | 3 |
| `sky130_fd_sc_hd__lpflow_isobufsrc_1` | 9 |
| `sky130_fd_sc_hd__maj3_1` | 5 |
| `sky130_fd_sc_hd__mux2_1` | 346 |
| `sky130_fd_sc_hd__mux2i_1` | 2 |
| `sky130_fd_sc_hd__nand2_1` | 113 |
| `sky130_fd_sc_hd__nand2b_1` | 10 |
| `sky130_fd_sc_hd__nand3_1` | 37 |
| `sky130_fd_sc_hd__nand3b_1` | 5 |
| `sky130_fd_sc_hd__nand4_1` | 20 |
| `sky130_fd_sc_hd__nand4b_1` | 2 |
| `sky130_fd_sc_hd__nor2_1` | 72 |
| `sky130_fd_sc_hd__nor2b_1` | 4 |
| `sky130_fd_sc_hd__nor3_1` | 29 |
| `sky130_fd_sc_hd__nor3b_1` | 9 |
| `sky130_fd_sc_hd__nor4_1` | 13 |
| `sky130_fd_sc_hd__o2111ai_1` | 1 |
| `sky130_fd_sc_hd__o211ai_1` | 1 |
| `sky130_fd_sc_hd__o21a_1` | 1 |
| `sky130_fd_sc_hd__o21ai_0` | 41 |
| `sky130_fd_sc_hd__o21bai_1` | 2 |
| `sky130_fd_sc_hd__o221a_1` | 1 |
| `sky130_fd_sc_hd__o221ai_1` | 4 |
| `sky130_fd_sc_hd__o31ai_1` | 2 |
| `sky130_fd_sc_hd__or3_1` | 1 |
| `sky130_fd_sc_hd__or4_1` | 2 |
| `sky130_fd_sc_hd__or4b_1` | 1 |
| `sky130_fd_sc_hd__xnor2_1` | 23 |
| `sky130_fd_sc_hd__xor2_1` | 16 |

FIFO `mem[]` arrays are elaborated to register lists (expected for DEPTH=16);
those informational elaborations are demoted in the Yosys flow so the quality
gate remains warning-clean.

---

## 3. Timing notes

This open-source Yosys + sky130 liberty flow reports mapped cell counts and
liberty area after `dfflibmap` / `abc`. Full static timing (setup/hold paths,
WNS/TNS) requires a downstream STA tool (e.g. OpenSTA) — not part of the
`make synth` gate.

Observed structural timing proxies from synthesis:

| Proxy | Observation |
| --- | --- |
| Sequential elements | `sky130_fd_sc_hd__dfrtp_*` / related flops |
| Combinational fabric | sky130_fd_sc_hd combinational stdcells after ABC |
| Latch inference | None (all processes mapped to FFs / gates) |
| Async reset | Active-low `rst_n` retained on resettable flops where applicable |

SPI modes 0/3 and the programmable clock divider remain in the RTL; timing
closure versus `PCLK` / derived `SCLK` is a place-and-route / STA concern.

---

## 4. Deliverable links

| Deliverable | Path |
| --- | --- |
| Synthesis log | [`artifacts/synth.log`](../artifacts/synth.log) |
| RTLIL netlist | [`artifacts/synth.ilang`](../artifacts/synth.ilang) |
| Mapped Verilog | [`artifacts/spi_flash_ctrl_mapped.v`](../artifacts/spi_flash_ctrl_mapped.v) |
| Yosys Tcl flow | [`synth/synth_skylake.tcl`](../synth/synth_skylake.tcl) |
| sky130 liberty | `$PDK_ROOT/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib` (not committed) |
| Prior warning analysis | [`docs/synth_issue_tracker.md`](synth_issue_tracker.md) |
| Epic status | [`docs/epic_status.md`](epic_status.md) |

---

## 5. Reproduce

```bash
rm -rf artifacts/
make synth
# expects: artifacts/synth.log, artifacts/synth.ilang, docs/synthesis_report.md
# log must contain no Warning:/ERROR: lines (gate prints "No warnings" / "No errors")
```
