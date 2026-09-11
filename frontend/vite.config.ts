import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// 每次构建自动生成 cacheId（yyyyMMddHHmm）：bump 不再手动，
// 浏览器 SW 每次部署后都会拿到新缓存前缀并清理旧资源。
const CACHE_ID = `vnss-${new Date()
  .toISOString()
  .replace(/[-:TZ]/g, "")
  .slice(0, 12)}`;

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["pwa-192.png", "pwa-512.png"],
      manifest: {
        name: "VN Script Studio",
        short_name: "VN Studio",
        description: "AI 辅助视觉小说 / 轻小说写作工作室",
        theme_color: "#002fa7",
        background_color: "#0d1220",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "/pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "/pwa-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
      workbox: {
        // 自动生成：每次构建都是新前缀，旧 hashed chunks 自动清理
        cacheId: CACHE_ID,
        cleanupOutdatedCaches: true,
        skipWaiting: true,
        clientsClaim: true,
        // Cache the app shell + hashed assets; API calls are network-only
        // (collab events / saves must never be served stale).
        navigateFallback: "/index.html",
        globPatterns: ["**/*.{js,css,html,svg,png,ico}"],
        // 大体量美术资源（9.1MB/33 张 PNG）不进 precache，首访只下载 PWA 必需项；
        // 这些图片在页面用到时由下方同源 CacheFirst 规则按需缓存。
        // 注意 pwa-192.png / pwa-512.png（manifest icons）在 public 根目录，不受影响。
        globIgnores: [
          "mascot/**",
          "writers/**",
          "ui/**",
          "agent/**",
          "workshop/**",
          "email/**",
          // 使用指南截图（约 14MB/44 张）不进 precache：首访不拖慢，页面用到时
          // 走下方同源图片 CacheFirst 规则按需缓存。
          "guide/**",
        ],
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/.*\.(png|jpg|jpeg|webp|gif)$/,
            handler: "CacheFirst",
            options: {
              cacheName: "images",
              expiration: { maxEntries: 60, maxAgeSeconds: 30 * 24 * 3600 },
            },
          },
          {
            // 同源图片兜底：相对路径（如 /mascot/angel.png）会按页面 origin 解析成
            // 绝对 URL，若部署在 http（dev/preview/LAN）上，上面 ^https:// 正则匹配
            // 不到；这里按 sameOrigin 匹配，兜住被 globIgnores 排除后按需加载的同源图片。
            //
            // 注意：这里刻意只做字符串匹配，不访问 url.pathname ——
            // vite.config.ts 用的是 tsconfig.node.json（lib 只有 ES2023，没有 DOM），
            // URL 的类型视各环境解析结果而定，取属性在 CI 的 Linux 上会报
            // TS2339（本机 Windows 不报），改成 String(url) 后两边都成立。
            urlPattern: ({ sameOrigin, url }) =>
              sameOrigin && /\.(png|jpe?g|webp|gif)(?:[?#]|$)/.test(String(url)),
            handler: "CacheFirst",
            options: {
              cacheName: "images",
              expiration: { maxEntries: 60, maxAgeSeconds: 30 * 24 * 3600 },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 4173,
    // e2e smoke tests 跑 vite preview：没有这个 proxy，/api 请求会 404
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // 所有 jsx-runtime 变体（ESM/CJS/生产）都必须进 react chunk：
          // react-markdown 依赖树里的 CJS 模块会 require('react/jsx-runtime')，
          // @rollup/plugin-commonjs 会额外打包一份 jsx-runtime.cjs 进 markdown chunk，
          // 全站 TSX 编译产物都从 markdown chunk 拿 jsx → markdown-*.js 被入口
          // modulepreload（伪懒加载）。object 形式只列 'react/jsx-runtime' 捕获不到
          // 这份 CJS 副本，所以用函数形式按 id 兜住全部变体。
          if (
            id.includes("jsx-runtime") ||
            id.includes("node_modules/react/") ||
            id.includes("node_modules/react-dom") ||
            id.includes("node_modules/react-router")
          ) {
            return "react";
          }
          if (
            id.includes("node_modules/react-markdown") ||
            id.includes("node_modules/remark-gfm")
          ) {
            return "markdown";
          }
          return undefined;
        },
      },
    },
  },
});
