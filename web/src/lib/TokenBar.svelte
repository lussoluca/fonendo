<script>
  import { totalIn } from './sse.js'

  let { usage, height = 6 } = $props()

  const parts = $derived.by(() => {
    if (!usage) return []
    const total = totalIn(usage) + (usage.output_tokens || 0)
    if (!total) return []
    return [
      ['var(--fresh)', usage.input_tokens || 0],
      ['var(--cache-write)', usage.cache_creation_input_tokens || 0],
      ['var(--cache-read)', usage.cache_read_input_tokens || 0],
      ['var(--output)', usage.output_tokens || 0],
    ]
      .filter(([, value]) => value > 0)
      .map(([color, value]) => [color, (100 * value) / total])
  })
</script>

<div class="bar" style:height="{height}px">
  {#each parts as [color, pct]}
    <span style:background={color} style:width="{pct}%"></span>
  {/each}
</div>

<style>
  .bar {
    display: flex;
    width: 100%;
    background: var(--panel-2);
    border-radius: 2px;
    overflow: hidden;
  }
  .bar span {
    display: block;
    min-width: 2px;
  }
</style>
