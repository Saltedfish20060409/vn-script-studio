import { expect, test, type Page } from "@playwright/test";

/**
 * End-to-end smoke tests — the critical user journey:
 * register → login → create project → write prose → save → generate RPY → export.
 *
 * These run against a real backend + built frontend (see playwright.config.ts).
 * Each test uses a unique username so parallel/serial reruns stay isolated.
 */

const PASSWORD = "e2e-secret-123";

function randomName(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
}

async function dismissTour(page: Page) {
  const overlay = page.getByTestId("onboarding-overlay");
  try {
    await overlay.waitFor({ state: "visible", timeout: 2_000 });
    await page.getByRole("button", { name: "跳过" }).click();
  } catch {
    /* 引导未出现：继续 */
  }
}

/** 公告横幅 + 新手引导 + Agent 面板：页面加载前注入标记，
 *  让弹层/悬浮面板不干扰（Agent 预设为 docked 收起在右缘） */
function seedLocalStorage(page: Page) {
  page.addInitScript(() => {
    try {
      localStorage.setItem("vnss-notice-read-v2", "1");
      localStorage.setItem("vnss-tour-v1", "1");
      localStorage.setItem(
        "vnss-agent-float-v6",
        JSON.stringify({ mode: "docked", edge: "right", along: 96, size: "mini" })
      );
    } catch {
      /* ignore */
    }
  });
}

async function register(page: Page, username: string) {
  seedLocalStorage(page);
  await page.goto("/login");
  await page.getByRole("tab", { name: "注册" }).click();
  await page.fill("#vnss-username", username);
  await page.fill("#vnss-email", `${username}@e2email.example.net`);
  await page.fill("#vnss-password", PASSWORD);
  await page.fill("#vnss-confirm", PASSWORD);
  await page.getByRole("button", { name: "注册并发送验证邮件" }).click();
  // 等待注册接口返回（成功→checkEmail 模式出现「返回登录」；失败→页面停留并显示错误）
  const regResp = page.waitForResponse(
    (r) => r.url().includes("/auth/register") && r.request().method() === "POST",
    { timeout: 15_000 }
  );
  await regResp;
  await page.getByRole("button", { name: "返回登录" }).click();
  await page.fill("#vnss-username", username);
  await page.fill("#vnss-password", PASSWORD);
  await page.getByRole("button", { name: "开始创作" }).click();
}

/** New users land on the empty library — create a blank project to reach the editor. */
async function createBlankProject(page: Page) {
  await dismissTour(page);
  await page.getByRole("button", { name: "空白剧本" }).click();
  await page.getByRole("textbox", { name: "新剧本标题" }).fill("E2E 测试剧本");
  await page.getByRole("button", { name: "创建" }).click();
  await dismissTour(page);
}

test("注册 → 登录 → 建项目 → 写作 → 保存 → 导出", async ({ page }) => {
  const username = randomName("e2e_");
  await register(page, username);

  await createBlankProject(page);
  await expect(page.getByLabel("作品标题")).toHaveValue("E2E 测试剧本", {
    timeout: 15_000,
  });

  const editor = page.getByTestId("script-editor");
  await expect(editor).toBeVisible();
  const draft = [
    "夏夜，雨声在空荡荡的站厅里回荡。",
    "",
    "夏言：末班车已经开走了……",
  ].join("\n");
  await editor.fill(draft);
  await expect(editor).toHaveValue(draft);

  await page.waitForTimeout(2500);
  await page.reload();
  await dismissTour(page);
  const after = page.getByTestId("script-editor");
  await expect(after).toHaveValue(/站厅里回荡/, { timeout: 15_000 });
  await expect(after).toHaveValue(/末班车已经开走了/);

  await page.getByRole("tab", { name: "RPY" }).click();
  await page.getByRole("button", { name: "根据剧本生成" }).click();
  await expect(page.getByTestId("script-editor")).toHaveValue(/末班车/, {
    timeout: 30_000,
  });

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 .rpy" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.rpy$/);
});

test("登出后回到登录页，旧账号可重新登录", async ({ page }) => {
  const username = randomName("e2e_relogin_");
  await register(page, username);
  await createBlankProject(page);
  await expect(page.getByLabel("作品标题")).toHaveValue("E2E 测试剧本", {
    timeout: 15_000,
  });

  await page.getByRole("button", { name: "退出" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.fill("#vnss-username", username);
  await page.fill("#vnss-password", PASSWORD);
  await page.getByRole("button", { name: "开始创作" }).click();
  await expect(page.getByLabel("作品标题")).toBeVisible({ timeout: 15_000 });
});

test("协作入口：成员页签可打开", async ({ page }) => {
  const username = randomName("e2e_collab_");
  await register(page, username);
  await createBlankProject(page);
  await expect(page.getByLabel("作品标题")).toHaveValue("E2E 测试剧本", {
    timeout: 15_000,
  });

  await page.getByRole("button", { name: "协作" }).click();
  await expect(page.getByText("成员", { exact: true })).toBeVisible();
  await expect(page.getByText(username)).toBeVisible();
});
