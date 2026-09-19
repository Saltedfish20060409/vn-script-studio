import { expect, test, type Page } from "@playwright/test";

/**
 * 写作页「标记批改」回归（真实前后端）。
 *
 * 覆盖：选中 → Ctrl+M 标记 → 跳转定位 → 刷新后仍在 → 删除；
 * 以及核心闭环：预置一条带改写稿的标记 → 接受（正文被改写）→ 撤回（正文还原）。
 *
 * 为什么不测"点处理以后 AI 返回什么"：那要真模型，结果不确定。
 * 这里改成在 localStorage 里预置一条"已处理"的标记（结构与后端返回一致），
 * 于是接受/撤回/失效这三条**确定性的**行为都能被真实验证。
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
      // 与 smoke 一致：把 AI 责编浮窗收成侧边标签（它默认停在右下角，
      // 会挡住写作区下半部分的按钮——这是产品侧的另一个话题，测试里先让开）
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

/** 在编辑器里程序化选中一段文字，并触发 select 事件让 React 记下选区 */
async function selectText(page: Page, text: string) {
  const ok = await page.getByTestId("script-editor").evaluate((el, needle) => {
    const ta = el as HTMLTextAreaElement;
    const from = ta.value.indexOf(needle);
    if (from < 0) return false;
    ta.focus();
    ta.setSelectionRange(from, from + needle.length);
    ta.dispatchEvent(new Event("select", { bubbles: true }));
    return true;
  }, text);
  expect(ok, `正文里找不到要选中的文字：${text}`).toBe(true);
}

test("选中 → Ctrl+M 标记 → 跳转定位 → 刷新后仍在 → 删除", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_mark_"));

  const editor = page.getByTestId("script-editor");
  const needle = "末班车";
  const source = await editor.inputValue();
  expect(source).toContain(needle);

  await selectText(page, needle);
  await page.keyboard.press("Control+m");

  const item = page.getByTestId("mark-item-0");
  await expect(item).toBeVisible();
  await expect(item).toContainText(needle);
  await expect(item).toContainText("待处理");

  // 跳转：点引用 → 正文里重新选中同一段
  await item.getByRole("button", { name: new RegExp(needle) }).click();
  const selected = await editor.evaluate((el) => {
    const ta = el as HTMLTextAreaElement;
    return ta.value.slice(ta.selectionStart, ta.selectionEnd);
  });
  expect(selected).toBe(needle);

  // 刷新后仍然在（本机记忆）
  await page.waitForTimeout(1500);
  await page.reload();
  await expect(page.getByTestId("script-editor")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("mark-item-0")).toContainText(needle);

  // 删除
  await page.getByTestId("mark-item-0").getByRole("button", { name: "✕" }).click();
  await expect(page.getByTestId("mark-item-0")).toHaveCount(0);
});

test("预置改写稿 → 接受写入正文 → 逐条撤回", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_mark_apply_"));

  const editor = page.getByTestId("script-editor");
  const original = "末班车";
  const replacement = "最后一班列车";
  const source = await editor.inputValue();
  expect(source).toContain(original);

  // 预置一条"已处理、待决定"的标记（结构 = 后端返回 + 前端字段）
  const from = source.indexOf(original);
  await page.evaluate(
    ({ quote, prefix, suffix, replacement, projectKey }) => {
      const mark = {
        id: "mk-seeded",
        chapterId: projectKey.chapterId,
        quote,
        prefix,
        suffix,
        instruction: "更书面一点",
        intent: "rewrite",
        status: "suggested",
        replacement,
        createdAt: Date.now(),
      };
      localStorage.setItem("vnss-marks-v1", JSON.stringify({ [projectKey.key]: [mark] }));
    },
    {
      quote: original,
      prefix: source.slice(Math.max(0, from - 20), from),
      suffix: source.slice(from + original.length, from + original.length + 20),
      replacement,
      projectKey: await page.evaluate(() => {
        const ws = JSON.parse(localStorage.getItem("vnss-workspace-v1") || "{}");
        return { key: `${ws.projectId}|${ws.chapterId}`, chapterId: ws.chapterId };
      }),
    }
  );

  await page.reload();
  await expect(page.getByTestId("script-editor")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("mark-item-0")).toContainText("待决定");
  await expect(page.getByTestId("mark-replacement-0")).toHaveValue(replacement);

  // 接受 → 正文被改写
  await page.getByTestId("mark-accept-0").click();
  await expect(page.getByTestId("script-editor")).toHaveValue(
    new RegExp(replacement)
  );
  await expect(page.getByTestId("mark-item-0")).toContainText("已写入");

  // 撤回 → 正文还原
  await page.getByTestId("mark-revert-0").click();
  await expect(page.getByTestId("script-editor")).toHaveValue(new RegExp(original));
  const value = await editor.inputValue();
  expect(value).not.toContain(replacement);
});

test("标记的那段正文被改掉 → 标记变「已失效」", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_mark_stale_"));

  const editor = page.getByTestId("script-editor");
  const needle = "末班车";
  await selectText(page, needle);
  await page.keyboard.press("Control+m");
  await expect(page.getByTestId("mark-item-0")).toContainText("待处理");

  // 手动把被标记的那句改掉
  await editor.evaluate((el, word) => {
    const ta = el as HTMLTextAreaElement;
    const from = ta.value.indexOf(word);
    ta.focus();
    ta.setSelectionRange(from, from + word.length);
  }, needle);
  await page.keyboard.type("末班船");
  await page.waitForTimeout(1200);

  // 编辑器会重新校验标记：定位不到 → 已失效，而且不该还能"处理"
  await expect(page.getByTestId("mark-item-0")).toContainText("已失效");
  await expect(page.getByTestId("marks-process-all")).toBeDisabled();
});
