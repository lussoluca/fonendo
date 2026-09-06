---
description: Inspect raw API captures from the logging proxy (list, or pass "<n> [system|tools|messages|response|raw]")
allowed-tools: Bash(python3:*)
---

Run this command and show the user its raw output verbatim in a code block:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/show_raw.py" $ARGUMENTS
```

If it reports no captures, explain that raw capture requires running Claude
Code through the proxy: `${CLAUDE_PLUGIN_ROOT}/scripts/claude-logged.sh`.

When showing a capture overview, briefly explain what the user is looking
at: the full request payload Claude Code sent to the API (system prompt,
tool JSON schemas, complete message history) and the raw SSE response
stream from the model.
