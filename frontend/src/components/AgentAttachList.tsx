import type { AgentAttachment } from "../api/client";
import styles from "./AgentChat.module.css";

type Props = {
  attachments: AgentAttachment[];
  busy: boolean;
  attachBusy: boolean;
  conversationId: string | null;
  onRemove: (index: number) => void;
  onIngest: () => void;
  onScan: () => void;
};

/**
 * 待发送附件列表 + 快捷动作（写入设定页 / 整理关系时间线）。
 * 纯受控展示——上传 / 写入 / 扫描逻辑留在 AgentChat。
 *
 * 两个捷径按钮**都不直接写**：它们只是"把这句话替你说了"，点了由 AgentChat 摆出方案卡片，
 * 确认后才落库。理由见 AgentChat.proposeSettingsIngest 的注释（线上有人附了改写稿、
 * 手滑点到这里，正文就被当成资料写进了设定页）。
 */
export function AgentAttachList({
  attachments,
  busy,
  attachBusy,
  conversationId,
  onRemove,
  onIngest,
  onScan,
}: Props) {
  if (attachments.length === 0) return null;
  return (
    <>
      <ul className={styles.attachList} aria-label="待发送附件">
        {attachments.map((a, i) => (
          <li key={`${a.filename}-${i}`}>
            <span title={a.warning || undefined}>
              {a.filename}
              <em>{a.chars ?? a.text.length} 字</em>
            </span>
            <button
              type="button"
              disabled={busy || attachBusy}
              onClick={() => onRemove(i)}
            >
              移除
            </button>
          </li>
        ))}
      </ul>
      <div className={styles.attachActions}>
        <button
          type="button"
          className={styles.attachActionBtn}
          disabled={busy || attachBusy || !conversationId}
          title="捷径：等价于说「根据附件更新设定」——会先给方案，确认后才写"
          onClick={onIngest}
        >
          写入设定页
        </button>
        <button
          type="button"
          className={styles.attachActionBtn}
          disabled={busy || attachBusy || !conversationId}
          title="捷径：等价于说「整理关系进待审」——会先给方案，确认后才扫"
          onClick={onScan}
        >
          整理关系/时间线
        </button>
      </div>
    </>
  );
}
