import { expect, test, type Page } from "@playwright/test";
import { openFilePage, openViewPanel } from "./nav";

/**
 * 关系图体检（机器先查一遍）。
 *
 * 一致性排查原来是"让模型读一遍再自己比"，但图上有一批问题是机器一眼可判的：
 * A 是 B 的父亲、B 又是 A 的父亲，这种矛盾不该花 token 也不该漏。
 * 这个文件覆盖的是**端到端**：在界面上真加出两条互指的关系，卡片要当场报矛盾。
 *
 * 规则本身的分支在 lib/graphAudit.test.ts 里逐条覆盖（19 条），这里只验接线。
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

async function openRelationsSub(page: Page) {
  // 结构分析现在是右侧抽屉（文件菜单里那条入口已去掉；两处渲染的是同一个 AnalysisPanels）
  await openViewPanel(page, "结构分析");
  const backstage = page.getByTestId("view-drawer");
  await backstage.getByRole("button", { name: "角色关系", exact: true }).first().click();
  await expect(backstage.getByLabel("角色 A")).toBeVisible({ timeout: 20_000 });
}

/** 新账号自带示例剧本（里面已经有一条词表外的关系 → 体检卡片本来就会出现），
 *  所以这里先建一个真正干净的空剧本，才能验「干净时不显示卡片」。 */
async function createBlankProject(page: Page) {
  await openFilePage(page, "打开（剧本库）");
  const backstage = page.getByTestId("file-backstage");
  const blank = backstage.getByRole("button", { name: "空白剧本" });
  await blank.waitFor({ state: "visible", timeout: 15_000 });
  await blank.click();
  // 标题输入框的 aria-label 随体裁变（「重命名剧本 / 重命名小说」），取第一个文本框即可：
  // 这条用例要的是"建一个干净的空剧本"，不该绑死某个标签写法。
  await backstage.getByRole("textbox").first().fill("E2E 关系图体检");
  await backstage.getByRole("button", { name: "创建" }).click();
  await expect(page.getByLabel("作品标题")).toHaveValue("E2E 关系图体检", { timeout: 15_000 });
}

/** 加两个角色卡（默认名字是 角色1 / 角色2，所以下拉里不重名）。 */
async function addTwoCharacters(page: Page) {
  await openViewPanel(page, "设定");
  const drawer = page.getByTestId("view-drawer");
  await drawer.getByRole("button", { name: "角色卡", exact: true }).first().click();
  await drawer.getByRole("button", { name: "添加角色" }).click();
  await drawer.getByRole("button", { name: "添加角色" }).click();
  await expect(drawer.locator('input[value="角色2"]')).toBeVisible({ timeout: 20_000 });
}

/** 加一条 A —标签→ B 的关系。 */
async function addRelation(page: Page, from: string, label: string, to: string) {
  await page.getByLabel("角色 A").selectOption({ label: from });
  await page.getByLabel("关系标签").fill(label);
  await page.getByLabel("角色 B").selectOption({ label: to });
  await page.getByRole("button", { name: "添加关系" }).click();
}

test("关系图体检：互指的方向性关系当场报矛盾，零 token", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_graph_"));
  await createBlankProject(page);
  await openRelationsSub(page);

  // 干净的图不显示卡片（不制造噪音）
  await expect(page.getByTestId("graph-audit")).toBeHidden();

  await addTwoCharacters(page);
  await openRelationsSub(page);

  // 两个角色、零关系：还是没有可报的问题
  await expect(page.getByTestId("graph-audit")).toBeHidden();

  // 「A 是 B 的父亲」写一条
  await addRelation(page, "角色1", "父亲", "角色2");
  await expect(page.getByTestId("graph-audit")).toBeHidden();

  // 反过来再写一条 → 按「A 是 B 的父亲」的读法，这两条必有一条是错的
  await addRelation(page, "角色2", "父亲", "角色1");

  const card = page.getByTestId("graph-audit");
  await expect(card).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("graph-audit-counts")).toContainText("1 处矛盾");
  await expect(page.getByTestId("graph-audit-size")).toContainText("2 角色");

  // 明细里写清是哪两条、为什么矛盾
  await card.getByRole("button", { name: "看明细" }).click();
  const detail = page.getByTestId("graph-audit-detail");
  await expect(detail).toBeVisible();
  await expect(detail).toContainText("父亲");
  await expect(detail).toContainText("双向");

  // 删掉其中一条，卡片就消失（说明它是跟着图实时算的，不是一次性快照）
  await page
    .locator("li", { hasText: "—父亲→" })
    .first()
    .getByRole("button", { name: "删除" })
    .click();
  await expect(page.getByTestId("graph-audit")).toBeHidden({ timeout: 20_000 });
});
