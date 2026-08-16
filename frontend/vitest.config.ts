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
  },
});
