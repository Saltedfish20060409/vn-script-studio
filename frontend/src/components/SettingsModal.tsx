import { useCallback, useEffect, useRef, useState } from "react";
import {
  applySettingsToDom,
  type AppSettings,
  type PanelGlass,
  type ServerSettingsOut,
  type ThemeMode,
} from "../lib/settings";
import { getSettings, getUsage, putSettings, type UsageTotals } from "../api/misc";
import { MascotFigure } from "./MascotFigure";
import { mascotLine } from "../lib/mascotCopy";
import styles from "./SettingsModal.module.css";

type Props = {
  open: boolean;
  onClose: () => void;
  settings: AppSettings;
  onChange: (s: AppSettings) => void;
};

type Pane = "theme" | "bg" | "usage" | "llm";

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

/** 用户级 LLM 凭据：优先用自己的 key，留空则回退服务端环境变量。 */
function LlmPane() {
  const [loaded, setLoaded] = useState<ServerSettingsOut | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [criticKey, setCriticKey] = useState("");
  const [criticBaseUrl, setCriticBaseUrl] = useState("");
  const [criticModel, setCriticModel] = useState("");

  const load = useCallback(() => {
    setError("");
    getSettings()
      .then((out) => {
        setLoaded(out);
        setBaseUrl(out.api_base_url ?? "");
        setModel(out.api_model ?? "");
        setCriticBaseUrl(out.critic_api_base_url ?? "");
        setCriticModel(out.critic_api_model ?? "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "读取失败"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await putSettings({
        // api_key 仅在用户输入新值或显式清空时发送；留空保持不变
        api_key: apiKey === "" ? undefined : apiKey,
        api_base_url: baseUrl,
        api_model: model,
        critic_api_key: criticKey === "" ? undefined : criticKey,
        critic_api_base_url: criticBaseUrl,
        critic_api_model: criticModel,
      });
      setApiKey("");
      setCriticKey("");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.form}>
      <p className={styles.note}>
        配置你自己的模型 Key 后，AI 请求将优先使用该 Key（按账号隔离，服务端加密存储）。
        留空则回退服务端环境变量配置。
      </p>
      {error && <p className={styles.error}>{error}</p>}
      <label>
        主模型 API Key
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={
            loaded?.has_api_key ? `已配置 ${loaded.api_key_masked}` : "sk-…"
          }
          autoComplete="off"
        />
      </label>
      <label>
        Base URL
        <input
          type="text"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.deepseek.com"
        />
      </label>
      <label>
        模型名
        <input
          type="text"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="deepseek-chat"
        />
      </label>
      <hr className={styles.divider} />
      <p className={styles.note}>可选：独立的评审模型（critic，改稿对照时使用）。</p>
      <label>
        评审模型 API Key
        <input
          type="password"
          value={criticKey}
          onChange={(e) => setCriticKey(e.target.value)}
          placeholder={
            loaded?.has_critic_api_key
              ? `已配置 ${loaded.critic_api_key_masked}`
              : "sk-…（可选）"
          }
          autoComplete="off"
        />
      </label>
      <label>
        评审 Base URL
        <input
          type="text"
          value={criticBaseUrl}
          onChange={(e) => setCriticBaseUrl(e.target.value)}
          placeholder="https://api.deepseek.com"
        />
      </label>
      <label>
        评审模型名
        <input
          type="text"
          value={criticModel}
          onChange={(e) => setCriticModel(e.target.value)}
          placeholder="deepseek-chat"
        />
      </label>
      <div className={styles.llmActions}>
        <button
          type="button"
          className={styles.primary}
          disabled={saving}
          onClick={() => void save()}
        >
          {saving ? "保存中…" : "保存凭据"}
        </button>
        <button
          type="button"
          className={styles.ghost}
          onClick={() => void (async () => {
            setSaving(true);
            setError("");
            try {
              await putSettings({ api_key: "" });
              setApiKey("");
              load();
            } catch (e) {
              setError(e instanceof Error ? e.message : "清除失败");
            } finally {
              setSaving(false);
            }
          })()}
        >
          清除主 Key
        </button>
        <button type="button" className={styles.ghost} onClick={load}>
          刷新
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
  const fileRef = useRef<HTMLInputElement>(null);
  const idleLineRef = useRef(mascotLine("settings"));
  const panLineRef = useRef(mascotLine("settingsPan"));
  const [holdingBg, setHoldingBg] = useState(false);

  useEffect(() => {
    if (!open) {
      setHoldingBg(false);
      return;
    }
    idleLineRef.current = mascotLine("settings");
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const onBgHold = useCallback((holding: boolean) => {
    setHoldingBg((prev) => {
      if (holding && !prev) {
        panLineRef.current = mascotLine("settingsPan");
      }
      return holding;
    });
  }, []);

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

  const mascotText = holdingBg ? panLineRef.current : idleLineRef.current;

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
                ["theme", "01", "外观"],
                ["bg", "02", "工具背景"],
                ["usage", "03", "用量"],
                ["llm", "04", "模型"],
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
                <p className={styles.note}>
                  模型 API Key 可在「模型」页签按账号配置（可选）；写作工艺与自检
                  由服务端环境变量配置。
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
        <div className={styles.mascotDock} aria-hidden>
          <MascotFigure
            className={styles.mascotFigure}
            size="md"
            mood={holdingBg ? "cheer" : "idle"}
            line={mascotText}
          />
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
