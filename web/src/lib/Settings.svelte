<script>
  // Theme + UI scale, persisted in localStorage.
  const THEME_KEY = 'fonendo-theme'
  const ZOOM_KEY = 'fonendo-zoom'
  const ZOOM_MIN = 0.8
  const ZOOM_MAX = 1.4
  const ZOOM_STEP = 0.1

  let theme = $state(localStorage.getItem(THEME_KEY) || 'dark')
  let zoom = $state(
    Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, parseFloat(localStorage.getItem(ZOOM_KEY)) || 1))
  )

  $effect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem(THEME_KEY, theme)
  })

  $effect(() => {
    document.documentElement.style.setProperty('--ui-zoom', String(zoom))
    localStorage.setItem(ZOOM_KEY, String(zoom))
  })

  function bump(direction) {
    zoom = Math.min(
      ZOOM_MAX,
      Math.max(ZOOM_MIN, +(zoom + direction * ZOOM_STEP).toFixed(2))
    )
  }
</script>

<div class="settings">
  <button
    class="font-btn"
    title="smaller text"
    disabled={zoom <= ZOOM_MIN}
    onclick={() => bump(-1)}
  >
    A−
  </button>
  <button
    class="zoom-label"
    title="reset text size"
    onclick={() => (zoom = 1)}
  >
    {Math.round(zoom * 100)}%
  </button>
  <button
    class="font-btn"
    title="larger text"
    disabled={zoom >= ZOOM_MAX}
    onclick={() => bump(1)}
  >
    A+
  </button>
  <button
    class="theme-btn"
    title={theme === 'dark' ? 'switch to light theme' : 'switch to dark theme'}
    onclick={() => (theme = theme === 'dark' ? 'light' : 'dark')}
  >
    {theme === 'dark' ? '☀' : '☾'}
  </button>
</div>

<style>
  .settings {
    display: flex;
    align-items: center;
    gap: 2px;
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 1px 4px;
  }
  .settings button {
    color: var(--muted);
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 6px;
  }
  .settings button:hover:not(:disabled) {
    color: var(--text);
    background: var(--panel-2);
  }
  .settings button:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .settings button:focus-visible {
    outline: 1px solid var(--accent);
  }
  .zoom-label {
    min-width: 38px;
    text-align: center;
  }
  .theme-btn {
    font-size: 13px;
  }
</style>
