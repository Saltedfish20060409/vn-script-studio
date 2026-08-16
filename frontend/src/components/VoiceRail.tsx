import type { Character } from "../types/vn";
import styles from "./CharacterWorkshop.module.css";

type Stats = {
  sampleCount: number;
  coverage: number;
  hasMindPack: boolean;
  ready: boolean;
  shortCount: number;
  sceneCount: number;
  interviewCount: number;
  volumeChars: number;
};

type Props = {
  railOpen: boolean;
  characters: Character[];
  character: Character | null;
  stats: Stats;
  onSelectChar: (id: string) => void;
  onClose: () => void;
};

export function VoiceRail({
  railOpen,
  characters,
  character,
  stats,
  onSelectChar,
  onClose,
}: Props) {
  const {
    sampleCount,
    coverage,
    hasMindPack,
    ready,
    shortCount,
    sceneCount,
    interviewCount,
    volumeChars,
  } = stats;
  return (
    <aside
      className={`${styles.rail} ${railOpen ? styles.railDrawerOpen : ""}`}
      id="workshop-rail"
    >
      <div className={styles.railHead}>
        <div>
          <p className={styles.railKicker}>CAST</p>
          <p className={styles.railLabel}>角色名单</p>
        </div>
        <button type="button" className={styles.railClose} onClick={onClose}>
          关闭
        </button>
      </div>
      <ul className={styles.charList}>
        {characters.map((c, i) => {
          const n = c.voiceCorpus?.length || 0;
          const active = c.id === character?.id;
          return (
            <li key={c.id}>
              <button
                type="button"
                className={active ? styles.charActive : styles.charBtn}
                onClick={() => onSelectChar(c.id)}
              >
                <span className={styles.charIdx} aria-hidden>
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span
                  className={styles.swatch}
                  style={{ background: c.color || "#888" }}
                />
                <span className={styles.charName}>{c.displayName}</span>
                <span className={styles.charStat}>
                  {n}
                  {c.voiceMind ? " · 包" : ""}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {character ? (
        <div className={styles.dossierCard}>
          <div className={styles.dossierMark} aria-hidden>
            档
          </div>
          <div className={styles.dossierHead}>
            <p className={styles.dossierIdx}>
              FILE{" "}
              {String(
                Math.max(1, characters.findIndex((c) => c.id === character.id) + 1)
              ).padStart(2, "0")}
            </p>
            <h3
              className={styles.dossierName}
              style={{ color: character.color || undefined }}
            >
              {character.displayName}
            </h3>
            <p className={styles.dossierMeta}>
              {sampleCount} 正例 · 覆盖 {coverage} 场景
              {hasMindPack ? " · 已有思维包" : " · 尚无思维包"}
              {ready ? " · 可合成" : ""}
            </p>
          </div>
          <dl className={styles.dossierGrid}>
            <div>
              <dt>短正例</dt>
              <dd>{shortCount}</dd>
            </div>
            <div>
              <dt>长场次</dt>
              <dd>{sceneCount}</dd>
            </div>
            <div>
              <dt>采访</dt>
              <dd>{interviewCount}</dd>
            </div>
            <div>
              <dt>字量</dt>
              <dd>{volumeChars}</dd>
            </div>
            <div>
              <dt>场景</dt>
              <dd>{coverage}</dd>
            </div>
            <div>
              <dt>可合成</dt>
              <dd>{ready ? "是" : "否"}</dd>
            </div>
            <div>
              <dt>思维包</dt>
              <dd>{hasMindPack ? "有" : "无"}</dd>
            </div>
          </dl>
          <div className={styles.dossierSeed}>
            <p>
              <em>语气</em>
              {character.voice || "（空）"}
            </p>
            <p>
              <em>简介</em>
              {character.bio || "（空）"}
            </p>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
