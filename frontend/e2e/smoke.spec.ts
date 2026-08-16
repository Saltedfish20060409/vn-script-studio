import { expect, test, type Page } from "@playwright/test";

/**
 * End-to-end smoke tests — the critical user journey:
 * register → login → create project → write a script → save → export .rpy.
 *
 * These run against a real backend + built frontend (see playwright.config.ts).
 * Each test uses a unique username so parallel/serial reruns stay isolated.
 */

const PASSWORD = "e2e-secret-123";

function randomName(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
}

async function register(page: Page, username: string) {
  await page.goto("/login");
  await page.getByRole("tab", { name: "注册" }).click();
  await page.fill("#vnss-username", username);
  await page.fill("#vnss-password", PASSWORD);
  await page.fill("#vnss-confirm", PASSWORD);
  await page.getByRole("button", { name: "注册并进入" }).click();
}

/** New users land on the empty library — create a blank project to reach the editor. */
async function createBlankProject(page: Page) {
  await page.getByRole("button", { name: "空白剧本" }).click();
  await page
    .getByRole("textbox", { name: "新剧本标题" })
    .fill("E2E 测试剧本");
  await page.getByRole("button", { name: "创建" }).click();
}

test("注册 → 登录 → 建项目 → 写作 → 保存 → 导出", async ({ page }) => {
  const username = randomName("e2e_");
  await register(page, username);

  // New user → empty library → create a blank project (lands in script editor).
  await createBlankProject(page);
  await expect(page.getByLabel("作品标题")).toHaveValue("E2E 测试剧本", {
    timeout: 15_000,
  });

  // Write a script draft (script editor is the visible textarea on load).
  const editor = page.getByTestId("script-editor");
  await expect(editor).toBeVisible();
  const draft = [
    "label start:",
    "",
    "scene bg station_night",
    "夏夜，雨声在空荡荡的站厅里回荡。",
    "",
    "夏言 \"末班车已经开走了……\"",
  ].join("\n");
  await editor.fill(draft);
  await expect(editor).toHaveValue(draft);

  // Autosave is debounced (~800ms) — wait for it to flush, then reload to
  // prove the draft persisted to the backend. Round-tripping through the
  // block codec may normalize blank lines, so assert key content instead of
  // exact equality.
  await page.waitForTimeout(2500);
  await page.reload();
  const after = page.getByTestId("script-editor");
  await expect(after).toHaveValue(/scene bg station_night/, { timeout: 15_000 });
  await expect(after).toHaveValue(/末班车已经开走了/);

  // Export .rpy: top bar button navigates to the export tab and generates.
  await page.getByRole("button", { name: "导出 .rpy" }).click();
  await expect(page.getByRole("button", { name: /下载 .rpy/ })).toBeVisible({
    timeout: 30_000,
  });
});

test("登出后回到登录页，旧账号可重新登录", async ({ page }) => {
  const username = randomName("e2e_relogin_");
  await register(page, username);
  await createBlankProject(page);
  await expect(page.getByLabel("作品标题")).toHaveValue("E2E 测试剧本", {
    timeout: 15_000,
  });

  // Logout via top bar.
  await page.getByRole("button", { name: "退出" }).click();
  await expect(page).toHaveURL(/\/login/);

  // Login again with the same credentials.
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
