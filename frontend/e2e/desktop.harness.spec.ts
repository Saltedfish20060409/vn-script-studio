import { expect, test, type Page } from "@playwright/test";

/**
 * 桌面视图的真实浏览器回归测试（组件台，无需后端）。
 *
 * 覆盖的都是"单元测试抓不到、但用户一眼能看出坏了"的行为：
 * 1. 图标落在固定座位上（不是自由坐标），拖动会换座位；
 * 2. **剧本窗口打开时，下面的工作台仍然点得动** —— 这条是真实 bug 的回归
 *    （桌面层是 fixed + inset:0，不做事件穿透就会把整屏点击都吃掉，只剩滚轮能用）；
 * 3. 双击剧本 → 打开的是**这个剧本**的工作台窗口，标题是剧本名（桌面没有"剧本编辑器"软件）；
 * 4. 右键菜单：剧本图标上是"打开/重命名/复制/删除"，空白处是"新建/整理/剧本库"；
 * 5. 剧本多于 6 个时有「更多剧本」入口，点了打开剧本库；
 * 6. 开始菜单里的「排列图标」把图标排回默认顺序（只动图标、不动窗口）；
 * 7. 键盘可操作（方向键移动、Enter 打开、F2 重命名、Delete 删除）；
 * 8. 一次性小抄：第一次进桌面出现、关掉不再出现、打开剧本窗口时不出现。
 */

const HARNESS = "/e2e/harness.html";

/**
 * 打开组件台。默认状态就是"第一次进来"：小抄会出现（它在右上角，不挡左列的图标），
 * 需要它已读的用例自己点「知道了」或往 localStorage 写标记。
 */
async function openHarness(page: Page, query = "") {
  await page.goto(HARNESS + query);
  await expect(page.getByTestId("desktop-view")).toBeVisible();
}

/** 图标当前位置（页面坐标），用来验证座位与拖动 */
async function iconBox(page: Page, name: string | RegExp) {
  const box = await page.getByRole("listitem", { name }).boundingBox();
  if (!box) throw new Error(`图标不可见：${name}`);
  return box;
}

test("桌面只把剧本和应用摆成固定座位（列优先），不重叠", async ({ page }) => {
  await openHarness(page);

  const first = await iconBox(page, "雨夜站台");
  const second = await iconBox(page, "九幽诀");
  // 同一个 x（同一列）、自上而下排开：这就是"固定座位"
  expect(Math.round(second.x)).toBe(Math.round(first.x));
  expect(second.y).toBeGreaterThan(first.y);

  // 任何两个图标都不重叠
  const labels = ["雨夜站台", "九幽诀", "夏日回声", "新建剧本", "AI 责编"];
  const boxes = [];
  for (const label of labels) boxes.push(await iconBox(page, label));
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i];
      const b = boxes[j];
      const overlap =
        a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
      expect(overlap, `${labels[i]} 与 ${labels[j]} 叠在一起了`).toBe(false);
    }
  }
});

test("拖动图标 → 换到最近的座位，松手自动对齐", async ({ page }) => {
  await openHarness(page);

  const before = await iconBox(page, "夏日回声");
  const target = await iconBox(page, "新建剧本");
  // 把「夏日回声」拖到「新建剧本」的座位上
  await page.mouse.move(before.x + before.width / 2, before.y + 20);
  await page.mouse.down();
  await page.mouse.move(target.x + target.width / 2, target.y + 20, { steps: 12 });
  await page.mouse.up();

  const moved = await iconBox(page, "夏日回声");
  // 落点是对齐到座位网格的（与目标座位同一行同一列）
  expect(Math.round(moved.x)).toBe(Math.round(target.x));
  expect(Math.abs(moved.y - target.y)).toBeLessThanOrEqual(2);
  // 被占座位的图标没被挤没，只是换到了别的地方
  await expect(page.getByRole("listitem", { name: "新建剧本" })).toBeVisible();
});

test("单击不触发拖动（图标不会抖），双击才打开剧本", async ({ page }) => {
  await openHarness(page);

  const icon = page.getByRole("listitem", { name: "九幽诀" });
  await icon.click();
  await expect(page.getByTestId("fake-workbench")).toHaveCount(0);

  await icon.dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("desktop-script-window")).toContainText("九幽诀");
  // 打开的是这个剧本自己的工作台（传对了 id）
  await expect(page.getByTestId("fake-workbench")).toContainText("九幽诀");
  // 桌面上没有"剧本编辑器"这个软件
  await expect(page.getByTestId("desktop-view")).not.toContainText("剧本编辑器");
});

test("剧本窗口打开时，下面的工作台仍然点得动、滚得动（桌面层必须事件穿透）", async ({
  page,
}) => {
  await openHarness(page);
  await page.getByRole("listitem", { name: "九幽诀" }).dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();

  // ① 鼠标点得动工作台里的按钮（以前桌面层把整屏点击吃掉了，只有滚轮有反应）
  await page.getByTestId("wb-button").click();
  await page.getByTestId("wb-button").click();
  await expect(page.getByTestId("wb-hits")).toHaveText("2");

  // ② 滚轮滚的是工作台自己，不是整个文档（文档一滚，工作台就跑到标题栏下面去了）
  const docBefore = await page.evaluate(() => window.scrollY);
  await page.mouse.move(680, 400);
  await page.mouse.wheel(0, 600);
  await expect
    .poll(() => page.getByTestId("fake-workbench").evaluate((el) => el.scrollTop))
    .toBeGreaterThan(0);
  expect(await page.evaluate(() => window.scrollY)).toBe(docBefore);

  // ③ 任务栏与标题栏仍然可点
  await page.getByRole("button", { name: "开始" }).click();
  await expect(page.getByRole("menuitem", { name: /切换为工作台视图/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menuitem", { name: /切换为工作台视图/ })).toHaveCount(0);
});

test("右键剧本图标有打开/重命名/复制/删除，点了会执行", async ({ page }) => {
  await openHarness(page);

  await page.getByRole("listitem", { name: "夏日回声" }).click({ button: "right" });
  const menu = page.getByTestId("desktop-context-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem")).toHaveText(["打开", "重命名…", "复制一份", "删除…"]);

  await menu.getByRole("menuitem", { name: "重命名…" }).click();
  await expect(menu).toHaveCount(0);
  await expect(page.getByTestId("harness-log")).toContainText("rename:p3");
});

test("右键空白处有新建/排列图标/打开剧本库", async ({ page }) => {
  await openHarness(page);

  await page.mouse.click(700, 420, { button: "right" });
  const menu = page.getByTestId("desktop-context-menu");
  await expect(menu.getByRole("menuitem", { name: /新建剧本/ })).toBeVisible();

  await menu.getByRole("menuitem", { name: /打开剧本库/ }).click();
  await expect(page.getByTestId("library-window")).toBeVisible();
});

test("剧本多于 6 个时出现「更多剧本」，双击打开剧本库", async ({ page }) => {
  await openHarness(page, "?many=1");

  const more = page.getByRole("listitem", { name: /更多剧本（9）/ });
  await expect(more).toBeVisible();
  // 桌面上只摆前 6 个剧本
  await expect(page.getByRole("listitem", { name: "长篇1" })).toBeVisible();
  await expect(page.getByRole("listitem", { name: "长篇7" })).toHaveCount(0);

  await more.dblclick();
  await expect(page.getByTestId("library-window")).toBeVisible();
});

test("开始菜单里能直接跳到这个剧本的设定 / 角色工坊 / 地图 / 剧情状态", async ({ page }) => {
  await openHarness(page);

  await page.getByRole("button", { name: "开始" }).click();
  const menu = page.getByRole("menu");
  // 桌面视角下这些篇章在剧本窗口里，开始菜单给一条直达路（不用先双击再找标签）
  await expect(menu.getByRole("menuitem", { name: "设定" })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "角色工坊" })).toBeVisible();

  await menu.getByRole("menuitem", { name: "地图" }).click();
  // 剧本窗口被打开，并且停在地图那一页
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("wb-tab")).toHaveText("当前篇章：map");
  await expect(page.getByTestId("harness-log")).toContainText("tab:map");
});

test("底部音乐条足够薄（贴底常驻，越薄越不挡写作）", async ({ page }) => {
  await page.goto(HARNESS + "?music=1");
  const bar = page.getByTestId("music-bar");
  await expect(bar).toBeVisible();
  const box = await bar.boundingBox();
  // 之前是 38px 按钮 + 0.45rem 内边距 ≈ 54px，现在 32px 按钮 + 0.28rem ≈ 43px
  expect(box?.height ?? 999).toBeLessThanOrEqual(48);
  // 但按钮仍然点得着（别为了薄把点击目标做没了）
  const play = await bar.locator('button[title="播放"], button[title="暂停"]').boundingBox();
  expect(play?.height ?? 0).toBeGreaterThanOrEqual(30);
});

test("开始菜单：系统项里有「排列图标」，点了回到默认顺序", async ({ page }) => {
  await openHarness(page);

  // 先摆乱一个图标
  const before = await iconBox(page, "夏日回声");
  const target = await iconBox(page, "新建剧本");
  await page.mouse.move(before.x + before.width / 2, before.y + 20);
  await page.mouse.down();
  await page.mouse.move(target.x + target.width / 2, target.y + 20, { steps: 10 });
  await page.mouse.up();

  await page.getByRole("button", { name: "开始" }).click();
  await page.getByRole("menuitem", { name: /排列图标/ }).click();

  // 回到默认座位：第 3 个剧本图标回到第一列第三个
  const tidy = await iconBox(page, "夏日回声");
  const first = await iconBox(page, "雨夜站台");
  expect(Math.round(tidy.x)).toBe(Math.round(first.x));
  expect(tidy.y).toBeGreaterThan(first.y);
});

test("键盘就能操作桌面：方向键移动、Enter 打开、F2 重命名、Delete 删除", async ({ page }) => {
  await openHarness(page, "?many=1");

  // 焦点落到第一个剧本图标（长篇1 = 第 0 个座位）
  await page.getByRole("listitem", { name: "长篇1" }).focus();
  // ↓ 走到同一列的第二个
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("listitem", { name: "长篇2" })).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(page.getByRole("listitem", { name: "长篇1" })).toBeFocused();
  // → 换列：6 个座位一列，第 0 个 → 第 6 个（第二列第一行 = 新建剧本）
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("listitem", { name: "新建剧本" })).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("listitem", { name: "长篇1" })).toBeFocused();

  // F2 = 重命名，Delete = 删除（都打到 StudioApp 的回调上）
  await page.keyboard.press("F2");
  await expect(page.getByTestId("harness-log")).toContainText("rename:q0");
  await page.keyboard.press("Delete");
  await expect(page.getByTestId("harness-log")).toContainText("delete:q0");

  // Enter = 打开这个剧本
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("harness-log")).toContainText("open:q0");
});

test("键盘上下不跨列（单列布局里按 → 不会乱跳）", async ({ page }) => {
  await openHarness(page);
  await page.getByRole("listitem", { name: "夏日回声" }).focus();
  // 只有一个剧本列，右边没有座位 → 焦点不动
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("listitem", { name: "夏日回声" })).toBeFocused();
});

test("一次性小抄：第一次进桌面出现，点「知道了」后不再出现", async ({ page }) => {
  await openHarness(page);

  const tips = page.getByTestId("desktop-tips");
  await expect(tips).toBeVisible();
  await expect(tips).toContainText("双击");
  await expect(tips).toContainText("右键");
  await expect(tips).toContainText("关掉所有窗口");

  await page.getByTestId("desktop-tips-close").click();
  await expect(tips).toHaveCount(0);

  // 关掉 = 记住，刷新后不再出现
  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible();
  await expect(page.getByTestId("desktop-tips")).toHaveCount(0);
});

test("小抄不挡刚打开的剧本窗口（打开窗口时自动收起）", async ({ page }) => {
  await openHarness(page);
  await expect(page.getByTestId("desktop-tips")).toBeVisible();

  await page.getByRole("listitem", { name: "九幽诀" }).dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("desktop-tips")).toHaveCount(0);
});

test("剧本图标带章数角标与进度提示；「继续写作」一键回到上次那一章", async ({ page }) => {
  await openHarness(page);

  // ① 角标：有章数就显示，0 章显示"空"
  await expect(page.getByTestId("icon-badge-project:p1")).toHaveText("12 章");
  await expect(page.getByTestId("icon-badge-project:p2")).toHaveText("空");
  // 没有章数信息就不画角标（别显示成 0 章）
  await expect(page.getByTestId("icon-badge-project:p3")).toHaveCount(0);

  // ② 提示里能看到"共 N 章 · 最后修改 …"
  const hint = await page.getByRole("listitem", { name: "雨夜站台" }).getAttribute("title");
  expect(hint).toContain("共 12 章");
  expect(hint).toContain("最后修改");

  // ③ 继续写作：写着上次的章节名，点了直接回到那个剧本的窗口
  const resume = page.getByTestId("desktop-resume");
  await expect(resume).toBeVisible();
  await expect(resume).toContainText("第 3 章 · 夜雨");
  await resume.click();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("harness-log")).toContainText("resume");
  // 窗口开着时就不该再显示"继续写作"（你已经在那了）
  await expect(page.getByTestId("desktop-resume")).toHaveCount(0);
});

test("任务栏常驻「工作台」出口（迷路了不用翻开始菜单）", async ({ page }) => {
  await openHarness(page);
  const exit = page.getByTestId("desktop-to-studio");
  await expect(exit).toBeVisible();
  await exit.click();
  await expect(page.getByTestId("harness-log")).toContainText("studio");
});

test("两条收拾桌面的动作各管一件事：排列图标只动图标，关掉所有窗口只关窗口", async ({
  page,
}) => {
  await openHarness(page);

  // 先开一个应用窗口（位置会被记住），再摆乱一个图标
  await page.getByRole("listitem", { name: "AI 责编" }).dblclick();
  await expect(page.getByTestId("desktop-window-agent")).toBeVisible();
  const before = await iconBox(page, "夏日回声");
  const target = await iconBox(page, "新建剧本");
  await page.mouse.move(before.x + before.width / 2, before.y + 20);
  await page.mouse.down();
  await page.mouse.move(target.x + target.width / 2, target.y + 20, { steps: 10 });
  await page.mouse.up();

  // ① 排列图标：图标回到默认顺序，窗口**不受影响**（两件事不该互相牵连）
  await page.getByRole("button", { name: "开始" }).click();
  await page.getByRole("menuitem", { name: /排列图标/ }).click();
  const tidy = await iconBox(page, "夏日回声");
  const first = await iconBox(page, "雨夜站台");
  expect(Math.round(tidy.x)).toBe(Math.round(first.x));
  expect(tidy.y).toBeGreaterThan(first.y);
  await expect(page.getByTestId("desktop-window-agent")).toBeVisible();

  // ② 关掉所有窗口：窗口收起，图标顺序保持不变（上面刚排好）
  await page.getByRole("button", { name: "开始" }).click();
  await page.getByRole("menuitem", { name: /关掉所有窗口/ }).click();
  await expect(page.getByTestId("desktop-window-agent")).toHaveCount(0);
  const stillTidy = await iconBox(page, "夏日回声");
  expect(Math.round(stillTidy.x)).toBe(Math.round(first.x));
});
