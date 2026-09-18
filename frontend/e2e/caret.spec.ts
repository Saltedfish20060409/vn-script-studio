import { expect, test, type Page } from "@playwright/test";

/**
 * 「上次停在这里」的真实回归（需要后端 + 数据库）。
 *
 * 这条功能的取舍来自线上数据：90% 的章节不到一屏，所以**不自动跳光标**（那会抢焦点），
 * 只在真的打开这一章时给一个可以点的入口。
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
      localStorage.setItem("vnss-firstrun-hidden", "1");
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

test("「上次停在这里」：回来时给入口、点了才跳；顺手写就没它的事", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 860 });
  await registerAndLogin(page, randomName("e2e_caret_"));

  const editor = page.getByTestId("script-editor");
  await editor.click();
  await page.keyboard.press("Control+End"); // 光标落到正文末尾
  const caret = await editor.evaluate((el) => (el as HTMLTextAreaElement).selectionStart);
  expect(caret).toBeGreaterThan(20);

  // 失焦即记住（点别处）
  await page.getByLabel("作品标题").click();
  await expect(page.getByTestId("caret-hint")).toHaveCount(0);

  // 重新打开：出现「上次停在这里」，光标不自动跳（还在别处）
  await page.reload();
  const hint = page.getByTestId("caret-hint");
  await expect(hint).toBeVisible({ timeout: 30_000 });
  expect(
    await editor.evaluate((el) => document.activeElement === el)
  ).toBe(false);

  // 点它才回到那个位置
  await page.getByTestId("caret-hint-jump").click();
  await expect
    .poll(() => editor.evaluate((el) => (el as HTMLTextAreaElement).selectionStart))
    .toBe(caret);
  await expect(page.getByTestId("caret-hint")).toHaveCount(0);

  // 手动改了正文 → 标记消失（人已经回来了，不用再提示）
  await page.reload();
  await expect(page.getByTestId("caret-hint")).toBeVisible({ timeout: 30_000 });
  await editor.click();
  await page.keyboard.type("。");
  await expect(page.getByTestId("caret-hint")).toHaveCount(0);
});
