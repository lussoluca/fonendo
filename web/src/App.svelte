<script>
  import {
    app,
    connect,
    loadCaptures,
    clearCaptures,
    callKey,
    selectedCall,
    drawerCall,
    loadSessionMeta,
  } from './lib/store.svelte.js'
  import { fmt, totalIn, shortModel } from './lib/sse.js'
  import TokenBar from './lib/TokenBar.svelte'
  import Detail from './lib/Detail.svelte'
  import SessionFlow from './lib/SessionFlow.svelte'
  import Settings from './lib/Settings.svelte'

  $effect(() => {
    loadCaptures()
    connect()
  })

  // --- search ---------------------------------------------------------
  let query = $state('')
  // null = no active search; otherwise Set of capture file names whose full
  // content (request payload + response) contains the query.
  let contentMatches = $state(null)
  let searching = $state(false)
  let searchTimer

  $effect(() => {
    const q = query.trim()
    clearTimeout(searchTimer)
    if (!q) {
      contentMatches = null
      searching = false
      return
    }
    searching = true
    searchTimer = setTimeout(async () => {
      try {
        const response = await fetch(`/__fonendo/api/search?q=${encodeURIComponent(q)}`)
        contentMatches = new Set(await response.json())
      } finally {
        searching = false
      }
    }, 250)
  })

  function matchesQuery(call) {
    if (contentMatches === null) return true
    const q = query.trim().toLowerCase()
    if (call.live) {
      return (
        JSON.stringify(call.request || {}).toLowerCase().includes(q) ||
        (call.sse || '').toLowerCase().includes(q)
      )
    }
    return contentMatches.has(call.file)
  }

  const filtered = $derived(app.calls.filter(matchesQuery))

  // --- session grouping -----------------------------------------------
  function sessionOf(call) {
    if (call.live) {
      // Claude Code sends metadata.user_id as a JSON string with session_id.
      const userId = call.request?.metadata?.user_id || ''
      try {
        const parsed = JSON.parse(userId)
        if (parsed?.session_id) return parsed.session_id
      } catch {
        // fall through to the plain-text form
      }
      const match = userId.match(/session_([0-9a-f-]{8,})/)
      return match ? match[1] : null
    }
    return call.session || null
  }

  const groups = $derived.by(() => {
    const byId = new Map()
    for (const call of filtered) {
      const id = sessionOf(call) || 'no-session'
      if (!byId.has(id))
        byId.set(id, { id, calls: [], in: 0, out: 0, live: false })
      const group = byId.get(id)
      group.calls.push(call)
      group.in += totalIn(call.usage)
      group.out += call.usage?.output_tokens || 0
      group.live = group.live || !!call.live
    }
    // app.calls is newest-first, so each group's first call is its newest;
    // order groups by that.
    return [...byId.values()]
  })

  // Session name/title come from the transcript, which Claude Code keeps
  // writing during a session: refetch when the set of sessions changes and
  // whenever a call finishes.
  $effect(() => {
    const ids = groups.map((g) => g.id)
    void app.calls.filter((c) => !c.live).length
    loadSessionMeta(ids)
  })

  function sessionLabel(id) {
    const meta = app.sessions[id]
    if (!meta) return { main: null, sub: null }
    return {
      main: meta.name || meta.title || null,
      sub: meta.name ? meta.title : null,
    }
  }

  const totals = $derived.by(() => {
    const sum = { in: 0, out: 0, calls: 0 }
    for (const call of app.calls) {
      if (call.live) continue
      sum.in += totalIn(call.usage)
      sum.out += call.usage?.output_tokens || 0
      sum.calls += 1
    }
    return sum
  })

  // --- group collapsing -------------------------------------------------
  // Manual open/close choices per session id; without one, only the newest
  // group (index 0) is open. An active full-text search expands everything.
  let expandOverride = $state({})

  function isOpen(group, index) {
    if (contentMatches !== null) return true
    return expandOverride[group.id] ?? index === 0
  }

  function toggleGroup(group, index) {
    expandOverride[group.id] = !isOpen(group, index)
  }

  function sessionHue(session) {
    let hash = 0
    for (const ch of session || '') hash = (hash * 31 + ch.charCodeAt(0)) | 0
    return ((hash % 360) + 360) % 360
  }

  function timeOf(call) {
    return (call.timestamp || '').slice(11, 19)
  }

  const current = $derived(selectedCall())
  const inDrawer = $derived(drawerCall())
  const selectedGroup = $derived(
    app.selectedKey?.startsWith('session:')
      ? groups.find((g) => `session:${g.id}` === app.selectedKey) || null
      : null
  )
</script>

<div class="layout">
  <header>
    <h1>fonendo<span class="dim">/</span>api stethoscope</h1>
    <div class="spacer"></div>
    <div class="legend">
      <i style:background="var(--fresh)"></i>fresh in
      <i style:background="var(--cache-write)"></i>cache write
      <i style:background="var(--cache-read)"></i>cache read
      <i style:background="var(--output)"></i>output
    </div>
    <div class="totals">
      {totals.calls} calls · in {fmt(totals.in)} · out {fmt(totals.out)}
    </div>
    <Settings />
    <div class="conn" class:on={app.connected} title={app.connected ? 'live event stream connected' : 'event stream disconnected'}>
      {app.connected ? 'live' : 'offline'}
    </div>
  </header>

  <aside>
    <div class="search">
      <input
        type="search"
        placeholder="search captures (full text)…"
        bind:value={query}
        spellcheck="false"
      />
      {#if searching}
        <span class="search-state">…</span>
      {:else if contentMatches !== null}
        <span class="search-state">{filtered.length}</span>
      {/if}
      <button
        class="clear"
        title="delete all recorded captures"
        onclick={async () => {
          if (confirm('Delete all recorded captures? This removes the files on disk.'))
            await clearCaptures()
        }}
      >
        clear
      </button>
    </div>

    {#if app.calls.length === 0}
      <div class="empty">
        No calls captured yet.<br /><br />
        Start Claude Code through the proxy:<br />
        <code>scripts/claude-logged.sh</code>
      </div>
    {:else if filtered.length === 0}
      <div class="empty">No captures match "{query}".</div>
    {/if}

    {#each groups as group, index (group.id)}
      {@const label = sessionLabel(group.id)}
      <button
        class="group-head"
        class:selected={app.selectedKey === `session:${group.id}`}
        title="show session flow"
        onclick={() => (app.selectedKey = `session:${group.id}`)}
      >
        <span
          class="caret"
          class:open={isOpen(group, index)}
          role="button"
          tabindex="-1"
          title={isOpen(group, index) ? 'collapse session' : 'expand session'}
          onclick={(e) => {
            e.stopPropagation()
            toggleGroup(group, index)
          }}
          onkeydown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.stopPropagation()
              toggleGroup(group, index)
            }
          }}
        >
          ▸
        </span>
        {#if group.id !== 'no-session'}
          <span class="session" style:--hue={sessionHue(group.id)} title="session {group.id}">
            {group.id.slice(0, 8)}
          </span>
        {:else}
          <span class="session plain">no session</span>
        {/if}
        {#if label.main}
          <span class="session-name" title={label.main}>{label.main}</span>
        {/if}
        {#if group.live}<span class="pulse">live</span>{/if}
        <span class="group-stats">
          {group.calls.length} calls · in {fmt(group.in)} · out {fmt(group.out)}
        </span>
        {#if label.sub}
          <span class="session-title" title={label.sub}>{label.sub}</span>
        {/if}
      </button>
      {#if isOpen(group, index)}
        {#each group.calls as call (callKey(call))}
        <button
          class="row"
          class:selected={app.selectedKey === callKey(call)}
          class:live={call.live}
          onclick={() => (app.selectedKey = callKey(call))}
        >
          <div class="row-top">
            <span class="time">{timeOf(call)}</span>
            <span class="model">{shortModel(call.model)}</span>
            {#if call.live}
              <span class="pulse right">streaming</span>
            {:else if call.status && call.status >= 400}
              <span class="err">{call.status}</span>
            {/if}
          </div>
          {#if call.live}
            <div class="row-meta">
              {call.messages} msgs · {call.tools} tools
            </div>
          {:else}
            <TokenBar usage={call.usage} />
            <div class="row-meta">
              in {fmt(totalIn(call.usage))} · out {fmt(call.usage?.output_tokens)}
              · {call.messages} msgs
            </div>
          {/if}
        </button>
        {/each}
      {/if}
    {/each}
  </aside>

  <main>
    {#if selectedGroup}
      <SessionFlow group={selectedGroup} meta={app.sessions[selectedGroup.id]} />
    {:else if current}
      <Detail call={current} />
    {:else}
      <div class="empty">Select a call, or a session header for its flow.</div>
    {/if}
  </main>

  {#if inDrawer}
    <div
      class="drawer-backdrop"
      role="presentation"
      onclick={() => (app.drawerKey = null)}
    ></div>
    <section class="drawer" aria-label="call detail panel">
      <div class="drawer-bar">
        <span class="drawer-title">
          {shortModel(inDrawer.model)} · {timeOf(inDrawer)}
          {#if inDrawer.live}<span class="pulse">streaming</span>{/if}
        </span>
        <button
          class="drawer-close"
          title="close panel (Esc)"
          onclick={() => (app.drawerKey = null)}
        >
          ✕
        </button>
      </div>
      <div class="drawer-body">
        <Detail call={inDrawer} />
      </div>
    </section>
  {/if}
</div>

<svelte:window
  onkeydown={(e) => {
    if (e.key === 'Escape' && app.drawerKey) app.drawerKey = null
  }}
/>

<style>
  .layout {
    display: grid;
    grid-template: 'header header' auto 'aside main' 1fr / 340px 1fr;
    height: 100%;
  }
  header {
    grid-area: header;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 10px 16px;
    border-bottom: 1px solid var(--line);
    background: var(--panel);
  }
  h1 {
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.04em;
  }
  .dim {
    color: var(--muted);
    padding: 0 2px;
  }
  .spacer {
    flex: 1;
  }
  .legend {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--muted);
    font-size: 11px;
  }
  .legend i {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    display: inline-block;
    margin-left: 8px;
  }
  .totals {
    color: var(--muted);
    font-size: 12px;
  }
  .conn {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 10px;
    border: 1px solid var(--line);
    color: var(--muted);
  }
  .conn.on {
    color: var(--live);
    border-color: var(--live);
  }
  aside {
    grid-area: aside;
    overflow-y: auto;
    border-right: 1px solid var(--line);
    background: var(--panel);
  }
  .search {
    position: sticky;
    top: 0;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: var(--panel);
    border-bottom: 1px solid var(--line);
  }
  .search input {
    flex: 1;
    font: inherit;
    font-size: 12px;
    color: var(--text);
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 5px 8px;
    outline: none;
  }
  .search input:focus-visible {
    border-color: var(--accent);
  }
  .search input::placeholder {
    color: var(--muted);
  }
  .search-state {
    color: var(--muted);
    font-size: 11px;
    min-width: 18px;
    text-align: right;
  }
  .clear {
    font-size: 11px;
    padding: 4px 9px;
    border-radius: 4px;
    border: 1px solid var(--line);
    color: var(--muted);
  }
  .clear:hover {
    color: var(--fresh);
    border-color: var(--fresh);
  }
  .group-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px 8px;
    width: 100%;
    text-align: left;
    padding: 8px 12px 4px;
    background: var(--bg);
    border-bottom: 1px solid var(--line);
  }
  .session-name {
    font-size: 12px;
    font-weight: 600;
    min-width: 14ch;
    flex: 1 1 auto;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .session-title {
    flex: 0 0 100%;
    padding-left: 20px;
    color: var(--muted);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .group-head:hover {
    background: var(--panel-2);
  }
  .group-head.selected {
    box-shadow: inset 2px 0 0 var(--accent);
  }
  .caret {
    color: var(--muted);
    font-size: 10px;
    width: 12px;
    flex: none;
    text-align: center;
    transition: transform 0.12s ease;
  }
  .caret.open {
    transform: rotate(90deg);
  }
  .caret:hover {
    color: var(--text);
  }
  .group-stats {
    color: var(--muted);
    font-size: 11px;
    margin-left: auto;
    white-space: nowrap;
  }
  .row {
    display: block;
    width: 100%;
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid var(--line);
  }
  .row:hover {
    background: var(--panel-2);
  }
  .row.selected {
    background: var(--panel-2);
    box-shadow: inset 2px 0 0 var(--accent);
  }
  .row.live {
    box-shadow: inset 2px 0 0 var(--live);
  }
  .row-top {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .time {
    color: var(--muted);
    font-size: 11px;
  }
  .model {
    font-weight: 600;
  }
  .session {
    font-size: 10px;
    padding: 0 6px;
    border-radius: 8px;
    background: hsl(var(--hue) 40% var(--chip-bg-l));
    color: hsl(var(--hue) 70% var(--chip-fg-l));
  }
  .session.plain {
    background: var(--panel-2);
    color: var(--muted);
  }
  .pulse {
    color: var(--live);
    font-size: 11px;
    animation: blink 1.2s ease-in-out infinite;
  }
  .pulse.right {
    margin-left: auto;
  }
  .err {
    color: var(--fresh);
    font-size: 11px;
    margin-left: auto;
  }
  @keyframes blink {
    50% {
      opacity: 0.35;
    }
  }
  .row-meta {
    color: var(--muted);
    font-size: 11px;
    margin-top: 4px;
  }
  main {
    grid-area: main;
    overflow-y: auto;
    padding: 16px 20px;
  }
  .drawer-backdrop {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 45%);
    z-index: 10;
  }
  .drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(760px, 92vw);
    background: var(--bg);
    border-left: 1px solid var(--line);
    box-shadow: -12px 0 32px rgb(0 0 0 / 45%);
    z-index: 11;
    display: grid;
    grid-template-rows: auto 1fr;
    animation: slide-in 0.18s ease-out;
  }
  @keyframes slide-in {
    from {
      transform: translateX(24px);
      opacity: 0;
    }
  }
  .drawer-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 16px;
    background: var(--panel);
    border-bottom: 1px solid var(--line);
  }
  .drawer-title {
    font-weight: 600;
    display: flex;
    gap: 10px;
    align-items: baseline;
  }
  .drawer-close {
    margin-left: auto;
    color: var(--muted);
    font-size: 14px;
    padding: 2px 8px;
    border-radius: 4px;
  }
  .drawer-close:hover {
    color: var(--text);
    background: var(--panel-2);
  }
  .drawer-close:focus-visible {
    outline: 1px solid var(--accent);
  }
  .drawer-body {
    overflow-y: auto;
    padding: 14px 18px;
  }
  .empty {
    color: var(--muted);
    padding: 24px 16px;
    line-height: 1.8;
  }
  code {
    color: var(--accent);
  }
</style>
