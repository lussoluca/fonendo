# fonendo

_A stethoscope for Claude Code_ — from the Italian **fonendoscopio**.

A Claude Code plugin that shows what actually travels between Claude Code
and the model, at two levels of detail:

1. **Token accounting** (always on once installed): per-call token usage
   extracted from the session transcript, shown with `/fonendo:show`.
2. **Raw traffic capture** (opt-in, via a local proxy): the complete request
   payload — system prompt text, tool JSON schemas, full message history —
   and the raw SSE response stream, inspected with `/fonendo:raw` or in the
   browser with the built-in inspector UI, which also shows calls live while
   they stream.

## Scope: study and debugging only

fonendo is a **passive observation tool**, built to study how an agentic
coding tool talks to its model and to debug that traffic. Like the
stethoscope it is named after, it listens and never touches:

- The proxy forwards every request and every response **byte-for-byte,
  unmodified, in both directions**. It never alters, injects, drops, or
  reorders anything on the wire.
- It must not be used as a base for tampering with model traffic —
  rewriting prompts or responses, stripping or spoofing headers, bypassing
  rate limits or safety systems, or impersonating clients. That is outside
  this project's purpose and may violate your API provider's terms of
  service.
- Everything runs and stays on your own machine, observing your own
  traffic, with your own credentials. Auth headers are forwarded upstream
  but redacted in the capture files.

## Level 1: token accounting

- A `Stop` hook fires every time Claude finishes responding. It parses the
  session transcript (the JSONL file Claude Code keeps for each session) and
  extracts the raw API `usage` block of every model call: fresh input tokens,
  cache writes, cache reads, and output tokens.
- The extracted records are written to `~/.claude/fonendo/<session_id>.jsonl`.
- The `/fonendo:show` command prints a per-call table with totals.

## Install

Run Claude Code with the plugin loaded:

```bash
claude --plugin-dir /Users/lussoluca/Sites/Development/AI/plugins/fonendo
```

After editing the plugin, reload it inside a session with `/reload-plugins`.

## Usage

Talk to Claude as usual, then run:

```
/fonendo:show            # current (most recent) session
/fonendo:show <id>       # specific session id (prefix match)
/fonendo:show --all      # every logged session
```

The viewer also works standalone, outside Claude Code:

```bash
python3 scripts/show_tokens.py
```

## Example output

```
  #  time       fresh in   cache wr   cache rd      out   total in  what
------------------------------------------------------------------------
  1  14:01:20          2     50,637          0    3,765     50,639  [thinking] tools: Bash,Agent
  2  14:01:45          2      4,237     50,637    1,836     54,876  [thinking] tools: Write
  3  14:02:04          2      1,927     54,874    1,706     56,803  tools: Write
------------------------------------------------------------------------
TOT                    6     56,801    105,511    7,307    162,318
```

## What the numbers teach you

- **The model is stateless.** Every call resends the entire conversation:
  system prompt, tool definitions, and all prior messages. That is why
  `total in` grows on every row even when you type a short message.
- **One turn is many calls.** Each tool use (reading a file, running a
  command) requires a full round trip to the model, each with the whole
  context attached.
- **Prompt caching makes this affordable.** The unchanged prefix of the
  conversation is written to a cache once (`cache wr`) and served cheaply on
  later calls (`cache rd`). Only the new suffix is processed at full price
  (`fresh in`).
- **Output is small compared to input.** The model generates a few thousand
  tokens per turn while reading hundreds of thousands. This asymmetry drives
  both latency and cost.

## Level 2: raw traffic capture (the proxy)

The transcript only carries token counts and message content. To see the
literal bytes — the system prompt Claude Code injects, the JSON schema of
every tool, and the SSE event stream coming back — route Claude Code through
the bundled logging proxy.

### Run

Install the proxy once as a login service, then launch Claude Code through it
from any project directory:

```bash
scripts/install-proxy-service.sh        # launchd on macOS, systemd --user on Linux
cd ~/some/project
/path/to/fonendo/scripts/claude-logged.sh
```

`install-proxy-service.sh` builds the inspector UI if needed, then registers
`scripts/proxy.py` on `127.0.0.1:8484` to start at login and restart if it
dies (`--uninstall` removes it). `claude-logged.sh` checks that the proxy is
reachable, sets `ANTHROPIC_BASE_URL=http://127.0.0.1:8484`, loads the plugin
with `--plugin-dir`, and passes any extra arguments to `claude`. Override the
port for both with `FONENDO_PROXY_PORT`. Without the service, run the proxy
by hand:

```bash
python3 scripts/proxy.py --port 8484
ANTHROPIC_BASE_URL=http://127.0.0.1:8484 claude --plugin-dir /path/to/fonendo
```

Every API call becomes one JSON file in `~/.claude/fonendo/raw/`,
holding the parsed request payload, redacted request headers, and the raw
response body (the full SSE stream for streaming calls).

### Inspect

```
/fonendo:raw                    # list captured calls
/fonendo:raw 3                  # overview of call #3
/fonendo:raw 3 system           # the full system prompt text
/fonendo:raw 3 tools            # every tool with schema size
/fonendo:raw 3 tools Bash       # full JSON schema of one tool
/fonendo:raw 3 messages         # the message history sent
/fonendo:raw 3 response         # assembled response (thinking, text, tool calls) + usage
/fonendo:raw 3 raw              # entire capture file
```

The viewer also works standalone: `python3 scripts/show_raw.py`.

### Inspector UI

The proxy serves a Svelte web app at:

```
http://127.0.0.1:8484/__fonendo/
```

- **Call list grouped by Claude Code session** (from the request's
  `metadata.user_id`), each group header showing the session name (set
  with `/rename`) and the title Claude Code generated, both read from the
  session transcript, plus call count and total input/output tokens; each
  row shows model and a stacked token bar (fresh input / cache write /
  cache read / output).
- **Full-text search** across all captures — system prompts, tool schemas,
  messages, and responses are searched server-side; group stats recompute
  on the filtered set.
- **Session flow view** (click a session header): a vertical timeline of the
  agentic loop — each user turn, then the chain of model calls it triggered,
  with thinking markers, response previews, tool-call chips, and
  "tool results fed back" connectors between calls. Context Claude Code
  injects on its own is told apart from typed text: hook output sent as a
  trailing `role: system` message shows as a dashed "system" card, and
  `<system-reminder>` blocks (CLAUDE.md, env facts) are stripped from the
  user preview and counted as "+N injected". Live calls appear in the
  flow while still streaming; clicking a call opens its full payload.
- **Detail tabs**: overview, system prompt, tool schemas, message history,
  assembled response (thinking, text, tool calls), and the raw capture JSON.
- **Live view**: the UI is connected to the proxy over an SSE event stream.
  Calls appear the moment Claude Code sends them and the response streams
  into the "response" tab in real time; when a call finishes, its row gains
  the final token bar and usage numbers.

`install-proxy-service.sh` builds the UI on first run (needs Node). To
build manually or develop it:

```bash
cd web
npm install
npm run build        # production build served by the proxy
npm run dev          # Vite dev server with API proxied to :8484
```

### Notes

- Auth headers (`x-api-key`, `authorization`) are forwarded upstream but
  written to the capture files as `<redacted>`.
- Capture files contain your full conversations and system prompts. They are
  local files under your home directory; treat them accordingly.
- The proxy is stdlib-only Python, forwards to `api.anthropic.com`, and
  streams responses through unbuffered, so latency is unaffected.

## Files

| Path                               | Purpose                                       |
| ---------------------------------- | --------------------------------------------- |
| `.claude-plugin/plugin.json`       | Plugin manifest                               |
| `hooks/hooks.json`                 | Registers the `Stop` hook                     |
| `scripts/log_tokens.py`            | Parses the transcript, writes the usage log   |
| `scripts/show_tokens.py`           | Renders the per-call table                    |
| `commands/show.md`                 | The `/fonendo:show` slash command             |
| `scripts/proxy.py`                 | Logging proxy for raw API traffic             |
| `scripts/install-proxy-service.sh` | Installs the proxy as a login service         |
| `scripts/claude-logged.sh`         | Runs Claude Code through the proxy + plugin   |
| `scripts/show_raw.py`              | Raw capture inspector (CLI)                   |
| `commands/raw.md`                  | The `/fonendo:raw` slash command              |
| `web/`                             | Svelte inspector UI (served at `/__fonendo/`) |
