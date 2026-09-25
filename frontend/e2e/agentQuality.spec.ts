import { expect, test, type Page } from "@playwright/test";
import { openViewPanel } from "./nav";

/**
 * 「让工具不输给裸聊」这一批的回归（真实前后端）。
 *
 * 测的是**接线**，不依赖模型输出质量：
 * ① 「资料」开关：取消勾选后，请求体里真的带上 exclude_sections（少喂资料）；
 * ② 标记批改的快捷反馈：点一下就把要求写进指令并发起新的处理请求（而不是让用户打字）；
 * ③ 「给我 3 版」走 candidates=3（多候选挑一版）。
 */

const PASSWORD = "e2e-secret-123";
const NEEDLE = "末班车";

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

async function selectText(page: Page, text: string) {
  const ok = await page.getByTestId("script-editor").evaluate((el, needle) => {
    const ta = el as HTMLTextAreaElement;
    const from = ta.value.indexOf(needle);
    if (from < 0) return false;
    ta.focus();
    ta.setSelectionRange(from, from + needle.length);
    ta.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true }));
    return true;
  }, text);
  expect(ok).toBe(true);
}

test("「资料」开关：取消勾选的资料块真的不进请求", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_sections_"));

  // 打开 AI 责编（右下角浮窗平时是收起的贴片：内容在 DOM 里但不可见）
  const toggle = page.getByTestId("agent-sections-toggle");
  if (!(await toggle.isVisible().catch(() => false))) {
    await page.getByTitle(/AI 责编/).first().click();
  }
  await expect(toggle).toBeVisible({ timeout: 20_000 });

  await toggle.click();
  await expect(page.getByTestId("agent-sections-menu")).toBeVisible();
  // 默认全带
  await expect(page.getByTestId("agent-section-bible")).toBeChecked();
  await page.getByTestId("agent-section-bible").uncheck();
  await expect(page.getByTestId("agent-sections-summary")).toContainText("本次不带");

  // 发一句话，断言请求里带上了 exclude_sections（waitForRequest 的断言收到的是请求本身）
  const posted = page.waitForRequest(
    (r) => r.url().includes("/agent/stream") && r.method() === "POST",
    { timeout: 30_000 }
  );
  const composer = page.getByPlaceholder(/用平常话说/).first();
  await composer.fill("在吗");
  await composer.press("Enter");
  const body = JSON.parse((await posted).postData() ?? "{}");
  expect(body.exclude_sections).toContain("bible");
});

test("约束体检：设定里写了互相冲突的要求就会被指出来", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_audit_"));

  // 视图 → 设定 → 世界观/大纲 子页，往「世界观」里写互相打架的要求
  await openViewPanel(page, "设定");
  const drawer = page.getByTestId("view-drawer");
  await drawer.getByRole("button", { name: /世界观/ }).first().click();
  const world = drawer.getByLabel(/世界观/);
  await expect(world).toBeVisible({ timeout: 20_000 });
  await world.fill("必须用第一人称叙述\n全知视角交代所有人的想法\n尽量短句");

  const card = page.getByTestId("constraint-audit");
  await expect(card).toBeVisible({ timeout: 20_000 });
  // 硬规则 1 条（必须用第一人称），软规则 1 条（尽量短句）
  await expect(page.getByTestId("constraint-audit-counts")).toContainText("硬规则 1");
  // 人称冲突要被指出来
  await expect(page.getByTestId("constraint-audit-conflicts")).toContainText("冲突");
  await card.getByRole("button", { name: "看明细" }).click();
  await expect(card).toContainText("必须用第一人称叙述");
});

test("免费档提示：用站内免费档时提示长任务建议配 Key", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_tier_"));

  const toggle = page.getByTestId("agent-sections-toggle");
  if (!(await toggle.isVisible().catch(() => false))) {
    await page.getByTitle(/AI 责编/).first().click();
  }
  await expect(toggle).toBeVisible({ timeout: 20_000 });

  const streamed = page.waitForResponse(
    (r) => r.url().includes("/agent/stream") && r.request().method() === "POST",
    { timeout: 120_000 }
  );
  const composer = page.getByPlaceholder(/用平常话说/).first();
  await composer.fill("在吗");
  await composer.press("Enter");
  await streamed;

  // 本地没配自己的 Key → 走站内免费档 → 应出现提示（含"设置 → 模型"的出口）
  await expect(page.getByTestId("agent-tier-hint")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("agent-tier-hint")).toContainText("免费档");
  await expect(page.getByTestId("agent-tier-hint")).toContainText("设置");
});

test("「证明它记得」：回复里带上本次依据的资料与摘录", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_evidence_"));

  const toggle = page.getByTestId("agent-sections-toggle");
  if (!(await toggle.isVisible().catch(() => false))) {
    await page.getByTitle(/AI 责编/).first().click();
  }
  await expect(toggle).toBeVisible({ timeout: 20_000 });

  // 发一句话，等流式响应回来（done 事件里带 contextMeta.includedDetails）
  const streamed = page.waitForResponse(
    (r) => r.url().includes("/agent/stream") && r.request().method() === "POST",
    { timeout: 120_000 }
  );
  const composer = page.getByPlaceholder(/用平常话说/).first();
  await composer.fill("接着写两句");
  await composer.press("Enter");
  const payload = await (await streamed).text();

  // 依据清单要有内容：标签 + 摘录（不是只有计数）
  expect(payload).toContain("includedDetails");
  expect(payload).toContain("当前章");
  // 界面上默认摆出「依据 N 项」
  await expect(page.getByTestId("agent-evidence")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("agent-evidence")).toContainText("依据");
});

test("快捷反馈与多候选：点一下就改指令重做，不必打字", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_quick_"));

  await selectText(page, NEEDLE);
  await page.keyboard.press("Control+m");
  await expect(page.getByTestId("mark-card")).toBeVisible();

  // 快捷反馈按钮在
  await expect(page.getByTestId("mark-card-quick-colder")).toBeVisible();

  // 点「再冷一点」→ 发起的请求里 instruction 应包含这句
  const posted = page.waitForRequest(
    (r) => r.url().includes("/marks/revise") && r.method() === "POST",
    { timeout: 30_000 }
  );
  await page.getByTestId("mark-card-quick-colder").click();
  const body = JSON.parse((await posted).postData() ?? "{}");
  expect(body.instruction).toContain("再冷一点");
  expect(body.quote).toBe(NEEDLE);

  // 「给我 3 版」→ 请求 candidates=3
  const multi = page.waitForRequest(
    (r) => r.url().includes("/marks/revise") && r.method() === "POST",
    { timeout: 30_000 }
  );
  await expect(page.getByTestId("mark-card-more")).toBeVisible();
  await page.getByTestId("mark-card-more").click();
  const multiBody = JSON.parse((await multi).postData() ?? "{}");
  expect(multiBody.candidates).toBe(3);
});
