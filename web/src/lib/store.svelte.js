// Global app state: capture list, live in-flight calls, SSE connection.
const BASE = '/__fonendo'

export const app = $state({
  calls: [], // newest first; live calls carry {live: true, sse: '...'}
  connected: false,
  selectedKey: null,
  drawerKey: null, // call shown in the right off-canvas panel
  // One-shot request for the drawer: open this tab and scroll to a target.
  // Detail consumes and clears it. focus: 'injected' (first <system-reminder>
  // block of the last user message) or 'system' (trailing system message).
  drawerRequest: null, // { tab, focus } | null
})

export function openDrawer(call, request = null) {
  app.drawerKey = key(call)
  app.drawerRequest = request
}

function key(call) {
  return call.live ? `live-${call.id}` : call.file
}

export function callKey(call) {
  return key(call)
}

export function selectedCall() {
  return app.calls.find((c) => key(c) === app.selectedKey) || null
}

export function drawerCall() {
  return app.calls.find((c) => key(c) === app.drawerKey) || null
}

function upsertLive(id, patch) {
  let call = app.calls.find((c) => c.live && c.id === id)
  if (!call) {
    call = { live: true, id, sse: '', request: null }
    app.calls.unshift(call)
  }
  Object.assign(call, patch)
  return call
}

export async function loadCaptures() {
  const response = await fetch(`${BASE}/api/captures`)
  const summaries = await response.json()
  summaries.sort((a, b) => (a.file < b.file ? 1 : -1))
  const live = app.calls.filter((c) => c.live)
  app.calls = [...live, ...summaries]
  if (!app.selectedKey && app.calls.length) app.selectedKey = key(app.calls[0])
}

export async function clearCaptures() {
  const response = await fetch(`${BASE}/api/clear`, { method: 'POST' })
  if (!response.ok) return
  // Keep live in-flight calls; their capture files don't exist yet.
  app.calls = app.calls.filter((c) => c.live)
  app.selectedKey = app.calls.length ? key(app.calls[0]) : null
}

export async function loadCapture(file) {
  const response = await fetch(`${BASE}/api/capture?file=${encodeURIComponent(file)}`)
  if (!response.ok) return null
  return response.json()
}

export function connect() {
  const source = new EventSource(`${BASE}/api/events`)
  source.onopen = () => (app.connected = true)
  source.onerror = () => (app.connected = false)

  source.addEventListener('call_start', (event) => {
    const payload = JSON.parse(event.data)
    const call = upsertLive(payload.id, {
      timestamp: payload.timestamp,
      path: payload.path,
      request: payload.request,
      model: payload.request?.model,
      messages: payload.request?.messages?.length || 0,
      tools: payload.request?.tools?.length || 0,
    })
    if (!app.selectedKey || app.selectedKey.startsWith('live-'))
      app.selectedKey = key(call)
  })

  source.addEventListener('chunk', (event) => {
    const payload = JSON.parse(event.data)
    const call = app.calls.find((c) => c.live && c.id === payload.id)
    if (call) call.sse += payload.data
  })

  source.addEventListener('call_end', (event) => {
    const payload = JSON.parse(event.data)
    const index = app.calls.findIndex((c) => c.live && c.id === payload.id)
    const summary = payload.summary || {}
    if (index >= 0) {
      const liveKey = key(app.calls[index])
      const wasSelected = app.selectedKey === liveKey
      const wasInDrawer = app.drawerKey === liveKey
      app.calls[index] = summary
      if (wasSelected && summary.file) app.selectedKey = summary.file
      if (wasInDrawer && summary.file) app.drawerKey = summary.file
    } else if (summary.file && !app.calls.some((c) => c.file === summary.file)) {
      app.calls.unshift(summary)
    }
  })
}
