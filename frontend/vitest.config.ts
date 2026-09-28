import { defineConfig } from "vitest/config";

/**
 * 前端单元测试配置：仅测试 lib/ 下的纯函数模块。
 *
 * 环境说明：
 * - environment: "node" —— 纯函数测试不依赖 DOM；localStorage 类全局在测试内自行 mock。
 * - pool: "threads" —— 使用 worker 线程而非子进程，避免受限环境下
 *   child_process.fork 触发 EPERM。
 * - resolve.preserveSymlinks —— 跳过 vite 在 Windows 上执行 `net use`
 *   子进程探测真实路径（同样规避受限环境的 spawn EPERM），
 *   对本项目（无符号链接）行为无影响。
 */
export default defineConfig({
  resolve: {
    preserveSymlinks: true,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    pool: "threads",
    // 覆盖率：只有 `npm run test:coverage` 才会用到，`npm test` 行为不变。
    // **刻意不设阈值**：这个仓库此前完全没有覆盖率基线，凭空定一个百分比只会逼人凑数字。
    // 先把数字变成可得的，再谈要不要设闸——尤其组件层目前是 0 覆盖，
    // 一个看上去体面的全局数字反而会掩盖"UI 一行都没测"这件事。
    coverage: {
      provider: "v8",
      include: ["src/**"],
      reporter: ["text", "html"],
    },
  },
});
