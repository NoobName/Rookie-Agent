import { defineConfig } from 'vite';
export default defineConfig({ root: 'apps/web', build: { outDir: '../../dist/web', emptyOutDir: true }, server: { port: 5173, strictPort: true } });
