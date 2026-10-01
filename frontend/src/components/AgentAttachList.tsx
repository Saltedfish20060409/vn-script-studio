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
 * 待发送附件 + 快捷动作（写入设定页 / 整理关系时间线）。
 * 纯受控展示——上传 / 写入 / 扫描逻辑留在 AgentChat。
 *
 * 两个捷径按钮**都不直接写**：它们只是"把这句话替你说了"，点了由 AgentChat 摆出方案卡片，
 * 确认后才落库。理由见 AgentChat.proposeSettingsIngest 的注释（线上有人附了改写稿、
 * 手滑点到这里，正文就被当成资料写进了设定页）。
 *
 * **形态：并入底部那一行**（作者反馈"这些东西太挡对话界面"）。
 * 以前这里是三条竖着的：附件列表（1–2 行）、一句常驻说明、捷径按钮一行；再加 AgentChat 的
 * `⚙ 资料` 行，折叠态也要占 4–6 行。现在它只贡献**一行的内容**，由 AgentChat 的 `.footerRow`
 * 统一排成一行（附件多了横向滚，不换行）。
 *
 * 「附件在本次对话里一直有效」那句没有删、也没有只塞进 tooltip：它是**防止线上误解**的
 * （有人以为"上一轮的附件这一轮已经没了"）。现在压成同一行里的「（每轮都会带上）」，
 * 完整句子仍在它的 title 里。
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
      <ul
        className={styles.attachList}
        aria-label="本次对话的附件"
        title="附件在本次对话里一直有效（每一轮都会带上）；不用了就点「移除」。"
      >
        {attachments.map((a, i) => (
          <li key={`${a.filename}-${i}`}>
            <span title={a.warning || undefined}>
              {a.filename}
              <em>{a.chars ?? a.text.length} 字</em>
            </span>
            <button
              type="button"
              disabled={busy || attachBusy}
              title={`移除「${a.filename}」`}
              onClick={() => onRemove(i)}
            >
              移除
            </button>
          </li>
        ))}
      </ul>
      {/* 同一行里的一句短说明：完整句子在它的 title 上（见组件注释） */}
      <span
        className={styles.attachNote}
        title="附件在本次对话里一直有效（每一轮都会带上）；不用了就点「移除」。"
      >
        （每轮都会带上）
      </span>
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
