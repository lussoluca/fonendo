import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  base: '/__fonendo/',
  plugins: [svelte()],
  server: {
    proxy: {
      '/__fonendo/api': 'http://127.0.0.1:8484',
    },
  },
})
