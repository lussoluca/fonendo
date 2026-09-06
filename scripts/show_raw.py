#!/usr/bin/env python3
"""Inspect raw API captures written by proxy.py.

Usage:
    show_raw.py                    # list all captured calls
    show_raw.py <n>                # overview of capture #n
    show_raw.py <n> system         # full system prompt text
    show_raw.py <n> tools          # tool names + descriptions
    show_raw.py <n> tools <name>   # full JSON schema of one tool
    show_raw.py <n> messages       # message history (previews)
    show_raw.py <n> response       # assembled model response + usage
    show_raw.py <n> raw            # dump the entire capture JSON
"""

import json
import sys
from pathlib import Path

RAW_DIR = Path.home() / ".claude" / "fonendo" / "raw"


def captures():
    return sorted(RAW_DIR.glob("*.json")) if RAW_DIR.is_dir() else []


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def block_preview(block, width=80):
    btype = block.get("type", "?")
    if btype == "text":
        return f"text: {block.get('text', '')[:width]!r}"
    if btype == "tool_use":
        args = json.dumps(block.get("input", {}))[:width]
        return f"tool_use: {block.get('name')} {args}"
    if btype == "tool_result":
        content = block.get("content")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        return f"tool_result: {str(content)[:width]!r}"
    if btype == "thinking":
        return f"thinking: {block.get('thinking', '')[:width]!r}"
    return btype


def parse_sse(body):
    """Assemble the final message from a raw SSE stream."""
    text, thinking, tool_uses, usage, model, stop = [], [], [], {}, None, None
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        if etype == "message_start":
            message = event.get("message", {})
            model = message.get("model")
            usage.update(message.get("usage") or {})
        elif etype == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                tool_uses.append({"name": block.get("name"), "input_json": ""})
        elif etype == "content_block_delta":
            delta = event.get("delta", {})
            dtype = delta.get("type")
            if dtype == "text_delta":
                text.append(delta.get("text", ""))
            elif dtype == "thinking_delta":
                thinking.append(delta.get("thinking", ""))
            elif dtype == "input_json_delta" and tool_uses:
                tool_uses[-1]["input_json"] += delta.get("partial_json", "")
        elif etype == "message_delta":
            usage.update(event.get("usage") or {})
            stop = (event.get("delta") or {}).get("stop_reason") or stop
    return {
        "model": model,
        "text": "".join(text),
        "thinking": "".join(thinking),
        "tool_uses": tool_uses,
        "usage": usage,
        "stop_reason": stop,
    }


def system_text(request):
    system = request.get("system")
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n\n".join(
            b.get("text", "") for b in system if isinstance(b, dict)
        )
    return ""


def cmd_list(files):
    print(f"{len(files)} captures in {RAW_DIR}\n")
    print(f"{'#':>3}  {'time':19}  {'model':28}  {'msgs':>4}  {'tools':>5}  "
          f"{'req size':>9}  {'status':>6}")
    for i, path in enumerate(files, 1):
        record = load(path)
        request = record.get("request") or {}
        print(
            f"{i:>3}  {record.get('timestamp', '')[:19]:19}  "
            f"{str(request.get('model', '-')):28}  "
            f"{len(request.get('messages') or []):>4}  "
            f"{len(request.get('tools') or []):>5}  "
            f"{len(json.dumps(request)) if request else 0:>9,}  "
            f"{record.get('response_status'):>6}"
        )


def cmd_overview(record):
    request = record.get("request") or {}
    system = system_text(request)
    tools = request.get("tools") or []
    messages = request.get("messages") or []
    print(f"{record['method']} {record['path']}  "
          f"status={record['response_status']}  {record['duration_s']}s")
    print(f"model:      {request.get('model')}")
    print(f"max_tokens: {request.get('max_tokens')}  "
          f"stream: {request.get('stream')}  "
          f"thinking: {bool(request.get('thinking'))}")
    raw_system = request.get("system")
    sections = len(raw_system) if isinstance(raw_system, list) else 1
    print(f"system:     {len(system):,} chars (sections: {sections})")
    print(f"tools:      {len(tools)} "
          f"({len(json.dumps(tools)):,} chars of JSON schema)")
    print(f"messages:   {len(messages)}")
    parsed = parse_sse(record.get("response_body", ""))
    if parsed["usage"]:
        print(f"usage:      {json.dumps(parsed['usage'])}")
    print("\nsubcommands: system | tools [name] | messages | response | raw")


def cmd_tools(request, name=None):
    tools = request.get("tools") or []
    if name:
        for tool in tools:
            if tool.get("name") == name:
                print(json.dumps(tool, indent=2, ensure_ascii=False))
                return
        print(f"no tool named {name!r}")
        return
    for tool in tools:
        desc = (tool.get("description") or "").split("\n")[0][:90]
        schema_size = len(json.dumps(tool.get("input_schema") or {}))
        print(f"{tool.get('name'):32} schema={schema_size:>6,}B  {desc}")


def cmd_messages(request):
    for i, message in enumerate(request.get("messages") or [], 1):
        content = message.get("content")
        print(f"--- [{i}] {message.get('role')}")
        if isinstance(content, str):
            print(f"    text: {content[:100]!r}")
        else:
            for block in content or []:
                print(f"    {block_preview(block)}")


def cmd_response(record):
    body = record.get("response_body", "")
    if "data:" not in body:
        print(body)
        return
    parsed = parse_sse(body)
    print(f"model: {parsed['model']}   stop_reason: {parsed['stop_reason']}")
    print(f"usage: {json.dumps(parsed['usage'])}\n")
    if parsed["thinking"]:
        print(f"=== thinking ===\n{parsed['thinking']}\n")
    if parsed["text"]:
        print(f"=== text ===\n{parsed['text']}\n")
    for tool_use in parsed["tool_uses"]:
        print(f"=== tool_use: {tool_use['name']} ===")
        print(tool_use["input_json"][:2000])


def main():
    files = captures()
    if not files:
        print(f"no captures in {RAW_DIR} — run the proxy first "
              f"(see proxy.py --help)")
        return 1
    if len(sys.argv) < 2:
        cmd_list(files)
        return 0

    try:
        index = int(sys.argv[1])
        record = load(files[index - 1])
    except (ValueError, IndexError):
        print(f"pick a capture number 1..{len(files)} (no argument = list)")
        return 1

    sub = sys.argv[2] if len(sys.argv) > 2 else "overview"
    request = record.get("request") or {}
    if sub == "overview":
        cmd_overview(record)
    elif sub == "system":
        print(system_text(request))
    elif sub == "tools":
        cmd_tools(request, sys.argv[3] if len(sys.argv) > 3 else None)
    elif sub == "messages":
        cmd_messages(request)
    elif sub == "response":
        cmd_response(record)
    elif sub == "raw":
        print(json.dumps(record, indent=1, ensure_ascii=False))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
