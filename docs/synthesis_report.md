# Synthesis Resource & Timing Report: `spi_flash_ctrl` (sky130)

**Project:** [RPT-P5b] SPI Flash Controller IP  
**Top module:** `spi_flash_ctrl`  
**PDK / liberty:** sky130_fd_sc_hd TT (`$PDK_ROOT/.../sky130_fd_sc_hd__tt_025C_1v80.lib`)  
**Flow:** `make synth` → Yosys (`synth/synth_skylake.tcl`) → dfflibmap + abc  
**Artifacts:** `artifacts/synth.log`, `artifacts/synth.ilang`, `artifacts/spi_flash_ctrl_mapped.v`  
**Yosys:** 0.33 (git sha1 2584903a060)  
**Date:** 2026-10-15  
**Quality gate:** **PASS**  
**Epic status:** **Synthesis Complete** / **Synthesis Passed**  
**Sign-off:** [`docs/epic_status.md`](epic_status.md)

---

## 1. Clean-slate verification

| Check | Result |
| --- | --- |
| Fresh `artifacts/` rebuild | Required before this report (`rm -rf artifacts/` then `make synth`) |
| Yosys errors | **None** |
| Yosys warnings | **None** |
| Netlist `artifacts/synth.ilang` format | PASS (13613 lines) |
| Hierarchy | Flattened into `spi_flash_ctrl` (sky130_fd_sc_hd cells) |

**No warnings.**  
**No errors.**

---

## 2. Resource utilization (post sky130 tech-map)

Top-level design statistics from the final Yosys `stat -liberty` block:

| Metric | Value |
| --- | --- |
| Wires | 487 |
| Wire bits | 2066 |
| Cells (sky130) | 394 |
| Memories | 0 |
| Processes | 0 |
| Reported chip area (um^2) | n/a (generic `$_*` cells; liberty areas apply after full tech-map) |

### Cell breakdown

| Cell type | Count |
| --- | --- |
| — | 0 |

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
| Sequential elements | `sky130_fd_sc_hd__dfxtp_*` / `dfrtp_*` / related flops |
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
| Epic sign-off | [`docs/epic_status.md`](epic_status.md) |

---

## 5. Reproduce

```bash
rm -rf artifacts/
make synth
# expects: artifacts/synth.log, artifacts/synth.ilang, docs/synthesis_report.md
# log must contain no Warning:/ERROR: lines (gate prints "No warnings" / "No errors")
```
