import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { HELP_DISCLAIMER, HELP_FAQ, HELP_QUICK } from "../lib/helpContent";
import {
  LN_QUICK_START_FAQ,
  LN_QUICK_START_INTRO,
  LN_QUICK_START_STEPS,
  LN_QUICK_START_TITLE,
} from "../lib/lnQuickStart";
import styles from "./HelpSheet.module.css";

type Props = {
  open: boolean;
  onClose: () => void;
  /** 嵌进桌面窗口里用：不画遮罩/不抢 ESC（窗口自己有标题栏与关闭按钮） */
  embedded?: boolean;
};

/**
 * 帮助面板按"你写的是什么"分成两条路。
 *
 * 为什么分：通用帮助是给视觉小说作者的（顶栏写着剧本 / 角色工坊 / 地图），
 * 而轻小说作者进来只想问"先干什么、一章写多少、拿什么投稿"。把两者混在一页里，
 * 前者嫌吵、后者要在术语里先学一遍另一套东西。这里不做用户画像猜测，直接给个开关。
 */
export function HelpSheet({ open, onClose, embedded = false }: Props) {
  const [path, setPath] = useState<"vn" | "ln">("vn");
  useEffect(() => {
    if (!open || embedded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, embedded]);

  if (!open) return null;
  const ln = path === "ln";
  const sheet = (
    <div className={embedded ? styles.sheetEmbedded : styles.sheet} onClick={(e) => e.stopPropagation()}>
      <div className={styles.body}>
        <p className={styles.idx}>HOW TO</p>
        <h2 id="help-sheet-title" className={styles.title}>
          {ln ? LN_QUICK_START_TITLE : "使用说明"}
        </h2>
        <div className={styles.pathTabs} role="tablist" aria-label="你写的是哪一种">
          <button
            type="button"
            role="tab"
            aria-selected={!ln}
            className={ln ? styles.pathOff : styles.pathOn}
            onClick={() => setPath("vn")}
          >
            视觉小说 / 游戏脚本
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={ln}
            className={ln ? styles.pathOn : styles.pathOff}
            onClick={() => setPath("ln")}
          >
            轻小说 / 网文
          </button>
        </div>
        {ln ? (
          <>
            <p className={styles.hint}>{LN_QUICK_START_INTRO}</p>
            <div className={styles.sections}>
              {LN_QUICK_START_STEPS.map((s, i) => (
                <section key={s.id}>
                  <h3>
                    {i + 1}. {s.title}
                  </h3>
                  <p className={styles.stepWhere}>在哪：{s.where}</p>
                  <p>{s.what}</p>
                  <p className={styles.stepWhy}>为什么：{s.why}</p>
                  {s.pitfall ? <p className={styles.stepPitfall}>容易踩的坑：{s.pitfall}</p> : null}
                </section>
              ))}
            </div>
            <div className={styles.faqList}>
              {LN_QUICK_START_FAQ.map((item) => (
                <details key={item.q}>
                  <summary>{item.q}</summary>
                  <p>{item.a}</p>
                </details>
              ))}
            </div>
          </>
        ) : (
          <>
            <div className={styles.sections}>
              {HELP_QUICK.map((s) => (
                <section key={s.title}>
                  <h3>{s.title}</h3>
                  <p>{s.body}</p>
                </section>
              ))}
            </div>
            <div className={styles.faqList}>
              {HELP_FAQ.map((item) => (
                <details key={item.q}>
                  <summary>{item.q}</summary>
                  <p>{item.a}</p>
                </details>
              ))}
            </div>
          </>
        )}
        <p className={styles.disclaimer}>{HELP_DISCLAIMER}</p>
        <div className={styles.actions}>
          <Link
            to="/guide"
            target="_blank"
            rel="noreferrer"
            className={styles.link}
          >
            打开完整使用指南
          </Link>
          {!embedded ? (
            <button type="button" className={styles.primary} onClick={onClose}>
              知道了
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
  if (embedded) return sheet;
  return (
    <div
      className={styles.backdrop}
      role="dialog"
      aria-modal="true"
      aria-labelledby="help-sheet-title"
      onClick={onClose}
    >
      {sheet}
    </div>
  );
}
