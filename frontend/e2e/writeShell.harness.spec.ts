import { expect, test, type Page } from "@playwright/test";

/**
 * 写作页顶栏菜单必须**点得到**——下拉不能被下面的工具条盖住。
 *
 * 为什么专门守这一条：顶栏菜单的下拉是绝对定位；稿纸工具条
 * （`.toolbar`，剧本/RPY + 查找 + 语音那一条）带着 `position: relative; z-index: 70`
 * 和 `backdrop-filter`。两者谁在上面**不由 z-index 数字单独决定**，
 * 而取决于各自落在哪个层叠上下文里——纯读 CSS 很容易判错（本人就判错过一次）。
 * 所以这里在真浏览器里量：菜单项中心点的 `elementFromPoint` 必须是菜单项自己。
 */

const MENUS = ["文件", "开始", "审阅", "视图"] as const;

/** 打开某个菜单，逐项检查"中心点上最顶层的是不是它自己"。 */
async function probeMenu(page: Page, menu: string) {
  const summary = page.locator("summary", { hasText: menu }).first();
  await summary.click();
  // **必须按 details[open] 取面板**：四个面板都被渲染进 DOM，
  // 关闭的那些没有 `open` 属性、不参与绘制。第一版没加这个限定，
  // 量到的是**关闭状态**的面板里的项，于是把"本来就不该在那个位置被点到"
  // 当成了"被工具条盖住"——一次自己骗自己的假复现。
  const panel = page.locator('details[open] [role="menu"]');
  await expect(panel).toBeVisible();

  const probe = await page.evaluate(() => {
    const panel = document.querySelector<HTMLElement>('details[open] [role="menu"]');
    if (!panel) return { total: 0, covered: [] as string[], scrollable: false };
    const items = Array.from(
      panel.querySelectorAll<HTMLElement>('[role="menuitem"]')
    );
    const covered: string[] = [];
    for (const el of items) {
      // 面板有自己的 max-height + overflow:auto（下拉太长时本就该在里面滚）。
      // 所以要**先把项滚进可视区**再判定——否则量到的是"框外的项被下面的稿纸盖住"，
      // 那是滚动语义，不是遮挡（第一版就是这么误报的：见上面 details[open] 那段注释）。
      el.scrollIntoView({ block: "nearest" });
      const b = el.getBoundingClientRect();
      if (!b.height) continue;
      const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      const ok = Boolean(hit && (hit === el || el.contains(hit) || el.parentElement === hit));
      if (!ok) {
        covered.push(
          `${(el.textContent ?? "").trim()} 被 ${hit?.tagName}.${String(
            (hit as HTMLElement | null)?.className ?? ""
          ).slice(0, 30)} 盖住`
        );
      }
    }
    const scrollable = panel.scrollHeight > panel.clientHeight + 1;
    panel.scrollTop = 0;
    return { total: items.length, covered, scrollable };
  });

  await page.keyboard.press("Escape");
  await summary.click();
  return probe;
}

test.describe("写作页顶栏菜单", () => {
  for (const genre of ["vn", "novel"] as const) {
    for (const menu of MENUS) {
      test(`${genre} · 「${menu}」菜单的每一项都点得到`, async ({ page }) => {
        await page.goto(`/e2e/writeShell.html?genre=${genre}`);
        await expect(page.getByTestId("harness-paper")).toBeVisible();

        const probe = await probeMenu(page, menu);
        expect(probe.total, "菜单里应当有菜单项").toBeGreaterThan(0);
        expect(probe.covered, `「${menu}」里有项被别的元素盖住`).toEqual([]);
      });
    }
  }

  test("点菜单项真的能触发动作（不是被盖住后点了别处）", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn");
    await page.locator("summary", { hasText: "视图" }).first().click();
    await page.getByRole("menuitem", { name: "写作分析", exact: true }).click();
    await expect(page.getByTestId("harness-log")).toContainText("analysis");
  });

  test("工具条自己仍然可点（提升层级的初衷不能被改回去）", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn");
    await page.getByRole("button", { name: "查找 / 替换" }).click();
    await expect(page.getByTestId("harness-log")).toContainText("find");
  });
});
