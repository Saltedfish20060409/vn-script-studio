import { mascotLine } from "../lib/mascotCopy";
import styles from "./SaveConflictDialog.module.css";

export type SaveConflictChoice = "keep_local" | "take_server" | "download";

type Props = {
  open: boolean;
  localTitle?: string;
  serverUpdatedAt?: string;
  onChoose: (choice: SaveConflictChoice) => void;
};

/** Shown when PUT /projects hits 409 — never silent-overwrite without choice. */
export function SaveConflictDialog({
  open,
  localTitle,
  serverUpdatedAt,
  onChoose,
}: Props) {
  if (!open) return null;
  const when = serverUpdatedAt
    ? new Date(serverUpdatedAt).toLocaleString()
    : "未知时间";
  return (
    <div className={styles.backdrop} role="presentation">
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label="工程保存冲突"
      >
        <div className={styles.body}>
          <p className={styles.idx}>CONFLICT</p>
          <h3 className={styles.title}>工程版本冲突</h3>
          <p className={styles.line}>{mascotLine("confirmSoft")}</p>
          <p className={styles.msg}>
            「{localTitle || "当前工程"}」在服务器上已有更新（{when}
            ）。本地未保存的修改仍在内存，并已暂存到浏览器。请选择如何处理：
          </p>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => onChoose("keep_local")}
            >
              保留我的修改
            </button>
            <button
              type="button"
              className={styles.ghost}
              onClick={() => onChoose("take_server")}
            >
              使用服务器版本
            </button>
            <button
              type="button"
              className={styles.ghost}
              onClick={() => onChoose("download")}
            >
              先下载本地稿
            </button>
          </div>
          <p className={styles.hint}>
            「保留我的修改」会强制覆盖服务器；「使用服务器」会丢掉本次未同步编辑（本地暂存仍可从浏览器取出）。
          </p>
        </div>
      </div>
    </div>
  );
}
