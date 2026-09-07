import styles from "./CharacterWorkshop.module.css";

type Props = {
  dontShowGuideAgain: boolean;
  onToggleCheck: (checked: boolean) => void;
  onDismiss: () => void;
  onStart: () => void;
};

export function VoiceGuideOverlay({
  dontShowGuideAgain,
  onToggleCheck,
  onDismiss,
  onStart,
}: Props) {
  return (
    <div className={styles.guideOverlay} role="dialog" aria-modal="true">
      <div className={styles.guideCard}>
        <div className={styles.guideMain}>
          <h3>角色工坊怎么用</h3>
          <p className={styles.guideLead}>
            把角色说话的口吻定下来，再用来试聊和写对白——不是普通聊天机器人。
          </p>
          <div className={styles.guideSteps}>
            <article>
              <strong>1. 定口吻</strong>
              <span>
                AI 按三种说话风格各写一组对白，挑最像角色的一组存成示例。请切换多个场景
                （被误解、别扭关心、面对权威等），只在一种场景里收会学偏。也可用长场次 / 采访加厚。
              </span>
            </article>
            <article>
              <strong>2. 出思维包</strong>
              <span>
                素材凑够下面任一条就能合成：短对白示例≥6 条、不同场景≥5 类、长场次≥2 段、
                或角色台词约≥800 字。够了再合成；想更进一步，也可把包导出经「女娲」深化后导入。
              </span>
            </article>
            <article>
              <strong>3. 试聊排练</strong>
              <span>有思维包后，与角色对话，或让两个角色互聊，看看口吻像不像。</span>
            </article>
          </div>
          <label className={styles.guideCheck}>
            <input
              type="checkbox"
              checked={dontShowGuideAgain}
              onChange={(e) => onToggleCheck(e.target.checked)}
            />
            下次不再出现
          </label>
          <div className={styles.guideActions}>
            <button type="button" className={styles.primary} onClick={onStart}>
              开始收集口吻
            </button>
            <button type="button" onClick={onDismiss}>
              知道了
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
