import type { Page } from "@playwright/test";

/** Word 壳：打开顶栏四菜单之一（文件 / 开始 / 审阅 / 视图）。 */
export async function openRibbonMenu(
  page: Page,
  name: "文件" | "开始" | "审阅" | "视图"
) {
  const ribbon = page.getByTestId("studio-ribbon");
  const menu = ribbon.locator("details").filter({ has: page.getByText(name, { exact: true }) });
  // summary 可能已 open：先关再开，保证面板可见
  const details = menu.first();
  const open = await details.getAttribute("open");
  if (open === null) {
    await details.locator("summary").click();
  }
  return details;
}

/** 文件 → 二级页（剧本库 / 导出 / 写作统计…） */
export async function openFilePage(page: Page, label: string | RegExp) {
  const menu = await openRibbonMenu(page, "文件");
  await menu.getByRole("menuitem", { name: label }).click();
  await page.getByTestId("file-backstage").waitFor({ state: "visible" });
}

/** 视图 → 右侧抽屉（设定 / 角色工坊 / 地图 / 剧情状态） */
export async function openViewPanel(page: Page, label: string | RegExp) {
  const menu = await openRibbonMenu(page, "视图");
  await menu.getByRole("menuitem", { name: label }).click();
  await page.getByTestId("view-drawer").waitFor({ state: "visible" });
}

export async function closeOverlay(page: Page) {
  const back = page.getByTestId("backstage-close");
  if (await back.isVisible().catch(() => false)) {
    await back.click();
    return;
  }
  const drawer = page.getByTestId("drawer-close");
  if (await drawer.isVisible().catch(() => false)) {
    await drawer.click();
  }
}
