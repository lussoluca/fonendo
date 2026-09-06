---
description: Show per-call token usage for this session (or pass a session id / --all)
allowed-tools: Bash(python3:*)
---

Run this command and show the user its raw output verbatim in a code block,
then add a short explanation of what the numbers reveal about how the LLM
works (stateless model, growing prompt, prompt caching):

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/show_tokens.py" $ARGUMENTS
```
