import { expect, test, type Page } from "@playwright/test";

/**
 * 语音输入的失败反馈。
 *
 * 起因：用户说"语音输入之前能用，现在不知道怎么样"——因为**界面根本不说**。
 * 原来 onerror 只处理 not-allowed，network 之类的错误被静默吞掉，点一下麦克风
 * 界面闪一下就没反应了，看起来像坏了、又没有任何线索。
 *
 * 真去触发一次 network 错误需要浏览器连不上 Google 的识别服务（本机直连确实不通），
 * 但那在 CI/别人机器上不可复现。所以这里**把识别对象换成假的**，
 * 只验证"错误会被说出来"这条契约；真实错误码来自实测（见报告）。
 */

const PASSWORD = "e2e-secret-123";

function randomName(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
}

/** 注入一个假的 SpeechRecognition：start() 后立刻报指定错误 */
async function stubSpeech(page: Page, errorCode: string) {
  await page.addInitScript((code) => {
    class FakeRecognition {
      lang = "";
      continuous = false;
      interimResults = false;
      onstart: null | (() => void) = null;
      onend: null | (() => void) = null;
      onerror: null | ((e: { error: string }) => void) = null;
      onresult: null | ((e: unknown) => void) = null;
      start() {
        setTimeout(() => {
          this.onstart?.();
          setTimeout(() => this.onerror?.({ error: code }), 80);
        }, 10);
      }
      stop() {
        this.onend?.();
      }
      abort() {
        /* no-op */
      }
    }
    (window as unknown as Record<string, unknown>).webkitSpeechRecognition = FakeRecognition;
    (window as unknown as Record<string, unknown>).SpeechRecognition = undefined;
  }, errorCode);
}

async function registerAndLogin(page: Page, username: string) {
  page.addInitScript(() => {
    try {
      for (let v = 1; v <= 30; v += 1) localStorage.setItem(`vnss-notice-read-v${v}`, "1");
      localStorage.setItem("vnss-firstrun-hidden", "1");
      localStorage.setItem(
        "vnss-agent-float-v6",
        JSON.stringify({ mode: "docked", edge: "right", along: 96, size: "mini" })
      );
    } catch {
      /* ignore */
    }
  });
  await page.goto("/login");
  await page.getByRole("tab", { name: "注册" }).click();
  await page.fill("#vnss-username", username);
  await page.fill("#vnss-email", `${username}@e2email.example.net`);
  await page.fill("#vnss-password", PASSWORD);
  await page.fill("#vnss-confirm", PASSWORD);
  await page.getByRole("button", { name: "注册并发送验证邮件" }).click();
  await page.waitForResponse((r) => r.url().includes("/auth/register"), { timeout: 20_000 });
  await page.getByRole("button", { name: "返回登录" }).click();
  await page.fill("#vnss-username", username);
  await page.fill("#vnss-password", PASSWORD);
  await page.getByRole("button", { name: "开始创作" }).click();
  await expect(page.getByTestId("script-editor")).toBeVisible({ timeout: 40_000 });
}

test("语音输入连不上服务时，界面要把原因说出来（不再静默失败）", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await stubSpeech(page, "network");
  await registerAndLogin(page, randomName("e2e_speech_"));

  const mic = page.getByTestId("speech-input-button");
  await expect(mic).toBeVisible({ timeout: 20_000 });
  await mic.click();

  const err = page.getByTestId("speech-error");
  await expect(err).toBeVisible({ timeout: 15_000 });
  await expect(err).toContainText("连不上语音识别服务");
  await expect(err).toContainText("打字输入");
  // 按钮回到"未聆听"状态，可以再点
  await expect(mic).toHaveAttribute("aria-pressed", "false");
});

test("没有麦克风权限时，提示去地址栏放行", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await stubSpeech(page, "not-allowed");
  await registerAndLogin(page, randomName("e2e_speech_perm_"));

  await page.getByTestId("speech-input-button").click();
  const err = page.getByTestId("speech-error");
  await expect(err).toBeVisible({ timeout: 15_000 });
  await expect(err).toContainText("麦克风权限");
});
