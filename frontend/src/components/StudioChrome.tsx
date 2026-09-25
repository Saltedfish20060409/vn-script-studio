import type { ReactNode } from "react";
import type { ViewSize } from "../lib/viewDrawerSize";
import styles from "./StudioChrome.module.css";

type BackstageProps = {
  title: string;
  onClose: () => void;
  children: ReactNode;
};

/** 文件菜单二级页：盖住稿纸中央，关了回到正文。 */
export function FileBackstage({ title, onClose, children }: BackstageProps) {
  return (
    <div
      className={styles.backstage}
      data-testid="file-backstage"
      role="dialog"
      aria-label={title}
    >
      <div className={styles.backstageBar}>
        <button
          type="button"
          className={styles.backBtn}
          data-testid="backstage-close"
          onClick={onClose}
        >
          ← 返回正文
        </button>
        <h2 className={styles.backstageTitle}>{title}</h2>
      </div>
      <div className={styles.backstageBody}>{children}</div>
    </div>
  );
}

type DrawerProps = {
  title: string;
  /** 宽度档：narrow（瞥一眼）/ wide（要宽度）/ full（专心改）。默认按面板给，见 lib/viewDrawerSize.ts */
  size?: ViewSize;
  onToggleSize?: () => void;
  onClose: () => void;
  children: ReactNode;
};

/**
 * 视图抽屉：右侧滑出，稿纸仍在底下不卸载。
 *
 * 宽度是这里最要紧的决定：把设定/角色/地图/剧情状态/结构分析一律做成 560px，
 * 会让"卡片网格、结构表、rail"这些本来就吃宽度的面板挤成一列——
 * 用户的原话是"不如前版看着详细易懂"。所以宽度按面板给默认档，
 * 并在标题栏给一个开关让作者自己决定"瞥一眼"还是"专心改"。
 */
export function StudioViewDrawer({
  title,
  size = "narrow",
  onToggleSize,
  onClose,
  children,
}: DrawerProps) {
  return (
    <aside
      className={`${styles.drawer} ${size === "wide" ? styles.drawerWide : ""} ${
        size === "full" ? styles.drawerFull : ""
      }`}
      data-testid="view-drawer"
      data-size={size}
      aria-label={title}
    >
      <div className={styles.drawerBar}>
        <h2 className={styles.drawerTitle}>{title}</h2>
        {onToggleSize ? (
          <button
            type="button"
            className={styles.drawerSizeBtn}
            data-testid="drawer-size-toggle"
            aria-pressed={size === "full"}
            title={size === "full" ? "收窄，让出稿纸" : "铺满，看清全部"}
            onClick={onToggleSize}
          >
            {size === "full" ? "⤡ 收窄" : "⤢ 铺满"}
          </button>
        ) : null}
        <button
          type="button"
          className={styles.backBtn}
          data-testid="drawer-close"
          onClick={onClose}
        >
          关闭
        </button>
      </div>
      <div className={styles.drawerBody}>{children}</div>
    </aside>
  );
}
