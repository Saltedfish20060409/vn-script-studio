import { useEffect, useRef, useState } from "react";
import { BOOT_TOTAL_MS, shouldPlayBoot } from "../lib/desktopView";
import styles from "./BootScreen.module.css";

const STEPS = ["正在启动 VN Script Studio…", "载入写作环境…", "准备就绪"];

/**
 * 开机画面：登录页的第一屏（对应"电脑开机之后"的那一下）。
 *
 * 三条底线，都是为了不让"像"变成"烦"：
 * 1. **短**：默认 1.5 秒，到点自动进入；同一会话只放一次（从登录页跳走再回来不重放）。
 * 2. **可跳过**：任何按键 / 点击 / 触摸立刻进登录页。
 * 3. **不挡事**：它只是一层覆盖动画，登录表单、备案信息、公告按钮都在下面照常渲染，
 *    所以放完（或被跳过后）什么都不缺。
 */
export function BootScreen() {
  const [visible, setVisible] = useState(() => {
    if (typeof window === "undefined") return false;
    const reduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let storage: Storage | null;
    try {
      storage = window.sessionStorage;
    } catch {
      storage = null;
    }
    return shouldPlayBoot({ storage, reducedMotion: reduced });
  });
  const [step, setStep] = useState(0);
  const doneRef = useRef(false);

  useEffect(() => {
    if (!visible) return;
    const finish = () => {
      if (doneRef.current) return;
      doneRef.current = true;
      setVisible(false);
    };
    const timer = window.setTimeout(finish, BOOT_TOTAL_MS);
    const stepTimer = window.setInterval(
      () => setStep((s) => Math.min(s + 1, STEPS.length - 1)),
      Math.max(200, Math.floor(BOOT_TOTAL_MS / STEPS.length))
    );
    const skip = () => finish();
    window.addEventListener("keydown", skip);
    window.addEventListener("pointerdown", skip);
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(stepTimer);
      window.removeEventListener("keydown", skip);
      window.removeEventListener("pointerdown", skip);
    };
  }, [visible]);

  if (!visible) return null;

  return (
    <div className={styles.boot} role="status" aria-live="polite" data-testid="boot-screen">
      <div className={styles.inner}>
        <div className={styles.mark} aria-hidden>
          <span className={styles.ring} />
          <span className={styles.slash} />
        </div>
        <p className={styles.brand}>VN Script Studio</p>
        <p className={styles.step}>{STEPS[step]}</p>
        <div className={styles.bar} aria-hidden>
          <span style={{ width: `${((step + 1) / STEPS.length) * 100}%` }} />
        </div>
        <p className={styles.skip}>按任意键跳过</p>
      </div>
    </div>
  );
}
