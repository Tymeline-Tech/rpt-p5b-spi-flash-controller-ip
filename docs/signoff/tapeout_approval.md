# Tape-out approval — spi_flash_ctrl

**Decision: APPROVED for tape-out** (Ready for Fabrication)
**Approver:** Nikhil N (Project Manager); recorded at his explicit instruction by Claude Code acting on his behalf
**Date:** 2026-10-17
**Evidence commit:** `a4db082dba02ba4cec2e3e540f6fe812747a9e64` (main)

| Criterion | Required | Measured | Evidence | Result |
|---|---|---|---|---|
| DRC | 0 errors | 0 violations (KLayout sky130A_mr.drc, feol/beol/offgrid, 256 rules) | `layout/drc.lyrdb` | PASS |
| LVS | Layout matches netlist | Netgen: "Circuits match uniquely." (1723 devices / 1836 nets each side) | `layout/lvs.report` | PASS |
| Setup timing @ 20 ns (50 MHz) | WNS >= 0 | WNS +12.9451 ns, TNS 0, 0 setup violations | `layout/metrics.json` | PASS |
| Hold timing | Slack >= 0 | +0.0314 ns, 0 hold violations | `layout/metrics.json` | PASS |
| Antenna | 0 violating nets | 0 | `layout/metrics.json` | PASS |
| Functional coverage | 100% | 100% of the declared scenario matrix (6 SPI commands x modes 0 and 3, FIFO/IRQ edge cases); enforced by `make simulate` → `coverage-report --require-100`, 16/16 tests pass | `scripts/generate_coverage_report.py`, `Makefile` | PASS |

Notes
- Functional coverage here is scenario coverage of the command/mode matrix the project declared; it is not line or toggle code coverage.
- Sign-off report: `docs/signoff/signoff_report.md`. Layout image: `layout/spi_flash_ctrl.png`.
- PDK: sky130A / sky130_fd_sc_hd. Top cell: spi_flash_ctrl.
