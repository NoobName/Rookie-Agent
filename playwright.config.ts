import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: 'tests/e2e',
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: `http://127.0.0.1:${process.env.AGENT_PORT || 8765}`,
    headless: true,
    viewport: { width: 1440, height: 950 },
  },
  reporter: 'list',
});
