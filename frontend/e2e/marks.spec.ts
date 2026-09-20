import { expect, test, type Page } from "@playwright/test";

/**
 * 写作页「标记批改」回归（真实前后端）。
 *
 * 重点覆盖"标记就在所选那一行旁边"这条设计要求：
 * - 卡片贴在活动标记那一行的下方（位置量出来，不是靠肉眼）；
 * - 滚动正文时卡片跟着走（不脱离那段正文）；
 * - 正文里能看到被标记的高亮（mirror 里出现带 data-mark-id 的 span）。
 *
 * 为什么不测"点处理以后 AI 返回什么"：那要真模型，结果不确定。
 * 这里改为在 localStorage 里预置一条"已处理"的标记（结构与后端返回一致），
 * 于是接受/撤回/失效这些**确定性的**行为可以被真实验证。
 */

const PASSWORD = "e2e-secret-123";
const NEEDLE = "末班车";
const REPLACEMENT = "最后一班列车";

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
      // 与 smoke 一致：AI 责编浮窗收成侧边标签（默认停在右下角，会挡住写作区下半部分按钮）
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

/** 精确选中一段文字（程序化设置选区 + 补一个 keyup，让 React 状态也同步到）。
 *  为什么要补 keyup：程序化的 setSelectionRange 不会触发 React 的 onSelect，
 *  而浮动「标记这段」按钮靠选区状态定位。 */
async function selectText(page: Page, text: string) {
  const ok = await page.getByTestId("script-editor").evaluate((el, needle) => {
    const ta = el as HTMLTextAreaElement;
    const from = ta.value.indexOf(needle);
    if (from < 0) return false;
    ta.focus();
    ta.setSelectionRange(from, from + needle.length);
    ta.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true }));
    return true;
  }, text);
  expect(ok, `正文里找不到要选中的文字：${text}`).toBe(true);
  const selected = await page.getByTestId("script-editor").evaluate((el) => {
    const ta = el as HTMLTextAreaElement;
    return ta.value.slice(ta.selectionStart, ta.selectionEnd);
  });
  expect(selected).toBe(text);
}

/** 用**真实鼠标拖选**一段文字（量出字形位置再拖）。
 *  专门用来验证"人是这么选的，按钮就得出现在这儿"这条路径。 */
async function dragSelectText(page: Page, text: string) {
  const editor = page.getByTestId("script-editor");
  let selected = "";
  // 坐标拖动偶尔会因为布局/滚动还没落位而落空 → 重算坐标重试（最多 3 次）
  for (let attempt = 0; attempt < 3 && selected.length === 0; attempt += 1) {
    const box = await editor.boundingBox();
    expect(box, "编辑器还不可见").not.toBeNull();
    const points = await editor.evaluate((el, needle) => {
      const ta = el as HTMLTextAreaElement;
      const mirror = ta.closest("div")?.querySelector("pre") as HTMLElement | null;
      const frame = ta.closest("div")?.getBoundingClientRect();
      if (!mirror || !frame) return null;
      const walker = document.createTreeWalker(mirror, NodeFilter.SHOW_TEXT);
      const nodes: Text[] = [];
      while (walker.nextNode()) nodes.push(walker.currentNode as Text);
      const start = ta.value.indexOf(needle);
      if (start < 0) return null;
      const end = start + needle.length - 1;
      const rectAt = (offset: number) => {
        let acc = 0;
        for (const n of nodes) {
          const len = n.data.length;
          if (offset < acc + len) {
            const local = offset - acc;
            if (local < 0) return null;
            const r = document.createRange();
            r.setStart(n, local);
            r.setEnd(n, Math.min(local + 1, len));
            return r.getBoundingClientRect();
          }
          acc += len;
        }
        return null;
      };
      const first = rectAt(start);
      const last = rectAt(end);
      if (!first || !last) return null;
      return {
        fromX: Math.round(first.left - frame.left) + 1,
        fromY: Math.round(first.top - frame.top) + Math.round(first.height / 2),
        toX: Math.round(last.right - frame.left) - 1,
        toY: Math.round(last.top - frame.top) + Math.round(last.height / 2),
      };
    }, text);
    expect(points, `正文里找不到要选中的文字：${text}`).not.toBeNull();
    await page.mouse.move(box!.x + points!.fromX, box!.y + points!.fromY);
    await page.mouse.down();
    await page.mouse.move(box!.x + points!.toX, box!.y + points!.toY, { steps: 10 });
    await page.mouse.up();
    selected = await editor.evaluate((el) => {
      const ta = el as HTMLTextAreaElement;
      return ta.value.slice(ta.selectionStart, ta.selectionEnd);
    });
    if (selected.length === 0) await page.waitForTimeout(200);
  }
  // 拖选只要选中了非空一段就算成功（不必与 needle 逐字相等，那是 selectText 的活）
  expect(selected.length).toBeGreaterThan(0);
}

/** 把正文换成一段长稿（React 受控 textarea：必须用原生 setter + input 事件才会触发 onChange） */
async function fillLongText(page: Page, needle: string) {
  const editor = page.getByTestId("script-editor");
  const longText = Array.from(
    { length: 60 },
    (_, i) =>
      `第${i + 1}段：雨落在站台上，他把手举到眼前。${
        i === 2 ? `${needle}已经开走了。` : "风从北边来，云压得很低。"
      }`
  ).join("\n\n");
  await editor.evaluate((el, text) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    setter?.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, longText);
  await page.waitForTimeout(2000);
  // 程序化替换后光标停在文末：先归零，否则后面"选中第 3 段"时视口还停在很下面
  await editor.evaluate((el) => {
    const ta = el as HTMLTextAreaElement;
    ta.setSelectionRange(0, 0);
    ta.scrollTop = 0;
    ta.dispatchEvent(new Event("scroll", { bubbles: true }));
  });
}

/** 活动标记那一行在编辑器里的可见位置（供"卡片是否贴着这一行"用） */
async function anchorGeometry(page: Page) {
  return page.evaluate((needle) => {
    const ta = document.querySelector('[data-testid="script-editor"]') as HTMLTextAreaElement | null;
    const spans = document.querySelectorAll("pre span[data-mark-id]");
    const frame = ta?.closest("div") as HTMLElement | null;
    if (!ta || !frame || spans.length === 0) return null;
    const line = spans[0].parentElement as HTMLElement; // placeLine
    const card = document.querySelector('[data-testid="mark-card"]') as HTMLElement | null;
    const frameRect = frame.getBoundingClientRect();
    const lineRect = line.getBoundingClientRect();
    const cardRect = card?.getBoundingClientRect() ?? null;
    return {
      frameHeight: Math.round(frameRect.height),
      // 该行相对编辑器可见区域的底边（滚出视野时会是负数）
      lineBottom: Math.round(lineRect.bottom - frameRect.top),
      cardTop: cardRect ? Math.round(cardRect.top - frameRect.top) : null,
      scrollTop: Math.round(ta.scrollTop),
      highlightText: spans[0].textContent ?? "",
      highlighted: (spans[0].textContent ?? "").includes(needle),
    };
  }, NEEDLE);
}

/** 选区末尾那个字符的位置 + 浮动按钮的位置（两边都用同一套 Range 量法） */
async function selectionBarGeometry(page: Page) {
  return page.evaluate(() => {
    const ta = document.querySelector('[data-testid="script-editor"]') as HTMLTextAreaElement;
    const frame = ta.closest("div") as HTMLElement;
    const mirror = frame.querySelector("pre") as HTMLElement;
    const fr = frame.getBoundingClientRect();
    const walker = document.createTreeWalker(mirror, NodeFilter.SHOW_TEXT);
    const nodes: Text[] = [];
    while (walker.nextNode()) nodes.push(walker.currentNode as Text);
    const target = ta.selectionEnd - 1;
    let acc = 0;
    let charRect: DOMRect | null = null;
    for (const n of nodes) {
      if (target < acc + n.data.length) {
        const r = document.createRange();
        const local = target - acc;
        r.setStart(n, local);
        r.setEnd(n, Math.min(local + 1, n.data.length));
        charRect = r.getBoundingClientRect();
        break;
      }
      acc += n.data.length;
    }
    const bar = document.querySelector('[data-testid="mark-selection-float"]');
    const b = bar ? bar.getBoundingClientRect() : null;
    const panel = document.querySelector('[data-testid="mark-selection"]');
    const p = panel ? panel.getBoundingClientRect() : null;
    return {
      frameTop: Math.round(fr.top),
      frameBottom: Math.round(fr.bottom),
      frameRight: Math.round(fr.right),
      charBottom: charRect ? Math.round(charRect.bottom) : null,
      charRight: charRect ? Math.round(charRect.right) : null,
      bar: b ? { top: Math.round(b.top), left: Math.round(b.left), right: Math.round(b.right) } : null,
      panelBtnTop: p ? Math.round(p.top) : null,
    };
  });
}

test("选中一段后，「标记这段」出现在选区旁边（不用去下面找）", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_mark_float_"));

  // 没选中时不该出现
  await expect(page.getByTestId("mark-selection-float")).toHaveCount(0);

  await dragSelectText(page, NEEDLE);
  const floatBtn = page.getByTestId("mark-selection-float");
  await expect(floatBtn).toBeVisible();
  // 等布局稳定再量：全套并发跑时偶尔会量到上一帧的位置（表现为偶发失败）
  await page.waitForTimeout(150);

  const geo = await selectionBarGeometry(page);
  expect(geo.charBottom).not.toBeNull();
  expect(geo.bar).not.toBeNull();
  // 按钮就在选中那几个字下面一点（不是跑到编辑器外面/页面下方）
  // 选区跨行时最后一个字可能落在下一视觉行，故上限留到 60px
  expect(geo.bar!.top - geo.charBottom!).toBeGreaterThan(-10);
  expect(geo.bar!.top - geo.charBottom!).toBeLessThan(60);
  expect(geo.bar!.top).toBeLessThan(geo.frameBottom);
  expect(geo.bar!.right).toBeLessThanOrEqual(geo.frameRight);
  // 对比：编辑器下面那个入口确实在编辑器之外的下方
  expect(geo.panelBtnTop!).toBeGreaterThan(geo.frameBottom);

  // 点它就地标记 → 按钮让位给卡片
  await floatBtn.click();
  await expect(page.getByTestId("mark-card")).toBeVisible();
  await expect(page.getByTestId("mark-chip-0")).toBeVisible();
  await expect(page.getByTestId("mark-selection-float")).toHaveCount(0);
  const applied = await page.evaluate(() =>
    (document.querySelector("pre span[data-mark-id]")?.textContent ?? "")
  );
  expect(applied.length).toBeGreaterThan(0);

  // 再选另一段 → 按钮又出现（可以连续标）
  await selectText(page, "站台");
  await expect(page.getByTestId("mark-selection-float")).toBeVisible();
});

test("Ctrl+M 标记：正文高亮 + 卡片贴着那一行 + 刷新后仍在", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_mark_"));

  const editor = page.getByTestId("script-editor");
  expect(await editor.inputValue()).toContain(NEEDLE);

  await selectText(page, NEEDLE);
  await page.keyboard.press("Control+m");

  // 卡片出现，且正文里那一段被标出来了
  await expect(page.getByTestId("mark-card")).toBeVisible();
  await expect(page.getByTestId("mark-card-quote")).toContainText(NEEDLE);
  await expect(page.getByTestId("mark-chip-0")).toBeVisible();

  const geo = await anchorGeometry(page);
  expect(geo).not.toBeNull();
  expect(geo!.highlighted).toBe(true);
  // 卡片就贴在这一行下面（允许 16px 内的误差：行距/边距）
  expect(geo!.cardTop).not.toBeNull();
  expect(geo!.cardTop! - geo!.lineBottom).toBeGreaterThanOrEqual(0);
  expect(geo!.cardTop! - geo!.lineBottom).toBeLessThan(16);

  // 刷新后标记还在（本机记忆），点标记条编号能跳回那一处
  await page.waitForTimeout(1500);
  await page.reload();
  await expect(page.getByTestId("script-editor")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("mark-chip-0").click();
  await expect(page.getByTestId("mark-card")).toBeVisible();
  const selected = await editor.evaluate((el) => {
    const ta = el as HTMLTextAreaElement;
    return ta.value.slice(ta.selectionStart, ta.selectionEnd);
  });
  expect(selected).toBe(NEEDLE);

  // 删掉这个标记
  await page.getByTestId("mark-chip-remove-0").click();
  await expect(page.getByTestId("mark-chip-0")).toHaveCount(0);
});

test("长章节：卡片跟着正文滚动，滚到标记行看不见时也不丢", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_mark_scroll_"));
  await fillLongText(page, NEEDLE);

  await selectText(page, NEEDLE);
  await page.keyboard.press("Control+m");
  await expect(page.getByTestId("mark-card")).toBeVisible();

  const before = await anchorGeometry(page);
  expect(before).not.toBeNull();
  expect(before!.highlighted).toBe(true);
  expect(before!.cardTop! - before!.lineBottom).toBeGreaterThanOrEqual(0);
  expect(before!.cardTop! - before!.lineBottom).toBeLessThan(24);

  // 往下滚一点：卡片跟着那一段一起上移，且仍然贴在行下面
  await page.getByTestId("script-editor").evaluate((el) => {
    const ta = el as HTMLTextAreaElement;
    ta.scrollTop = ta.scrollTop + 120;
    ta.dispatchEvent(new Event("scroll", { bubbles: true }));
  });
  await page.waitForTimeout(200);
  const after = await anchorGeometry(page);
  expect(after!.scrollTop).toBeGreaterThan(before!.scrollTop);
  expect(after!.cardTop!).toBeLessThan(before!.cardTop!);
  expect(after!.cardTop! - after!.lineBottom).toBeGreaterThanOrEqual(0);
  expect(after!.cardTop! - after!.lineBottom).toBeLessThan(16);

  // 滚到最底：标记行已经离开视野，卡片仍留在编辑器里（不会跑到看不见的地方）
  await page.getByTestId("script-editor").evaluate((el) => {
    const ta = el as HTMLTextAreaElement;
    ta.scrollTop = ta.scrollHeight;
    ta.dispatchEvent(new Event("scroll", { bubbles: true }));
  });
  await page.waitForTimeout(200);
  const bottom = await anchorGeometry(page);
  expect(bottom!.lineBottom!).toBeLessThan(0);
  expect(bottom!.cardTop).not.toBeNull();
  expect(bottom!.cardTop!).toBeGreaterThanOrEqual(0);
  expect(bottom!.cardTop!).toBeLessThan(60); // 贴住编辑器顶部
  expect(bottom!.cardTop!).toBeLessThan(bottom!.frameHeight);
});

test("预置改写稿 → 卡片上对照 → 接受写入正文 → 撤回", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_mark_apply_"));

  const editor = page.getByTestId("script-editor");
  const source = await editor.inputValue();
  expect(source).toContain(NEEDLE);
  const from = source.indexOf(NEEDLE);

  await page.evaluate(
    ({ quote, prefix, suffix, replacement, key, chapterId }) => {
      const mark = {
        id: "mk-seeded",
        chapterId,
        quote,
        prefix,
        suffix,
        instruction: "更书面一点",
        intent: "rewrite",
        status: "suggested",
        replacement,
        createdAt: Date.now(),
      };
      localStorage.setItem("vnss-marks-v1", JSON.stringify({ [key]: [mark] }));
    },
    {
      quote: NEEDLE,
      prefix: source.slice(Math.max(0, from - 20), from),
      suffix: source.slice(from + NEEDLE.length, from + NEEDLE.length + 20),
      replacement: REPLACEMENT,
      key: await page.evaluate(() => {
        const ws = JSON.parse(localStorage.getItem("vnss-workspace-v1") || "{}");
        return `${ws.projectId}|${ws.chapterId}`;
      }),
      chapterId: await page.evaluate(
        () => JSON.parse(localStorage.getItem("vnss-workspace-v1") || "{}").chapterId
      ),
    }
  );

  await page.reload();
  await expect(page.getByTestId("script-editor")).toBeVisible({ timeout: 30_000 });

  // 点标记条 → 卡片出现，并给出左右对照
  await page.getByTestId("mark-chip-0").click();
  await expect(page.getByTestId("mark-card")).toBeVisible();
  await expect(page.getByTestId("mark-card-replacement")).toHaveValue(REPLACEMENT);

  // 接受 → 正文被改写
  await page.getByTestId("mark-card-accept").click();
  await expect(editor).toHaveValue(new RegExp(REPLACEMENT));

  // 撤回 → 正文还原
  await page.getByTestId("mark-card-revert").click();
  await expect(editor).toHaveValue(new RegExp(NEEDLE));
  const value = await editor.inputValue();
  expect(value).not.toContain(REPLACEMENT);
});

test("被标记的那段正文被改掉 → 卡片显示「已失效」且不可处理", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await registerAndLogin(page, randomName("e2e_mark_stale_"));

  const editor = page.getByTestId("script-editor");
  await selectText(page, NEEDLE);
  await page.keyboard.press("Control+m");
  await expect(page.getByTestId("mark-card")).toContainText("待处理");

  // 手动把被标记的那句改掉
  await editor.evaluate((el, word) => {
    const ta = el as HTMLTextAreaElement;
    const from = ta.value.indexOf(word);
    ta.focus();
    ta.setSelectionRange(from, from + word.length);
  }, NEEDLE);
  await page.keyboard.type("末班船");
  await page.waitForTimeout(1200);

  await expect(page.getByTestId("mark-card")).toContainText("已失效");
  await expect(page.getByTestId("mark-card-process")).toBeDisabled();
  await expect(page.getByTestId("marks-process-all")).toBeDisabled();
});
