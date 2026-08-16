import styles from "./CharacterWorkshop.module.css";

export type ReadinessInfo = {
  ready: boolean;
  paths: string[];
  nextHint: string;
};

type Props = {
  info: ReadinessInfo;
  narrow: string;
  compact?: boolean;
};

export function VoiceReadinessBanner({ info, narrow, compact }: Props) {
  return (
    <div className={info.ready ? styles.readyBannerOk : styles.readyBanner}>
      <p className={styles.readyTitle}>
        {info.ready ? "可以合成思维包了" : "合成门槛（满足任一路径即可）"}
      </p>
      {!compact && (
        <ul className={styles.readyPaths}>
          {info.paths.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <p className={styles.readyHint}>{info.nextHint}</p>
      {narrow && <p className={styles.readyWarn}>{narrow}</p>}
      {!info.ready && (
        <p className={styles.readyTip}>
          小技巧：三选一请<strong>切换不同场景</strong>
          再生成，不要只改「场景压力」却一直停在同一类情境——否则思维包会偏窄。
        </p>
      )}
    </div>
  );
}
