"use client";

import { useEffect, useRef, useState } from "react";
import {
  applySettingsToDom,
  DEFAULT_SETTINGS,
  saveSettings,
  type AppSettings,
  type ThemeMode,
} from "@/lib/settings";
import styles from "./SettingsModal.module.css";

type Props = {
  open: boolean;
  onClose: () => void;
  settings: AppSettings;
  onChange: (s: AppSettings) => void;
};

type Pane = "help" | "api" | "theme" | "bg";

function BgPanPreview({
  image,
  scale,
  opacity,
  panX,
  panY,
  onPan,
}: {
  image: string;
  scale: number;
  opacity: number;
  panX: number;
  panY: number;
  onPan: (x: number, y: number) => void;
}) {
  const drag = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      if (!drag.current) return;
      const dx = e.clientX - drag.current.startX;
      const dy = e.clientY - drag.current.startY;
      onPan(drag.current.originX + dx, drag.current.originY + dy);
    };
    const onUp = () => {
      drag.current = null;
      setDragging(false);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [dragging, onPan]);

  return (
    <div className={styles.bgPreviewWrap}>
      <div
        className={styles.bgPreview}
        style={{
          backgroundImage: `url(${JSON.stringify(image)})`,
          backgroundSize: `${scale * 100}%`,
          backgroundPosition: `calc(50% + ${panX}px) calc(50% + ${panY}px)`,
          opacity,
          cursor: dragging ? "grabbing" : "grab",
        }}
        onPointerDown={(e) => {
          e.preventDefault();
          drag.current = {
            startX: e.clientX,
            startY: e.clientY,
            originX: panX,
            originY: panY,
          };
          setDragging(true);
        }}
        role="presentation"
        title="拖动调整取景区"
      />
      <p className={styles.bgDragHint}>在预览区拖动以平移背景取景</p>
    </div>
  );
}

export function SettingsModal({ open, onClose, settings, onChange }: Props) {
  const [pane, setPane] = useState<Pane>("help");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  function patch(p: Partial<AppSettings>) {
    const next = { ...settings, ...p };
    onChange(next);
    saveSettings(next);
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
        bgOpacity: Math.max(settings.bgOpacity, 0.35),
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
          <h2>设置</h2>
          <button type="button" className={styles.close} onClick={onClose}>
            ×
          </button>
        </header>
        <div className={styles.body}>
          <nav className={styles.nav}>
            {(
              [
                ["help", "快捷入门"],
                ["api", "API 接入"],
                ["theme", "外观"],
                ["bg", "工具背景"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={pane === id ? styles.navActive : styles.navBtn}
                onClick={() => setPane(id)}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className={styles.content}>
            {pane === "help" && (
              <div className={styles.help}>
                <h3>5 分钟上手</h3>
                <ol>
                  <li>
                    在「API 接入」填入 DeepSeek Key（也可继续用
                    <code>packages/web/.env.local</code>）。
                  </li>
                  <li>
                    右侧<strong>审稿 Agent</strong>可拖动；点「—」收成标签，「□」放大。
                  </li>
                  <li>
                    Agent 顶部有<strong>续写 / 改写选区 / 润色 / 分支 / 大纲 / 统一语气</strong>
                    ，也可自由对话写剧情。
                  </li>
                  <li>
                    剧本页拖选文字后，改写/润色会带着选区发给编辑。
                  </li>
                  <li>
                    「地图」可平移缩放；「分析」含分支树、角色关系、时间线、语气报告。
                  </li>
                  <li>设置 →「外观」可切换日夜间并调整字体大小。</li>
                  <li>导出页可下载 .rpy 或工程 JSON 备份。</li>
                </ol>
                <p>
                  提示：Agent 默认像轻小说责编——先谈戏、给稿；你说「写入剧本」才会改工程。
                </p>
              </div>
            )}

            {pane === "api" && (
              <div className={styles.form}>
                <label>
                  API Key
                  <input
                    type="password"
                    value={settings.apiKey}
                    onChange={(e) => patch({ apiKey: e.target.value })}
                    placeholder="sk-...（优先于 .env.local）"
                    autoComplete="off"
                  />
                </label>
                <label>
                  Base URL
                  <input
                    value={settings.apiBaseUrl}
                    onChange={(e) => patch({ apiBaseUrl: e.target.value })}
                    placeholder="https://api.deepseek.com"
                  />
                </label>
                <label>
                  模型
                  <input
                    value={settings.apiModel}
                    onChange={(e) => patch({ apiModel: e.target.value })}
                    placeholder="deepseek-chat / deepseek-v4-flash …"
                  />
                </label>
                <label>
                  写作工艺 Skills
                  <select
                    value={settings.craftMode}
                    onChange={(e) =>
                      patch({
                        craftMode: e.target.value as
                          | "auto"
                          | "off"
                          | "lite"
                          | "full",
                      })
                    }
                  >
                    <option value="auto">自动（推荐：Agent 按任务/风险判断）</option>
                    <option value="full">总是全套</option>
                    <option value="lite">总是轻量</option>
                    <option value="off">总是关闭</option>
                  </select>
                </label>
                <p className={styles.note}>
                  自动模式：讨论关闭工艺；润色/分支用轻量；续写/写戏在设定厚或章短时用全套，章已很密时偏轻量。对话里也可说「关闭工艺」「短拍」「强制工艺」。
                </p>
                <label>
                  写作自检（第二遍）
                  <select
                    value={settings.selfReview}
                    onChange={(e) =>
                      patch({
                        selfReview: e.target.value as "auto" | "on" | "off",
                      })
                    }
                  >
                    <option value="auto">
                      自动（续写/写戏/改写/润色会自检社会常理与叙事）
                    </option>
                    <option value="on">总是开启（写作类任务）</option>
                    <option value="off">关闭（更快、少一次调用）</option>
                  </select>
                </label>
                <p className={styles.note}>
                  自检会多一次模型调用：先出稿，再按「陌生人距离、盘问串、信息动机、惜话」等审查，不通过则改写后再写入。不能消灭所有 AI 味，但能拦住一批明显违背常理的稿。
                </p>
                <p className={styles.note}>
                  <strong>降低「自己审自己」盲区：</strong>
                  ① 规则引擎先查盘问串/乒乓（不靠模型自觉）；②
                  下方可填<strong>另一套责编模型</strong>（如写作用
                  DeepSeek、责编用 Claude/经 OpenRouter）——交叉审查最有效。
                </p>
                <label>
                  责编模型（可空=与上面相同）
                  <input
                    value={settings.criticApiModel}
                    onChange={(e) => patch({ criticApiModel: e.target.value })}
                    placeholder="留空则与写作模型相同；建议换一家"
                  />
                </label>
                <label>
                  责编 Base URL（可空）
                  <input
                    value={settings.criticApiBaseUrl}
                    onChange={(e) =>
                      patch({ criticApiBaseUrl: e.target.value })
                    }
                    placeholder="例如 https://openrouter.ai/api/v1"
                  />
                </label>
                <label>
                  责编 API Key（可空）
                  <input
                    type="password"
                    value={settings.criticApiKey}
                    onChange={(e) => patch({ criticApiKey: e.target.value })}
                    placeholder="留空则复用上方 Key"
                    autoComplete="off"
                  />
                </label>
                <p className={styles.note}>
                  <strong>写作向模型怎么选（本工作室走 OpenAI 兼容接口）</strong>
                  <br />
                  · 文笔/人设口吻优先：Claude 系（如 Claude Sonnet / Opus，或专门向创作的
                  Fable 等）通常更自然、更少「AI 说明书腔」。
                  <br />
                  · 综合创作+改稿：GPT-5
                  系也不错，偏稳、好跟指令。
                  <br />
                  · 长上下文世界书：Gemini Pro 类窗口大，适合厚设定检索。
                  <br />
                  · 性价比/自用日更：DeepSeek（你现在的配置）够用，但文学韵律往往更平——适合草稿与批量，定稿可换更强写作模型。
                  <br />
                  · 接法：把 Base URL 改成 OpenRouter / 硅基流动 / 官方兼容网关，Model
                  填对应 id，Key 填该平台的 key。
                </p>
                <button
                  type="button"
                  className={styles.ghost}
                  onClick={() =>
                    patch({
                      apiKey: "",
                      apiBaseUrl: DEFAULT_SETTINGS.apiBaseUrl,
                      apiModel: DEFAULT_SETTINGS.apiModel,
                      craftMode: DEFAULT_SETTINGS.craftMode,
                      selfReview: DEFAULT_SETTINGS.selfReview,
                      criticApiKey: "",
                      criticApiBaseUrl: "",
                      criticApiModel: "",
                    })
                  }
                >
                  清除本机 API 覆盖
                </button>
              </div>
            )}

            {pane === "theme" && (
              <div className={styles.form}>
                <p className={styles.note}>日间 / 夜间，以及全局字体大小。</p>
                <div className={styles.themeRow}>
                  <button
                    type="button"
                    className={
                      settings.theme === "day"
                        ? styles.themeActive
                        : styles.themeCard
                    }
                    onClick={() => setTheme("day")}
                  >
                    <span className={styles.themePreviewDay} />
                    日间模式
                  </button>
                  <button
                    type="button"
                    className={
                      settings.theme === "night"
                        ? styles.themeActive
                        : styles.themeCard
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
                    onChange={(e) =>
                      patch({ fontScale: Number(e.target.value) })
                    }
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
              </div>
            )}

            {pane === "bg" && (
              <div className={styles.form}>
                <p className={styles.note}>
                  导入图片后会铺满工作室底层。可在预览区<strong>拖动</strong>调整取景区，并调节缩放与透明度。
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
                    onChange={(e) =>
                      patch({ bgScale: Number(e.target.value) })
                    }
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
                    onChange={(e) =>
                      patch({ bgOpacity: Number(e.target.value) })
                    }
                  />
                </label>
                <button
                  type="button"
                  className={styles.ghost}
                  onClick={() => patch({ bgPanX: 0, bgPanY: 0 })}
                >
                  复位取景位置
                </button>
              </div>
            )}
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
