import { useEffect, useRef, useState } from "react";
import { mascotArtSrc, type MascotMood } from "../lib/mascotArt";
import styles from "./MascotFeedback.module.css";

export interface PetFeedback {
  /** 雪菜表情：cheer / think / fluster / worried 等 */
  mood: MascotMood;
  text: string;
  /** 显示时长 ms（默认 2200） */
  duration?: number;
}

type Props = {
  feedback: PetFeedback | null;
};

/** 关键操作的角色反馈气泡：保存成功/失败/AI 完成时，雪菜头像 + 气泡弹出。 */
export function MascotFeedback({ feedback }: Props) {
  const [shown, setShown] = useState<PetFeedback | null>(null);
  const [leaving, setLeaving] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    if (!feedback) {
      setShown(null);
      setLeaving(false);
      return;
    }
    setShown(feedback);
    setLeaving(false);
    timer.current = window.setTimeout(() => {
      setLeaving(true);
      timer.current = window.setTimeout(() => setShown(null), 260);
    }, feedback.duration ?? 2200);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [feedback]);

  if (!shown) return null;

  return (
    <div
      className={`${styles.wrap} ${leaving ? styles.leaving : ""}`}
      role="status"
      aria-live="polite"
      data-testid="mascot-feedback"
    >
      <div className={styles.bubble}>{shown.text}</div>
      <img
        className={styles.face}
        src={mascotArtSrc(shown.mood)}
        alt=""
        draggable={false}
      />
    </div>
  );
}
