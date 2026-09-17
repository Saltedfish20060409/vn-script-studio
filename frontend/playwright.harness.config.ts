import { defineConfig } from "@playwright/test";

/**
 * 桌面视图组件台的 Playwright 配置（**不需要后端**）。
 *
 * 用 vite dev server 起 e2e/harness.html（只挂 DesktopView + 假数据），
 * 所以能在真实浏览器里验证：双击剧本开窗口、拖动换座位、开始菜单项。
 * 生产构建只以 index.html 为入口，这个页面不会进 dist。
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.harness.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5199",
    viewport: { width: 1280, height: 800 },
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5199 --strictPort",
    cwd: "./",
    url: "http://127.0.0.1:5199/e2e/harness.html",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
