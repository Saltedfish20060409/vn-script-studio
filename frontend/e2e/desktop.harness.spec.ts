import { expect, test, type Page } from "@playwright/test";

/**
 * 桌面视图的真实浏览器回归测试（组件台，无需后端）。
 *
 * 覆盖的都是"单元测试抓不到、但用户一眼能看出坏了"的行为：
 * 1. 图标落在固定座位上（不是自由坐标），拖动会换座位；
 * 2. 双击剧本 → 打开的是**这个剧本**的工作台窗口，标题是剧本名（桌面没有"剧本编辑器"软件）；
 * 3. 开始菜单里有"整理图标"，点了回到自动排列。
 */

const HARNESS = "/e2e/harness.html";

async function openHarness(page: Page) {
  await page.goto(HARNESS);
  await expect(page.getByTestId("desktop-view")).toBeVisible();
}

/** 图标当前位置（页面坐标），用来验证座位与拖动 */
async function iconBox(page: Page, name: string) {
  const box = await page.getByRole("listitem", { name }).boundingBox();
  if (!box) throw new Error(`图标不可见：${name}`);
  return box;
}

test("桌面只把剧本和应用摆成固定座位（列优先），不重叠", async ({ page }) => {
  await openHarness(page);

  const first = await iconBox(page, /雨夜站台/);
  const second = await iconBox(page, /九幽诀/);
  // 同一个 x（同一列）、自上而下排开：这就是"固定座位"
  expect(Math.round(second.x)).toBe(Math.round(first.x));
  expect(second.y).toBeGreaterThan(first.y);

  // 任何两个图标都不重叠
  const labels = ["雨夜站台", "九幽诀", "夏日回声", "新建剧本", "剧本库", "AI 责编"];
  const boxes = [];
  for (const label of labels) boxes.push(await iconBox(page, new RegExp(label)));
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

  const before = await iconBox(page, /夏日回声/);
  const target = await iconBox(page, /新建剧本/);
  // 把「夏日回声」拖到「新建剧本」的座位上
  await page.mouse.move(before.x + before.width / 2, before.y + 20);
  await page.mouse.down();
  await page.mouse.move(target.x + target.width / 2, target.y + 20, { steps: 12 });
  await page.mouse.up();

  const moved = await iconBox(page, /夏日回声/);
  // 落点是对齐到座位网格的（与目标座位同一行同一列）
  expect(Math.round(moved.x)).toBe(Math.round(target.x));
  expect(Math.abs(moved.y - target.y)).toBeLessThanOrEqual(2);
  // 被占座位的图标没被挤没，只是换到了别的地方
  await expect(page.getByRole("listitem", { name: /新建剧本/ })).toBeVisible();
});

test("单击不触发拖动（图标不会抖），双击才打开剧本", async ({ page }) => {
  await openHarness(page);

  const icon = page.getByRole("listitem", { name: /九幽诀/ });
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

test("开始菜单：系统项里有整理图标，点了回到自动排列", async ({ page }) => {
  await openHarness(page);

  // 先摆乱一个图标
  const before = await iconBox(page, /夏日回声/);
  const target = await iconBox(page, /新建剧本/);
  await page.mouse.move(before.x + before.width / 2, before.y + 20);
  await page.mouse.down();
  await page.mouse.move(target.x + target.width / 2, target.y + 20, { steps: 10 });
  await page.mouse.up();

  await page.getByRole("button", { name: "开始" }).click();
  await page.getByRole("menuitem", { name: /整理图标/ }).click();

  // 回到默认座位：第 3 个剧本图标回到第一列第三个
  const tidy = await iconBox(page, /夏日回声/);
  const first = await iconBox(page, /雨夜站台/);
  expect(Math.round(tidy.x)).toBe(Math.round(first.x));
  expect(tidy.y).toBeGreaterThan(first.y);
});
