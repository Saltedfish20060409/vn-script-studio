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
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/.*\.(png|jpg|jpeg|webp|gif)$/,
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
  build: {
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          // Heavy vendor libs — split so app edits don't invalidate these caches
          react: ["react", "react-dom", "react-router-dom"],
          markdown: ["react-markdown", "remark-gfm"],
        },
      },
    },
  },
});
