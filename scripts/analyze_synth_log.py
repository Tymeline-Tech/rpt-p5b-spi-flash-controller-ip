#!/usr/bin/env python3
"""Parse Yosys synthesis artifacts for critical warning categories.

Categories of interest (story: Synthesis Execution & Critical Warning Analysis):
  - inferred latch (positive latch creation)
  - unconnected / undriven signals (textual Warnings + unused_bits in netlist)
  - other Warning: lines (e.g. memory → register)

Maps findings to APB (spi_reg_block), FIFO (spi_tx/rx_fifo), SPI Master
(spi_master), and Top (spi_flash_ctrl).

Usage (from repo root, after `make synth`):
  python3 scripts/analyze_synth_log.py
  python3 scripts/analyze_synth_log.py --log artifacts/synth.log \\
      --ilang artifacts/synth.ilang
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


MODULE_BUCKETS = (
    ("FIFO", ("spi_tx_fifo", "spi_rx_fifo")),
    ("APB", ("spi_reg_block",)),
    ("SPI Master", ("spi_master",)),
    ("Top", ("spi_flash_ctrl",)),
)


def bucket_for(text: str) -> str:
    lower = text.lower()
    for name, keys in MODULE_BUCKETS:
        if any(k in lower for k in keys):
            return name
    return "Other / flow"


def parse_warnings(log_text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, line in enumerate(log_text.splitlines(), 1):
        if line.startswith("Warning:"):
            out.append((i, line.strip()))
    return out


def parse_latch_messages(log_text: str) -> dict[str, list[tuple[int, str]]]:
    """Split PROC_DLATCH commentary into positive vs negative latch messages."""
    pos: list[tuple[int, str]] = []
    neg: list[tuple[int, str]] = []
    for i, line in enumerate(log_text.splitlines(), 1):
        s = line.strip()
        low = s.lower()
        if "no latch inferred" in low:
            neg.append((i, s))
        elif re.search(r"\binferred latch\b|\bcreating latch\b|\blatch for signal\b", low):
            if "no latch" not in low:
                pos.append((i, s))
    return {"positive": pos, "negative": neg}


def parse_unconnected_text(log_text: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    pat = re.compile(r"unconnected|undriven|dangling", re.I)
    for i, line in enumerate(log_text.splitlines(), 1):
        if pat.search(line):
            hits.append((i, line.strip()))
    return hits


def parse_unused_bits(ilang_text: str) -> list[dict[str, str]]:
    """Walk RTLIL and collect wires carrying unused_bits attributes.

    Yosys typically emits attributes immediately before the wire, e.g.::

        attribute \\src "rtl/spi_flash_ctrl.sv:66..."
        attribute \\unused_bits "0"
        wire \\rx_full
    """
    findings: list[dict[str, str]] = []
    current_mod = ""
    pending_attrs: dict[str, str] = {}

    wire_re = re.compile(
        r"^\s*wire(?:\s+width\s+(\d+))?\s+(?:input\s+\d+\s+|output\s+\d+\s+)?\\?(\S+)\s*$"
    )
    mod_re = re.compile(r"^module\s+\\?(\S+)\s*$")
    attr_re = re.compile(r'^\s*attribute\s+\\(\S+)\s+"([^"]*)"\s*$')

    for line in ilang_text.splitlines():
        m = mod_re.match(line)
        if m:
            current_mod = m.group(1)
            pending_attrs = {}
            continue
        if line.strip() == "end":
            current_mod = ""
            pending_attrs = {}
            continue

        am = attr_re.match(line)
        if am:
            pending_attrs[am.group(1)] = am.group(2)
            continue

        wm = wire_re.match(line)
        if wm:
            if "unused_bits" in pending_attrs:
                width = wm.group(1) or "1"
                name = wm.group(2)
                src = pending_attrs.get("src", "")
                findings.append(
                    {
                        "module": current_mod,
                        "signal": name,
                        "width": width,
                        "unused_bits": pending_attrs["unused_bits"],
                        "src": src,
                        "bucket": bucket_for(current_mod + " " + src),
                    }
                )
            pending_attrs = {}
            continue

        # Any other non-attribute statement ends the pending attribute block.
        if line.strip() and not line.strip().startswith("attribute"):
            pending_attrs = {}

    return findings


def summarize(log_path: Path, ilang_path: Path | None) -> int:
    if not log_path.is_file():
        print(f"error: missing log {log_path}", file=sys.stderr)
        return 1

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    warnings = parse_warnings(log_text)
    latches = parse_latch_messages(log_text)
    unconn_text = parse_unconnected_text(log_text)

    print("=== Yosys Warning: lines ===")
    if not warnings:
        print("  (none)")
    else:
        by_bucket: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for ln, msg in warnings:
            by_bucket[bucket_for(msg)].append((ln, msg))
        for bucket, items in sorted(by_bucket.items()):
            print(f"  [{bucket}] {len(items)}")
            for ln, msg in items:
                print(f"    L{ln}: {msg}")

    uniq = Counter(msg for _, msg in warnings)
    print(f"\nUnique Warning messages: {len(uniq)} (total {len(warnings)})")

    print("\n=== Inferred latch ===")
    print(f"  Positive latch creations: {len(latches['positive'])}")
    for ln, msg in latches["positive"][:20]:
        print(f"    L{ln}: {msg}")
    print(f"  Explicit 'No latch inferred': {len(latches['negative'])}")
    # Show one sample per module bucket
    seen_bucket: set[str] = set()
    for ln, msg in latches["negative"]:
        b = bucket_for(msg)
        if b not in seen_bucket:
            seen_bucket.add(b)
            print(f"    sample [{b}] L{ln}: {msg[:120]}")

    print("\n=== Textual unconnected / undriven ===")
    if not unconn_text:
        print("  (none)")
    else:
        for ln, msg in unconn_text:
            print(f"    L{ln}: {msg}")

    if ilang_path is not None and ilang_path.is_file():
        print("\n=== Netlist unused_bits (unconnected after opt) ===")
        findings = parse_unused_bits(ilang_path.read_text(encoding="utf-8", errors="replace"))
        if not findings:
            print("  (none)")
        else:
            by_bucket: dict[str, list[dict[str, str]]] = defaultdict(list)
            for f in findings:
                by_bucket[f["bucket"]].append(f)
            for bucket, items in sorted(by_bucket.items()):
                print(f"  [{bucket}] {len(items)}")
                for f in items:
                    src = f["src"] or "?"
                    print(
                        f"    {f['module']}.{f['signal']} "
                        f"unused_bits=\"{f['unused_bits']}\" src={src}"
                    )
    elif ilang_path is not None:
        print(f"\n(warning: ilang not found at {ilang_path})", file=sys.stderr)

    print("\n=== Verdict ===")
    n_latch = len(latches["positive"])
    n_unconn_warn = len([1 for _, m in warnings if re.search(r"unconnected|undriven", m, re.I)])
    print(f"  inferred_latch_defects={n_latch}")
    print(f"  unconnected_warning_lines={n_unconn_warn}")
    print(f"  other_warning_lines={len(warnings)}")
    print("  See docs/synth_issue_tracker.md for mapped analysis.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", type=Path, default=Path("artifacts/synth.log"))
    ap.add_argument("--ilang", type=Path, default=Path("artifacts/synth.ilang"))
    args = ap.parse_args()
    return summarize(args.log, args.ilang)


if __name__ == "__main__":
    sys.exit(main())
