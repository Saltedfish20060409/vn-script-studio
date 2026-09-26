import { expect, test, type Page } from "@playwright/test";

/**
 * 桌面组件台回归（无需后端）。
 *
 * 语义（B 方案）：双击剧本 = 在桌面上打开**这个剧本自己的窗口**，桌面不退场；
 * 窗口标题栏的「全屏写作」才离开桌面（那一套由 desktop.spec.ts 在真机里验）。
 */

const HARNESS = "/e2e/harness.html";

async function openHarness(page: Page, query = "") {
  await page.goto(HARNESS + query);
  await expect(page.getByTestId("desktop-view")).toBeVisible();
}

async function iconBox(page: Page, name: string | RegExp) {
  const box = await page.getByRole("listitem", { name }).boundingBox();
  if (!box) throw new Error(`图标不可见：${name}`);
  return box;
}

test("桌面只把剧本和应用摆成固定座位（列优先），不重叠", async ({ page }) => {
  await openHarness(page);

  const first = await iconBox(page, "雨夜站台");
  const second = await iconBox(page, "九幽诀");
  expect(Math.round(second.x)).toBe(Math.round(first.x));
  expect(second.y).toBeGreaterThan(first.y);

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
  await page.mouse.move(before.x + before.width / 2, before.y + 20);
  await page.mouse.down();
  await page.mouse.move(target.x + target.width / 2, target.y + 20, { steps: 12 });
  await page.mouse.up();

  const moved = await iconBox(page, "夏日回声");
  expect(Math.round(moved.x)).toBe(Math.round(target.x));
  expect(Math.abs(moved.y - target.y)).toBeLessThanOrEqual(2);
  await expect(page.getByRole("listitem", { name: "新建剧本" })).toBeVisible();
});

test("单击不触发拖动，双击在桌面上打开这个剧本的窗口", async ({ page }) => {
  await openHarness(page);

  const icon = page.getByRole("listitem", { name: "九幽诀" });
  await icon.click();
  await expect(page.getByTestId("desktop-script-window")).toHaveCount(0);

  await icon.dblclick();
  // 桌面不退场：这一层还在（标题栏 / 任务栏），只是让位给窗口
  await expect(page.getByTestId("desktop-view")).toBeVisible();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("fake-workbench")).toBeVisible();
  await expect(page.getByTestId("fake-workbench")).toContainText("九幽诀");
  await expect(page.getByTestId("harness-log")).toContainText("open:p2");
  // 图标让位给窗口（不然会浮在稿纸上面）
  await expect(page.getByRole("listitem", { name: "雨夜站台" })).toHaveCount(0);
});

test("窗口里的工作台仍可点、可滚（压扁这个老问题不能回来）", async ({ page }) => {
  await openHarness(page);
  await page.getByRole("listitem", { name: "九幽诀" }).dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();

  await page.getByTestId("wb-button").click();
  await page.getByTestId("wb-button").click();
  await expect(page.getByTestId("wb-hits")).toHaveText("2");

  /* 工作台在桌面里是**定高**的（标题栏 30px 到任务栏 46px 之间），内容比它高时
     必须由它自己滚。这里量的是那条老问题：允许内部 flex 收缩时 .layout/.main
     会被压扁，行高塌成 1px，表现为"按钮点不到/滚动条不出现"。
     生产里同一个壳由 writeShell.harness.spec.ts 守着工具条那一层，这里守桌面这一层。 */
  const scroll = await page.getByTestId("harness-shell").evaluate((el) => ({
    scrollable: el.scrollHeight > el.clientHeight + 1,
    clientHeight: el.clientHeight,
  }));
  expect(scroll.scrollable, "桌面窗口里的工作台应当能自己滚").toBe(true);
  await page.getByTestId("harness-shell").evaluate((el) => {
    el.scrollTop = 400;
  });
  expect(
    await page.getByTestId("harness-shell").evaluate((el) => el.scrollTop)
  ).toBeGreaterThan(0);
  // 滚到底也不能把工作台推到标题栏/任务栏底下去
  // （boundingBox 给的是 {x, y, width, height}——没有 top 字段，写错会静默变成 undefined）
  const box = await page.getByTestId("harness-shell").boundingBox();
  expect(Math.round(box?.y ?? -1)).toBe(30);
  expect(Math.round(box?.height ?? 0)).toBe(800 - 30 - 46);
});

test("右键剧本图标有打开/重命名/复制/删除，点了会执行", async ({ page }) => {
  await openHarness(page);

  await page.getByRole("listitem", { name: "夏日回声" }).click({ button: "right" });
  const menu = page.getByTestId("desktop-context-menu");
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /打开/ })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: /重命名/ })).toBeVisible();

  await menu.getByRole("menuitem", { name: /重命名/ }).click();
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
  await expect(page.getByRole("listitem", { name: "长篇1" })).toBeVisible();
  await expect(page.getByRole("listitem", { name: "长篇7" })).toHaveCount(0);

  await more.dblclick();
  await expect(page.getByTestId("library-window")).toBeVisible();
});

test("开始菜单能直达设定/地图，并在桌面上那扇窗里翻到那一页", async ({ page }) => {
  await openHarness(page);

  await page.getByRole("button", { name: "开始" }).click();
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem", { name: "设定" })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "角色工坊" })).toBeVisible();

  await menu.getByRole("menuitem", { name: "地图" }).click();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("desktop-view")).toBeVisible();
  await expect(page.getByTestId("wb-tab")).toHaveText("当前面板：map");
  await expect(page.getByTestId("harness-log")).toContainText("tab:map");
});

test("底部音乐条足够薄", async ({ page }) => {
  await page.goto(HARNESS + "?music=1");
  const bar = page.getByTestId("music-bar");
  await expect(bar).toBeVisible();
  const box = await bar.boundingBox();
  expect(box?.height ?? 999).toBeLessThanOrEqual(48);
  const play = await bar.locator('button[title="播放"], button[title="暂停"]').boundingBox();
  expect(play?.height ?? 0).toBeGreaterThanOrEqual(30);
});

test("开始菜单：排列图标回到默认顺序", async ({ page }) => {
  await openHarness(page);

  const before = await iconBox(page, "夏日回声");
  const target = await iconBox(page, "新建剧本");
  await page.mouse.move(before.x + before.width / 2, before.y + 20);
  await page.mouse.down();
  await page.mouse.move(target.x + target.width / 2, target.y + 20, { steps: 10 });
  await page.mouse.up();

  await page.getByRole("button", { name: "开始" }).click();
  await page.getByRole("menuitem", { name: /排列图标/ }).click();

  const tidy = await iconBox(page, "夏日回声");
  const first = await iconBox(page, "雨夜站台");
  expect(Math.round(tidy.x)).toBe(Math.round(first.x));
  expect(tidy.y).toBeGreaterThan(first.y);
});

test("键盘：方向键移动、Enter 打开、F2 重命名、Delete 删除", async ({ page }) => {
  await openHarness(page, "?many=1");

  await page.getByRole("listitem", { name: "长篇1" }).focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("listitem", { name: "长篇2" })).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(page.getByRole("listitem", { name: "长篇1" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("listitem", { name: "新建剧本" })).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("listitem", { name: "长篇1" })).toBeFocused();

  await page.keyboard.press("F2");
  await expect(page.getByTestId("harness-log")).toContainText("rename:q0");
  await page.keyboard.press("Delete");
  await expect(page.getByTestId("harness-log")).toContainText("delete:q0");

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("harness-log")).toContainText("open:q0");
});

test("键盘上下不跨列", async ({ page }) => {
  await openHarness(page);
  await page.getByRole("listitem", { name: "夏日回声" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("listitem", { name: "夏日回声" })).toBeFocused();
});

test("一次性小抄：第一次进桌面出现，点「知道了」后不再出现", async ({ page }) => {
  await openHarness(page);

  const tips = page.getByTestId("desktop-tips");
  await expect(tips).toBeVisible();
  await expect(tips).toContainText("双击");
  await expect(tips).toContainText("右键");

  await page.getByTestId("desktop-tips-close").click();
  await expect(tips).toHaveCount(0);

  await page.reload();
  await expect(page.getByTestId("desktop-view")).toBeVisible();
  await expect(page.getByTestId("desktop-tips")).toHaveCount(0);
});

test("打开作品窗口后：图标与小抄退场，桌面与任务栏还在", async ({ page }) => {
  await openHarness(page);
  await expect(page.getByTestId("desktop-tips")).toBeVisible();

  await page.getByRole("listitem", { name: "九幽诀" }).dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("desktop-view")).toBeVisible();
  await expect(page.getByTestId("desktop-task-script")).toBeVisible();
  await expect(page.getByTestId("desktop-tips")).toHaveCount(0);
  await expect(page.getByRole("listitem", { name: "雨夜站台" })).toHaveCount(0);
});

test("剧本图标角标与「继续写作」打开这扇窗", async ({ page }) => {
  await openHarness(page);

  await expect(page.getByTestId("icon-badge-project:p1")).toHaveText("12 章");
  await expect(page.getByTestId("icon-badge-project:p2")).toHaveText("空");
  await expect(page.getByTestId("icon-badge-project:p3")).toHaveCount(0);

  const hint = await page.getByRole("listitem", { name: "雨夜站台" }).getAttribute("title");
  expect(hint).toContain("共 12 章");
  expect(hint).toContain("最后修改");

  const resume = page.getByTestId("desktop-resume");
  await expect(resume).toBeVisible();
  await expect(resume).toContainText("第 3 章 · 夜雨");
  await resume.click();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("fake-workbench")).toContainText("雨夜站台");
  await expect(page.getByTestId("harness-log")).toContainText("resume");
  await expect(page.getByTestId("desktop-resume")).toHaveCount(0);
});

test("「全屏写作」离开桌面，「返回桌面」回来还是这扇窗", async ({ page }) => {
  await openHarness(page);
  await page.getByRole("listitem", { name: "九幽诀" }).dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();

  await page.getByTestId("script-window-fullscreen").click();
  // 全屏 = 桌面整层退场，工作台铺满整页（顶栏那套 Word 壳）
  await expect(page.getByTestId("desktop-view")).toHaveCount(0);
  await expect(page.getByTestId("fake-workbench")).toBeVisible();
  await expect(page.getByTestId("harness-log")).toContainText("fullscreen");
  const box = await page.getByTestId("harness-shell").boundingBox();
  expect(Math.round(box?.top ?? 0)).toBe(0);

  // 从全屏回来：窗口状态没被丢掉，因此还是那扇窗（不是回到图标页）
  await page.getByTestId("wb-return-desktop").click();
  await expect(page.getByTestId("desktop-view")).toBeVisible();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("fake-workbench")).toContainText("九幽诀");
});

test("最小化到任务栏：图标回来，点任务栏按钮还原", async ({ page }) => {
  await openHarness(page);
  await page.getByRole("listitem", { name: "九幽诀" }).dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();

  await page.getByTestId("script-window-minimize").click();
  await expect(page.getByTestId("desktop-script-window")).toHaveCount(0);
  // 最小化 ≠ 关掉：任务栏上还留着这扇窗，桌面图标也回来了
  await expect(page.getByTestId("desktop-task-script")).toBeVisible();
  await expect(page.getByRole("listitem", { name: "雨夜站台" })).toBeVisible();
  // 工作台被收起（display:none），不是盖在桌面底下等着被点到
  expect(
    await page.getByTestId("harness-shell").evaluate((el) => getComputedStyle(el).display)
  ).toBe("none");

  await page.getByTestId("desktop-task-script").click();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await expect(page.getByTestId("harness-log")).toContainText("restore");
});

test("关闭窗口回桌面图标，双击能再开", async ({ page }) => {
  await openHarness(page);
  await page.getByRole("listitem", { name: "九幽诀" }).dblclick();
  await page.getByTestId("script-window-close").click();

  await expect(page.getByTestId("desktop-script-window")).toHaveCount(0);
  await expect(page.getByTestId("desktop-task-script")).toHaveCount(0);
  await expect(page.getByRole("listitem", { name: "九幽诀" })).toBeVisible();

  await page.getByRole("listitem", { name: "九幽诀" }).dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
});

test("任务栏「工作台」出口进入稿纸", async ({ page }) => {
  await openHarness(page);
  const exit = page.getByTestId("desktop-to-studio");
  await expect(exit).toBeVisible();
  await exit.click();
  await expect(page.getByTestId("fake-workbench")).toBeVisible();
  await expect(page.getByTestId("harness-log")).toContainText("studio");
});

test("排列图标只动图标，关掉所有窗口只关窗口（含作品窗口）", async ({ page }) => {
  await openHarness(page);

  await page.getByRole("listitem", { name: "AI 责编" }).dblclick();
  await expect(page.getByTestId("desktop-window-agent")).toBeVisible();
  // 作品窗口也开着：关掉所有窗口时它要一起关（窗口拖到看不见时的找回手段）
  await page.getByRole("button", { name: "开始" }).click();
  await page.getByRole("menuitem", { name: /^写作$/ }).click();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  // 但图标这会儿为了让位给窗口收起来了，先关掉它再量图标
  await page.getByTestId("script-window-close").click();

  const before = await iconBox(page, "夏日回声");
  const target = await iconBox(page, "新建剧本");
  await page.mouse.move(before.x + before.width / 2, before.y + 20);
  await page.mouse.down();
  await page.mouse.move(target.x + target.width / 2, target.y + 20, { steps: 10 });
  await page.mouse.up();

  await page.getByRole("button", { name: "开始" }).click();
  await page.getByRole("menuitem", { name: /排列图标/ }).click();
  const tidy = await iconBox(page, "夏日回声");
  const first = await iconBox(page, "雨夜站台");
  expect(Math.round(tidy.x)).toBe(Math.round(first.x));
  expect(tidy.y).toBeGreaterThan(first.y);
  await expect(page.getByTestId("desktop-window-agent")).toBeVisible();

  // 再开一次作品窗口，验"关掉所有窗口"两扇一起关
  await page.getByRole("listitem", { name: "九幽诀" }).dblclick();
  await expect(page.getByTestId("desktop-script-window")).toBeVisible();
  await page.getByRole("button", { name: "开始" }).click();
  await page.getByRole("menuitem", { name: /关掉所有窗口/ }).click();
  await expect(page.getByTestId("desktop-window-agent")).toHaveCount(0);
  await expect(page.getByTestId("desktop-script-window")).toHaveCount(0);
  const stillTidy = await iconBox(page, "夏日回声");
  expect(Math.round(stillTidy.x)).toBe(Math.round(first.x));
});
