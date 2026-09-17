import { defineConfig, devices } from "@playwright/test";

/**
 * Frontend e2e smoke tests.
 *
 * Requires a running backend. By default we reuse the shared dev database on
 * port 54102 (see backend/.env) and start both servers via webServer:
 *   - backend: uvicorn on :8000 (DATABASE_URL_TEST must point at the test DB)
 *   - frontend: vite preview on :4173 (production build)
 *
 * Local run:
 *   cd frontend
 *   npm run build
 *   set DATABASE_URL_TEST=postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_test
 *   npx playwright test
 */
export default defineConfig({
  testDir: "./e2e",
  // 组件台那几条（*.harness.spec.ts）跑的是 vite dev 上的 /e2e/harness.html，
  // 由 playwright.harness.config.ts 负责（npm run test:harness）；这里必须排除，
  // 否则 preview 服务器上没有那个页面、必然全挂。
  testIgnore: "**/*.harness.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command:
        "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000",
      cwd: "../backend",
      env: {
        DATABASE_URL:
          process.env.E2E_DATABASE_URL ||
          "postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_e2e",
        DEEPSEEK_API_KEY: process.env.DEEPSEEK_API_KEY || "",
        AUTH_AUTO_VERIFY: "true",
        RATE_LIMIT_ENABLED: "false",
        // get_settings() hard-rejects the default SECRET_KEY; CI has no
        // backend/.env so the spawned uvicorn must receive a valid key.
        SECRET_KEY:
          process.env.E2E_SECRET_KEY ||
          "e2e-test-secret-key-0123456789abcdef0123456789abcdef",
      },
      // 就绪探针必须用 /health：生产配置关掉了 /docs（docs_url=None），
      // 用 /docs 会一直等到超时 —— 这是 e2e 以前必挂的原因之一。
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "npm run preview -- --host 127.0.0.1 --port 4173",
      cwd: "./",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
