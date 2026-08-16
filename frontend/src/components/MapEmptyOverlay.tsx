import { EmptyStage } from "./EmptyStage";
import { mascotLine } from "../lib/mascotCopy";
import styles from "./MapStudio.module.css";

type Props = {
  onExtractFromScript?: () => void;
};

/** Empty-world overlay shown while there is nothing on the map. Pure presentational. */
export function MapEmptyOverlay({ onExtractFromScript }: Props) {
  return (
    <div className={styles.emptyOverlay}>
      <EmptyStage
        stamp="MAP"
        title="世界观地图还空着"
        line={mascotLine("emptyMap")}
        compact
      >
        {onExtractFromScript ? (
          <button
            type="button"
            className={styles.primary}
            onClick={onExtractFromScript}
          >
            智能提取地图
          </button>
        ) : null}
      </EmptyStage>
    </div>
  );
}
