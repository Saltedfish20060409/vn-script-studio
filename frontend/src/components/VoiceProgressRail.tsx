import styles from "./CharacterWorkshop.module.css";

type Zone = "shape" | "pack" | "chat";

type Props = {
  sampleCount: number;
  uniqueCount: number;
  hasMindPack: boolean;
  ready: boolean;
  nextHint: string;
  onStep: (zone: Zone) => void;
};

export function VoiceProgressRail({
  sampleCount,
  uniqueCount,
  hasMindPack,
  ready,
  nextHint,
  onStep,
}: Props) {
  const steps: Array<{
    id: Zone;
    title: string;
    desc: string;
    done: boolean;
    cta: string;
  }> = [
    {
      id: "shape",
      title: "① 定声音",
      desc:
        sampleCount > 0
          ? `已有 ${sampleCount} 条 · ${uniqueCount} 类场景` +
            (uniqueCount <= 1 && sampleCount >= 2 ? "（偏窄，请换场景）" : "")
          : "建议多场景三选一，勿单场景刷",
      done: sampleCount > 0,
      cta: sampleCount > 0 ? "继续塑形" : "开始塑形",
    },
    {
      id: "pack",
      title: "② 出思维包",
      desc: hasMindPack ? "已解锁对话" : ready ? "已达门槛，可以合成" : nextHint,
      done: hasMindPack,
      cta: hasMindPack ? "查看思维包" : "去合成",
    },
    {
      id: "chat",
      title: "③ 试聊排练",
      desc: hasMindPack ? "与角色聊或角色互聊" : "需先有思维包",
      done: hasMindPack,
      cta: hasMindPack ? "去试聊" : "先完成思维包",
    },
  ];
  const next = steps.find((s) => !s.done) || steps[2];

  const doneCount = steps.filter((s) => s.done).length;
  const pct = Math.round((doneCount / steps.length) * 100);

  return (
    <div className={styles.progress}>
      <div className={styles.progressRail} aria-label={`进度 ${doneCount}/3`}>
        <div className={styles.progressRailTop}>
          <span>档案养成</span>
          <strong>
            {doneCount}/3 · {next.title.replace(/^[①②③]\s*/, "")}
          </strong>
        </div>
        <div className={styles.progressRailTrack}>
          <div className={styles.progressRailFill} style={{ width: `${pct}%` }} />
        </div>
        <div className={styles.progressRailSteps}>
          {steps.map((s) => (
            <button
              key={s.id}
              type="button"
              className={
                s.done
                  ? styles.progressDotDone
                  : s.id === next.id
                    ? styles.progressDotOn
                    : styles.progressDot
              }
              disabled={s.id === "chat" && !hasMindPack}
              onClick={() => onStep(s.id)}
              title={s.title}
            >
              {s.title.replace(/^([①②③]).*/, "$1")}
            </button>
          ))}
        </div>
      </div>
      <ol className={styles.progressList}>
        {steps.map((s) => (
          <li
            key={s.id}
            className={
              s.done
                ? styles.progressDone
                : s.id === next.id
                  ? styles.progressCurrent
                  : styles.progressItem
            }
          >
            <button
              type="button"
              className={styles.progressJump}
              disabled={s.id === "chat" && !hasMindPack}
              onClick={() => onStep(s.id)}
            >
              <strong>{s.title}</strong>
              <span>{s.desc}</span>
            </button>
            {s.id === next.id ? (
              <button
                type="button"
                className={styles.primary}
                disabled={s.id === "chat" && !hasMindPack}
                onClick={() => onStep(s.id)}
              >
                {s.cta}
              </button>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
