import { defineConfig } from 'vite';
export default defineConfig({
  root: 'apps/web',
  build: { outDir: '../../dist/web', emptyOutDir: true },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': `http://127.0.0.1:${process.env.AGENT_PORT || 8765}` },
  },
});
