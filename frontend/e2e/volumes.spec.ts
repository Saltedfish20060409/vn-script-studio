import { expect, test, type Page } from "@playwright/test";

/**
 * 分卷回归（真实前后端）。
 *
 * 轻小说/网文按卷连载：卷要能建、能改名、能删（删了章节回到「未分卷」而不是删章节），
 * 新章节要落进当前查看的那一卷，章节要能改归属，卷头要显示每卷章数。
 * 卷存在工程数据里（服务端），所以刷新后仍在。
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

/** 驱动应用内的 prompt（输入框 + 确认按钮） */
async function answerPrompt(page: Page, value: string, confirmLabel: string) {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await dialog.locator("input").fill(value);
  await dialog.getByRole("button", { name: confirmLabel }).click();
}

const VOL_CHIP = /^volume-chip-vol-/;
const CHAPTER_CHIP = /^chapter-chip-/;

test("建卷 → 新章节落进当前卷 → 卷头显示章数", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_vol_"));

  // 一开始没有卷：不显示卷标行
  await expect(page.getByTestId("volume-row")).toHaveCount(0);
  const chaptersBefore = await page.getByTestId(CHAPTER_CHIP).count();
  expect(chaptersBefore).toBeGreaterThan(0);

  // 建第一卷
  await page.getByTestId("volume-add").first().click();
  await answerPrompt(page, "第一卷 春", "创建");
  await expect(page.getByTestId("volume-row")).toBeVisible();
  const volChip = page.getByTestId(VOL_CHIP).first();
  await expect(volChip).toContainText("第一卷 春");
  await expect(volChip).toContainText("0 章");
  // 已有章节还没归卷 → 出现「未分卷」一档，章数正确
  await expect(page.getByTestId("volume-chip-loose")).toContainText(`${chaptersBefore} 章`);

  // 在当前卷里新建一章 → 落进这一卷
  await page.getByRole("button", { name: "+ 章" }).click();
  await answerPrompt(page, "春之一", "添加");
  await expect(volChip).toContainText("1 章");
  await expect(page.getByTestId(CHAPTER_CHIP)).toHaveCount(1); // 只显示当前卷的章节
  await expect(page.getByTestId(CHAPTER_CHIP).first()).toContainText("春之一");

  // 切到未分卷：原来的章节还在
  await page.getByTestId("volume-chip-loose").click();
  await expect(page.getByTestId(CHAPTER_CHIP)).toHaveCount(chaptersBefore);
});

test("章节改归属 → 卷改名 → 删卷后章节回到「未分卷」，刷新后仍在", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_vol2_"));

  await page.getByTestId("volume-add").first().click();
  await answerPrompt(page, "第一卷", "创建");
  await page.getByTestId("volume-add").first().click();
  await answerPrompt(page, "第二卷", "创建");
  await expect(page.getByTestId(VOL_CHIP)).toHaveCount(2);

  // 把未分卷的某一章归入第一卷
  await page.getByTestId("volume-chip-loose").click();
  const totalChapters = await page.getByTestId(CHAPTER_CHIP).count();
  await page.getByTestId(CHAPTER_CHIP).first().click();
  await page.getByTestId("chapter-volume-select").selectOption({ label: "第一卷" });
  const firstVol = page.getByTestId(VOL_CHIP).first();
  await expect(firstVol).toContainText("1 章");
  await expect(page.getByTestId("volume-chip-loose")).toContainText(`${totalChapters - 1} 章`);

  // 改卷名
  await firstVol.click();
  await page.getByTestId("volume-rename").click();
  await answerPrompt(page, "卷一·春", "保存");
  await expect(page.getByTestId(VOL_CHIP).first()).toContainText("卷一·春");

  // 刷新后仍在（卷在工程数据里，不是本机缓存）
  await page.waitForTimeout(1500);
  await page.reload();
  await expect(page.getByTestId(VOL_CHIP).first()).toContainText("卷一·春", { timeout: 30_000 });

  // 删卷 → 章节回到「未分卷」（章节本身不能被删掉）
  await page.getByTestId(VOL_CHIP).first().click();
  await page.getByTestId("volume-delete").click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "删掉这卷" })
    .click();
  await expect(page.getByTestId(VOL_CHIP)).toHaveCount(1);
  await expect(page.getByTestId("volume-chip-loose")).toContainText(`${totalChapters} 章`);
  await expect(page.getByTestId(CHAPTER_CHIP)).toHaveCount(totalChapters);
});
