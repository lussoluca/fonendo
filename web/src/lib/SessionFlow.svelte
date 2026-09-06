<script>
  import { app, callKey } from './store.svelte.js'
  import {
    parseSSE,
    fmt,
    totalIn,
    shortModel,
    firstMessageSeed,
    laneKind,
    seedHue,
  } from './sse.js'
  import TokenBar from './TokenBar.svelte'

  let { group } = $props()

  const chronological = $derived([...group.calls].reverse())

  function liveTrigger(call) {
    const messages = call.request?.messages || []
    if (!messages.length) return { type: 'none' }
    const content = messages[messages.length - 1].content
    if (typeof content === 'string') return { type: 'user', preview: content.slice(0, 200) }
    const blocks = Array.isArray(content) ? content : []
    const results = blocks.filter((b) => b?.type === 'tool_result')
    if (results.length) return { type: 'tool_result', count: results.length }
    const texts = blocks
      .filter((b) => b?.type === 'text')
      .map((b) => b.text || '')
      .join(' ')
    return { type: 'user', preview: texts.slice(0, 200) }
  }

  function info(call) {
    if (!call.live) {
      return {
        trigger: call.trigger || { type: 'none' },
        response: call.response || { thinking: false, text_preview: '', tool_calls: [] },
        usage: call.usage,
        seed: call.thread_seed ?? '',
      }
    }
    const parsed = parseSSE(call.sse)
    return {
      trigger: liveTrigger(call),
      response: {
        thinking: !!parsed.thinking || parsed.hasThinking,
        text_preview: parsed.text.slice(0, 200),
        tool_calls: parsed.toolUses.map((t) => t.name),
      },
      usage: parsed.usage,
      seed: firstMessageSeed(call.request),
    }
  }

  const rows = $derived(chronological.map((call) => ({ call, ...info(call) })))

  // Split the chronological rows into segments: the main agent loop renders
  // full-width; every other thread (subagents, title, suggestions, quota)
  // becomes a colored side lane. Contiguous same-thread rows share a lane box.
  const LANE_LABELS = {
    agent: 'subagent',
    title: 'session title',
    suggestions: 'input suggestions',
    quota: 'quota probe',
  }

  const segments = $derived.by(() => {
    let mainSeed = null
    const out = []
    for (const row of rows) {
      const kind = laneKind(row.seed)
      if (mainSeed === null && kind === 'agent') mainSeed = row.seed
      const lane = row.seed === mainSeed ? 'main' : kind
      const last = out[out.length - 1]
      if (last && last.seed === row.seed && last.lane === lane) {
        last.rows.push(row)
      } else {
        out.push({ seed: row.seed, lane, hue: seedHue(row.seed), rows: [row] })
      }
    }
    return out
  })

  function timeOf(call) {
    return (call.timestamp || '').slice(11, 19)
  }
</script>

{#snippet callNode(row, inLane)}
  {@const { call, trigger, response, usage } = row}
  {#if trigger.type === 'user'}
    <div class="node user-node">
      <div class="dot user-dot"></div>
      <div class="user-card">
        <span class="who">{inLane ? 'task' : 'user'}</span>
        <span class="preview">{trigger.preview || '(empty message)'}</span>
      </div>
    </div>
  {:else if trigger.type === 'tool_result'}
    <div class="loopback">
      ⮑ {trigger.count} tool result{trigger.count === 1 ? '' : 's'} fed back
      into the next call
    </div>
  {/if}

  <div class="node">
    <div class="dot" class:live-dot={call.live}></div>
    <button
      class="call-card"
      class:selected={app.drawerKey === callKey(call)}
      class:live={call.live}
      onclick={() => (app.drawerKey = callKey(call))}
    >
      <div class="card-top">
        <span class="time">{timeOf(call)}</span>
        <span class="model">{shortModel(call.model)}</span>
        {#if call.live}
          <span class="pulse">streaming</span>
        {:else if call.status && call.status >= 400}
          <span class="err">{call.status}</span>
        {/if}
        <span class="tokens">
          in {fmt(totalIn(usage))} · out {fmt(usage?.output_tokens)}
        </span>
      </div>
      <TokenBar {usage} height={4} />
      <div class="card-body">
        {#if response.thinking}
          <span class="thinking">∿ thinking</span>
        {/if}
        {#if response.text_preview}
          <span class="text-preview">{response.text_preview}</span>
        {/if}
        {#if response.tool_calls.length}
          <div class="tool-row">
            →
            {#each response.tool_calls as tool}
              <span class="tool-chip">{tool}</span>
            {/each}
          </div>
        {/if}
        {#if !response.thinking && !response.text_preview && !response.tool_calls.length}
          <span class="muted">no content{call.live ? ' yet' : ''}</span>
        {/if}
      </div>
    </button>
  </div>
{/snippet}

<div class="flow-head">
  <h2>session flow</h2>
  <span class="sub">
    {group.id === 'no-session' ? 'calls without session metadata' : group.id}
    · {group.calls.length} calls · in {fmt(group.in)} · out {fmt(group.out)}
  </span>
</div>

<p class="muted intro">
  One agentic turn = one user message followed by a chain of model calls.
  Every call resends the whole history; each tool result loops straight back
  into the next call. Subagents and utility calls run as separate
  conversations — shown here as colored side lanes. Click a call to inspect
  its full payload in a side panel.
</p>

<div class="timeline">
  {#each segments as segment, index (index)}
    {#if segment.lane === 'main'}
      {#each segment.rows as row (callKey(row.call))}
        {@render callNode(row, false)}
      {/each}
    {:else}
      <div class="lane" style:--lane-hue={segment.hue}>
        <div class="lane-head">
          <span class="lane-label">{LANE_LABELS[segment.lane] || segment.lane}</span>
          {#if segment.rows.some((r) => r.call.live)}
            <span class="pulse">running</span>
          {/if}
          {#if segment.lane === 'agent'}
            <span class="lane-seed">{segment.seed.slice(0, 90)}</span>
          {/if}
        </div>
        {#each segment.rows as row (callKey(row.call))}
          {@render callNode(row, true)}
        {/each}
      </div>
    {/if}
  {/each}
</div>

<style>
  .flow-head {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 6px;
  }
  h2 {
    font-size: 16px;
  }
  .sub,
  .muted {
    color: var(--muted);
    font-size: 11px;
  }
  .intro {
    max-width: 560px;
    margin-bottom: 18px;
  }
  .timeline {
    position: relative;
    margin-left: 8px;
    padding-left: 20px;
    border-left: 1px solid var(--line);
    display: grid;
    gap: 10px;
    max-width: 760px;
  }
  .lane {
    margin-left: 26px;
    padding: 8px 10px 10px;
    border: 1px solid hsl(var(--lane-hue) 35% 50% / 45%);
    border-left: 3px solid hsl(var(--lane-hue) 55% 55%);
    border-radius: 6px;
    background: hsl(var(--lane-hue) 30% 50% / 7%);
    display: grid;
    gap: 8px;
  }
  .lane .node .dot {
    display: none;
  }
  .lane-head {
    display: flex;
    align-items: baseline;
    gap: 10px;
    min-width: 0;
  }
  .lane-label {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: hsl(var(--lane-hue) 60% var(--chip-fg-l));
  }
  .lane-seed {
    color: var(--muted);
    font-size: 10px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .node {
    position: relative;
  }
  .dot {
    position: absolute;
    left: -25px;
    top: 12px;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--panel-2);
    border: 2px solid var(--muted);
  }
  .user-dot {
    background: var(--accent);
    border-color: var(--accent);
  }
  .live-dot {
    background: var(--live);
    border-color: var(--live);
    animation: blink 1.2s ease-in-out infinite;
  }
  .user-node {
    margin-top: 8px;
  }
  .lane .user-node {
    margin-top: 0;
  }
  .user-card {
    display: flex;
    gap: 10px;
    align-items: baseline;
    padding: 8px 12px;
    border: 1px solid var(--accent);
    border-radius: 6px;
    background: color-mix(in srgb, var(--accent) 8%, var(--panel));
  }
  .who {
    color: var(--accent);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .preview {
    font-size: 12px;
  }
  .loopback {
    color: var(--muted);
    font-size: 11px;
    padding: 0 0 0 4px;
  }
  .call-card {
    display: grid;
    gap: 6px;
    width: 100%;
    text-align: left;
    padding: 10px 12px;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 6px;
  }
  .call-card:hover {
    border-color: var(--muted);
  }
  .call-card.selected {
    border-color: var(--accent);
  }
  .call-card.live {
    border-color: var(--live);
  }
  .card-top {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }
  .time {
    color: var(--muted);
    font-size: 11px;
  }
  .model {
    font-weight: 600;
  }
  .tokens {
    margin-left: auto;
    color: var(--muted);
    font-size: 11px;
  }
  .err {
    color: var(--fresh);
    font-size: 11px;
  }
  .pulse {
    color: var(--live);
    font-size: 11px;
    animation: blink 1.2s ease-in-out infinite;
  }
  @keyframes blink {
    50% {
      opacity: 0.35;
    }
  }
  .card-body {
    display: grid;
    gap: 4px;
    font-size: 12px;
  }
  .thinking {
    color: var(--muted);
    font-style: italic;
  }
  .text-preview {
    color: var(--text);
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }
  .tool-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    color: var(--muted);
  }
  .tool-chip {
    font-size: 11px;
    padding: 1px 8px;
    border-radius: 8px;
    background: var(--panel-2);
    color: var(--output);
    border: 1px solid var(--line);
  }
</style>
