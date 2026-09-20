import { expect, test, type Page } from "@playwright/test";

/**
 * 导入小说文件的回归（真实前后端）。
 *
 * 修的三件事：整本书塞进一个章节、每行一个块、只能导 2MB。
 * 这里直接从界面导入一份"两卷四章"的 epub 式纯文本，断言章节/卷结构真的建出来了。
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

const NOVEL = [
  "雨城",
  "作者：某人",
  "",
  "第一卷 春",
  "",
  "第一章 站台",
  "",
  "雨落在站台上，他把手举到眼前。",
  "那双手不是他的。",
  "",
  "第二章 归途",
  "",
  "末班车已经开走了。",
  "",
  "第二卷 夏",
  "",
  "第一章 蝉声",
  "",
  "夏天很热，蝉在叫。",
  "",
  "第二章 夜路",
  "",
  "他走了一整夜。",
].join("\n");

test("导入小说文件：按章切分、按卷归组、正文按段落成块", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_import_"));

  const imported = page.waitForResponse(
    (r) => r.url().includes("/projects/import") && r.request().method() === "POST",
    { timeout: 30_000 }
  );
  // 页面上有两个 file input（顶栏导入 + AI 对话附件），按 accept 精确定位导入那个
  await page.locator('input[type="file"][accept*=".docx"]').first().setInputFiles({
    name: "雨城.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(NOVEL, "utf-8"),
  });
  const res = await imported;
  expect(res.status()).toBe(200);
  const project = await res.json();

  // 后端结构：两卷四章（不是"整本塞进一章"）
  expect((project.volumes ?? []).map((v: { title: string }) => v.title)).toEqual([
    "第一卷 春",
    "第二卷 夏",
  ]);
  expect(project.chapters.map((c: { title: string }) => c.title)).toEqual([
    "第一章 站台",
    "第二章 归途",
    "第一章 蝉声",
    "第二章 夜路",
  ]);
  // 正文按段落成块：同一段的连续两行合成**一个** narration 块（不是一行一块）
  const firstBlocks = project.chapters[0].blocks as Array<{ type: string; text?: string }>;
  const narration = firstBlocks.filter((b) => b.type === "narration");
  const merged = narration.find((b) => (b.text ?? "").includes("雨落在站台上"));
  expect(merged, "没找到正文段").toBeTruthy();
  expect(merged!.text).toContain("那双手不是他的。");
  // 开头那两行（书名/作者）也被带进来了，没丢
  expect(narration.some((b) => (b.text ?? "").includes("作者"))).toBe(true);

  // 界面上真的能切卷、能切章
  await expect(page.getByTestId("volume-row")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId(/^volume-chip-vol-/)).toHaveCount(2);
  await expect(page.getByTestId("script-editor")).toHaveValue(/雨落在站台上/);
});
