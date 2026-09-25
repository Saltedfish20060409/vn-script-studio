import type { ReactNode } from "react";
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
  wide?: boolean;
  onClose: () => void;
  children: ReactNode;
};

/** 视图抽屉：右侧滑出，稿纸仍在底下不卸载。 */
export function StudioViewDrawer({ title, wide, onClose, children }: DrawerProps) {
  return (
    <aside
      className={`${styles.drawer} ${wide ? styles.drawerWide : ""}`}
      data-testid="view-drawer"
      aria-label={title}
    >
      <div className={styles.drawerBar}>
        <h2 className={styles.drawerTitle}>{title}</h2>
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
