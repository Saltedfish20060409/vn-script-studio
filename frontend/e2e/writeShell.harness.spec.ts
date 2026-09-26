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
    await page.getByRole("menuitem", { name: "结构分析", exact: true }).click();
    await expect(page.getByTestId("harness-log")).toContainText("analysis");
  });

  test("工具条自己仍然可点（提升层级的初衷不能被改回去）", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn");
    await page.getByRole("button", { name: "查找 / 替换" }).click();
    await expect(page.getByTestId("harness-log")).toContainText("find");
  });

  test("文件菜单保持精简：项目二级页收进分组，能下钻也能返回", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn");
    await page.locator("summary", { hasText: "文件" }).first().click();

    // 第一层不该再摊平出全部项目页（摊平是 19 项、要滚）
    const first = await page.evaluate(
      () =>
        document.querySelectorAll('details[open] [role="menuitem"]').length
    );
    expect(first, `文件菜单第一层有 ${first} 项，太多了`).toBeLessThanOrEqual(12);

    await page.getByTestId("file-group-project").click();
    await expect(page.getByRole("menuitem", { name: "稿件体检" })).toBeVisible();
    await page.getByTestId("file-group-back").click();
    await expect(page.getByTestId("file-group-project")).toBeVisible();
  });

  test("键盘：Alt+V 打开视图菜单、↑↓ 移动焦点、Esc 关闭", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn");
    // 必须先等组件挂载好再发按键：快捷键监听器是 React 挂载后才注册的，
    // 抢在挂载前按就等于按在空气上（这条竞态让本用例一度"时好时坏"）。
    await expect(page.getByTestId("studio-ribbon")).toBeVisible();
    const panel = page.locator('details[open] [role="menu"]');

    await page.keyboard.press("Alt+v");
    await expect(panel).toBeVisible();
    // 打开后焦点应当已经在第一项上（否则键盘用户还得再 Tab 一圈）
    await expect(page.getByRole("menuitem", { name: "设定" })).toBeFocused();

    await page.keyboard.press("ArrowDown");
    await expect(page.getByRole("menuitem", { name: "角色工坊" })).toBeFocused();
    await page.keyboard.press("End");
    await expect(page.getByRole("menuitem", { name: "结构分析" })).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
  });

  test("四个菜单都有 Alt 助记键，且各开各的", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn");
    await expect(page.getByTestId("studio-ribbon")).toBeVisible();
    const panel = page.locator('details[open] [role="menu"]');
    // 每个键都要开出**它自己**那个菜单（顺便排除"上一个没关、看起来像开了"的假通过）
    for (const [key, ownItem] of [
      ["Alt+f", "新建剧本"],
      ["Alt+e", "剧本"],
      ["Alt+r", "AI 责编"],
      ["Alt+v", "设定"],
    ] as const) {
      await page.keyboard.press(key);
      await expect(panel, `按 ${key} 后应当有菜单打开`).toBeVisible();
      await expect(
        page.getByRole("menuitem", { name: ownItem, exact: false }),
        `按 ${key} 后应当能看到「${ownItem}」`
      ).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(panel, `Esc 后 ${key} 的菜单应当关掉`).toHaveCount(0);
    }
  });
});

/**
 * 抽屉（设定 / 角色工坊 / 地图 / 剧情状态 / 结构分析）被**整宽的工具条**横着压住。
 *
 * 这是用户实测报的问题，成因是 z-index 排错了：抽屉 45 / 文件二级页 40，
 * 而稿纸工具条是 70，且工具条整宽——于是它横着盖在右侧抽屉的上部，
 * 半透明底又把抽屉里的字透出来。这组守卫钉住两件事：
 * ① 抽屉最上面那一块必须由抽屉自己接管（命中测试）；
 * ② 抽屉与菜单下拉的底色必须**不透明**（`--panel-bg` 在自定义壁纸下是半透明的，
 *    直接拿它当背景就会透出后面的字——用户也报了这一点）。
 */
const ALPHA_OF = (raw: string): number => {
  if (!raw || raw === "transparent") return 0;
  // color-mix() 的 computed 值在 Chrome 里是 color(srgb r g b / a)（分量 0~1）
  const srgb = raw.match(/color\(srgb\s+[\d.]+\s+[\d.]+\s+[\d.]+\s*(?:\/\s*([\d.]+))?\)/);
  if (srgb) return srgb[1] === undefined ? 1 : parseFloat(srgb[1]);
  const m = raw.match(/rgba?\(([^)]+)\)/);
  if (!m) return -1; // 未知格式：让断言直接失败，别假装通过
  const parts = m[1].split(",").map((v) => parseFloat(v.trim()));
  return parts.length > 3 ? parts[3] : 1;
};

test.describe("视图抽屉的层叠与不透明", () => {
  /**
   * 打开"自定义壁纸"模式。
   *
   * 为什么必须**在壁纸模式下**验不透明：日间/夜间主题的 `--panel-bg` 本来就是不透明的
   * （92% / 90% 实色混合），所以不挂壁纸时这两条断言会"通过得毫无意义"。
   * 半透明只出现在 `html[data-custom-bg="1"]` 下——`--panel-bg` 变成 52% 透明
   * 或 `rgba(18,8,12,.55)`，那正是用户报"透出后面的字"的场景。
   */
  async function useWallpaper(page: Page) {
    await page.evaluate(() => {
      document.documentElement.dataset.customBg = "1";
      document.documentElement.dataset.panelGlass = "mist";
    });
  }

  test("抽屉上部没有被工具条压住（点得到、看得见）", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn&drawer=1");
    await expect(page.getByTestId("view-drawer")).toBeVisible();

    const probe = await page.evaluate(() => {
      const el = document.querySelector<HTMLElement>('[data-testid="view-drawer"]')!;
      const b = el.getBoundingClientRect();
      // 标题栏以内：这一带正落在整宽工具条的横带上
      const x = b.left + b.width / 2;
      const y = b.top + 12;
      const hit = document.elementFromPoint(x, y);
      return {
        y: Math.round(y),
        inside: Boolean(hit && (hit === el || el.contains(hit))),
        by: hit
          ? `${hit.tagName}.${String((hit as HTMLElement).className).slice(0, 34)}`
          : "(none)",
      };
    });
    expect(probe.inside, `抽屉在 y=${probe.y} 被 ${probe.by} 盖住了`).toBe(true);
  });

  test("抽屉正文顶部也没有被盖住", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn&drawer=1");
    const probe = await page.evaluate(() => {
      const drawer = document.querySelector<HTMLElement>('[data-testid="view-drawer"]')!;
      const content = document.querySelector<HTMLElement>('[data-testid="drawer-content"]')!;
      const cb = content.getBoundingClientRect();
      const hit = document.elementFromPoint(cb.left + 8, cb.top + 8);
      return {
        inside: Boolean(hit && drawer.contains(hit)),
        by: hit
          ? `${hit.tagName}.${String((hit as HTMLElement).className).slice(0, 34)}`
          : "(none)",
      };
    });
    expect(probe.inside, `抽屉正文被 ${probe.by} 盖住了`).toBe(true);
  });

  test("抽屉底色不透明（含自定义壁纸模式）", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn&drawer=1");
    await useWallpaper(page);
    const raw = await page
      .getByTestId("view-drawer")
      .evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(ALPHA_OF(raw), `壁纸模式下抽屉底色 alpha=${raw}`).toBe(1);
    // 顺带确认真的进了壁纸模式（否则上面那条等于没测）
    expect(await page.evaluate(() => document.documentElement.dataset.customBg)).toBe("1");
  });

  test("菜单下拉底色不透明（含自定义壁纸模式）", async ({ page }) => {
    await page.goto("/e2e/writeShell.html?genre=vn");
    await useWallpaper(page);
    for (const menu of MENUS) {
      const summary = page.locator("summary", { hasText: menu }).first();
      await summary.click();
      const panel = page.locator('details[open] [role="menu"]');
      await expect(panel).toBeVisible();
      const raw = await panel.evaluate((el) => getComputedStyle(el).backgroundColor);
      expect(ALPHA_OF(raw), `「${menu}」下拉底色 alpha=${raw}`).toBe(1);
      await page.keyboard.press("Escape");
      await summary.click();
    }
  });
});
