import { useEffect, useRef, useState } from "react";
import {
  applySettingsToDom,
  type AppSettings,
  type PanelGlass,
  type ThemeMode,
} from "../lib/settings";
import styles from "./SettingsModal.module.css";

type Props = {
  open: boolean;
  onClose: () => void;
  settings: AppSettings;
  onChange: (s: AppSettings) => void;
};

type Pane = "theme" | "bg";

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
  const [pane, setPane] = useState<Pane>("theme");
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
          <h2>设置</h2>
          <button type="button" className={styles.close} onClick={onClose}>
            ×
          </button>
        </header>
        <div className={styles.body}>
          <nav className={styles.nav}>
            {(
              [
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
                <p className={styles.note}>
                  模型 API Key、Base URL、写作工艺与自检均由服务端环境变量配置，前端不参与。
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
                <label>
                  可读性暗角 {Math.round((settings.bgScrim ?? 0.42) * 100)}%
                  <input
                    type="range"
                    min={0}
                    max={0.85}
                    step={0.01}
                    value={settings.bgScrim ?? 0.42}
                    onChange={(e) =>
                      patch({ bgScrim: Number(e.target.value) })
                    }
                  />
                </label>
                <p className={styles.note}>
                  面板玻璃：有壁纸时生效。「自动」跟随日间→雾色 / 夜间→墨色；也可手动锁定。
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
                      onClick={() =>
                        patch({ panelGlass: id as PanelGlass })
                      }
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
