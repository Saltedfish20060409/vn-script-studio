import { expect, test, type Page } from "@playwright/test";

/**
 * 桌面视图的真实回归（需要后端 + 数据库，跟 smoke 一样跑）。
 *
 * 为什么要单开一个 spec：桌面视角是"外壳 + 定高工作区"，改外壳的几何很容易把工作台里
 * 的排版压坏，而**单元测试完全看不到**（2026-09-17 就是这样：外壳变成定高后，
   里面 overflow:auto 的标签栏/章节条被 flex 压成 1px，内容溢出后被引导条盖住，
   用户的表现是"写作页的剧本/分析切不了、章节也点不动"）。
 *
 * 这里只断言"用户看得见、点得到"的行为，不碰实现细节。
 */

const PASSWORD = "e2e-secret-123";

function randomName(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
}

function seedLocalStorage(page: Page) {
  page.addInitScript(() => {
    try {
      for (let v = 1; v <= 30; v += 1) localStorage.setItem(`vnss-notice-read-v${v}`, "1");
      localStorage.setItem("vnss-tour-v1", "1");
      localStorage.setItem("vnss-music-bar", "0");
      // AI 责编浮窗预设成"贴边收起"，用来验证桌面视角下它不再渲染
      localStorage.setItem(
        "vnss-agent-float-v6",
        JSON.stringify({ mode: "docked", edge: "right", along: 96, size: "mini" })
      );
    } catch {
      /* ignore */
    }
  });
}

async function registerAndLogin(page: Page, username: string) {
  seedLocalStorage(page);
  await page.goto("/login");
  await page.getByRole("tab", { name: "注册" }).click();
  await page.fill("#vnss-username", username);
  await page.fill("#vnss-email", `${username}@e2email.example.net`);
  await page.fill("#vnss-password", PASSWORD);
  await page.fill("#vnss-confirm", PASSWORD);
  await page.getByRole("button", { name: "注册并发送验证邮件" }).click();
  await page.waitForResponse(
    (r) => r.url().includes("/auth/register") && r.request().method() === "POST",
    { timeout: 20_000 }
  );
  await page.getByRole("button", { name: "返回登录" }).click();
  await page.fill("#vnss-username", username);
  await page.fill("#vnss-password", PASSWORD);
  await page.getByRole("button", { name: "开始创作" }).click();
  await expect(page.getByTestId("script-editor")).toBeVisible({ timeout: 40_000 });
}

test("桌面视角：篇章标签栏没被压扁、剧本/分析与章节都能切、设置齿轮不浮在底下", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_desktop_");
  await registerAndLogin(page, username);

  // 新账号自带一个可写的示例剧本；先加一章，方便验证章节切换
  const title = await page.getByLabel("作品标题").inputValue();
  await page.getByRole("button", { name: "+ 章" }).click();
  // 加章会先问标题（有默认值），确认即可
  await page.getByRole("button", { name: "添加" }).click();
  await expect(page.getByRole("option")).toHaveCount(5, { timeout: 20_000 });
  await page.waitForTimeout(1500);

  // 切到桌面视图并重新进入
  await page.evaluate(() => {
    localStorage.setItem("vnss-workspace-v1", JSON.stringify({ view: "desktop" }));
  });
  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible({ timeout: 30_000 });

  // 双击剧本图标 = 打开这个剧本的工作台窗口
  await page.getByRole("listitem", { name: title }).dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("script-editor")).toBeVisible();

  // ① 六个篇章标签栏必须是正常高度（被压扁时只有 1px）
  const tabNav = page.locator('nav[aria-label="剧本篇章"]');
  await expect(tabNav).toBeVisible();
  await expect(tabNav.getByRole("button")).toHaveCount(6);
  const tabs = tabNav.getByRole("button", { name: /写作/ });
  const tabsBox = await tabs.boundingBox();
  expect(tabsBox?.height ?? 0).toBeGreaterThan(30);
  // 标签中心点上就是标签本身（没被别的长条盖住）
  const topAtTabs = await tabs.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return top ? top.closest("button") === el : false;
  });
  expect(topAtTabs, "篇章标签被别的东西盖住了").toBe(true);

  // ② 写作页的"分析"能切
  await page.getByRole("button", { name: "分析", exact: true }).click();
  await expect(page.getByRole("button", { name: "分析", exact: true })).toHaveClass(/subActive/);

  // ③ 回到剧本页后能切章节
  await page.getByRole("button", { name: "剧本", exact: true }).click();
  await page.getByRole("option").nth(1).click();
  await expect(page.getByRole("option").nth(1)).toHaveAttribute("aria-selected", "true");

  // ④ 桌面视角里不该有悬浮设置齿轮（开始菜单里有"系统设置"）
  await expect(page.getByRole("button", { name: "打开设置" })).toHaveCount(0);

  // ⑤ 工作台窗口只占标题栏与任务栏之间；整页不滚动，改由工作台自己滚
  const shell = page.locator(".vnss-app");
  const box = await shell.boundingBox();
  expect(Math.round(box?.y ?? 0)).toBe(30);
  expect(Math.round((box?.y ?? 0) + (box?.height ?? 0))).toBe(860 - 46);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(await shell.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);

  // ⑥ 页脚（使用指南 / 备案号）必须在工作台内容的最下面，而不是被溢出的编辑器盖在框里
  const footer = page.locator("footer");
  await expect(footer).toHaveCount(1);
  const footerBox = await footer.boundingBox();
  const mainBox = await page.locator("main").boundingBox();
  expect(footerBox?.y ?? 0).toBeGreaterThanOrEqual(
    Math.round((mainBox?.y ?? 0) + (mainBox?.height ?? 0)) - 2
  );

  // 滚到工作台底部：页脚要露出来，而且点得到（被编辑器盖住时这里会点到别的元素）
  await shell.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  await page.waitForTimeout(400);
  await expect(footer).toBeInViewport();
  const footerOnTop = await footer.evaluate((el) => {
    const link = el.querySelector("a");
    if (!link) return false;
    const r = link.getBoundingClientRect();
    return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === link;
  });
  expect(footerOnTop, "页脚被别的内容盖住了").toBe(true);
});

test("桌面视角：往下滚工作台时顶栏仍贴在标题栏下面（不会被压住）", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_desktop_scroll_");
  await registerAndLogin(page, username);
  const title = await page.getByLabel("作品标题").inputValue();
  await page.evaluate(() => {
    localStorage.setItem("vnss-workspace-v1", JSON.stringify({ view: "desktop" }));
  });
  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("listitem", { name: title }).dblclick();
  await expect(page.getByTestId("script-editor")).toBeVisible();

  await page.locator(".vnss-app").evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  await page.waitForTimeout(400);

  const titleBar = await page.getByTestId("desktop-script-window").boundingBox();
  expect(Math.round(titleBar?.y ?? -1)).toBe(0);
  // 工作台的顶栏（含"作品标题"输入框）仍然贴在标题栏下面、没被吃掉
  const titleInput = await page.getByLabel("作品标题").boundingBox();
  expect(titleInput?.y ?? 0).toBeGreaterThanOrEqual(30);
  expect(titleInput?.y ?? 0).toBeLessThan(120);
  expect(titleInput?.width ?? 0).toBeGreaterThan(80);
});

test("桌面视角：图标角标显示章数，「继续写作」回到上次那一章", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_desktop_badge_");
  await registerAndLogin(page, username);
  const title = await page.getByLabel("作品标题").inputValue();

  // 加一章（示例剧本自带 4 章 → 5 章），再停在第 2 章
  await page.getByRole("button", { name: "+ 章" }).click();
  await page.getByRole("button", { name: "添加" }).click();
  await expect(page.getByRole("option")).toHaveCount(5, { timeout: 20_000 });
  await page.getByRole("option").nth(1).click();
  await expect(page.getByRole("option").nth(1)).toHaveAttribute("aria-selected", "true");
  const chapterLabel = ((await page.getByRole("option").nth(1).textContent()) ?? "")
    .replace(/^\d+/, "")
    .trim();
  await page.waitForTimeout(2500);

  await page.evaluate(() => {
    localStorage.setItem("vnss-workspace-v1", JSON.stringify({ view: "desktop" }));
  });
  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible({ timeout: 30_000 });

  // ① 角标 = 这个剧本的章数（列表接口直接给，不用逐个项目去查）
  const icon = page.getByRole("listitem", { name: title });
  await expect(icon.locator('[data-testid^="icon-badge-"]')).toHaveText("5 章");
  // ② 提示里有"共 5 章 · 最后修改 …"
  const hint = await icon.getAttribute("title");
  expect(hint).toContain("共 5 章");
  expect(hint).toContain("最后修改");

  // ③ 「继续写作」写着上次那一章，点了直接回到那里
  const resume = page.getByTestId("desktop-resume");
  await expect(resume).toBeVisible();
  await expect(resume).toContainText(chapterLabel);
  await resume.click();
  await expect(page.getByTestId("script-editor")).toBeVisible();
  await expect(page.getByRole("option").nth(1)).toHaveAttribute("aria-selected", "true");
});

test("工作台视图：页脚（使用指南 / 备案号）在页面最底部，没被音乐条压住", async ({ page }) => {  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_footer_");
  await registerAndLogin(page, username);

  // 滚到页面底部（页脚在内容最后）
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(500);

  const footer = page.locator("footer");
  await expect(footer).toBeInViewport();
  await expect(footer).toContainText("使用指南");

  // 底部固定的音乐条不能盖住它（以前会被压在条下面点不到）
  const bar = page.getByTestId("music-bar");
  if (await bar.count()) {
    const barBox = await bar.boundingBox();
    const footerBox = await footer.boundingBox();
    expect(footerBox?.y ?? 0).toBeGreaterThanOrEqual(0);
    expect((footerBox?.y ?? 0) + (footerBox?.height ?? 0)).toBeLessThanOrEqual(barBox?.y ?? 0);
  }

  // 页脚里的"使用指南"真的点得到（elementFromPoint 命中的就是它）
  const linkOnTop = await footer.evaluate((el) => {
    const link = el.querySelector("a");
    if (!link) return false;
    const r = link.getBoundingClientRect();
    return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === link;
  });
  expect(linkOnTop, "页脚被别的东西盖住了").toBe(true);
});

test("桌面视角：一次性小抄、任务栏出口，以及不再叠一个 AI 浮窗", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_desktop_tips_");
  await registerAndLogin(page, username);
  const title = await page.getByLabel("作品标题").inputValue();

  // 模拟"第一次进桌面视角"：清掉小抄已读标记
  await page.evaluate(() => {
    localStorage.setItem("vnss-workspace-v1", JSON.stringify({ view: "desktop" }));
    localStorage.removeItem("vnss-desktop-tips-v1");
  });
  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible({ timeout: 30_000 });

  // ① 小抄出现，四条要点都在，点「知道了」之后刷新也不再出现
  const tips = page.getByTestId("desktop-tips");
  await expect(tips).toBeVisible();
  await expect(tips).toContainText("双击剧本图标");
  await expect(tips).toContainText("右键");
  await page.getByTestId("desktop-tips-close").click();
  await expect(tips).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("desktop-tips")).toHaveCount(0);

  // ② 桌面视角下不渲染 AI 责编的浮动面板（同一功能只留"应用窗口"一套 UI）
  await expect(page.locator('button[title^="AI 责编"]')).toHaveCount(0);

  // ③ 双击剧本 → 顶栏「审稿」应该打开桌面上的 AI 责编窗口，而不是浮窗
  await page.getByRole("listitem", { name: title }).dblclick();
  await expect(page.getByTestId("script-editor")).toBeVisible();
  await page.getByRole("button", { name: "审稿" }).click();
  await expect(page.getByTestId("desktop-window-agent")).toBeVisible();

  // ④ 任务栏常驻「工作台」出口：一键回三栏视图
  await page.getByTestId("desktop-to-studio").click();
  await expect(page.getByTestId("desktop-view")).toHaveCount(0);
  await expect(page.getByTestId("script-editor")).toBeVisible();
});
