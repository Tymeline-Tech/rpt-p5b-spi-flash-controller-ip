#!/usr/bin/env python3
"""Parse cocotb simulation logs and emit a functional coverage report.

Reads ``artifacts/simulation*.log`` (and optionally ``artifacts/sim/results.xml``)
produced by ``make simulate``, maps test names that encode SPI command + mode
onto the Epic KPI matrix, and writes
``artifacts/functional_coverage_report.md``.

Required KPI scenarios
----------------------
* SPI commands ``0x03``, ``0x0B``, ``0x02``, ``0x20``, ``0x05``, ``0x06``
  each exercised in SPI Mode 0 and Mode 3.
* FIFO / interrupt edge cases (TX overflow, RX underflow, IRQ assert/clear,
  back-to-back reads).
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

# ---------------------------------------------------------------------------
# Command / mode matrix required by the Epic KPI
# ---------------------------------------------------------------------------
REQUIRED_COMMANDS: OrderedDict[int, str] = OrderedDict(
    [
        (0x03, "Read"),
        (0x0B, "Fast Read"),
        (0x02, "Page Program"),
        (0x20, "Sector Erase"),
        (0x05, "Read Status"),
        (0x06, "Write Enable"),
    ]
)
REQUIRED_MODES = (0, 3)

# Test-name fragments → (opcode, mode). Names encode command + SPI mode.
COMMAND_TEST_PATTERNS: list[tuple[re.Pattern[str], int, int]] = [
    (re.compile(r"test_read_cmd_mode0\b"), 0x03, 0),
    (re.compile(r"test_read_cmd_mode3\b"), 0x03, 3),
    (re.compile(r"test_fast_read_cmd_mode0\b"), 0x0B, 0),
    (re.compile(r"test_fast_read_cmd_mode3\b"), 0x0B, 3),
    (re.compile(r"test_page_program_mode0\b"), 0x02, 0),
    (re.compile(r"test_page_program_mode3\b"), 0x02, 3),
    (re.compile(r"test_sector_erase_mode0\b"), 0x20, 0),
    (re.compile(r"test_sector_erase_mode3\b"), 0x20, 3),
    (re.compile(r"test_read_status_mode0\b"), 0x05, 0),
    (re.compile(r"test_read_status_mode3\b"), 0x05, 3),
    (re.compile(r"test_write_enable_mode0\b"), 0x06, 0),
    (re.compile(r"test_write_enable_mode3\b"), 0x06, 3),
    # Smoke / interrupt paths that also exercise a command in a mode
    (re.compile(r"test_smoke_read_status\b"), 0x05, 0),
    (re.compile(r"test_interrupt_assert_and_clear\b"), 0x03, 0),
    (re.compile(r"test_back_to_back_reads\b"), 0x03, 0),
]

# FIFO / interrupt edge-case scenarios (not command×mode cells)
EDGE_CASE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"test_tx_fifo_overflow\b"), "TX FIFO overflow (16-entry full + 17th write)"),
    (re.compile(r"test_rx_fifo_underflow\b"), "RX FIFO underflow (empty read)"),
    (re.compile(r"test_interrupt_assert_and_clear\b"), "IRQ assert on completion + STATUS clear"),
    (re.compile(r"test_back_to_back_reads\b"), "Back-to-back Read re-init stress"),
]

# cocotb summary table / narrative lines
PASS_RE = re.compile(
    r"(?:^|\*\*\s+)(?P<name>[\w.]+)\s+(?:passed|PASS)\b",
    re.IGNORECASE,
)
FAIL_RE = re.compile(
    r"(?:^|\*\*\s+)(?P<name>[\w.]+)\s+(?:failed|FAIL)\b",
    re.IGNORECASE,
)
# "running module.test_name (N/M)" — records discovery even before result
RUNNING_RE = re.compile(
    r"running\s+(?P<name>[\w.]+)\s+\(",
    re.IGNORECASE,
)


def _basename(qualified: str) -> str:
    """Strip module prefix: ``pkg.test_foo`` → ``test_foo``."""
    return qualified.rsplit(".", 1)[-1]


def parse_log_text(text: str) -> dict[str, str]:
    """Return ``{test_basename: 'PASS'|'FAIL'|'UNKNOWN'}`` from cocotb log text."""
    results: dict[str, str] = {}

    for match in RUNNING_RE.finditer(text):
        name = _basename(match.group("name"))
        results.setdefault(name, "UNKNOWN")

    for match in FAIL_RE.finditer(text):
        name = _basename(match.group("name"))
        # Ignore the aggregate "TESTS=… FAIL=0" footer line
        if name.upper() in {"TESTS", "TEST"}:
            continue
        if "FAIL=" in match.group(0).upper():
            continue
        results[name] = "FAIL"

    for match in PASS_RE.finditer(text):
        name = _basename(match.group("name"))
        if name.upper() in {"TESTS", "TEST"}:
            continue
        # Do not overwrite an earlier FAIL from the same log
        if results.get(name) != "FAIL":
            results[name] = "PASS"

    return results


def parse_results_xml(path: Path) -> dict[str, str]:
    """Parse cocotb ``results.xml`` (xUnit) into ``{test: PASS|FAIL}``."""
    results: dict[str, str] = {}
    if not path.is_file():
        return results
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return results

    for case in root.iter("testcase"):
        name = case.attrib.get("name") or ""
        if not name:
            continue
        name = _basename(name)
        failed = any(child.tag in ("failure", "error") for child in case)
        results[name] = "FAIL" if failed else "PASS"
    return results


def collect_results(log_paths: list[Path], results_xml: Path | None) -> dict[str, str]:
    """Merge PASS/FAIL from all logs + optional results.xml (FAIL wins)."""
    merged: dict[str, str] = {}

    for log_path in log_paths:
        if not log_path.is_file():
            continue
        text = log_path.read_text(encoding="utf-8", errors="replace")
        for name, status in parse_log_text(text).items():
            if status == "FAIL" or name not in merged or merged[name] == "UNKNOWN":
                merged[name] = status
            elif merged[name] != "FAIL" and status == "PASS":
                merged[name] = "PASS"

    if results_xml is not None:
        for name, status in parse_results_xml(results_xml).items():
            if status == "FAIL" or name not in merged or merged[name] == "UNKNOWN":
                merged[name] = status
            elif merged[name] != "FAIL" and status == "PASS":
                merged[name] = "PASS"

    return merged


def map_command_coverage(test_results: dict[str, str]) -> dict[tuple[int, int], str]:
    """Map required (opcode, mode) cells to Pass/Fail/Missing."""
    cells: dict[tuple[int, int], str] = {
        (op, mode): "Missing" for op in REQUIRED_COMMANDS for mode in REQUIRED_MODES
    }

    for pattern, opcode, mode in COMMAND_TEST_PATTERNS:
        for test_name, status in test_results.items():
            if pattern.search(test_name):
                key = (opcode, mode)
                if status == "PASS":
                    # Prefer Pass; only overwrite Missing / keep Fail if already Fail
                    if cells[key] != "Fail":
                        cells[key] = "Pass"
                elif status == "FAIL":
                    cells[key] = "Fail"
                elif cells[key] == "Missing":
                    cells[key] = "Unknown"
    return cells


def map_edge_coverage(test_results: dict[str, str]) -> list[tuple[str, str, str]]:
    """Return ``[(scenario, test_name, Pass|Fail|Missing), ...]`` for edge cases."""
    rows: list[tuple[str, str, str]] = []
    for pattern, scenario in EDGE_CASE_PATTERNS:
        matched_name = ""
        status = "Missing"
        for test_name, test_status in test_results.items():
            if pattern.search(test_name):
                matched_name = test_name
                if test_status == "PASS":
                    status = "Pass"
                elif test_status == "FAIL":
                    status = "Fail"
                else:
                    status = "Unknown"
                break
        rows.append((scenario, matched_name or pattern.pattern, status))
    return rows


def render_report(
    cells: dict[tuple[int, int], str],
    edge_rows: list[tuple[str, str, str]],
    test_results: dict[str, str],
    log_names: list[str],
) -> str:
    """Build the markdown functional-coverage report."""
    cmd_pass = sum(1 for v in cells.values() if v == "Pass")
    cmd_total = len(cells)
    edge_pass = sum(1 for _, _, s in edge_rows if s == "Pass")
    edge_total = len(edge_rows)
    kpi_ok = cmd_pass == cmd_total and edge_pass == edge_total
    rate = 100.0 * cmd_pass / cmd_total if cmd_total else 0.0

    lines: list[str] = [
        "# Functional Coverage Report — SPI Flash Controller",
        "",
        "Aggregated from cocotb regression logs (`artifacts/simulation*.log`).",
        "",
        f"**Sources:** {', '.join(log_names) if log_names else '(none)'}",
        "",
        f"**Command × Mode coverage:** {cmd_pass}/{cmd_total} ({rate:.1f}%)",
        f"**FIFO / Interrupt edge cases:** {edge_pass}/{edge_total}",
        f"**Epic KPI (100% Functional Coverage Rate):** "
        f"{'MET' if kpi_ok else 'NOT MET'}",
        "",
        "## Command / Mode Matrix",
        "",
        "| Command | Opcode | Mode 0 | Mode 3 |",
        "|---------|--------|--------|--------|",
    ]

    for opcode, name in REQUIRED_COMMANDS.items():
        m0 = cells[(opcode, 0)]
        m3 = cells[(opcode, 3)]
        lines.append(f"| {name} | `0x{opcode:02X}` | {m0} | {m3} |")

    lines.extend(
        [
            "",
            "## FIFO / Interrupt Edge Cases",
            "",
            "| Scenario | Test | Status |",
            "|----------|------|--------|",
        ]
    )
    for scenario, test_name, status in edge_rows:
        lines.append(f"| {scenario} | `{test_name}` | {status} |")

    lines.extend(
        [
            "",
            "## Parsed Test Results",
            "",
            "| Test | Status |",
            "|------|--------|",
        ]
    )
    if test_results:
        for name in sorted(test_results):
            lines.append(f"| `{name}` | {test_results[name]} |")
    else:
        lines.append("| *(no tests parsed)* | — |")

    lines.extend(
        [
            "",
            "## Compliance Summary",
            "",
            f"- Required SPI commands covered in Modes 0 and 3: "
            f"**{cmd_pass}/{cmd_total}**",
            f"- FIFO / interrupt edge cases covered: "
            f"**{edge_pass}/{edge_total}**",
            f"- Functional Coverage Rate KPI: "
            f"**{'100%' if kpi_ok else f'{rate:.1f}% (incomplete)'}**",
            "",
        ]
    )
    return "\n".join(lines)


def coverage_complete(
    cells: dict[tuple[int, int], str],
    edge_rows: list[tuple[str, str, str]],
) -> bool:
    return all(v == "Pass" for v in cells.values()) and all(
        s == "Pass" for _, _, s in edge_rows
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=Path("artifacts"),
        help="Artifacts directory (default: artifacts/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output markdown path (default: <artifacts>/functional_coverage_report.md)",
    )
    parser.add_argument(
        "--require-100",
        action="store_true",
        help="Exit non-zero unless every required scenario is Pass",
    )
    args = parser.parse_args(argv)

    artifacts: Path = args.artifacts
    output: Path = args.output or (artifacts / "functional_coverage_report.md")

    log_paths = sorted(artifacts.glob("simulation*.log"))
    # Also accept the legacy alias copied by the Makefile
    sim_log = artifacts / "sim.log"
    if sim_log.is_file() and sim_log not in log_paths:
        log_paths.append(sim_log)

    results_xml = artifacts / "sim" / "results.xml"
    test_results = collect_results(log_paths, results_xml)

    cells = map_command_coverage(test_results)
    edge_rows = map_edge_coverage(test_results)
    report = render_report(
        cells,
        edge_rows,
        test_results,
        [p.name for p in log_paths],
    )

    artifacts.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Wrote {output}")

    complete = coverage_complete(cells, edge_rows)
    cmd_pass = sum(1 for v in cells.values() if v == "Pass")
    print(
        f"Command×Mode: {cmd_pass}/{len(cells)}; "
        f"edge cases: {sum(1 for _, _, s in edge_rows if s == 'Pass')}/{len(edge_rows)}; "
        f"KPI={'MET' if complete else 'NOT MET'}"
    )

    if args.require_100 and not complete:
        print("ERROR: functional coverage is below 100%", file=sys.stderr)
        return 1
    if not test_results:
        print("ERROR: no test results found in simulation logs", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
