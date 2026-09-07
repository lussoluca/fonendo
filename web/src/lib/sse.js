// Parse a raw Anthropic SSE response body into an assembled message.
export function parseSSE(raw) {
  const out = {
    model: null,
    thinking: '',
    hasThinking: false,
    thinkingTokens: 0,
    text: '',
    toolUses: [],
    usage: {},
    stopReason: null,
    error: null,
  }
  if (!raw) return out
  if (!raw.includes('data:')) {
    // Non-streaming JSON response (or an error payload).
    try {
      const message = JSON.parse(raw)
      if (message.type === 'error') {
        out.error = message.error?.message || raw
        return out
      }
      out.model = message.model
      out.usage = message.usage || {}
      out.stopReason = message.stop_reason
      for (const block of message.content || []) {
        if (block.type === 'text') out.text += block.text
        else if (block.type === 'thinking') {
          out.hasThinking = true
          out.thinking += block.thinking || ''
        }
        else if (block.type === 'tool_use')
          out.toolUses.push({ name: block.name, input: JSON.stringify(block.input, null, 2) })
      }
    } catch {
      out.error = raw.slice(0, 2000)
    }
    return out
  }
  for (const line of raw.split('\n')) {
    if (!line.startsWith('data:')) continue
    let event
    try {
      event = JSON.parse(line.slice(5).trim())
    } catch {
      continue
    }
    switch (event.type) {
      case 'message_start':
        out.model = event.message?.model
        Object.assign(out.usage, event.message?.usage || {})
        break
      case 'content_block_start':
        if (event.content_block?.type === 'tool_use')
          out.toolUses.push({ name: event.content_block.name, input: '' })
        else if (event.content_block?.type === 'thinking') out.hasThinking = true
        break
      case 'content_block_delta': {
        const delta = event.delta || {}
        if (delta.type === 'text_delta') out.text += delta.text || ''
        else if (delta.type === 'thinking_delta') {
          out.thinking += delta.thinking || ''
          // Some models withhold thinking text and stream only per-delta
          // token estimates instead.
          if (typeof delta.estimated_tokens === 'number')
            out.thinkingTokens += delta.estimated_tokens
        }
        else if (delta.type === 'input_json_delta' && out.toolUses.length)
          out.toolUses[out.toolUses.length - 1].input += delta.partial_json || ''
        break
      }
      case 'message_delta':
        Object.assign(out.usage, event.usage || {})
        out.stopReason = event.delta?.stop_reason || out.stopReason
        break
      case 'error':
        out.error = event.error?.message || 'stream error'
        break
    }
  }
  return out
}

export function systemText(request) {
  const system = request?.system
  if (typeof system === 'string') return system
  if (Array.isArray(system)) return system.map((b) => b?.text || '').join('\n\n')
  return ''
}

export function totalIn(usage) {
  if (!usage) return 0
  return (
    (usage.input_tokens || 0) +
    (usage.cache_creation_input_tokens || 0) +
    (usage.cache_read_input_tokens || 0)
  )
}

export function fmt(n) {
  return (n || 0).toLocaleString('en-US')
}

export function shortModel(model) {
  return (model || '?').replace(/^claude-/, '').replace(/-\d{8}$/, '')
}

// First user message's text prefix — identifies a conversation thread.
// Injected <system-reminder> blocks are stripped first: parallel subagents
// share the same reminder prefix and would otherwise collide.
// Must stay in sync with first_message_seed() in scripts/proxy.py.
const SYSTEM_REMINDER_RE = /<system-reminder>[\s\S]*?<\/system-reminder>/g

// What prompted a call: a typed prompt, tool results, and any injected
// context. Claude Code appends hook output as a trailing `role: system`
// message and wraps other injected context in <system-reminder> text blocks
// inside the user message; neither is typed by a human. A trailing system
// message is attached as `system` to the message before it, so the typed
// prompt stays visible. Mirrors outline_trigger() in scripts/proxy.py — keep
// the two in sync.
export function outlineTrigger(request) {
  const messages = request?.messages || []
  if (!messages.length) return { type: 'none' }
  const last = messages[messages.length - 1]
  if (laneKind('', { request }) === 'classifier') {
    const action = classifierAction(last)
    if (action) return { type: 'user', label: 'graded action', preview: action.slice(0, 200), injected: 0 }
  }
  if (last.role !== 'system') return describeTriggerMessage(last)
  const joined = messageTexts(last).join(' ').trim()
  const system = { source: injectedSource(joined), preview: joined.slice(0, 200) }
  if (messages.length < 2) return { type: 'system', system }
  return { ...describeTriggerMessage(messages[messages.length - 2]), system }
}

// The action a permission-classifier call grades: the last transcript entry
// before </transcript> (a {"Bash": ...}-style JSON line).
function classifierAction(message) {
  let last = ''
  for (const raw of messageTexts(message)) {
    const text = raw.trim()
    if (!text) continue
    if (text.startsWith('</transcript>')) break
    if (text.startsWith('{')) last = text
  }
  return last
}

function messageTexts(message) {
  const content = message.content
  if (typeof content === 'string') return [content]
  return (Array.isArray(content) ? content : [])
    .filter((b) => b?.type === 'text')
    .map((b) => b.text || '')
}

function describeTriggerMessage(message) {
  const content = message.content
  const blocks = Array.isArray(content) ? content.filter((b) => b && typeof b === 'object') : []
  const results = blocks.filter((b) => b.type === 'tool_result')
  if (results.length) return { type: 'tool_result', count: results.length }
  const human = []
  let injected = 0
  for (const text of messageTexts(message)) {
    const stripped = text.replace(SYSTEM_REMINDER_RE, '').trim()
    if (stripped !== text.trim()) injected++
    if (stripped) human.push(stripped)
  }
  return { type: 'user', preview: human.join(' ').slice(0, 200), injected }
}

// Short label for a system message, e.g. "SessionStart:startup hook success".
function injectedSource(text) {
  const firstLine = text.split('\n', 1)[0].trim()
  const match = firstLine.match(/^([\w:-]+(?: hook \w+)?)/)
  return (match ? match[1] : firstLine).slice(0, 60)
}

export function firstMessageSeed(request) {
  const messages = request?.messages || []
  if (!messages.length) return ''
  const content = messages[0].content
  const text =
    typeof content === 'string'
      ? content
      : (Array.isArray(content) ? content : [])
          .filter((b) => b?.type === 'text')
          .map((b) => b.text || '')
          .join(' ')
  const stripped = text.replace(SYSTEM_REMINDER_RE, '').trim()
  return (stripped || text.trim()).slice(0, 200)
}

// Classify a thread by its seed: main-loop vs known utility sidechains vs
// spawned subagents.
const CLASSIFIER_PROMPT_RE = /You are a security monitor for autonomous AI coding agents/

// Which conversation family a call belongs to. `lane` (from the proxy
// summary) or the request's system prompt catches auto mode's permission
// classifier; the seed splits the rest. Mirrors lane_kind() in
// scripts/proxy.py — keep the two in sync.
export function laneKind(seed, { lane, request } = {}) {
  if (lane === 'classifier') return 'classifier'
  if (request && CLASSIFIER_PROMPT_RE.test(systemText(request).slice(0, 600))) return 'classifier'
  if (seed.startsWith('<session>')) return 'title'
  if (seed.startsWith('[SUGGESTION MODE')) return 'suggestions'
  if (seed === 'quota') return 'quota'
  return 'agent'
}

export function seedHue(seed) {
  let hash = 0
  for (const ch of seed) hash = (hash * 31 + ch.charCodeAt(0)) | 0
  return ((hash % 360) + 360) % 360
}
