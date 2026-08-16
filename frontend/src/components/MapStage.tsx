import { STAGE_W, STAGE_H, STAGE_X, STAGE_Y } from "../lib/mapWorld";
import styles from "./MapStudio.module.css";

/** Unified Persona LOC_MAP HUD. */
export function MapStage() {
  const box = {
    left: STAGE_X,
    top: STAGE_Y,
    width: STAGE_W,
    height: STAGE_H,
  };

  return (
    <div className={styles.stage} style={box} aria-hidden>
      <div className={styles.hudFrame}>
        <div className={styles.hudTop}>
          <span className={styles.hudIdx}>LOC_MAP</span>
          <p className={styles.hudTitle}>World Reference</p>
        </div>
        <div className={styles.hudBody}>
          <div className={styles.hudBracket} data-corner="tl" />
          <div className={styles.hudBracket} data-corner="tr" />
          <div className={styles.hudBracket} data-corner="bl" />
          <div className={styles.hudBracket} data-corner="br" />
          <div className={styles.hudSlash} />
        </div>
        <div className={styles.hudFoot}>
          <span>GRID · ACTIVE</span>
          <em>REF / PIN / LINK</em>
        </div>
      </div>
    </div>
  );
}
