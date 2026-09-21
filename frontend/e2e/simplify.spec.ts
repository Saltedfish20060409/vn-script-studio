import { expect, test, type Page } from "@playwright/test";

/**
 * 「降低复杂度」的回归测试 —— 全部是「什么时候让用户看到什么」，不是删功能。
 *
 * 四条底线：
 * 1. 新人第一屏不再是一段功能名长文，而是三个可点的动作；
 * 2. 项目页常用子页在前，长尾收进「更多」，但**一个都没少**；
 * 3. 停在长尾子页时「更多」自动展开（老用户不丢入口，刷新也不丢）；
 * 4. 「写作参考卡」不再和「设定条目」并列，但入口仍在。
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

async function gotoTab(page: Page, name: string) {
  const rail = page.locator('nav[aria-label="剧本篇章"]');
  await rail.getByRole("button", { name: new RegExp(name) }).click();
}

test("新人第一屏：没有功能名长文弹窗，只有三个可点的动作", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_simple_"));

  // 旧的四步长文弹窗已经删掉，不该再出现
  await expect(page.getByTestId("onboarding-overlay")).toHaveCount(0);

  // 三步清单在第一屏，而且每步都短、可点
  const checklist = page.getByRole("region", { name: "新手上手三步" });
  await expect(checklist).toBeVisible({ timeout: 20_000 });
  await expect(checklist).toContainText("三步上手");
  for (const label of ["让 AI 续写这一段", "生成可试玩的脚本", "导出 Word 存档"]) {
    await expect(checklist.getByRole("button", { name: new RegExp(label) })).toBeVisible();
  }

  // 清单确实在编辑区上方（不是藏在页面底部）
  const bar = await checklist.boundingBox();
  const editor = await page.getByTestId("script-editor").boundingBox();
  expect(bar && editor && bar.y < editor.y).toBe(true);

  // 删掉弹窗没有丢失「怎么写」这条关键信息：空编辑器的提示里就写着
  await expect(page.getByTestId("script-editor")).toHaveAttribute(
    "placeholder",
    /旁白直接写/
  );
});

test("项目页：「更多」能开也能关，长尾一个都没少", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_subs_"));
  await gotoTab(page, "项目");

  const more = page.getByTestId("project-subs-more");
  for (const label of ["剧本库", "写作统计", "结构分析", "导出"]) {
    await expect(page.getByRole("button", { name: label, exact: true }).first()).toBeVisible({
      timeout: 20_000,
    });
  }
  // 长尾默认不出现
  for (const label of ["本地化", "成员", "账本 / 摘要"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toHaveCount(0);
  }
  await expect(more).toHaveText(/更多/);

  // 展开：五个长尾都在，加上原来四个 = 9 个，一个没删；按钮变成「收起」
  await more.click();
  for (const label of ["账本 / 摘要", "素材", "本地化", "快照 / 分享", "成员"]) {
    await expect(page.getByRole("button", { name: label, exact: true }).first()).toBeVisible();
  }
  await expect(more).toHaveText(/收起/);

  // 关得掉：这就是曾经的 bug——展开后按钮被页签替换、点开就收不回来
  await more.click();
  await expect(more).toHaveText(/更多/);
  for (const label of ["本地化", "成员"]) {
    await expect(page.getByRole("button", { name: label, exact: true })).toHaveCount(0);
  }
  // 关掉之后原来的四个常用页签还在（没被连带藏起来）
  for (const label of ["剧本库", "写作统计", "结构分析", "导出"]) {
    await expect(page.getByRole("button", { name: label, exact: true }).first()).toBeVisible();
  }
});

test("停在长尾子页时：收起也看得见自己在哪，刷新后不丢", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_subs_keep_"));
  await gotoTab(page, "项目");

  const more = page.getByTestId("project-subs-more");
  await more.click();
  await page.getByRole("button", { name: "本地化", exact: true }).click();
  await expect(more).toHaveText(/收起/);

  // 手动收起：当前页那一个页签要留着（否则"看不见自己在哪"），其余长尾收起来
  await more.click();
  await expect(page.getByRole("button", { name: "本地化", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "成员", exact: true })).toHaveCount(0);

  // 刷新后仍停在长尾页，且当前页签依然看得见
  await page.reload();
  const active = page.getByRole("button", { name: "本地化", exact: true }).first();
  await expect(active).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("project-subs-more")).toHaveText(/更多/);
});

test("设定页：写作参考卡不再和设定条目并列，但入口还在", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_world_"));
  await gotoTab(page, "设定");

  for (const label of ["角色卡", "世界观 / 大纲", /^设定条目/]) {
    await expect(page.getByRole("button", { name: label }).first()).toBeVisible({
      timeout: 20_000,
    });
  }
  // 进阶的写作参考卡默认不并列出现
  await expect(page.getByRole("button", { name: "写作参考卡", exact: true })).toHaveCount(0);

  const more = page.getByTestId("world-subs-more");
  await more.click();
  const card = page.getByRole("button", { name: "写作参考卡", exact: true });
  await expect(card).toBeVisible();
  await expect(more).toHaveText(/收起/);

  // 点进去功能照旧（收藏参考卡 + 萌百搜索都还在）
  await card.click();
  await expect(page.getByPlaceholder(/搜索萌百/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/AI 写作时作为参考/)).toBeVisible();

  // 这里同样要能收回来：当前停在这一页，所以页签留着、按钮回到「更多」
  await more.click();
  await expect(more).toHaveText(/更多/);
  await expect(card).toBeVisible();
  await expect(page.getByPlaceholder(/搜索萌百/)).toBeVisible();
});

test("Agent 起手句：一下都不用打字，点一下就填好", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_starter_"));

  // 打开 AI 责编（平时贴边收起）
  const toggle = page.getByTestId("agent-sections-toggle");
  if (!(await toggle.isVisible().catch(() => false))) {
    await page.getByTitle(/AI 责编/).first().click();
  }
  await expect(toggle).toBeVisible({ timeout: 20_000 });

  const starters = page.getByTestId("agent-starters");
  await expect(starters).toBeVisible();

  // 点一个起手句 → 输入框里就有内容了（不用打字），而且**没有**被自动发送
  const composer = page.getByPlaceholder(/用平常话说/).first();
  await expect(composer).toHaveValue("");
  await page.getByRole("button", { name: "接着往下写一段" }).click();
  await expect(composer).toHaveValue("接着往下写一段");
  await expect(starters).toHaveCount(0);
});

test("Agent 面板里的文字要看得清：压在背景图上的行必须有不透明底", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_contrast_"));

  const toggle = page.getByTestId("agent-sections-toggle");
  if (!(await toggle.isVisible().catch(() => false))) {
    await page.getByTitle(/AI 责编/).first().click();
  }
  await expect(page.getByTestId("agent-starters")).toBeVisible({ timeout: 20_000 });

  /**
   * 线上问题：起手句和 ⚙ 资料 两行糊在背景图里几乎看不清。
   *
   * 为什么这里断言「底色不透明」而不是算对比度：面板底是**半透明渐变 + 背景图**
   * （AgentChat .messages / AgentFloat .panel），getComputedStyle 看不到图，
   * 算出来的对比度会虚高（实测旧样式反而"达标"6.96:1）。真正决定看得清与否的，
   * 是这几行背后有没有一层不透明底把图挡掉——那才是可确定性断言的东西。
   */
  const surfaces = await page.evaluate(() => {
    // color-mix() 的 computed 值在 Chrome 里是 `color(srgb r g b / a)`（分量 0~1），
    // 不是 rgba()；两种都要认，否则会一律解析成 0（踩过）。
    const alphaOf = (raw: string): number => {
      if (!raw || raw === "transparent") return 0;
      const c = raw.match(/color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:\/\s*([\d.]+))?\)/);
      if (c) return c[4] === undefined ? 1 : parseFloat(c[4]);
      const m = raw.match(/rgba?\(([^)]+)\)/);
      if (!m) return -1; // 未知格式：让断言直接失败，别假装通过
      const p = m[1].split(",").map((v) => parseFloat(v.trim()));
      return p.length > 3 ? p[3] : 1;
    };
    const bgAlpha = (sel: string) => {
      const el = document.querySelector(sel);
      return el ? alphaOf(getComputedStyle(el).backgroundColor) : -2;
    };
    const color = (sel: string) => {
      const el = document.querySelector(sel);
      return el ? getComputedStyle(el).color : "missing";
    };
    return {
      cardAlpha: bgAlpha('[data-testid="agent-starters"]'),
      chipAlpha: bgAlpha('[data-testid="agent-starters"] button'),
      hintColor: color('[data-testid="agent-starters"] span'),
      sectionColor: color('[data-testid="agent-sections-summary"]'),
    };
  });

  expect(surfaces.cardAlpha, "起手句卡片必须是实底（否则背景图透上来就糊了）").toBeGreaterThanOrEqual(0.9);
  expect(surfaces.chipAlpha, "起手句按钮不能是透明底").toBeGreaterThan(0);
  for (const [name, got] of [
    ["起手句提示", surfaces.hintColor],
    ["⚙ 资料 说明", surfaces.sectionColor],
  ] as const) {
    // 文字要用主墨色 --ink，不能用弱化的 --ink-soft（#4a5568 → rgb(74,85,104)）
    expect(got, `${name} 不该用弱化色`).not.toMatch(/^rgba?\(74,\s*85,\s*104/);
    expect(got).toBeTruthy();
  }

  // 自证：把旧样式（透明底）注回去，这个护栏必须能判不合格
  await page.addStyleTag({
    content: '[data-testid="agent-starters"] { background: transparent !important; border: none !important; }',
  });
  const afterInject = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="agent-starters"]');
    if (!el) return -2;
    const raw = getComputedStyle(el).backgroundColor;
    if (raw === "transparent") return 0;
    const m = raw.match(/rgba?\(([^)]+)\)/);
    if (!m) return -1;
    const p = m[1].split(",").map((v) => parseFloat(v.trim()));
    return p.length > 3 ? p[3] : 1;
  });
  expect(afterInject, "护栏失效：注入透明底后仍判合格").toBeLessThan(0.9);
});
