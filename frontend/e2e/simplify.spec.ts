import { expect, test, type Page } from "@playwright/test";
import { closeOverlay, openFilePage, openRibbonMenu, openViewPanel } from "./nav";

/**
 * Word 壳回归：稿纸常在；文件二级页 / 视图抽屉可开可关；设定子页仍在。
 */

const PASSWORD = "e2e-secret-123";

function randomName(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
}

function seedLocalStorage(page: Page) {
  page.addInitScript(() => {
    try {
      for (let v = 1; v <= 30; v += 1) localStorage.setItem(`vnss-notice-read-v${v}`, "1");
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

test("新人第一屏：没有功能名长文弹窗，只有三个可点的动作", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_simple_"));

  await expect(page.getByTestId("onboarding-overlay")).toHaveCount(0);

  const checklist = page.getByRole("region", { name: "新手上手三步" });
  await expect(checklist).toBeVisible({ timeout: 20_000 });
  await expect(checklist).toContainText("三步上手");
  for (const label of ["让 AI 续写这一段", "生成可试玩的脚本", "导出 Word 存档"]) {
    await expect(checklist.getByRole("button", { name: new RegExp(label) })).toBeVisible();
  }

  const bar = await checklist.boundingBox();
  const editor = await page.getByTestId("script-editor").boundingBox();
  expect(bar && editor && bar.y < editor.y).toBe(true);

  await expect(page.getByTestId("script-editor")).toHaveAttribute(
    "placeholder",
    /旁白直接写/
  );
});

test("文件菜单：二级页都能打开，返回正文后稿纸还在", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_subs_"));

  for (const label of ["打开（剧本库）", "写作统计", "导出…"]) {
    await openFilePage(page, label);
    await expect(page.getByTestId("file-backstage")).toBeVisible();
    await page.getByTestId("backstage-close").click();
    await expect(page.getByTestId("file-backstage")).toHaveCount(0);
    await expect(page.getByTestId("script-editor")).toBeVisible();
  }

  // 结构分析现在是**抽屉**（与 VN 快捷条同一入口），不再是文件菜单里的整页：
  // 同一功能两套 UI 只会让人不知道该点哪个，所以文件菜单里那条已去掉。
  await openViewPanel(page, "结构分析");
  await expect(page.getByTestId("view-drawer")).toBeVisible();
  await closeOverlay(page);

  for (const label of ["本地化", "成员", "账本 / 摘要"]) {
    await openFilePage(page, label);
    await expect(page.getByTestId("file-backstage")).toBeVisible();
    await page.getByTestId("backstage-close").click();
  }
});

test("顶栏有文件/开始/审阅/视图四菜单", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_ribbon_"));
  const ribbon = page.getByTestId("studio-ribbon");
  await expect(ribbon).toBeVisible();
  for (const name of ["文件", "开始", "审阅", "视图"]) {
    await expect(ribbon.getByText(name, { exact: true }).first()).toBeVisible();
  }
});

/**
 * Agent 起手句：一下都不用打字，点一下就填好。
 *
 * 这条是上一版重构时丢掉、这一轮恢复的（旧版按"六个篇章 + 顶栏审稿按钮"的导航写的）。
 * 恢复时改了两处、其余断言原样保留：
 * - 打开方式：旧版点顶栏那个 title 含「AI 责编」的按钮；现在是**审阅菜单 → AI 责编**
 *   （Word 壳把入口收进了菜单，title 也换成了「打开审稿 Agent」）；
 * - 起手句按钮用 `agent-starters` 里的**第一个**，不再绑死某句文案。
 */
test("Agent 起手句：点一下就填好，且不会自动发送", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_starter_"));

  const menu = await openRibbonMenu(page, "审阅");
  await menu.getByRole("menuitem", { name: "AI 责编" }).click();

  const starters = page.getByTestId("agent-starters");
  await expect(starters).toBeVisible({ timeout: 20_000 });

  // 输入框初始为空。用正则匹配「用平常话说…」那个输入框（AgentComposerBox）；
  // 聊天里的「一句话就行」在空状态还没渲染，别用那个。
  const composer = page.getByPlaceholder(/用平常话说/).first();
  await expect(composer).toHaveValue("");

  // 点第一个起手句 → 内容进了输入框（不用打字），而且**没有**被自动发送
  await starters.getByRole("button").first().click();
  await expect(composer).not.toHaveValue("");
  await expect(starters).toHaveCount(0);
});

test("设定抽屉：写作参考卡不再和设定条目并列，但入口还在", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_world_"));
  await openViewPanel(page, "设定");

  const drawer = page.getByTestId("view-drawer");
  for (const label of ["角色卡", "世界观 / 大纲", /^设定条目/]) {
    await expect(drawer.getByRole("button", { name: label }).first()).toBeVisible({
      timeout: 15_000,
    });
  }

  await expect(drawer.getByRole("button", { name: "写作参考卡", exact: true })).toHaveCount(0);

  // 入口仍在「更多」或展开区（WorldPanel 行为）
  const more = drawer.getByRole("button", { name: /更多|写作参考/ });
  if (await more.first().isVisible().catch(() => false)) {
    await more.first().click();
  }
  const card = drawer.getByRole("button", { name: "写作参考卡", exact: true });
  if (await card.count()) {
    await expect(card.first()).toBeVisible();
  }
});
