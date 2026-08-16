import { WriterPortrait } from "./WriterPortrait";
import styles from "./AgentChat.module.css";

export type PartyCard = { id: string | null; name: string };

type Props = {
  multiSelect: boolean;
  partyCards: PartyCard[];
  activeLensIds: string[];
  brainstormTopic: string;
  busy: boolean;
  lensBusy: boolean;
  writerCards: Array<{ id: string | null; role: string; name: string }>;
  onClose: () => void;
  onToggleMulti: (v: boolean) => void;
  onTopicChange: (v: string) => void;
  onBrainstorm: () => void;
  onSelectCard: (key: string) => void;
};

/** 作家参谋档案弹层：多选组队、头脑风暴、作家卡网格。纯展示。 */
export function AgentPersonaOverlay({
  multiSelect,
  partyCards,
  activeLensIds,
  brainstormTopic,
  busy,
  lensBusy,
  writerCards,
  onClose,
  onToggleMulti,
  onTopicChange,
  onBrainstorm,
  onSelectCard,
}: Props) {
  return (
    <div className={styles.stageOverlay} role="dialog" aria-modal="true">
      <header className={styles.overlayHead}>
        <div>
          <p className={styles.overlayIdx}>PARTY</p>
          <h3 className={styles.overlayTitle}>参谋档案</h3>
        </div>
        <button type="button" className={styles.hudBtn} onClick={onClose}>
          关闭
        </button>
      </header>
      <p className={styles.personaPanelLead}>
        点开档案选用作家参谋。默认是通用文学编辑；多选可组队头脑风暴。
      </p>
      <label className={styles.multiToggle}>
        <input
          type="checkbox"
          checked={multiSelect}
          onChange={(e) => onToggleMulti(e.target.checked)}
        />
        多选（组队头脑风暴）
      </label>
      {multiSelect || activeLensIds.length >= 2 ? (
        <div className={styles.partyStage}>
          <div className={styles.partySeats}>
            <div className={styles.partySeat}>
              <WriterPortrait lensId={null} size="sm" />
              <span className={styles.partySeatName}>责编主持</span>
            </div>
            {partyCards.map((c) => (
              <div key={c.id as string} className={styles.partySeat}>
                <WriterPortrait lensId={c.id} size="sm" selected />
                <span className={styles.partySeatName}>{c.name}</span>
              </div>
            ))}
            {Array.from({
              length: Math.max(0, 2 - partyCards.length),
            }).map((_, i) => (
              <div
                key={`empty-${i}`}
                className={`${styles.partySeat} ${styles.partySeatEmpty}`}
              >
                <span className={styles.partyEmptyMark}>?</span>
                <span className={styles.partySeatName}>空席</span>
              </div>
            ))}
          </div>
          <div className={styles.brainstormBox}>
            <input
              className={styles.brainstormInput}
              value={brainstormTopic}
              onChange={(e) => onTopicChange(e.target.value)}
              placeholder="议题（可空）：例如「下一场如何升温」"
              disabled={busy || lensBusy}
            />
            <button
              type="button"
              className={styles.brainstormBtn}
              disabled={busy || lensBusy || activeLensIds.length < 2}
              onClick={onBrainstorm}
            >
              开始头脑风暴
            </button>
          </div>
        </div>
      ) : null}
      <div className={styles.personaGrid}>
        {writerCards.map((card) => {
          const key = card.id ?? "__default__";
          const isDefault = card.id === null;
          const selected = isDefault
            ? activeLensIds.length === 0
            : activeLensIds.includes(card.id as string);
          return (
            <button
              key={key}
              type="button"
              className={
                selected
                  ? `${styles.personaCard} ${styles.personaCardOn}`
                  : styles.personaCard
              }
              disabled={lensBusy}
              onClick={() => onSelectCard(key)}
            >
              <WriterPortrait lensId={card.id} size="sm" selected={selected} />
              <span className={styles.personaCardRole}>{card.role}</span>
              <strong className={styles.personaCardName}>{card.name}</strong>
              {selected ? (
                <span className={styles.personaCardCheck}>
                  {multiSelect ? "入队" : "对话中"}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
