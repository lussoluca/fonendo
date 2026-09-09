#!/usr/bin/env python3
"""Local logging proxy for the Anthropic API, with a built-in inspector UI.

Sits between Claude Code and api.anthropic.com and captures every request
and response byte, so you can inspect exactly what a coding agent sends to
the model: the system prompt text, the tool JSON schemas, the full message
history, and the raw SSE stream that comes back.

Run it, then start Claude Code pointed at it:

    python3 proxy.py --port 8484
    ANTHROPIC_BASE_URL=http://127.0.0.1:8484 claude

Inspector UI (live view of ongoing calls included):

    http://127.0.0.1:8484/__fonendo/

The UI is a Svelte app served from ../web/dist; build it once with
`npm install && npm run build` inside the web/ directory.

Each API call is written to ~/.claude/fonendo/raw/ as a single JSON
file. Auth headers (x-api-key, authorization) are forwarded upstream but
never written to the log files.

Stdlib only; no dependencies.
"""

import argparse
import http.client
import json
import queue
import re
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

UPSTREAM_HOST = "api.anthropic.com"
RAW_DIR = Path.home() / ".claude" / "fonendo" / "raw"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
UI_PREFIX = "/__fonendo"

CAPTURE_NAME_RE = re.compile(r"^[\w.-]+\.json$")
SESSION_RE = re.compile(r"session_([0-9a-f-]{8,})")
SESSION_ID_RE = re.compile(r"^[0-9a-f-]{8,64}$")

# Never persisted to the capture files.
REDACTED_HEADERS = {"x-api-key", "authorization", "cookie", "proxy-authorization"}
# Hop-by-hop headers, not forwarded in either direction.
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-connection",
    "transfer-encoding",
    "upgrade",
    "te",
    "trailer",
    "host",
    "content-length",
    "accept-encoding",
}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".woff2": "font/woff2",
}

_seq_lock = threading.Lock()
_seq = 0


def next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def sse_usage(body_text):
    """Merge the usage blocks found in a raw SSE response body."""
    usage = {}
    stop_reason = None
    for line in body_text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        if etype == "message_start":
            usage.update((event.get("message") or {}).get("usage") or {})
        elif etype == "message_delta":
            usage.update(event.get("usage") or {})
            stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
    return usage, stop_reason


def outline_response(body_text):
    """Compact outline of a model response: thinking?, text preview, tools."""
    outline = {"thinking": False, "text_preview": "", "tool_calls": []}
    if not body_text:
        return outline
    if "data:" not in body_text:
        try:
            message = json.loads(body_text)
        except json.JSONDecodeError:
            return outline
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "thinking":
                outline["thinking"] = True
            elif block.get("type") == "text":
                outline["text_preview"] = (
                    outline["text_preview"] + block.get("text", "")
                )[:200]
            elif block.get("type") == "tool_use":
                outline["tool_calls"].append(block.get("name", "?"))
        return outline
    text_len = 0
    for line in body_text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        if etype == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                outline["tool_calls"].append(block.get("name", "?"))
            elif block.get("type") == "thinking":
                outline["thinking"] = True
        elif etype == "content_block_delta" and text_len < 200:
            delta = event.get("delta") or {}
            if delta.get("type") == "text_delta":
                outline["text_preview"] += delta.get("text", "")
                text_len = len(outline["text_preview"])
    outline["text_preview"] = outline["text_preview"][:200]
    return outline


def outline_trigger(request_json):
    """What prompted this call: a typed prompt, tool results, and any injected
    context.

    Claude Code appends hook output (SessionStart, UserPromptSubmit, ...) as a
    trailing ``role: system`` message, and wraps other injected context
    (CLAUDE.md, env facts) in ``<system-reminder>`` text blocks inside the user
    message. Neither is typed by a human. A trailing system message is reported
    under ``system`` next to the message that precedes it, so the typed prompt
    stays visible; reminder blocks are stripped from ``preview`` and counted in
    ``injected``.
    Must stay in sync with outlineTrigger() in web/src/lib/sse.js.
    """
    messages = (request_json or {}).get("messages") or []
    if not messages:
        return {"type": "none"}
    last = messages[-1]
    if lane_kind(request_json) == "classifier":
        action = classifier_action(last)
        if action:
            return {"type": "user", "label": "graded action", "preview": action[:200], "injected": 0}
    if last.get("role") != "system":
        return describe_trigger_message(last)
    joined = " ".join(message_texts(last)).strip()
    system = {"source": injected_source(joined), "preview": joined[:200]}
    if len(messages) < 2:
        return {"type": "system", "system": system}
    trigger = describe_trigger_message(messages[-2])
    trigger["system"] = system
    return trigger


def message_texts(message):
    content = message.get("content")
    if isinstance(content, str):
        return [content]
    return [
        b.get("text", "")
        for b in content or []
        if isinstance(b, dict) and b.get("type") == "text"
    ]


def describe_trigger_message(message):
    content = message.get("content")
    blocks = [] if isinstance(content, str) else [
        b for b in content or [] if isinstance(b, dict)
    ]
    results = [b for b in blocks if b.get("type") == "tool_result"]
    if results:
        return {"type": "tool_result", "count": len(results)}
    human = []
    injected = 0
    for text in message_texts(message):
        stripped = SYSTEM_REMINDER_RE.sub("", text).strip()
        if stripped != text.strip():
            injected += 1
        if stripped:
            human.append(stripped)
    return {
        "type": "user",
        "preview": " ".join(human)[:200],
        "injected": injected,
    }


def injected_source(text):
    """Short label for a system message: its first line up to the first colon
    group, e.g. ``SessionStart:startup hook success``."""
    first_line = text.split("\n", 1)[0].strip()
    match = re.match(r"^([\w:-]+(?: hook \w+)?)", first_line)
    return (match.group(1) if match else first_line)[:60]


CLASSIFIER_PROMPT_RE = re.compile(r"You are a security monitor for autonomous AI coding agents")


def system_text(request_json):
    system = (request_json or {}).get("system")
    if isinstance(system, list):
        return " ".join(b.get("text", "") for b in system if isinstance(b, dict))
    return system or ""


def lane_kind(request_json):
    """Which conversation family a request belongs to.

    ``classifier`` is auto mode's permission classifier: one call per tool use,
    grading the newest action in a transcript excerpt. Everything else is left
    to the seed-based split (main agent, subagents, title, suggestions, quota)
    done by laneKind() in web/src/lib/sse.js.
    Must stay in sync with laneKind() in web/src/lib/sse.js.
    """
    if CLASSIFIER_PROMPT_RE.search(system_text(request_json)[:600]):
        return "classifier"
    return None


def classifier_action(message):
    """The action a permission-classifier call grades: the last transcript
    entry before ``</transcript>`` (a ``{"Bash": ...}``-style JSON line)."""
    texts = [t.strip() for t in message_texts(message) if t.strip()]
    last = ""
    for text in texts:
        if text.startswith("</transcript>"):
            break
        if text.startswith("{"):
            last = text
    return last


SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def first_message_seed(request_json):
    """First user message's text prefix — identifies a conversation thread.

    Calls belonging to the same agent loop share their first message, while
    subagents and utility sidechains (title, suggestions, quota probes) each
    start a fresh history, so this prefix separates the lanes of a session.
    Injected <system-reminder> blocks are stripped first: parallel subagents
    share the same reminder prefix and would otherwise collide.
    Must stay in sync with firstMessageSeed() in web/src/lib/sse.js.
    """
    messages = (request_json or {}).get("messages") or []
    if not messages:
        return ""
    content = messages[0].get("content")
    if isinstance(content, str):
        text = content
    else:
        text = " ".join(
            b.get("text", "")
            for b in content or []
            if isinstance(b, dict) and b.get("type") == "text"
        )
    stripped = SYSTEM_REMINDER_RE.sub("", text).strip()
    return (stripped or text.strip())[:200]


def summarize(request_json, status, response_text, duration_s, timestamp):
    """Build the small metadata block the UI lists calls by."""
    request_json = request_json or {}
    usage, stop_reason = sse_usage(response_text or "")
    if not usage:
        try:
            usage = json.loads(response_text).get("usage") or {}
        except (json.JSONDecodeError, AttributeError, TypeError):
            usage = {}
    system = request_json.get("system")
    if isinstance(system, list):
        system_chars = sum(
            len(b.get("text", "")) for b in system if isinstance(b, dict)
        )
    else:
        system_chars = len(system or "")
    # Claude Code encodes metadata.user_id as a JSON string:
    # {"device_id": ..., "account_uuid": ..., "session_id": "<uuid>"}
    session = None
    user_id = (request_json.get("metadata") or {}).get("user_id") or ""
    try:
        session = (json.loads(user_id) or {}).get("session_id")
    except (json.JSONDecodeError, TypeError):
        pass
    if not session:
        match = SESSION_RE.search(user_id)
        if match:
            session = match.group(1)
    return {
        "timestamp": timestamp,
        "duration_s": duration_s,
        "model": request_json.get("model"),
        "status": status,
        "stream": bool(request_json.get("stream")),
        "messages": len(request_json.get("messages") or []),
        "tools": len(request_json.get("tools") or []),
        "system_chars": system_chars,
        "usage": usage,
        "stop_reason": stop_reason,
        "session": session,
        "trigger": outline_trigger(request_json),
        "response": outline_response(response_text or ""),
        "thread_seed": first_message_seed(request_json),
        "lane": lane_kind(request_json),
    }


class EventBus:
    """Fan-out of proxy events to connected UI clients (SSE)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._clients = []
        self.inflight = {}  # id -> {"start": event, "chunks": [str]}

    def subscribe(self):
        client = queue.Queue(maxsize=4096)
        with self._lock:
            self._clients.append(client)
            snapshot = []
            for call in self.inflight.values():
                snapshot.append(("call_start", call["start"]))
                if call["chunks"]:
                    snapshot.append(
                        (
                            "chunk",
                            {
                                "id": call["start"]["id"],
                                "data": "".join(call["chunks"]),
                            },
                        )
                    )
        for item in snapshot:
            client.put_nowait(item)
        return client

    def unsubscribe(self, client):
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def publish(self, event_name, payload):
        with self._lock:
            if event_name == "call_start":
                self.inflight[payload["id"]] = {"start": payload, "chunks": []}
            elif event_name == "chunk":
                call = self.inflight.get(payload["id"])
                if call:
                    call["chunks"].append(payload["data"])
            elif event_name == "call_end":
                self.inflight.pop(payload["id"], None)
            clients = list(self._clients)
        for client in clients:
            try:
                client.put_nowait((event_name, payload))
            except queue.Full:
                pass


BUS = EventBus()
_summary_cache = {}  # filename -> (mtime, summary)


def capture_summary(path):
    mtime = path.stat().st_mtime
    cached = _summary_cache.get(path.name)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    # Recompute instead of trusting record["summary"], so files written by
    # older proxy versions pick up summary improvements.
    summary = summarize(
        record.get("request"),
        record.get("response_status"),
        record.get("response_body", ""),
        record.get("duration_s"),
        record.get("timestamp"),
    )
    summary = dict(summary)
    summary["file"] = path.name
    _summary_cache[path.name] = (mtime, summary)
    return summary


_session_meta_cache = {}  # session_id -> (transcript path, mtime, meta)


def session_meta(session_id):
    """Name and title Claude Code gave a session, read from its transcript.

    The transcript (``~/.claude/projects/<project>/<session_id>.jsonl``)
    carries ``{"type": "custom-title", "customTitle": ...}`` when the user
    names the session with ``/rename`` and ``{"type": "ai-title",
    "aiTitle": ...}`` when Claude Code generates a title from the first
    prompt. The last record of each kind wins. Cached per transcript mtime.
    """
    if not session_id or not SESSION_ID_RE.match(session_id):
        return None
    cached = _session_meta_cache.get(session_id)
    path = cached[0] if cached else None
    if path is None or not path.is_file():
        matches = (
            sorted(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
            if PROJECTS_DIR.is_dir()
            else []
        )
        if not matches:
            return None
        path = matches[0]
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if cached and cached[0] == path and cached[1] == mtime:
        return cached[2]
    meta = {"name": None, "title": None}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if '"custom-title"' not in line and '"ai-title"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = entry.get("type")
                if kind == "custom-title":
                    meta["name"] = entry.get("customTitle") or None
                elif kind == "ai-title":
                    meta["title"] = entry.get("aiTitle") or None
    except OSError:
        return None
    _session_meta_cache[session_id] = (path, mtime, meta)
    return meta


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # Quiet default access log; we print one line per call ourselves.
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path.startswith(UI_PREFIX):
            self._ui()
        else:
            self._proxy()

    def do_POST(self):
        if self.path.startswith(UI_PREFIX):
            route = self.path[len(UI_PREFIX):].split("?")[0]
            if route == "/api/clear":
                self._clear_captures()
            else:
                self._json_response(404, {"error": "not found"})
        else:
            self._proxy()

    def do_PUT(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    # ------------------------------------------------------------- UI side

    def _ui(self):
        route = self.path[len(UI_PREFIX):].split("?")[0] or "/"
        if route == "/api/captures":
            files = sorted(RAW_DIR.glob("*.json")) if RAW_DIR.is_dir() else []
            summaries = [s for s in (capture_summary(p) for p in files) if s]
            self._json_response(200, summaries)
        elif route == "/api/capture":
            name = (self.path.split("file=", 1) + [""])[1].split("&")[0]
            if not CAPTURE_NAME_RE.match(name):
                self._json_response(400, {"error": "bad file name"})
                return
            path = RAW_DIR / name
            if not path.is_file():
                self._json_response(404, {"error": "no such capture"})
                return
            self._send_bytes(200, "application/json", path.read_bytes())
        elif route == "/api/sessions":
            ids = parse_qs(urlparse(self.path).query).get("ids", [""])[0]
            result = {}
            for session_id in ids.split(","):
                meta = session_meta(session_id.strip())
                if meta:
                    result[session_id.strip()] = meta
            self._json_response(200, result)
        elif route == "/api/search":
            query = parse_qs(urlparse(self.path).query).get("q", [""])[0]
            query = query.strip().lower()
            matches = []
            if query and RAW_DIR.is_dir():
                for path in sorted(RAW_DIR.glob("*.json")):
                    try:
                        if query in path.read_text(encoding="utf-8").lower():
                            matches.append(path.name)
                    except OSError:
                        continue
            self._json_response(200, matches)
        elif route == "/api/events":
            self._events()
        else:
            self._static(route)

    def _clear_captures(self):
        deleted = 0
        if RAW_DIR.is_dir():
            for path in RAW_DIR.glob("*.json"):
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    pass
        _summary_cache.clear()
        self._json_response(200, {"deleted": deleted})

    def _events(self):
        client = BUS.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                try:
                    event_name, payload = client.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                data = json.dumps(payload, ensure_ascii=False)
                self.wfile.write(
                    f"event: {event_name}\ndata: {data}\n\n".encode()
                )
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            BUS.unsubscribe(client)

    def _static(self, route):
        if not WEB_DIST.is_dir():
            self._send_bytes(
                200,
                "text/html; charset=utf-8",
                b"<h1>fonendo UI not built</h1>"
                b"<p>Run <code>npm install && npm run build</code> in the "
                b"plugin's <code>web/</code> directory, then reload.</p>",
            )
            return
        rel = route.lstrip("/") or "index.html"
        target = (WEB_DIST / rel).resolve()
        if not str(target).startswith(str(WEB_DIST)) or not target.is_file():
            target = WEB_DIST / "index.html"
        mime = MIME.get(target.suffix, "application/octet-stream")
        self._send_bytes(200, mime, target.read_bytes())

    def _json_response(self, status, payload):
        self._send_bytes(
            status,
            "application/json",
            json.dumps(payload, ensure_ascii=False).encode(),
        )

    def _send_bytes(self, status, mime, body):
        try:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # ---------------------------------------------------------- proxy side

    def _proxy(self):
        started = time.time()
        call_id = next_seq()
        length = int(self.headers.get("Content-Length") or 0)
        request_body = self.rfile.read(length) if length else b""
        try:
            request_json = json.loads(request_body) if request_body else None
        except json.JSONDecodeError:
            request_json = None

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started))
        if request_json is not None:
            BUS.publish(
                "call_start",
                {
                    "id": call_id,
                    "timestamp": timestamp,
                    "method": self.command,
                    "path": self.path,
                    "request": request_json,
                },
            )

        upstream_headers = {}
        for name, value in self.headers.items():
            if name.lower() not in HOP_HEADERS:
                upstream_headers[name] = value
        upstream_headers["Host"] = UPSTREAM_HOST
        # Force an uncompressed response so the capture is plain text.
        upstream_headers["Accept-Encoding"] = "identity"

        conn = http.client.HTTPSConnection(
            UPSTREAM_HOST, context=ssl.create_default_context(), timeout=600
        )
        try:
            conn.request(self.command, self.path, request_body, upstream_headers)
            resp = conn.getresponse()

            self.send_response(resp.status, resp.reason)
            for name, value in resp.getheaders():
                if name.lower() not in HOP_HEADERS | {"content-encoding"}:
                    self.send_header(name, value)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            # Stream upstream bytes to the client immediately, tee into a
            # buffer for the capture file and to live UI subscribers.
            response_chunks = []
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                response_chunks.append(chunk)
                if request_json is not None:
                    BUS.publish(
                        "chunk",
                        {"id": call_id, "data": chunk.decode("utf-8", "replace")},
                    )
                self.wfile.write(b"%X\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            response_body = b"".join(response_chunks)
            response_headers = dict(resp.getheaders())
            status = resp.status
        except Exception as exc:  # noqa: BLE001 - report any upstream failure
            try:
                self.send_error(502, f"proxy error: {exc}")
            except Exception:
                pass
            response_body = f"<proxy error: {exc}>".encode()
            response_headers = {}
            status = 502
        finally:
            conn.close()

        capture_file = self._capture(
            started, timestamp, request_json, request_body, status, response_body,
            response_headers,
        )
        if request_json is not None:
            summary = summarize(
                request_json,
                status,
                response_body.decode("utf-8", "replace"),
                round(time.time() - started, 3),
                timestamp,
            )
            summary["file"] = capture_file
            BUS.publish("call_end", {"id": call_id, "summary": summary})

    def _capture(self, started, timestamp, request_json, request_body, status,
                 response_body, response_headers=None):
        try:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            logged_headers = {
                name: ("<redacted>" if name.lower() in REDACTED_HEADERS else value)
                for name, value in self.headers.items()
            }
            duration = round(time.time() - started, 3)
            response_text = response_body.decode("utf-8", "replace")
            record = {
                "timestamp": timestamp,
                "duration_s": duration,
                "method": self.command,
                "path": self.path,
                "request_headers": logged_headers,
                "request": request_json,
                "request_raw": None if request_json is not None else
                    request_body.decode("utf-8", "replace"),
                "response_status": status,
                "response_headers": response_headers or {},
                "response_body": response_text,
                "summary": summarize(
                    request_json, status, response_text, duration, timestamp
                ),
            }

            ts = time.strftime("%Y%m%dT%H%M%S", time.localtime(started))
            path = RAW_DIR / f"{ts}_{next_seq():04d}.json"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=1)

            model = (request_json or {}).get("model", "-")
            print(
                f"[{timestamp}] {self.command} {self.path} model={model} "
                f"status={status} req={len(request_body):,}B "
                f"resp={len(response_body):,}B -> {path.name}",
                flush=True,
            )
            return path.name
        except Exception as exc:  # noqa: BLE001 - capture must never kill the proxy
            print(f"capture failed: {exc}", file=sys.stderr, flush=True)
            return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8484)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.bind, args.port), ProxyHandler)
    print(
        f"logging proxy on http://{args.bind}:{args.port} -> "
        f"https://{UPSTREAM_HOST}\n"
        f"inspector UI:   http://{args.bind}:{args.port}{UI_PREFIX}/\n"
        f"captures in     {RAW_DIR}\n"
        f"start Claude Code with: "
        f"ANTHROPIC_BASE_URL=http://{args.bind}:{args.port} claude",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
