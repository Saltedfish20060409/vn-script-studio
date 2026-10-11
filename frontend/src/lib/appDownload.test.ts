import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { APP_APK_MIRROR_URL, APP_APK_URL } from "./appDownload";

/**
 * 这两个地址是登录页 / 页脚 / 使用指南 / 设置四处共用的唯一真源，
 * 改动会直接影响用户能不能下到安装包，所以把意图钉在这里。
 */
describe("Android 安装包地址", () => {
  it("主链接是站内相对路径，跟着站点走（不把域名写死进代码）", () => {
    expect(APP_APK_URL.startsWith("/dl/")).toBe(true);
    expect(APP_APK_URL).not.toMatch(/^https?:/);
  });

  it("主链接不带版本号：latest 这个名字换版本时保持不变", () => {
    // 曾经的口径是"去 GitHub 下载第一个文件"，靠位置指路；换成直链后靠名字。
    // 一旦有人把 v0.1.0 写进地址，每次发版都会断掉已经发出去的链接。
    expect(APP_APK_URL.endsWith("-latest.apk")).toBe(true);
    expect(APP_APK_URL).not.toMatch(/\d+\.\d+\.\d+/);
  });

  it("备用链接是 GitHub Releases（直链打不开时才用）", () => {
    expect(APP_APK_MIRROR_URL).toContain("github.com/");
    expect(APP_APK_MIRROR_URL).toContain("/releases");
  });

  it("PWA 导航回退必须排除下载目录", () => {
    // 实盘：装好 PWA 的浏览器里点「Android 客户端」，看到的是**网页版界面**而不是开始下载
    // —— Service Worker 的 NavigationRoute 把任何同源导航都回成缓存的 index.html，
    // 而迅雷这类下载器绕过 SW，反而能下到真包（症状就是"浏览器不行、下载器可以"）。
    // curl / Invoke-WebRequest 同样不经过 SW，所以只看它们会得到假的"没问题"。
    // 修法是 vite.config.ts 里的 navigateFallbackDenylist；这里守着它别被删掉或改窄。
    const conf = readFileSync(new URL("../../vite.config.ts", import.meta.url), "utf8");
    const m = conf.match(/navigateFallbackDenylist:\s*\[([^\]]*)\]/);
    expect(m, "vite.config.ts 里没有 navigateFallbackDenylist").toBeTruthy();
    expect(m?.[1] ?? "").toContain("dl");
  });
});
