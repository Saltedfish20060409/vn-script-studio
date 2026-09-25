import { expect, test, type Page } from "@playwright/test";
import { openViewPanel } from "./nav";

/**
 * 桌面视图回归：桌面只作启动器，选中作品进入稿纸（Word 壳）。
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
    localStorage.setItem("vnss-workspace-v1", JSON.stringify({ view: "desktop" }));
  });
  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("listitem", { name: title }).dblclick();
  await expect(page.getByTestId("script-editor")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("studio-ribbon")).toBeVisible();
}

test("桌面启动器：双击剧本进入稿纸，Ribbon 与大纲可用", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_desktop_");
  await registerAndLogin(page, username);

  const title = await page.getByLabel("作品标题").inputValue();
  await page.getByRole("button", { name: "+ 章" }).click();
  await page.getByRole("button", { name: "添加" }).click();
  await expect(page.getByRole("option")).toHaveCount(5, { timeout: 20_000 });
  await page.waitForTimeout(1500);

  await goDesktopAndOpen(page, title);

  // 不再套桌面双壳窗口
  await expect(page.getByTestId("desktop-script-window")).toHaveCount(0);

  const ribbon = page.getByTestId("studio-ribbon");
  const box = await ribbon.boundingBox();
  expect(box?.height ?? 0).toBeGreaterThan(30);

  // 视图 → 写作分析
  await openViewPanel(page, "写作分析");
  await expect(page.getByTestId("file-backstage").or(page.getByTestId("view-drawer"))).toBeVisible();
  const close = page.getByTestId("backstage-close").or(page.getByTestId("drawer-close"));
  await close.first().click();

  // 章节可切
  await page.getByRole("option").nth(1).click();
  await expect(page.getByRole("option").nth(1)).toHaveAttribute("aria-selected", "true");
});

test("桌面启动器：图标角标显示章数，「继续写作」进入稿纸", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  const username = randomName("e2e_desktop_badge_");
  await registerAndLogin(page, username);
  const title = await page.getByLabel("作品标题").inputValue();

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

  const icon = page.getByRole("listitem", { name: title });
  await expect(icon.locator('[data-testid^="icon-badge-"]')).toHaveText("5 章");
  const hint = await icon.getAttribute("title");
  expect(hint).toContain("共 5 章");
  expect(hint).toContain("最后修改");

  const resume = page.getByTestId("desktop-resume");
  await expect(resume).toBeVisible();
  await expect(resume).toContainText(chapterLabel);
  await resume.click();
  await expect(page.getByTestId("script-editor")).toBeVisible();
  await expect(page.getByRole("option").nth(1)).toHaveAttribute("aria-selected", "true");
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
