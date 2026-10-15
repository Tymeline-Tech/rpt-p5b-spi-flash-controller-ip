#!/usr/bin/env python3
"""Validate OpenROAD P&R collateral without requiring a full P&R run.

Checks:
  1. Tcl brace/bracket balance in pr_flow/openroad_pr.tcl
  2. Required repo files resolve (SDC, script, expected netlist path after synth)
  3. PDK paths resolve when PDK_ROOT is set
  4. If `openroad` is on PATH, run prepare/read-only mode (-exit)

Exit 0 on success.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "pr_flow" / "openroad_pr.tcl"
SDC = REPO / "constraints" / "design.sdc"
SDC_ALIAS = REPO / "constraints" / "spi_flash_ctrl.sdc"
NETLIST = REPO / "artifacts" / "spi_flash_ctrl_mapped.v"

PDK_REL = [
    "sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd.tlef",
    "sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef",
    "sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib",
]


def check_balance(text: str, path: Path) -> None:
    pairs = {"{": "}", "[": "]", "(": ")"}
    openers = set(pairs)
    closers = {v: k for k, v in pairs.items()}
    stack: list[tuple[str, int]] = []
    in_brace_comment = False  # Tcl # comments to EOL
    i = 0
    line = 1
    while i < len(text):
        ch = text[i]
        if ch == "\n":
            line += 1
            in_brace_comment = False
            i += 1
            continue
        if in_brace_comment:
            i += 1
            continue
        if ch == "#" and (i == 0 or text[i - 1] in " \t\n;"):
            in_brace_comment = True
            i += 1
            continue
        if ch == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                if text[i] == "\\" and i + 1 < len(text):
                    i += 2
                    continue
                if text[i] == "\n":
                    line += 1
                i += 1
            i += 1
            continue
        if ch in openers:
            stack.append((ch, line))
        elif ch in closers:
            if not stack or stack[-1][0] != closers[ch]:
                raise SystemExit(f"ERROR: unbalanced '{ch}' in {path} near line {line}")
            stack.pop()
        i += 1
    if stack:
        ch, ln = stack[-1]
        raise SystemExit(f"ERROR: unclosed '{ch}' in {path} opened at line {ln}")
    print(f"OK: Tcl delimiter balance — {path.relative_to(REPO)}")


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"ERROR: missing {label}: {path}")
    print(f"OK: {label} — {path.relative_to(REPO) if path.is_relative_to(REPO) else path}")


def main() -> int:
    require_file(SCRIPT, "OpenROAD flow script")
    require_file(SDC, "design SDC")
    require_file(SDC_ALIAS, "project SDC alias")

    sdc_text = SDC.read_text(encoding="utf-8")
    if "create_clock -period 20.0 [get_ports clk]" not in sdc_text:
        raise SystemExit("ERROR: constraints/design.sdc missing required create_clock line")
    print("OK: SDC contains create_clock -period 20.0 [get_ports clk]")

    tcl = SCRIPT.read_text(encoding="utf-8")
    check_balance(tcl, SCRIPT)
    for token in (
        "PDK_ROOT",
        "read_verilog",
        "CORE_UTILIZATION",
        "40",
        "design.sdc",
        "spi_flash_ctrl",
    ):
        if token not in tcl:
            raise SystemExit(f"ERROR: {SCRIPT.name} missing expected token {token!r}")
    print("OK: openroad_pr.tcl contains PDK/netlist/floorplan setup tokens")

    if NETLIST.is_file():
        print(f"OK: mapped netlist present — {NETLIST.relative_to(REPO)}")
    else:
        print(
            f"WARN: mapped netlist not built yet ({NETLIST.relative_to(REPO)}); "
            "run make synth before OpenROAD prepare."
        )

    pdk_root = os.environ.get("PDK_ROOT", "").strip()
    if pdk_root:
        root = Path(pdk_root)
        for rel in PDK_REL:
            path = root / rel
            if not path.is_file():
                raise SystemExit(f"ERROR: PDK file missing: {path}")
            print(f"OK: PDK path resolves — {path}")
    else:
        print("WARN: PDK_ROOT unset — skipped live PDK path resolution")

    openroad = shutil.which("openroad")
    if openroad:
        if not pdk_root:
            print("WARN: openroad found but PDK_ROOT unset — skip openroad -exit")
            return 0
        if not NETLIST.is_file():
            print("WARN: openroad found but netlist missing — skip openroad -exit")
            return 0
        env = os.environ.copy()
        env["OPENROAD_PREPARE_ONLY"] = "1"
        env["OPENROAD_FLOW_ROOT"] = str(REPO)
        print(f"INFO: running OpenROAD prepare/read-only: {openroad} -exit {SCRIPT}")
        proc = subprocess.run(
            [openroad, "-exit", str(SCRIPT)],
            cwd=str(REPO),
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            raise SystemExit(f"ERROR: openroad -exit failed with code {proc.returncode}")
        print("OK: OpenROAD prepare/read-only completed")
    else:
        print(
            "WARN: openroad binary not on PATH — syntax/path checks only "
            "(gate containers do not ship OpenROAD; collateral is reviewable Tcl/SDC)."
        )

    print("validate_config: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
