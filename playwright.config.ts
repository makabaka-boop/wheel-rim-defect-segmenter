import { defineConfig } from '@playwright/test';

// Compose 网络内通过 E2E_BASE_URL 指向 web 服务（如 http://web:5173）；
// 本地开发时自动拉起 uvicorn 与 vite dev server。
const externalBaseURL = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: externalBaseURL ?? 'http://localhost:5173',
  },
  webServer: externalBaseURL
    ? undefined
    : [
        {
          command:
            'python3 -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000',
          url: 'http://127.0.0.1:8000/health',
          reuseExistingServer: !process.env.CI,
          timeout: 60_000,
        },
        {
          command: 'npm run dev',
          url: 'http://localhost:5173',
          reuseExistingServer: !process.env.CI,
          timeout: 60_000,
        },
      ],
});
