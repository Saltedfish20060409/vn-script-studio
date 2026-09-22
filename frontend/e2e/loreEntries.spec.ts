import { expect, test, type Page } from "@playwright/test";

/**
 * 设定条目的两条新链路（对应宣传视频评论里的痛点）：
 * 1. 「写了一堆设定文档，AI 读不到」→ 直接选文件导入，切成条目；
 * 2. 「全是 AI 自己生成、编辑自由度太小」→ AI 只能提议，作者在待审列表里逐条接受。
 *
 * 第 2 条的「提议」需要真模型才会产生，所以这里把待审列表接口 **打桩**，
 * 验证的是前端契约：会不会显示、接受时有没有把 id 发对。
 * 后端真正落库的链路由 backend/tests/test_api_lore_inbox.py 用真库覆盖。
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

async function openEntriesSub(page: Page) {
  await page.getByRole("button", { name: "设定", exact: true }).first().click();
  await page.getByRole("button", { name: /^设定条目/ }).first().click();
  await expect(page.getByRole("button", { name: "批量导入" })).toBeVisible({ timeout: 20_000 });
}

/** 一份贴过来就会切错的"设定文档"：小标题 + 空行段落，一条写关键词一条不写。 */
const LORE_DOC = [
  "# 青云门",
  "关键词：青云、青云门",
  "东域正道之首，山门在青云山落霞峰，掌门玄真。",
  "",
  "# 夺魂案",
  "三年前夺魂案死七人，凶手至今未获，官府结案为意外。",
  "",
  "# 洗剑池",
  "后山洗剑池，水深三丈，池底有断剑。",
].join("\n");

test("设定文档导入：先预览再确认，触发词自动补上", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_lore_"));
  await openEntriesSub(page);

  await page.getByRole("button", { name: /批量导入/ }).click();
  await page.getByTestId("lore-import-file").setInputFiles({
    name: "设定集.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(LORE_DOC, "utf-8"),
  });

  // 先预览，不直接落库
  const preview = page.getByTestId("lore-import-preview");
  await expect(preview).toBeVisible({ timeout: 20_000 });
  await expect(preview).toContainText("识别到 3 条");
  // 写在第 2 段的「夺魂案」没写关键词行，但推荐词里应该有它自己
  await expect(preview).toContainText("夺魂案");

  // 第三条不要（预览里取消勾选）
  await page.getByLabel("导入第 3 条").uncheck();
  await expect(preview).toContainText("已取消 1 条");

  // 等的是**带这次改动**的那次 PUT（不是任意一次自动保存）
  const saved = page.waitForRequest(
    (r) =>
      r.url().includes("/projects/") &&
      r.method() === "PUT" &&
      (r.postData() ?? "").includes("青云门"),
    { timeout: 30_000 }
  );
  await page.getByTestId("lore-import-confirm").click();
  await expect(preview).toBeHidden();

  // 条目列表里出现两条，第三条没进来
  await expect(page.getByRole("button", { name: /^设定条目（2）/ })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.locator('input[value="青云门"]')).toBeVisible();
  await expect(page.locator('input[value="夺魂案"]')).toBeVisible();
  await expect(page.locator('input[value="洗剑池"]')).toHaveCount(0);

  // 触发词真的写进了保存请求：青云门带"青云"，夺魂案被自动补上了自己
  const body = JSON.parse((await saved).postData() ?? "{}");
  const entries = (body.loreEntries ?? body.data?.loreEntries ?? []) as Array<{
    title: string;
    keywords?: string[];
  }>;
  const qingyun = entries.find((e) => e.title === "青云门");
  const duohun = entries.find((e) => e.title === "夺魂案");
  expect(qingyun?.keywords ?? []).toContain("青云");
  expect(duohun?.keywords ?? []).toContain("夺魂案");
});

test("待审列表：AI 提议的设定条目要作者点了接受才进设定库", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_lore_review_"));

  const proposal = {
    id: "inbox-lore-1",
    kind: "lore_entry",
    payload: {
      title: "玄真",
      body: "青云门掌门，剑法冷厉，与主角父亲旧识。",
      keywords: ["玄真", "掌门"],
    },
    evidence: [{ source: "agent", quote: "附件第一节" }],
    status: "pending",
    dedupeKey: "lore:玄真",
    createdAt: new Date().toISOString(),
  };

  // 打桩待审列表：真提议要真模型，这里只验证前端契约
  await page.route("**/analysis/facts/inbox*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [proposal] }),
    });
  });

  let acceptedIds: string[] = [];
  await page.route("**/analysis/facts/accept", async (route) => {
    const body = JSON.parse(route.request().postData() ?? "{}");
    acceptedIds = body.ids ?? [];
    const projectRes = await route.fetch();
    const project = await projectRes.json();
    project.project.loreEntries = [
      { id: "le-1", title: "玄真", body: proposal.payload.body, keywords: ["玄真", "掌门"] },
    ];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(project),
    });
  });

  // 项目 → 结构分析（待审列表就在这里；AI 回复里也这么指路）
  await page.getByRole("button", { name: "项目", exact: true }).first().click();
  await page.getByRole("button", { name: "结构分析", exact: true }).first().click();
  const openBtn = page.getByRole("button", { name: /待审列表/ }).first();
  await expect(openBtn).toBeEnabled({ timeout: 20_000 });
  await openBtn.click();

  const loreSection = page.getByTestId("fact-review-lore");
  await expect(loreSection).toBeVisible();
  await expect(loreSection).toContainText("接受后才进设定库");
  await expect(loreSection).toContainText("玄真");
  await expect(loreSection).toContainText("触发词：玄真、掌门");

  await page.getByRole("button", { name: /接受所选/ }).click();
  await expect.poll(() => acceptedIds).toEqual(["inbox-lore-1"]);

  // 接受后这条真的出现在设定条目里
  await openEntriesSub(page);
  await expect(page.locator('input[value="玄真"]')).toBeVisible({ timeout: 20_000 });
});

/**
 * 实体链接：一条设定讲的是谁，说清楚之后检索就能沿边走一步——
 * 命中「青云门」会顺手带出掌门角色卡，反过来问这个角色也会带出这条设定。
 * 这里验的是前端链路：能不能关联、保存请求里有没有这条边、刷新后还在不在。
 * 上下文里真的多带了什么，由 backend/tests/test_lore_links.py 覆盖。
 */
test("设定条目关联角色：点一下建边，保存请求与刷新后都在", async ({ page }) => {
  // 注册 + 建边 + 等自动保存 + 刷新后复查，步骤比别的用例长，给三倍时间
  test.slow();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_lorelink_"));

  // 新账号自带的示例剧本里已经有「林夏」，直接拿它当关联目标
  await openEntriesSub(page);
  await page.getByRole("button", { name: "新增条目" }).click();
  await page.locator('input[placeholder*="条目标题"]').fill("青云门");
  await page.locator('input[placeholder^="如 青云"]').fill("青云、掌门");

  // 关联下拉里的分组是「角色 / 地点 / 章节」，标签用实体的显示名
  const linkSelect = page.locator('[data-testid^="lore-link-add-"]').first();
  await linkSelect.selectOption({ label: "角色：林夏" });

  // 关联后变成可以点掉的 chip，下拉里不再重复出现它
  const linkBox = page.locator('[data-testid^="lore-links-"]').first();
  await expect(linkBox.getByRole("button", { name: /林夏/ })).toBeVisible();
  await expect(linkSelect.locator('option[value="character::linxia"]')).toHaveCount(0);

  /** 从 PUT 请求体里取「青云门」这条设定的 links（键名与嵌套层级两种写法都兜住） */
  const linksOf = (raw: string) => {
    try {
      const body = JSON.parse(raw) as {
        loreEntries?: Array<{ title: string; links?: Array<{ toType: string; toId: string }> }>;
        data?: {
          loreEntries?: Array<{ title: string; links?: Array<{ toType: string; toId: string }> }>;
        };
      };
      const entries = body.loreEntries ?? body.data?.loreEntries ?? [];
      return entries.find((e) => e.title === "青云门")?.links ?? [];
    } catch {
      return [];
    }
  };

  // 保存请求里真的有这条边（等的是**带这次改动**的那次 PUT）
  const saved = page.waitForRequest(
    (r) =>
      r.method() === "PUT" &&
      r.url().includes("/projects/") &&
      linksOf(r.postData() ?? "").some((l) => l.toType === "character" && l.toId === "linxia"),
    { timeout: 30_000 }
  );
  // 触发一次保存（改个触发词最省事），然后确认那次请求带着 links
  await page.locator('input[placeholder^="如 青云"]').fill("青云、掌门、山门");
  await saved;

  // 刷新后还在 = 真的落了库，不是只留在内存里
  // （刷新后会恢复到刚才那一页——设定条目，所以这里等标题栏，不等写作页的编辑器）
  await page.reload();
  await expect(page.getByLabel("作品标题")).toBeVisible({ timeout: 40_000 });
  await openEntriesSub(page);
  await expect(page.locator('input[value="青云门"]')).toBeVisible({ timeout: 20_000 });
  await expect(
    page.locator('[data-testid^="lore-links-"]').first().getByRole("button", { name: /林夏/ })
  ).toBeVisible();

  // 点掉 chip：保存请求里这条边消失
  const removed = page.waitForRequest(
    (r) =>
      r.method() === "PUT" &&
      r.url().includes("/projects/") &&
      (r.postData() ?? "").includes("青云门") &&
      linksOf(r.postData() ?? "").length === 0,
    { timeout: 30_000 }
  );
  await page
    .locator('[data-testid^="lore-links-"]')
    .first()
    .getByRole("button", { name: /林夏/ })
    .click();
  await removed;
});
