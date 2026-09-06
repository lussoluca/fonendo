#!/usr/bin/env python3
"""Print a per-call token usage table for one session (or all sessions).

Usage:
    show_tokens.py [session_id | --all]

Without arguments it shows the most recently updated session log.
Reads the JSONL files written by log_tokens.py in ~/.claude/fonendo/.
"""

import json
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".claude" / "fonendo"


def load(log_file):
    records = []
    with open(log_file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def fmt(n):
    return f"{n:,}"


def show_session(log_file):
    records = load(log_file)
    if not records:
        print(f"No records in {log_file}")
        return

    session_id = log_file.stem
    print(f"Session: {session_id}")
    print(f"Model calls: {len(records)}\n")

    header = (
        f"{'#':>3}  {'time':8}  {'fresh in':>9}  {'cache wr':>9}  "
        f"{'cache rd':>9}  {'out':>7}  {'total in':>9}  what"
    )
    print(header)
    print("-" * len(header))

    totals = {"in": 0, "cw": 0, "cr": 0, "out": 0}
    for i, r in enumerate(records, 1):
        t = (r.get("timestamp") or "")[11:19]
        fin = r.get("input_tokens", 0)
        cw = r.get("cache_creation_input_tokens", 0)
        cr = r.get("cache_read_input_tokens", 0)
        out = r.get("output_tokens", 0)
        totals["in"] += fin
        totals["cw"] += cw
        totals["cr"] += cr
        totals["out"] += out

        tools = r.get("tools_called") or []
        if tools:
            what = "tools: " + ",".join(tools[:3])
            if len(tools) > 3:
                what += f" +{len(tools) - 3}"
        else:
            what = (r.get("text_preview") or "").replace("\n", " ")[:40]
        if r.get("has_thinking"):
            what = "[thinking] " + what

        print(
            f"{i:>3}  {t:8}  {fmt(fin):>9}  {fmt(cw):>9}  "
            f"{fmt(cr):>9}  {fmt(out):>7}  {fmt(fin + cw + cr):>9}  {what[:50]}"
        )

    print("-" * len(header))
    total_in = totals["in"] + totals["cw"] + totals["cr"]
    print(
        f"{'TOT':>3}  {'':8}  {fmt(totals['in']):>9}  {fmt(totals['cw']):>9}  "
        f"{fmt(totals['cr']):>9}  {fmt(totals['out']):>7}  {fmt(total_in):>9}"
    )

    print(
        "\nColumns:\n"
        "  fresh in  = input tokens processed from scratch this call\n"
        "  cache wr  = input tokens written to the prompt cache\n"
        "  cache rd  = input tokens served from the prompt cache (cheap)\n"
        "  out       = tokens the model generated\n"
        "  total in  = full prompt size the model actually saw\n"
        "\nNote how 'total in' grows every call: the whole conversation\n"
        "(system prompt, tools, every prior message) is resent each time —\n"
        "the model is stateless. The cache columns show how Claude Code\n"
        "avoids paying full price for the repeated prefix."
    )


def main():
    if not LOG_DIR.is_dir():
        print(f"No logs yet ({LOG_DIR} missing). Talk to Claude first.")
        return 1

    logs = sorted(
        LOG_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not logs:
        print(f"No logs yet in {LOG_DIR}.")
        return 1

    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg == "--all":
        for log_file in logs:
            show_session(log_file)
            print("\n" + "=" * 80 + "\n")
    elif arg:
        matches = [p for p in logs if p.stem.startswith(arg)]
        if not matches:
            print(f"No session log matching '{arg}'.")
            return 1
        show_session(matches[0])
    else:
        show_session(logs[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
