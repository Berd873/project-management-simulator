import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests', timeout: 90000, workers: 1,
  expect: { timeout: 45000 },
  use: { baseURL: 'http://127.0.0.1:8765', headless: true, channel: process.platform === 'win32' ? 'msedge' : undefined, viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: { command: '"../.venv/Scripts/python.exe" "tests/e2e_server.py"', url: 'http://127.0.0.1:8765/api/v1/health', reuseExistingServer: false, timeout: 45000 },
})
