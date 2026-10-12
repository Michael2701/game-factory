import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests',
  retries: 0,
  timeout: 15000,
  use: { baseURL: 'http://127.0.0.1:41731', browserName: 'chromium', headless: true },
  webServer: {
    command: 'npx vite preview --port 41731 --strictPort --host 127.0.0.1',
    url: 'http://127.0.0.1:41731',
    timeout: 60000,
  },
});
