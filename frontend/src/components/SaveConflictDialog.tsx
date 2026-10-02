import { mascotLine } from "../lib/mascotCopy";
import { PROJECT_CONFLICT_DETAIL } from "../lib/restoreGuard";
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
        aria-label="保存冲突"
      >
        <div className={styles.body}>
          <p className={styles.idx}>CONFLICT</p>
          <h3 className={styles.title}>数据已在其他位置被修改</h3>
          <p className={styles.line}>{mascotLine("confirmSoft")}</p>
          <p className={styles.msg}>
            「{localTitle || "当前工程"}」服务器时间 {when}。
            {PROJECT_CONFLICT_DETAIL}
          </p>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => onChoose("take_server")}
            >
              刷新（用服务器最新版）
            </button>
            <button
              type="button"
              className={styles.ghost}
              onClick={() => onChoose("keep_local")}
            >
              保留本地（覆盖服务器）
            </button>
            <button
              type="button"
              className={styles.ghost}
              onClick={() => onChoose("download")}
            >
              先把我这版下载备份
            </button>
          </div>
          <p className={styles.hint}>
            「刷新」丢弃本地未上传改动并载入服务器版；「保留本地」会覆盖服务器（对方未保存内容会丢）；可先「下载备份」留底。
          </p>
        </div>
      </div>
    </div>
  );
}
