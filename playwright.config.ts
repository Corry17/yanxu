import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests/browser",
  timeout: 90000,
  workers: 1,
  webServer: {
    command: ".venv/bin/python -m backend",
    url: "http://127.0.0.1:8775/api/session",
    reuseExistingServer: true,
    timeout: 30000,
    env: { RESEARCH_DATA: ".research/browser-db" },
  },
  outputDir: ".research/browser-results",
  use: {
    baseURL: "http://127.0.0.1:8775",
    channel: "chrome",
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
  },
});
