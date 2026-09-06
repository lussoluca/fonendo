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
  const stripped = text.replace(/<system-reminder>[\s\S]*?<\/system-reminder>/g, '').trim()
  return (stripped || text.trim()).slice(0, 200)
}

// Classify a thread by its seed: main-loop vs known utility sidechains vs
// spawned subagents.
export function laneKind(seed) {
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
