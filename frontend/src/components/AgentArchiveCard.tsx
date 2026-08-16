import { WriterPortrait } from "./WriterPortrait";
import styles from "./AgentChat.module.css";

export type AgentArchiveCardProps = {
  card: {
    id: string | null;
    name: string;
    role: string;
    blurb: string;
  };
  multiSelect: boolean;
  activeLensIds: string[];
  lensBusy: boolean;
  onClose: () => void;
  onAction: (cardId: string | null) => void;
};

/**
 * 作家档案弹层。纯受控展示——选卡 / 组队 / 关闭逻辑留在 AgentChat。
 */
export function AgentArchiveCard({
  card,
  multiSelect,
  activeLensIds,
  lensBusy,
  onClose,
  onAction,
}: AgentArchiveCardProps) {
  return (
    <div
      className={styles.archiveBackdrop}
      role="presentation"
      onClick={onClose}
    >
      <div
        className={styles.archive}
        role="dialog"
        aria-modal="true"
        aria-label={`${card.name} 档案`}
        onClick={(e) => e.stopPropagation()}
      >
        <WriterPortrait lensId={card.id} size="lg" selected />
        <div className={styles.archiveBody}>
          <p className={styles.archiveIdx}>档案</p>
          <p className={styles.archiveRole}>{card.role}</p>
          <h3 className={styles.archiveName}>{card.name}</h3>
          <p className={styles.archiveBlurb}>{card.blurb}</p>
          <div className={styles.archiveActions}>
            <button
              type="button"
              className={styles.helpClose}
              onClick={onClose}
            >
              关闭
            </button>
            <button
              type="button"
              className={styles.brainstormBtn}
              disabled={lensBusy}
              onClick={() => onAction(card.id)}
            >
              {multiSelect
                ? activeLensIds.includes(card.id as string)
                  ? "移出队伍"
                  : "加入队伍"
                : card.id === null ||
                    (activeLensIds.length === 1 &&
                      activeLensIds[0] === card.id)
                  ? "设为默认编辑"
                  : "设为对话对象"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
