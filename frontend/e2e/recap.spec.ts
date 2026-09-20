import { expect, test, type Page } from "@playwright/test";

/**
 * 前情提要回归（真实前后端，本地没配模型密钥）。
 *
 * 覆盖能在无模型环境下确定验证的部分：
 * - 入口在分卷/不分卷两种形态下都在；
 * - 点了会真的发出请求，失败时给**明确提示**（而不是一直转圈）；
 * - 有内容时能插进正文（这里用直接调接口拿到 400 之外的路径不现实，
 *   所以只测"面板出现 + 错误可见 + 能关闭"）。
 * 生成质量与范围选择由后端 mock 测试覆盖（tests/test_api_recap.py）。
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
      localStorage.setItem("vnss-desktop-tips-v1", "1");
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

test("前情提要入口在：点开面板会真的请求，并且不会卡住", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_recap_"));

  // 不分卷时也有入口
  const entry = page.getByTestId("chapter-recap");
  await expect(entry).toBeVisible();

  const posted = page.waitForRequest(
    (r) => r.url().includes("/recap") && r.method() === "POST",
    { timeout: 15_000 }
  );
  await entry.click();
  const req = await posted;
  const body = JSON.parse(req.postData() ?? "{}");
  expect(body.mode).toBe("before");

  await expect(page.getByTestId("recap-card")).toBeVisible();

  // 本地环境有没有模型密钥取决于 .env：要么出文本，要么给明确报错——不允许一直转圈。
  const text = page.getByTestId("recap-text");
  const error = page.getByTestId("recap-error");
  await expect
    .poll(async () => (await text.count()) > 0 || (await error.count()) > 0, { timeout: 90_000 })
    .toBe(true);
  if (await text.count()) {
    await expect(text).not.toHaveValue("");
  } else {
    await expect(error).not.toBeEmpty();
  }
  // 两种情况下「重新生成」都要能再点（不能卡在生成中）
  await expect(page.getByTestId("recap-regenerate")).toBeEnabled();

  // 能收起
  await page.getByTestId("recap-card").getByRole("button", { name: "⌄" }).click();
  await expect(page.getByTestId("recap-card")).toHaveCount(0);
});

test("分卷后：卷头的前情提要入口把卷 id 带上", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_recap_vol_"));

  await page.getByTestId("volume-add").first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.locator("input").fill("第二卷");
  await dialog.getByRole("button", { name: "创建" }).click();
  await expect(page.getByTestId(/^volume-chip-vol-/).first()).toBeVisible();

  const posted = page.waitForRequest(
    (r) => r.url().includes("/recap") && r.method() === "POST",
    { timeout: 15_000 }
  );
  await page.getByTestId("volume-recap").click();
  const body = JSON.parse((await posted).postData() ?? "{}");
  // 第一卷还没内容可回顾 → 后端会 400，但请求里必须带上当前卷
  expect(body.volume_id).toBeTruthy();
  await expect(page.getByTestId("recap-card")).toBeVisible();
});
