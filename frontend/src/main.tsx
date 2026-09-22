import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import App from "./App";
import { installErrorReporter } from "./lib/errorReporter";
// 自托管展示/等宽字体（仅 latin，中文走系统字体回退）
import "@fontsource/baloo-2/latin-600.css";
import "@fontsource/baloo-2/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "./styles/globals.css";

installErrorReporter();

// PWA：注册 Service Worker。registerType=autoUpdate + skipWaiting + clientsClaim
// 保证每次部署（新 cacheId + 新 hash 资源）后新版本自动接管，
// 用户无需手动清缓存即可看到更新。
registerSW({ immediate: true });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
);
