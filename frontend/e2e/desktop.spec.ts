import { expect, test, type Page } from "@playwright/test";
import { openViewPanel } from "./nav";

/**
 * 桌面回归：打开项目 = **在桌面上打开这个项目的窗口**（标题栏 + 稿纸）。
 * 窗口标题栏的「全屏写作」才离开桌面（那一套由 writeShell / 组件台守着）。
 */

const PASSWORD = "e2e-secret-123";

function randomName(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
}

function seedLocalStorage(page: Page) {
  page.addInitScript(() => {
    try {
      for (let v = 1; v <= 30; v += 1) localStorage.setItem(`vnss-notice-read-v${v}`, "1");
      localStorage.setItem("vnss-boot-v1", "1");
      localStorage.setItem("vnss-music-bar", "0");
      // 组件台/真机共用同一台机器时别把"上次开着的那扇窗"带进来（这条用例要的是图标页）
      localStorage.removeItem("vnss-desktop-window-v1");
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

async function goDesktopAndOpen(page: Page, title: string) {
  await page.evaluate(() => {
    localStorage.removeItem("vnss-desktop-window-v1");
    localStorage.setItem("vnss-workspace-v1", JSON.stringify({ view: "desktop" }));
  });
  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("listitem", { name: title }).dblclick();
  // 打开的是一扇窗：标题栏在，稿纸在它下面，桌面没有退场
  await expect(page.getByTestId("desktop-script-window")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("script-editor")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("studio-ribbon")).toBeVisible();
}

test("桌面作品窗口：双击剧本在桌面上开窗，Ribbon 与大纲可用；全屏写作与返回桌面", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_desktop_");
  await registerAndLogin(page, username);

  const title = await page.getByLabel("作品标题").inputValue();
  const chapters = page.getByTestId("chapter-outline").getByRole("option");
  const before = await chapters.count();
  await page.getByRole("button", { name: "+ 章" }).click();
  await page.getByRole("button", { name: "添加" }).click();
  await expect(chapters).toHaveCount(before + 1, { timeout: 20_000 });
  await page.waitForTimeout(1500);

  await goDesktopAndOpen(page, title);

  // 桌面还在（图标让位给窗口，任务栏与标题栏照旧）——一扇窗，一套稿纸
  await expect(page.getByTestId("desktop-view")).toBeVisible();
  await expect(page.getByTestId("desktop-task-script")).toBeVisible();

  const ribbon = page.getByTestId("studio-ribbon");
  const box = await ribbon.boundingBox();
  expect(box?.height ?? 0).toBeGreaterThan(30);
  // 工作台摆在标题栏(30px)与任务栏(46px)之间：不能被压到屏幕外，也不能盖住任务栏
  // （boundingBox 给的是 {x, y, width, height}）
  expect(Math.round(box?.y ?? -1)).toBeGreaterThanOrEqual(30);
  expect(Math.round((box?.y ?? 0) + (box?.height ?? 0))).toBeLessThanOrEqual(860 - 46);

  // 视图 → 结构分析（原「写作分析」；文件菜单里那条已按"同一功能不要两套 UI"去掉）
  await openViewPanel(page, "结构分析");
  await expect(page.getByTestId("file-backstage").or(page.getByTestId("view-drawer"))).toBeVisible();
  const close = page.getByTestId("backstage-close").or(page.getByTestId("drawer-close"));
  await close.first().click();

  // 章节可切
  const outlineOptions = page.getByTestId("chapter-outline").getByRole("option");
  await outlineOptions.nth(1).click();
  await expect(outlineOptions.nth(1)).toHaveAttribute("aria-selected", "true");

  // 「全屏写作」= 收起桌面、稿纸铺满；顶栏「文件 → 返回桌面」回来还是这扇窗
  await page.getByTestId("script-window-fullscreen").click();
  await expect(page.getByTestId("desktop-view")).toHaveCount(0);
  await expect(page.getByTestId("script-editor")).toBeVisible();
  await page.locator("summary", { hasText: "文件" }).first().click();
  await page.getByRole("menuitem", { name: "返回桌面" }).click();
  await expect(page.getByTestId("desktop-view")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
});

test("桌面作品窗口：图标角标显示章数，「继续写作」打开该作品的窗口", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_desktop_badge_");
  await registerAndLogin(page, username);
  const title = await page.getByLabel("作品标题").inputValue();

  const chapters = page.getByTestId("chapter-outline").getByRole("option");
  const before = await chapters.count();
  await page.getByRole("button", { name: "+ 章" }).click();
  await page.getByRole("button", { name: "添加" }).click();
  await expect(chapters).toHaveCount(before + 1, { timeout: 20_000 });
  await chapters.nth(1).click();
  await expect(chapters.nth(1)).toHaveAttribute("aria-selected", "true");
  const chapterLabel = ((await chapters.nth(1).textContent()) ?? "")
    .replace(/^\d+/, "")
    .trim();
  await page.waitForTimeout(2500);

  await page.evaluate(() => {
    localStorage.removeItem("vnss-desktop-window-v1");
    localStorage.setItem("vnss-workspace-v1", JSON.stringify({ view: "desktop" }));
  });
  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible({ timeout: 30_000 });

  const icon = page.getByRole("listitem", { name: title });
  await expect(icon.locator('[data-testid^="icon-badge-"]')).toHaveText(`${before + 1} 章`);
  const hint = await icon.getAttribute("title");
  expect(hint).toContain(`共 ${before + 1} 章`);
  expect(hint).toContain("最后修改");

  const resume = page.getByTestId("desktop-resume");
  await expect(resume).toBeVisible();
  await expect(resume).toContainText(chapterLabel);
  await resume.click();
  // 「继续写作」打开的还是这扇窗（当前作品 + 上次那一章），不是跳去另一套外壳
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("script-editor")).toBeVisible();
  await expect(page.getByRole("option").nth(1)).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("desktop-resume")).toHaveCount(0);
});

test("工作台视图：页脚在页面最底部，没被音乐条压住", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_footer_");
  await registerAndLogin(page, username);

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(500);

  const footer = page.locator("footer");
  await expect(footer).toBeVisible();
  await expect(footer).toBeInViewport();
});
