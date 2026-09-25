import { expect, test, type Page } from "@playwright/test";
import { openViewPanel } from "./nav";

/**
 * 地图「按需功能开关」回归（真实前后端）。
 *
 * 覆盖用户提的做法：不刚需的功能做成**可关闭/打开**，而不是一直占着界面。
 * - 默认：手绘开着、「距离与行程时间」关着；
 * - 打开距离 → 连线上出现「约 N 公里 · 步行约 X 天」的标注，并显示比例尺；
 * - 改比例尺 → 标注跟着变（说明真的按比例尺算，不是写死的）；
 * - 关掉手绘 → 「画笔」工具消失；再打开 → 回来（数据一直保留）；
 * - 刷新后开关仍在（存在本机）。
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

/** 进地图页，并确保有地点与通路（没有就智能提取一次） */
async function openMapWithLinks(page: Page) {
  await openViewPanel(page, "地图");
  const drawer = page.getByTestId("view-drawer");
  await expect(drawer.getByTestId("map-features-toggle")).toBeVisible({ timeout: 20_000 });
  const pins = drawer.locator("[data-pin]");
  if ((await pins.count()) < 2) {
    const extract = drawer.getByRole("button", { name: "智能提取地图" });
    if (await extract.count()) {
      await extract.first().click();
      await page.waitForTimeout(1500);
    }
  }
  await expect(pins.first()).toBeVisible({ timeout: 20_000 });
}

test("距离与行程时间是按需开的：打开才显示，改比例尺会跟着变", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_map_"));
  await openMapWithLinks(page);

  // 默认关闭：没有任何距离标注
  await expect(page.getByTestId("map-distance-label")).toHaveCount(0);
  await expect(page.getByTestId("map-scale-hint")).toHaveCount(0);

  // 打开「距离与行程时间」
  await page.getByTestId("map-features-toggle").click();
  await expect(page.getByTestId("map-features-menu")).toBeVisible();
  await page.getByTestId("map-feature-distance").check();
  await expect(page.getByTestId("map-scale-hint")).toContainText("公里");

  // 通路上出现距离 + 行程读法
  const labels = page.getByTestId("map-distance-label");
  await expect(labels.first()).toBeVisible({ timeout: 15_000 });
  const first = (await labels.first().textContent()) ?? "";
  expect(first).toMatch(/约 \d/);

  // 改比例尺（地区 100px=10km → 100px=100km）→ 标注里的公里数应显著变大
  await page.getByTestId("map-measure-km").fill("100");
  await page.waitForTimeout(400);
  const after = (await labels.first().textContent()) ?? "";
  const num = (s: string) => Number((s.match(/约 (\d+(?:\.\d+)?)/) ?? [])[1] ?? "0");
  expect(num(after)).toBeGreaterThan(num(first));
});

test("单位跟着题材尺度走：城市按分钟、大陆按天（这是用户提的问题）", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_map_scale_"));
  await openMapWithLinks(page);

  await page.getByTestId("map-features-toggle").click();
  await page.getByTestId("map-feature-distance").check();
  const labels = page.getByTestId("map-distance-label");
  await expect(labels.first()).toBeVisible({ timeout: 15_000 });

  // 城市 / 日常：100 像素 = 1 公里 → 家、学校、车站这种距离应该是分钟级，不是"天"
  await page.getByTestId("map-scale-preset").selectOption("urban");
  await page.waitForTimeout(400);
  await expect(page.getByTestId("map-measure-km")).toHaveValue("1");
  const urbanLabel = (await labels.first().textContent()) ?? "";
  expect(urbanLabel).not.toContain("天");
  expect(urbanLabel).toMatch(/分钟|小时/);
  // 城市尺度下交通方式给出通勤选项
  const transportOptions = await page
    .getByTestId("map-measure-transport")
    .locator("option")
    .allTextContents();
  expect(transportOptions.slice(0, 2).join(" ")).toMatch(/步行|自行车/);
  expect(transportOptions.join(" ")).toContain("公交");

  // 异世界 / 大陆：100 像素 = 100 公里 → 同样的路变成按天
  await page.getByTestId("map-scale-preset").selectOption("continental");
  await page.waitForTimeout(400);
  await expect(page.getByTestId("map-measure-km")).toHaveValue("100");
  const bigLabel = (await labels.first().textContent()) ?? "";
  expect(bigLabel).toContain("天");

  // 尺度属于**作品数据**：把本机缓存清掉再刷新，设置仍然在（换设备也跟得上）
  const scalePersisted = page.waitForResponse(
    (r) =>
      r.request().method() === "PUT" &&
      /\/api\/v1\/projects\/[^/]+$/.test(r.url()) &&
      (r.request().postData() ?? "").includes('"urban"'),
    { timeout: 25_000 }
  );
  await page.getByTestId("map-scale-preset").selectOption("urban");
  await scalePersisted; // 等这一次保存落盘（而不是等"任意一次 PUT"）
  await page.evaluate(() => localStorage.removeItem("vnss-map-features-v1"));
  await page.reload();
  await expect(page.getByTestId("map-features-toggle")).toBeVisible({ timeout: 40_000 });
  await page.getByTestId("map-features-toggle").click();
  await page.getByTestId("map-feature-distance").check();
  await expect(page.getByTestId("map-measure-km")).toHaveValue("1", { timeout: 15_000 });
  await expect(page.getByTestId("map-scale-preset")).toHaveValue("urban");
});

test("手绘开关：关掉画笔工具消失、再打开回来；刷新后开关仍在", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_map2_"));
  await openMapWithLinks(page);

  // 默认开着：工具栏里有「画笔」
  const drawBtn = page.getByRole("button", { name: "画笔", exact: true });
  await expect(drawBtn.first()).toBeVisible();

  // 关掉
  await page.getByTestId("map-features-toggle").click();
  await page.getByTestId("map-feature-strokes").uncheck();
  await expect(page.getByRole("button", { name: "画笔", exact: true })).toHaveCount(0);

  // 刷新后仍然是关的（存在本机）
  await page.reload();
  await expect(page.getByTestId("map-features-toggle")).toBeVisible({ timeout: 40_000 });
  await expect(page.getByRole("button", { name: "画笔", exact: true })).toHaveCount(0);

  // 再打开 → 回来（数据一直没删）
  await page.getByTestId("map-features-toggle").click();
  await page.getByTestId("map-feature-strokes").check();
  await expect(page.getByRole("button", { name: "画笔", exact: true }).first()).toBeVisible();
  await expect(page.locator("[data-pin]").first()).toBeVisible();
});
