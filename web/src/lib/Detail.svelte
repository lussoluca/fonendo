<script>
  import { app, loadCapture } from './store.svelte.js'
  import { parseSSE, systemText, fmt, totalIn, shortModel } from './sse.js'
  import TokenBar from './TokenBar.svelte'

  let { call } = $props()

  let tab = $state('overview')
  let record = $state(null)
  const cache = new Map()

  $effect(() => {
    if (call.live) {
      record = null
      return
    }
    const file = call.file
    if (cache.has(file)) {
      record = cache.get(file)
      return
    }
    record = null
    loadCapture(file).then((data) => {
      if (data) cache.set(file, data)
      if (call.file === file) record = data
    })
  })

  const request = $derived(call.live ? call.request : record?.request)
  const responseRaw = $derived(call.live ? call.sse : record?.response_body || '')
  const parsed = $derived(parseSSE(responseRaw))
  const usage = $derived(call.live ? parsed.usage : call.usage || parsed.usage)
  const system = $derived(systemText(request))
  const tools = $derived(request?.tools || [])
  const messages = $derived(request?.messages || [])

  function isInjected(block) {
    return block?.type === 'text' && /^\s*<system-reminder>/.test(block.text || '')
  }

  // Where a one-shot drawer request points: [messageIndex, blockIndex|null].
  function focusTarget(focus) {
    if (focus === 'system') {
      const index = messages.findLastIndex((m) => m.role === 'system')
      return index >= 0 ? [index, null] : null
    }
    if (focus === 'injected') {
      const index = messages.findLastIndex((m) => m.role === 'user')
      if (index < 0) return null
      const content = messages[index].content
      const block = Array.isArray(content) ? content.findIndex(isInjected) : -1
      return [index, block >= 0 ? block : null]
    }
    return null
  }

  let focused = $state(null) // [messageIndex, blockIndex|null] to highlight

  $effect(() => {
    const req = app.drawerRequest
    if (!req || !messages.length) return
    tab = req.tab || tab
    focused = focusTarget(req.focus)
    app.drawerRequest = null
    if (!focused) return
    const [m, b] = focused
    requestAnimationFrame(() => {
      const el = document.getElementById(b === null ? `msg-${m}` : `msg-${m}-block-${b}`)
      el?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    })
  })

  function isFocused(m, b = null) {
    return focused && focused[0] === m && focused[1] === b
  }

  const TABS = ['overview', 'system', 'tools', 'messages', 'response', 'raw']

  function pretty(value) {
    return JSON.stringify(value, null, 2)
  }

  function blockText(block) {
    if (typeof block === 'string') return block
    if (block.type === 'text') return block.text
    if (block.type === 'thinking') return block.thinking
    if (block.type === 'tool_use') return pretty(block.input)
    if (block.type === 'tool_result') {
      const content = block.content
      if (Array.isArray(content))
        return content.map((c) => c?.text || pretty(c)).join('\n')
      return typeof content === 'string' ? content : pretty(content)
    }
    return pretty(block)
  }

  function blockLabel(block) {
    if (typeof block === 'string') return 'text'
    if (block.type === 'tool_use') return `tool_use · ${block.name}`
    if (block.type === 'tool_result') return 'tool_result'
    return block.type
  }

  let rawLimit = $state(200000)
  const rawJson = $derived(
    call.live ? pretty({ request, response_sse: call.sse }) : pretty(record)
  )

  const invokedTools = $derived(parsed.toolUses)
</script>

<div class="head">
  <h2>
    {shortModel(call.model || request?.model)}
    {#if call.live}<span class="live-tag">streaming</span>{/if}
  </h2>
  <span class="sub">
    {call.timestamp || ''}
    {#if !call.live && record}
      · {record.method} {record.path} · {record.response_status} ·
      {record.duration_s}s
    {/if}
  </span>
</div>

<nav>
  {#each TABS as name}
    <button class:active={tab === name} onclick={() => (tab = name)}>
      {name}
    </button>
  {/each}
</nav>

{#if !call.live && !record}
  <p class="muted">loading capture…</p>
{:else if tab === 'overview'}
  <div class="cards">
    <div class="card">
      <span class="card-label">total input</span>
      <strong>{fmt(totalIn(usage))}</strong>
      <TokenBar {usage} height={8} />
      <small>
        fresh {fmt(usage?.input_tokens)} · cache write
        {fmt(usage?.cache_creation_input_tokens)} · cache read
        {fmt(usage?.cache_read_input_tokens)}
      </small>
    </div>
    <div class="card">
      <span class="card-label">output</span>
      <strong>{fmt(usage?.output_tokens)}</strong>
      <small>stop: {parsed.stopReason || call.stop_reason || '…'}</small>
    </div>
    <div class="card">
      <span class="card-label">request payload</span>
      <strong>{messages.length} messages</strong>
      <small>
        {tools.length} tools · system {fmt(system.length)} chars ·
        stream {String(request?.stream ?? false)}
      </small>
    </div>
    <div class="card">
      <span class="card-label">tools used</span>
      <strong>{invokedTools.length || 'none'}</strong>
      {#if invokedTools.length}
        <div class="used-chips">
          {#each invokedTools as toolUse, index (index)}
            <button
              class="used-chip"
              title="show tool input in response tab"
              onclick={() => (tab = 'response')}
            >
              {toolUse.name}
            </button>
          {/each}
        </div>
      {:else}
        <small>{call.live ? 'nothing invoked yet' : 'text-only response'}</small>
      {/if}
    </div>
    {#if parsed.error}
      <div class="card error">
        <span class="card-label">error</span>
        <small>{parsed.error}</small>
      </div>
    {/if}
  </div>
  <p class="muted note">
    Everything above was sent again in full for this single call — the model
    is stateless. The cache columns are how that stays affordable.
  </p>
{:else if tab === 'system'}
  {#if system}
    <details class="block" open>
      <summary>
        <span class="name">system prompt</span>
        <span class="muted">{fmt(system.length)} chars</span>
      </summary>
      <pre class="doc">{system}</pre>
    </details>
  {:else}
    <p class="muted">No system prompt in this request.</p>
  {/if}
{:else if tab === 'tools'}
  {#if tools.length === 0}
    <p class="muted">No tools in this request.</p>
  {/if}
  {#each tools as tool}
    <details class="block">
      <summary>
        <span class="name">{tool.name}</span>
        <span class="muted">
          schema {fmt(JSON.stringify(tool.input_schema || {}).length)} B
        </span>
      </summary>
      {#if tool.description}<pre class="doc">{tool.description}</pre>{/if}
      <pre class="code">{pretty(tool.input_schema)}</pre>
    </details>
  {/each}
{:else if tab === 'messages'}
  {#each messages as message, index}
    <div class="msg {message.role}" class:focused={isFocused(index)} id="msg-{index}">
      <div class="msg-head">
        <span class="role {message.role}">{message.role}</span>
        <span class="muted">#{index + 1}</span>
        {#if message.role === 'system'}
          <span class="tag">appended by Claude Code (hook output)</span>
        {/if}
      </div>
      {#if typeof message.content === 'string'}
        <details class="block" open={message.content.length < 400}>
          <summary>
            <span class="name">text</span>
            <span class="muted">{fmt(message.content.length)} chars</span>
          </summary>
          <pre class="doc">{message.content}</pre>
        </details>
      {:else}
        {#each message.content || [] as block, blockIndex}
          <details
            class="block"
            class:injected={isInjected(block)}
            class:focused={isFocused(index, blockIndex)}
            id="msg-{index}-block-{blockIndex}"
            open={blockText(block).length < 400 || isFocused(index, blockIndex)}
          >
            <summary>
              <span class="name">{blockLabel(block)}</span>
              {#if isInjected(block)}
                <span class="tag">injected by Claude Code</span>
              {/if}
              <span class="muted">{fmt(blockText(block).length)} chars</span>
            </summary>
            <pre class="doc">{blockText(block)}</pre>
          </details>
        {/each}
      {/if}
    </div>
  {/each}
{:else if tab === 'response'}
  {#if parsed.error}
    <pre class="doc error">{parsed.error}</pre>
  {/if}
  {#if parsed.thinking}
    <details class="block" open>
      <summary><span class="name">thinking</span></summary>
      <pre class="doc thinking">{parsed.thinking}</pre>
    </details>
  {:else if parsed.hasThinking}
    <div class="block open-block">
      <div class="name">thinking</div>
      <p class="muted">
        ~{fmt(parsed.thinkingTokens)} tokens (content withheld by the API —
        this model streams only token counts and an encrypted signature)
      </p>
    </div>
  {/if}
  {#if parsed.text}
    <details class="block" open>
      <summary>
        <span class="name">text</span>
        <span class="muted">{fmt(parsed.text.length)} chars</span>
      </summary>
      <pre class="doc">{parsed.text}</pre>
    </details>
  {/if}
  {#each parsed.toolUses as toolUse}
    <details class="block" open>
      <summary><span class="name">tool_use · {toolUse.name}</span></summary>
      <pre class="code">{toolUse.input}</pre>
    </details>
  {/each}
  {#if call.live}
    <p class="muted cursor">▋ receiving…</p>
  {/if}
  {#if Object.keys(usage || {}).length}
    <p class="muted">usage: {pretty(usage)}</p>
  {/if}
{:else if tab === 'raw'}
  <pre class="code">{rawJson.slice(0, rawLimit)}</pre>
  {#if rawJson.length > rawLimit}
    <button class="more" onclick={() => (rawLimit = Infinity)}>
      show all ({fmt(rawJson.length)} chars)
    </button>
  {/if}
{/if}

<style>
  .head {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 12px;
  }
  h2 {
    font-size: 16px;
  }
  .live-tag {
    color: var(--live);
    font-size: 11px;
    margin-left: 8px;
    animation: blink 1.2s ease-in-out infinite;
  }
  @keyframes blink {
    50% {
      opacity: 0.35;
    }
  }
  .sub {
    color: var(--muted);
    font-size: 11px;
  }
  nav {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--line);
    margin-bottom: 14px;
  }
  nav button {
    padding: 6px 12px;
    color: var(--muted);
    border-bottom: 2px solid transparent;
  }
  nav button.active {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  nav button:focus-visible,
  .more:focus-visible {
    outline: 1px solid var(--accent);
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 12px;
    display: grid;
    gap: 6px;
    min-width: 0;
  }
  .card .card-label {
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .card strong {
    font-size: 20px;
  }
  .card small,
  .muted {
    color: var(--muted);
  }
  .card.error small,
  .doc.error {
    color: var(--fresh);
  }
  .note {
    margin-top: 14px;
    max-width: 560px;
  }
  .used-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    min-width: 0;
  }
  .used-chip {
    font-size: 11px;
    padding: 2px 9px;
    border-radius: 9px;
    max-width: 100%;
    text-align: left;
    overflow-wrap: anywhere;
    background: var(--panel-2);
    border: 1px solid var(--output);
    color: var(--output);
  }
  .used-chip:hover {
    background: color-mix(in srgb, var(--output) 12%, var(--panel-2));
  }
  .doc {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 12px;
    font-size: 12px;
  }
  .doc.thinking {
    color: var(--muted);
    font-style: italic;
  }
  .code {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 12px;
    font-size: 12px;
    color: var(--code);
  }
  .block {
    margin-bottom: 10px;
  }
  .block summary {
    cursor: pointer;
    padding: 6px 0;
    list-style: none;
  }
  .block summary::before {
    content: '▸ ';
    color: var(--muted);
  }
  .block[open] summary::before {
    content: '▾ ';
  }
  .name {
    font-weight: 600;
    margin-right: 8px;
  }
  .msg {
    margin-bottom: 16px;
    padding: 8px 12px;
    border: 1px solid var(--line);
    border-left: 3px solid var(--muted);
    border-radius: 6px;
    background: var(--panel);
  }
  .msg.user {
    border-left-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 5%, var(--panel));
  }
  .msg.assistant {
    border-left-color: var(--output);
    background: color-mix(in srgb, var(--output) 5%, var(--panel));
  }
  .msg .doc {
    background: var(--bg);
  }
  .msg-head {
    display: flex;
    gap: 8px;
    margin-bottom: 6px;
  }
  .role {
    font-size: 11px;
    padding: 1px 8px;
    border-radius: 8px;
    background: var(--panel-2);
  }
  .role.user {
    color: var(--accent);
  }
  .role.assistant {
    color: var(--output);
  }
  .role.system {
    color: var(--live);
  }
  .msg.system {
    border-left-color: var(--live);
    border-style: dashed;
    background: color-mix(in srgb, var(--live) 5%, var(--panel));
  }
  .tag {
    font-size: 11px;
    color: var(--live);
    padding: 1px 8px;
    border: 1px dashed var(--live);
    border-radius: 8px;
  }
  .block.injected > summary .name {
    color: var(--live);
  }
  .focused {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: 6px;
  }
  .cursor {
    animation: blink 1s step-start infinite;
  }
  .more {
    color: var(--accent);
    padding: 8px 0;
  }
  .open-block .name {
    padding: 6px 0;
    display: block;
  }
</style>
