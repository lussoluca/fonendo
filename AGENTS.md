# AGENTS.md

## Project Overview

`logger` is a Claude Code plugin that shows what actually travels between
Claude Code and the model, at two levels of detail:

1. **Token accounting** (always on once installed): a `Stop` hook parses the
   session transcript and writes per-call token usage records to
   `~/.claude/fonendo/<session_id>.jsonl`; `/fonendo:show` renders them
   as a table.
2. **Raw traffic capture** (opt-in): a local logging proxy
   (`scripts/proxy.py`) sits between Claude Code and `api.anthropic.com`,
   captures every request and response byte to
   `~/.claude/fonendo/raw/`, and serves a live Svelte inspector UI at
   `http://127.0.0.1:8484/__fonendo/`. `/fonendo:raw` inspects captures from
   the CLI.

**Tech stack:** Python 3 (stdlib only — no dependencies) for the hook,
viewers, and proxy; Svelte 5 + Vite 6 for the inspector UI; Claude Code
plugin manifest (`.claude-plugin/plugin.json`), hooks (`hooks/hooks.json`),
and slash commands (`commands/*.md`).

## Repository Layout

| Path                         | Purpose                                        |
| ---------------------------- | ---------------------------------------------- |
| `.claude-plugin/plugin.json` | Plugin manifest                                |
| `hooks/hooks.json`           | Registers the `Stop` hook                      |
| `scripts/log_tokens.py`      | Stop hook: parses transcript, writes usage log |
| `scripts/show_tokens.py`     | Renders the per-call token table               |
| `scripts/proxy.py`           | Logging proxy for raw API traffic + UI server  |
| `scripts/claude-logged.sh`   | Starts proxy + Claude Code together            |
| `scripts/show_raw.py`        | Raw capture inspector (CLI)                    |
| `commands/show.md`           | The `/fonendo:show` slash command              |
| `commands/raw.md`            | The `/fonendo:raw` slash command               |
| `web/`                       | Svelte inspector UI (served at `/__fonendo/`)  |

## Setup

Python scripts run directly with the system `python3` — stdlib only, nothing
to install. The web UI needs Node:

```bash
cd web
npm install
npm run build        # production build served by the proxy from web/dist/
npm run dev          # Vite dev server, API proxied to 127.0.0.1:8484
```

To run the plugin itself:

```bash
claude --plugin-dir /path/to/logger      # load the plugin
scripts/claude-logged.sh                 # proxy + claude together (raw capture)
```

After editing the plugin, reload it inside a session with `/reload-plugins`.

There is no Justfile or Makefile; the commands above are the complete
interface. Consider adding a Justfile if the command surface grows.

## Key Conventions

- **Python stays stdlib-only.** `proxy.py`, `log_tokens.py`,
  `show_tokens.py`, and `show_raw.py` must not gain third-party
  dependencies. This is a deliberate design constraint: the plugin must run
  anywhere `python3` exists.
- **The proxy must never write to stdout/stderr when started by
  `claude-logged.sh`.** Claude Code's TUI owns the terminal; proxy output is
  redirected to `~/.claude/fonendo/proxy.log`.
- **Auth headers are redacted in capture files.** `x-api-key` and
  `authorization` are forwarded upstream but written as `<redacted>`. Any
  change to capture serialization must preserve this.
- **The `Stop` hook is idempotent.** `log_tokens.py` rebuilds the whole
  session log from the transcript on every Stop event; do not introduce
  incremental state.
- **Slash commands print script output verbatim.** `commands/*.md` wrap the
  Python viewers; keep the "show raw output in a code block" contract.
- **Vite base path is `/__fonendo/`.** The proxy serves `web/dist` under that
  prefix; keep `vite.config.js` `base` and the proxy route in sync.
- `web/dist/` and `web/node_modules/` are gitignored; `dist` is rebuilt by
  `claude-logged.sh` on first run.

## Git Workflow

### Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <description>
```

**Types:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `perf`, `build`.
**Scope** is optional — use the affected component (e.g. `proxy`, `web`, `hooks`).

Keep the description lowercase, imperative, no period.

### Branching

- Branch naming: `feat/`, `fix/`, `chore/`, `test/`, `docs/` prefix +
  kebab-case description (e.g., `feat/har-export`, `fix/sse-buffering`).
- **Never push directly to `main` or `master`.** Create a feature branch and
  open a pull/merge request.

### Rebasing

- Always rebase onto `main` before pushing. No merge commits.
- Use `--force-with-lease` (never `--force`) after rebasing.
- Rebase before the first push, before opening a PR/MR, and whenever the
  base branch advances.

## Package Management

### Python

None. The scripts are stdlib-only by design — do not add a
`requirements.txt`, `pyproject.toml`, or any import outside the standard
library.

### Node (npm, in `web/` only)

- Add: `cd web && npm install <package>`
- Dev: `cd web && npm install --save-dev <package>`
- Lock then install: `npm install` (updates `package-lock.json` automatically)

### Dependency Safety

Before adding or upgrading any dependency, follow these rules:

1. **Never assume you know the latest version.** Your training data is
   outdated. Always verify against the live registry before adding or
   upgrading any package.

2. **Check the live registry:**

   ```bash
   curl -s https://registry.npmjs.org/<package>/latest | jq '{version: .version, engines: .engines}'
   ```

3. **Use the newest stable major version** compatible with the project
   runtime. Check actual compatibility metadata (`engines.node`, Svelte 5 /
   Vite 6 peer ranges).

4. **Avoid releases published within the last 5 days** to reduce supply
   chain attack risk. Check the release date from the registry response.

5. **Always regenerate the lockfile** after changing `package.json`, then
   install from the lock.

## Testing

There is no automated test suite. Verify changes manually:

- **Hook / token accounting**: run a session with the plugin loaded, then
  `python3 scripts/show_tokens.py` and check the table against the
  transcript.
- **Proxy / raw capture**: `scripts/claude-logged.sh`, run a turn, then
  `python3 scripts/show_raw.py` and open
  `http://127.0.0.1:8484/__fonendo/`.
- **Web UI**: `cd web && npm run dev` against a running proxy.

## Command Safety

### Safe (run autonomously)

- `python3 scripts/show_tokens.py [...]` — read-only viewer
- `python3 scripts/show_raw.py [...]` — read-only viewer
- `cd web && npm run build` / `npm run dev`
- `git status`, `git log`, `git diff`

### Dangerous (ask user first)

- `cd web && npm install <package>` — dependency changes
- `scripts/claude-logged.sh` — starts a proxy and a nested Claude Code
  instance; binds a local port
- `python3 scripts/proxy.py --port <n>` — binds a local port
- `git push`

### Destructive (never run)

- Deleting `~/.claude/fonendo/` or its contents — user's captured data
- `rm -rf`, `git push --force`

## Important Rules

- Python scripts stay stdlib-only — never add third-party imports.
- Never log or persist auth header values; keep the `<redacted>` behavior.
- The proxy never writes to the terminal when launched via
  `claude-logged.sh`; log to `~/.claude/fonendo/proxy.log`.
- Keep `log_tokens.py` idempotent — full rebuild per Stop event, no
  incremental state.
- Capture files contain full conversations and system prompts; treat
  `~/.claude/fonendo/` as sensitive and never commit its contents.
- Verify npm package versions on the live registry before adding or
  upgrading; avoid releases newer than 5 days.
- Follow Conventional Commits; branch with `feat/`/`fix/`/... prefixes;
  rebase, never merge-commit.
