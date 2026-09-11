import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  applySettingsToDom,
  type AppSettings,
  type PanelGlass,
  type ServerSettingsOut,
  type ThemeMode,
} from "../lib/settings";
import {
  getModelCatalogue,
  getSettings,
  getUsage,
  putSettings,
  testLlm,
  type ModelPreset,
  type UsageTotals,
} from "../api/misc";
import { t } from "../lib/i18n";
import {
  loadLlmCredentials,
  loadStorageMode,
  saveLlmCredentials,
  saveStorageMode,
  type LlmStorageMode,
} from "../lib/llmCredentials";
import {
  getDeskPetState,
  setDeskPetEnabled,
  subscribeDeskPet,
} from "../lib/deskPet";
import {
  loadClickFx,
  notifyClickFx,
  setClickFx,
  subscribeClickFx,
} from "../lib/clickFx";
import {
  loadMusicBar,
  notifyMusicBar,
  setMusicBar,
  subscribeMusicBar,
} from "../lib/musicBar";
import styles from "./SettingsModal.module.css";

type Props = {
  open: boolean;
  onClose: () => void;
  settings: AppSettings;
  onChange: (s: AppSettings) => void;
};

type Pane = "theme" | "bg" | "usage" | "llm";

/** 各厂商「申请 API Key」控制台地址（预设里选了哪家就显示哪家的链接）。 */
const VENDOR_KEY_URL: Record<string, string> = {
  DeepSeek: "https://platform.deepseek.com/api_keys",
  Zhipu: "https://open.bigmodel.cn/usercenter/apikeys",
  Alibaba: "https://bailian.console.aliyun.com/",
  Moonshot: "https://platform.moonshot.cn/console/api-keys",
  ByteDance: "https://console.volcengine.com/ark",
  Anthropic: "https://console.anthropic.com/settings/keys",
  Google: "https://aistudio.google.com/app/apikey",
  OpenAI: "https://platform.openai.com/api-keys",
  Ollama: "https://ollama.com/download",
};

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function UsageRow({ label, t }: { label: string; t: UsageTotals }) {
  return (
    <div className={styles.usageRow}>
      <span className={styles.usageLabel}>{label}</span>
      <span>{t.calls} 次调用</span>
      <span>
        输入 {fmtTokens(t.promptTokens)} · 输出 {fmtTokens(t.completionTokens)}
      </span>
      <strong>{fmtTokens(t.totalTokens)} tokens</strong>
    </div>
  );
}

function UsagePane() {
  const [usage, setUsage] = useState<{ today: UsageTotals; total: UsageTotals } | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    getUsage()
      .then(setUsage)
      .catch((e) => setError(e instanceof Error ? e.message : "用量读取失败"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className={styles.form}>
      <p className={styles.note}>模型 token 消耗（服务端记账，按用户统计）。</p>
      <div className={styles.usageBox}>
        {error && <p className={styles.error}>{error}</p>}
        {usage ? (
          <>
            <UsageRow label="今日" t={usage.today} />
            <UsageRow label="累计" t={usage.total} />
          </>
        ) : (
          !error && <p className={styles.note}>加载中…</p>
        )}
      </div>
      <button type="button" className={styles.ghost} onClick={load}>
        刷新
      </button>
    </div>
  );
}

/** 本机 LLM 凭据：Key / URL 存在浏览器，请求后端时带上以连接模型。 */
function LlmPane() {
  const [serverFallback, setServerFallback] = useState<ServerSettingsOut | null>(
    null
  );
  const [error, setError] = useState("");
  const [savedNote, setSavedNote] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [criticKey, setCriticKey] = useState("");
  const [criticBaseUrl, setCriticBaseUrl] = useState("");
  const [criticModel, setCriticModel] = useState("");
  const [storageMode, setStorageModeState] = useState<LlmStorageMode>(loadStorageMode);
  const [presets, setPresets] = useState<ModelPreset[]>([]);
  const [presetId, setPresetId] = useState<string>("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    text: string;
  } | null>(null);

  const load = useCallback(() => {
    setError("");
    setSavedNote("");
    setStorageModeState(loadStorageMode());
    const local = loadLlmCredentials();
    setApiKey(local.apiKey);
    setBaseUrl(local.baseUrl);
    setModel(local.model);
    setCriticKey(local.criticApiKey);
    setCriticBaseUrl(local.criticBaseUrl);
    setCriticModel(local.criticModel);
    getSettings()
      .then((s) => {
        setServerFallback(s);
        // account 模式：服务端只回显 masked key，不回明文
        if (loadStorageMode() === "account" && s.has_api_key) {
          setApiKey("");
          setSavedNote(
            `账号已保存 Key（${s.api_key_masked}）。留空保存表示沿用账号 Key。`
          );
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : "读取失败"));
    getModelCatalogue()
      .then(({ presets: p }) => setPresets(p))
      .catch(() => {
        /* preset catalogue is a nice-to-have */
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const persist = (next: {
    apiKey: string;
    baseUrl: string;
    model: string;
    criticKey: string;
    criticBaseUrl: string;
    criticModel: string;
  }, opts?: { clearAccountKey?: boolean }) => {
    saveStorageMode(storageMode);
    if (storageMode === "account") {
      // 账号加密存储：key 上服务端(仅回显 masked)，并清掉本机 key 防止 header 覆盖
      saveLlmCredentials({
        apiKey: "",
        baseUrl: "",
        model: "",
        criticApiKey: "",
        criticBaseUrl: "",
        criticModel: "",
      });
      void putSettings({
        api_key: opts?.clearAccountKey ? "" : next.apiKey === "" ? undefined : next.apiKey,
        base_url: next.baseUrl || undefined,
        api_model: next.model || undefined,
        critic_api_key: opts?.clearAccountKey ? "" : next.criticKey === "" ? undefined : next.criticKey,
        critic_api_base_url: next.criticBaseUrl || undefined,
        critic_api_model: next.criticModel || undefined,
      })
        .then((s) => {
          setSavedNote(
            opts?.clearAccountKey
              ? "账号 Key 已清除"
              : s.has_api_key
                ? `已保存到账号（加密存储 · ${s.api_key_masked}）。下次登录自动生效。`
                : "已保存到账号（未设置主 Key）"
          );
        })
        .catch((e) =>
          setError(e instanceof Error ? e.message : "保存到账号失败")
        );
      return;
    }
    // 本机存储：localStorage + X-LLM headers（现状）
    saveLlmCredentials({
      apiKey: next.apiKey,
      baseUrl: next.baseUrl,
      model: next.model,
      criticApiKey: next.criticKey,
      criticBaseUrl: next.criticBaseUrl,
      criticModel: next.criticModel,
    });
  };

  const save = () => {
    setError("");
    persist({
      apiKey,
      baseUrl,
      model,
      criticKey,
      criticBaseUrl,
      criticModel,
    });
    if (storageMode !== "account") {
      setSavedNote(t("settings.savedLocal"));
    }
    setTestResult(null);
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    persist({
      apiKey,
      baseUrl,
      model,
      criticKey,
      criticBaseUrl,
      criticModel,
    });
    try {
      const r = await testLlm({
        api_key: apiKey === "" ? undefined : apiKey,
        base_url: baseUrl,
        model,
      });
      setTestResult(
        r.ok
          ? {
              ok: true,
              text: `连接成功 · ${r.model} · ${r.latency_ms} ms`,
            }
          : { ok: false, text: r.error ?? "连接失败" }
      );
    } catch (e) {
      setTestResult({
        ok: false,
        text: e instanceof Error ? e.message : "连接失败",
      });
    } finally {
      setTesting(false);
    }
  };

  const applyPreset = (presetId: string) => {
    const p = presets.find((x) => x.id === presetId);
    if (!p) return;
    setPresetId(p.id);
    setBaseUrl(p.base_url);
    setModel(p.model);
    setTestResult(null);
    setSavedNote("");
  };

  const sourceLabel = apiKey
    ? t("settings.activeClient")
    : serverFallback?.has_api_key
      ? t("settings.activeUser")
      : t("settings.activeServer");

  return (
    <div className={styles.form}>
      <p className={styles.note}>{t("settings.llmNote")}</p>
      {error && <p className={styles.error}>{error}</p>}
      <p className={styles.note}>
        {t("settings.activeModel", {
          model: model || serverFallback?.active_model || "deepseek-v4-flash",
        })}{" "}
        · {sourceLabel}
      </p>
      {presets.length > 0 && (
        <label>
          {t("settings.preset")}
          <select
            value={presetId}
            onChange={(e) => applyPreset(e.target.value)}
            data-testid="model-preset-select"
          >
            <option value="">{t("settings.presetPick")}</option>
            {presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
          <span className={styles.note}>
            {presets.find((p) => p.id === presetId)?.note ??
              "选择预设只会帮你填好 Base URL 与模型名，Key 仍需自己输入。"}
          </span>
          {(() => {
            const current = presets.find((p) => p.id === presetId);
            const link = current ? VENDOR_KEY_URL[current.vendor] : undefined;
            if (!current) return null;
            return (
              <span className={styles.note}>
                {link ? (
                  <>
                    还没有 Key？
                    <a href={link} target="_blank" rel="noreferrer">
                      去 {current.vendor} 控制台申请
                    </a>
                    （注册后免费额度通常够试用）。
                  </>
                ) : (
                  "该厂商的 Key 申请地址见其官网控制台。"
                )}
              </span>
            );
          })()}
        </label>
      )}
      <label>
        凭据存储方式
        <select
          value={storageMode}
          onChange={(e) => setStorageModeState(e.target.value as LlmStorageMode)}
        >
          <option value="account">账号存储（推荐 · 服务端加密 · 跨设备）</option>
          <option value="local">本机存储（仅当前浏览器）</option>
        </select>
        <span className={styles.note}>
          {storageMode === "account"
            ? "Key 加密保存在你的账号里，下次登录自动生效，且不暴露在浏览器本地（防 XSS 窃取）。"
            : "Key 只存在本机 localStorage，随请求头发送；换设备/清缓存需重填。"}
        </span>
      </label>
      <label>
        {t("settings.apiKey")}
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={storageMode === "account" ? "留空 = 沿用账号已存 Key" : "sk-…"}
          autoComplete="off"
        />
      </label>
      <label>
        {t("settings.baseUrl")}
        <input
          type="text"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.deepseek.com"
        />
      </label>
      <label>
        {t("settings.model")}
        <input
          type="text"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="deepseek-v4-flash"
        />
      </label>
      {savedNote && <p className={styles.okNote}>{savedNote}</p>}
      {testResult && (
        <p className={testResult.ok ? styles.okNote : styles.error}>
          {testResult.text}
        </p>
      )}
      <hr className={styles.divider} />
      <p className={styles.note}>{t("settings.criticHint")}</p>
      <label>
        {t("settings.criticKey")}
        <input
          type="password"
          value={criticKey}
          onChange={(e) => setCriticKey(e.target.value)}
          placeholder="sk-…（可选）"
          autoComplete="off"
        />
      </label>
      <label>
        {t("settings.criticBaseUrl")}
        <input
          type="text"
          value={criticBaseUrl}
          onChange={(e) => setCriticBaseUrl(e.target.value)}
          placeholder="https://api.deepseek.com"
        />
      </label>
      <label>
        {t("settings.criticModel")}
        <input
          type="text"
          value={criticModel}
          onChange={(e) => setCriticModel(e.target.value)}
          placeholder="deepseek-v4-flash"
        />
      </label>
      <div className={styles.llmActions}>
        <button type="button" className={styles.primary} onClick={save}>
          {t("settings.save")}
        </button>
        <button
          type="button"
          className={styles.ghost}
          disabled={testing}
          onClick={() => void runTest()}
        >
          {testing ? t("settings.testing") : t("settings.testConn")}
        </button>
        <button
          type="button"
          className={styles.ghost}
          onClick={() => {
            setApiKey("");
            persist(
              {
                apiKey: "",
                baseUrl,
                model,
                criticKey,
                criticBaseUrl,
                criticModel,
              },
              { clearAccountKey: true }
            );
            if (storageMode !== "account") setSavedNote("");
            setTestResult(null);
          }}
        >
          {t("settings.clearMainKey")}
        </button>
        <button type="button" className={styles.ghost} onClick={load}>
          {t("settings.refresh")}
        </button>
      </div>
    </div>
  );
}

function BgPanPreview({  image,
  scale,
  opacity,
  panX,
  panY,
  onPan,
  onHoldChange,
}: {
  image: string;
  scale: number;
  opacity: number;
  panX: number;
  panY: number;
  onPan: (x: number, y: number) => void;
  onHoldChange?: (holding: boolean) => void;
}) {
  const drag = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const [holding, setHolding] = useState(false);

  useEffect(() => {
    onHoldChange?.(holding);
  }, [holding, onHoldChange]);

  useEffect(() => {
    if (!holding) return;
    const onMove = (e: PointerEvent) => {
      if (!drag.current) return;
      const dx = e.clientX - drag.current.startX;
      const dy = e.clientY - drag.current.startY;
      onPan(drag.current.originX + dx, drag.current.originY + dy);
    };
    const onUp = () => {
      drag.current = null;
      setHolding(false);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [holding, onPan]);

  return (
    <div className={styles.bgPreviewWrap}>
      <div
        className={styles.bgPreview}
        style={{
          backgroundImage: `url(${JSON.stringify(image)})`,
          backgroundSize: `${scale * 100}%`,
          backgroundPosition: `calc(50% + ${panX}px) calc(50% + ${panY}px)`,
          opacity,
          cursor: holding ? "grabbing" : "grab",
        }}
        onPointerDown={(e) => {
          e.preventDefault();
          drag.current = {
            startX: e.clientX,
            startY: e.clientY,
            originX: panX,
            originY: panY,
          };
          setHolding(true);
        }}
        role="presentation"
        title="按住并拖动以调整取景区"
      />
      <p className={styles.bgDragHint}>按住预览区可平移取景；松手前旁白会一直陪着。</p>
    </div>
  );
}

export function SettingsModal({ open, onClose, settings, onChange }: Props) {
  const [pane, setPane] = useState<Pane>("theme");
  const deskPetOn = useSyncExternalStore(
    subscribeDeskPet,
    () => getDeskPetState().enabled,
    () => getDeskPetState().enabled
  );
  const clickFxOn = useSyncExternalStore(
    subscribeClickFx,
    loadClickFx,
    loadClickFx
  );
  const musicBarOn = useSyncExternalStore(
    subscribeMusicBar,
    loadMusicBar,
    loadMusicBar
  );
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // 取景拖拽时的占位回调（立绘已移除，保留接口）
  const onBgHold = useCallback((_holding: boolean) => {}, []);

  if (!open) return null;

  function patch(p: Partial<AppSettings>) {
    const next = { ...settings, ...p };
    onChange(next);
    applySettingsToDom(next);
  }

  function setTheme(theme: ThemeMode) {
    patch({ theme });
  }

  async function onBgFile(file: File) {
    if (!file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => {
      const data = String(reader.result || "");
      patch({
        bgImage: data,
        bgPanX: 0,
        bgPanY: 0,
        // Deep artworks read better with a bit more presence + scrim
        bgOpacity: Math.max(settings.bgOpacity, 0.48),
        bgScrim: Math.max(settings.bgScrim ?? 0.42, 0.45),
        // Keep current glass preference (do not force back to auto)
      });
    };
    reader.readAsDataURL(file);
  }

  return (
    <div className={styles.backdrop} onClick={onClose} role="presentation">
      <div
        className={styles.modal}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="设置"
      >
        <header className={styles.head}>
          <div className={styles.headBanner} aria-hidden />
          <h2>
            <span className={styles.headIdx} aria-hidden>
              CFG
            </span>
            设置
          </h2>
          <button type="button" className={styles.close} onClick={onClose}>
            ×
          </button>
        </header>
        <div className={styles.body}>
          <nav className={styles.nav}>
            {(
              [
                ["theme", "01", t("settings.theme")],
                ["bg", "02", t("settings.wallpaper")],
                ["usage", "03", t("settings.usage")],
                ["llm", "04", t("settings.llm")],
              ] as const
            ).map(([id, idx, label]) => (
              <button
                key={id}
                type="button"
                className={pane === id ? styles.navActive : styles.navBtn}
                onClick={() => setPane(id)}
              >
                <span className={styles.navIdx} aria-hidden>
                  {idx}
                </span>
                {label}
              </button>
            ))}
          </nav>
          <div className={styles.content}>
            {pane === "theme" && (
              <div className={styles.form}>
                <p className={styles.note}>日间 / 夜间，以及全局字体大小。</p>
                <div className={styles.themeRow}>
                  <button
                    type="button"
                    className={
                      settings.theme === "day" ? styles.themeActive : styles.themeCard
                    }
                    onClick={() => setTheme("day")}
                  >
                    <span className={styles.themePreviewDay} />
                    日间模式
                  </button>
                  <button
                    type="button"
                    className={
                      settings.theme === "night" ? styles.themeActive : styles.themeCard
                    }
                    onClick={() => setTheme("night")}
                  >
                    <span className={styles.themePreviewNight} />
                    夜间模式
                  </button>
                </div>
                <label>
                  字体大小 {Math.round((settings.fontScale ?? 1) * 100)}%
                  <input
                    type="range"
                    min={0.85}
                    max={1.4}
                    step={0.05}
                    value={settings.fontScale ?? 1}
                    onChange={(e) => patch({ fontScale: Number(e.target.value) })}
                  />
                </label>
                <p
                  className={styles.fontPreview}
                  style={{ fontSize: `calc(1rem * ${settings.fontScale ?? 1})` }}
                >
                  预览：林夏站在雨夜月台上，听见末班广播。
                </p>
                <button
                  type="button"
                  className={styles.ghost}
                  onClick={() => patch({ fontScale: 1 })}
                >
                  恢复默认字号
                </button>
                <label>
                  桌宠
                  <select
                    value={deskPetOn ? "1" : "0"}
                    onChange={(e) => setDeskPetEnabled(e.target.value === "1")}
                    data-testid="desk-pet-toggle"
                  >
                    <option value="1">开启（可拖动 · 右键菜单）</option>
                    <option value="0">关闭</option>
                  </select>
                  <span className={styles.note}>
                    桌面小助手：点击换心情冒泡，右键有菜单；位置自动记住。
                  </span>
                </label>
                <label>
                  音乐播放条
                  <select
                    value={musicBarOn ? "1" : "0"}
                    onChange={(e) => {
                      setMusicBar(e.target.value === "1");
                      notifyMusicBar();
                    }}
                    data-testid="music-bar-toggle"
                  >
                    <option value="1">开启（固定在页面底部）</option>
                    <option value="0">关闭</option>
                  </select>
                  <span className={styles.note}>
                    底部听歌：搜索/列表/歌词；关闭后立即停止播放并隐藏。
                  </span>
                </label>
                <label>
                  点击特效
                  <select
                    value={clickFxOn ? "1" : "0"}
                    onChange={(e) => {
                      setClickFx(e.target.value === "1");
                      notifyClickFx();
                    }}
                    data-testid="click-fx-toggle"
                  >
                    <option value="1">开启（赛璐璐圆环 + 粒子）</option>
                    <option value="0">关闭</option>
                  </select>
                  <span className={styles.note}>
                    点击处的轻量装饰动画；纯视觉、不拦截点击，输入框内不触发。
                  </span>
                </label>
                <p className={styles.note}>
                  模型连接信息（API Key、Base URL、模型名）在「模型」页签配置：可加密保存到你的账号（跨设备），也可只存当前浏览器。之后的 AI 调用会用你配置的模型。
                </p>
              </div>
            )}

            {pane === "bg" && (
              <div className={styles.form}>
                <p className={styles.note}>
                  导入图片后会铺满工作室底层。可在预览区<strong>拖动</strong>
                  调整取景区，并调节缩放与透明度。
                </p>
                <div className={styles.bgActions}>
                  <button
                    type="button"
                    className={styles.primary}
                    onClick={() => fileRef.current?.click()}
                  >
                    导入图片
                  </button>
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/*"
                    hidden
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void onBgFile(f);
                      e.target.value = "";
                    }}
                  />
                  <button
                    type="button"
                    className={styles.ghost}
                    onClick={() =>
                      patch({
                        bgImage: "",
                        bgPanX: 0,
                        bgPanY: 0,
                        bgScale: 1,
                      })
                    }
                  >
                    清除背景
                  </button>
                </div>
                {settings.bgImage ? (
                  <BgPanPreview
                    image={settings.bgImage}
                    scale={settings.bgScale}
                    opacity={settings.bgOpacity}
                    panX={settings.bgPanX}
                    panY={settings.bgPanY}
                    onPan={(bgPanX, bgPanY) => patch({ bgPanX, bgPanY })}
                    onHoldChange={onBgHold}
                  />
                ) : (
                  <p className={styles.note}>尚未导入图片。</p>
                )}
                <label>
                  缩放 {Math.round(settings.bgScale * 100)}%
                  <input
                    type="range"
                    min={0.5}
                    max={3}
                    step={0.05}
                    value={settings.bgScale}
                    onChange={(e) => patch({ bgScale: Number(e.target.value) })}
                  />
                </label>
                <label>
                  透明度 {Math.round(settings.bgOpacity * 100)}%
                  <input
                    type="range"
                    min={0.08}
                    max={0.85}
                    step={0.01}
                    value={settings.bgOpacity}
                    onChange={(e) => patch({ bgOpacity: Number(e.target.value) })}
                  />
                </label>
                <label>
                  可读性暗角 {Math.round((settings.bgScrim ?? 0.42) * 100)}%
                  <input
                    type="range"
                    min={0}
                    max={0.85}
                    step={0.01}
                    value={settings.bgScrim ?? 0.42}
                    onChange={(e) => patch({ bgScrim: Number(e.target.value) })}
                  />
                </label>
                <p className={styles.note}>
                  面板玻璃：有壁纸时生效。「自动」跟随日间→雾色 /
                  夜间→墨色；也可手动锁定。
                </p>
                <div className={styles.themeRow}>
                  {(
                    [
                      ["auto", "自动"],
                      ["ink", "墨色玻璃"],
                      ["mist", "雾色玻璃"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className={
                        (settings.panelGlass ?? "auto") === id
                          ? styles.themeActive
                          : styles.themeCard
                      }
                      onClick={() => patch({ panelGlass: id as PanelGlass })}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  className={styles.primary}
                  onClick={() =>
                    patch({
                      panelGlass: "ink",
                      bgScrim: 0.5,
                      theme: "night",
                      bgOpacity: Math.max(settings.bgOpacity, 0.45),
                    })
                  }
                >
                  一键适配深色壁纸
                </button>
                <button
                  type="button"
                  className={styles.ghost}
                  onClick={() => patch({ bgPanX: 0, bgPanY: 0 })}
                >
                  复位取景位置
                </button>
              </div>
            )}
            {pane === "usage" && <UsagePane />}
            {pane === "llm" && <LlmPane />}
          </div>
        </div>
      </div>
    </div>
  );
}

export function SettingsGear({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className={styles.gear}
      onClick={onClick}
      title="设置"
      aria-label="打开设置"
    >
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
        <path
          fill="currentColor"
          d="M19.14 12.94c.04-.31.06-.63.06-.94s-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.1 7.1 0 0 0-1.63-.94l-.36-2.54A.5.5 0 0 0 14.9 2h-3.8a.5.5 0 0 0-.49.42l-.36 2.54c-.58.23-1.12.54-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L3.71 8.84a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.13.23.4.32.64.22l2.39-.96c.5.4 1.05.72 1.63.94l.36 2.54c.05.25.25.42.49.42h3.8c.24 0 .44-.17.49-.42l.36-2.54c.58-.23 1.12-.54 1.63-.94l2.39.96c.24.1.51 0 .64-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7z"
        />
      </svg>
    </button>
  );
}
