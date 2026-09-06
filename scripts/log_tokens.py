#!/usr/bin/env python3
"""Stop-hook logger: extract per-API-call token usage from the session transcript.

Claude Code passes hook input as JSON on stdin, including `transcript_path`,
the JSONL file holding the full session conversation. Every assistant line in
that file carries the raw API `usage` block for one model call. This script
rebuilds a compact usage log for the session on every Stop event, so the log
is always consistent with the transcript (idempotent, no incremental state).

Log location: ~/.claude/fonendo/<session_id>.jsonl
"""

import json
import os
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".claude" / "fonendo"


def parse_transcript(transcript_path):
    """Return one record per model API call, deduped by API message id.

    Streaming responses can appear as several transcript lines sharing the
    same message.id; the last line has the final cumulative usage, so later
    lines overwrite earlier ones.
    """
    calls = {}
    order = []
    with open(transcript_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message") or {}
            usage = message.get("usage")
            msg_id = message.get("id")
            if not usage or not msg_id:
                continue

            content = message.get("content") or []
            text_parts = []
            tool_names = []
            has_thinking = False
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    tool_names.append(block.get("name", "?"))
                elif btype == "thinking":
                    has_thinking = True

            record = calls.get(msg_id)
            if record is None:
                record = {"id": msg_id}
                calls[msg_id] = record
                order.append(msg_id)

            record.update(
                {
                    "timestamp": entry.get("timestamp"),
                    "model": message.get("model"),
                    "input_tokens": usage.get("input_tokens", 0),
                    "cache_creation_input_tokens": usage.get(
                        "cache_creation_input_tokens", 0
                    ),
                    "cache_read_input_tokens": usage.get(
                        "cache_read_input_tokens", 0
                    ),
                    "output_tokens": usage.get("output_tokens", 0),
                    "stop_reason": message.get("stop_reason"),
                    "tools_called": record.get("tools_called", []) + tool_names,
                    "has_thinking": record.get("has_thinking", False)
                    or has_thinking,
                    "text_preview": (
                        " ".join(text_parts)[:120]
                        or record.get("text_preview", "")
                    ),
                }
            )
    return [calls[msg_id] for msg_id in order]


def main():
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    transcript_path = hook_input.get("transcript_path")
    session_id = hook_input.get("session_id", "unknown")
    if not transcript_path or not os.path.isfile(transcript_path):
        return 0

    records = parse_transcript(transcript_path)
    if not records:
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{session_id}.jsonl"
    tmp_file = log_file.with_suffix(".jsonl.tmp")
    with open(tmp_file, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp_file.replace(log_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
