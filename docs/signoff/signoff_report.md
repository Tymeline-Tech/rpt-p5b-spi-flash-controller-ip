# Physical Design Sign-off Report: `spi_flash_ctrl`

**Project:** [RPT-P5b] SPI Flash Controller IP  
**Design / top module:** `spi_flash_ctrl`  
**PDK:** sky130A / `sky130_fd_sc_hd`  
**Target clock:** 20 ns period (50 MHz)  
**Report purpose:** Aggregate measured place-and-route, timing, DRC, and LVS evidence for PM tape-out review.  
**This document reports results only; it does not approve or sign off tape-out.**

---

## 1. Evidence files

| Artifact | Path |
| --- | --- |
| PnR / timing metrics | `layout/metrics.json` |
| KLayout DRC database | `layout/drc.lyrdb` |
| Netgen LVS report | `layout/lvs.report` |
| Final GDSII | `layout/spi_flash_ctrl.gds` |
| Powered post-route netlist | `layout/spi_flash_ctrl.pnl.v` |
| Layout image | `layout/spi_flash_ctrl.png` (**not present** in this repository checkout) |

All numeric results below are taken from `layout/metrics.json`, `layout/drc.lyrdb`, and `layout/lvs.report` only.

---

## 2. Timing closure (vs 20 ns / 50 MHz)

Source: finish-stage keys in `layout/metrics.json` (`run__flow__platform__time_units` = `1ns`).

| Metric | Measured value | Target / contract |
| --- | --- | --- |
| Clock period / frequency target | 20 ns / 50 MHz | Project parameter `clock_period_ns=20` |
| Setup WNS (`finish__timing__setup__ws`) | 12.9451 ns | ≥ 0 ns |
| Setup TNS (`finish__timing__setup__tns`) | 0 ns | — |
| Hold worst slack (`finish__timing__hold__ws`) | 0.0314242 ns | ≥ 0 ns |
| Hold TNS (`finish__timing__hold__tns`) | 0 ns | — |
| Setup violation count (`finish__timing__drv__setup_violation_count`) | 0 | ≤ 0 |
| Hold violation count (`finish__timing__drv__hold_violation_count`) | 0 | ≤ 0 |
| Reported fmax (`finish__timing__fmax`) | 141746000 Hz (~141.7 MHz) | ≥ 50 MHz |

Setup and hold worst slacks are positive at the finish stage; violation counts are zero.

---

## 3. Place-and-route physical metrics

Source: finish-stage keys in `layout/metrics.json` (area units per `run__flow__platform__distance_units` = `1um`).

| Metric | Measured value |
| --- | --- |
| Die area (`finish__design__die__area`) | 51069.2 µm² |
| Core area (`finish__design__core__area`) | 49254.7 µm² |
| Instance area (`finish__design__instance__area`) | 23144.7 µm² |
| Stdcell instance area (`finish__design__instance__area__stdcell`) | 23144.7 µm² |
| Instance utilization (`finish__design__instance__utilization`) | 0.469898 (46.9898%) |
| Stdcell utilization (`finish__design__instance__utilization__stdcell`) | 0.469898 (46.9898%) |
| Total instance count (`finish__design__instance__count`) | 6719 |
| Stdcell instance count (`finish__design__instance__count__stdcell`) | 2387 |
| Fill cell count (`finish__design__instance__count__class:fill_cell`) | 4332 |
| IO count (`finish__design__io`) | 110 |
| Net count (`finish__design__nets`) | 1797 |
| Detailed-route wirelength (`detailedroute__route__wirelength`) | 51229 |
| Antenna violating nets (`detailedroute__antenna__violating__nets`) | 0 |
| Antenna violating pins (`detailedroute__antenna__violating__pins`) | 0 |
| Total power (`finish__power__total`) | 0.00179019 |
| Internal power (`finish__power__internal__total`) | 0.00140231 |
| Switching power (`finish__power__switching__total`) | 0.00038787 |
| Leakage power (`finish__power__leakage__total`) | 1.06983e-8 |

Utilization above is the **measured** finish-stage value (0.469898), not the floorplan input target of 40%.

---

## 4. DRC (KLayout)

Source: `layout/drc.lyrdb`.

| Field | Value from file |
| --- | --- |
| Description | SKY130 DRC runset |
| Generator | `drc: script='/pdk/sky130A/libs.tech/klayout/drc/sky130A_mr.drc'` |
| Top cell | `spi_flash_ctrl` |
| Rule categories in database | 256 |
| OFFGRID-named categories (subset) | 38 (e.g. `dnwell_OFFGRID`, `nwell_OFFGRID`, …) |
| Violation items (`<item>` count) | **0** |
| `<items>` section | empty |

DRC result: **clean — 0 violations**.

Rule coverage in this database includes FEOL-style categories (e.g. `nwell.*`, `difftap.*`, `poly.*`), BEOL-style categories (e.g. `m1`–`m5`, `via*`, `li*`), and OFFGRID categories (`*_OFFGRID`), as named in `layout/drc.lyrdb`.

---

## 5. LVS (Netgen)

Source: `layout/lvs.report`.  
Compared views (per project sign-off): `layout/spi_flash_ctrl.gds` vs `layout/spi_flash_ctrl.pnl.v`, top cell `spi_flash_ctrl`.

| Field | Value from file |
| --- | --- |
| Top-cell device count (Circuit 1 / Circuit 2) | 1723 / 1723 |
| Top-cell net count (Circuit 1 / Circuit 2) | 1836 / 1836 |
| Netgen statement | `Netlists match uniquely.` |
| Device-class equivalence | `Device classes spi_flash_ctrl and spi_flash_ctrl are equivalent.` |
| **Final result** | **`Final result: Circuits match uniquely.`** |

Note recorded in the same report (does not change the Final result line):  
`The following cells had property errors: sky130_fd_sc_hd__conb_1`.

---

## 6. Layout image

`layout/spi_flash_ctrl.png` is not present in this checkout, so no layout image is embedded here. Layout geometry evidence remains `layout/spi_flash_ctrl.gds`.

---

## 7. Summary for PM review

| Check | Result (measured) |
| --- | --- |
| Timing @ 20 ns / 50 MHz | Setup WNS 12.9451 ns, Hold WS 0.0314242 ns; 0 setup / 0 hold violations |
| Utilization | 46.9898% (`finish__design__instance__utilization` = 0.469898) |
| Area | Die 51069.2 µm²; core 49254.7 µm²; instance 23144.7 µm² |
| Instances | 2387 stdcell / 6719 total (incl. fill) |
| Power (finish total) | 0.00179019 |
| DRC | 0 violations (`layout/drc.lyrdb`) |
| LVS | Circuits match uniquely (1723/1723 devices, 1836/1836 nets) |

Ready for PM tape-out review
