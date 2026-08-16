import styles from "./CharacterWorkshop.module.css";

type Props = {
  value: string;
  railOpen?: boolean;
  onToggleRail?: () => void;
  showGuide?: boolean;
  onShowGuide?: () => void;
};

export function VoiceWorkshopHero({
  value,
  railOpen,
  onToggleRail,
  showGuide,
  onShowGuide,
}: Props) {
  return (
    <header className={styles.hero}>
      <div className={styles.heroBanner} aria-hidden />
      <div className={styles.heroCopy}>
        <p className={styles.heroIdx}>档案室 · FILE</p>
        <h2>角色工坊</h2>
        <p className={styles.heroValue}>{value}</p>
      </div>
      {onToggleRail && (
        <div className={styles.heroMeta}>
          <button
            type="button"
            className={styles.railToggle}
            aria-expanded={railOpen}
            onClick={onToggleRail}
          >
            {railOpen ? "收起名单" : "打开名单"}
          </button>
          {!showGuide && (
            <button type="button" className={styles.ghostLink} onClick={onShowGuide}>
              查看引导
            </button>
          )}
        </div>
      )}
    </header>
  );
}
