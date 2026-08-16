import { MascotFigure } from "./MascotFigure";
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
        <div className={styles.guideMascot} aria-hidden>
          <MascotFigure size="lg" mood="cheer" line="三步走完，声音就立住了。" />
        </div>
        <div className={styles.guideMain}>
          <h3>角色工坊怎么用</h3>
          <p className={styles.guideLead}>
            把脑中的角色声音定下来，再用来试聊和写对白——不是普通聊天机器人。
          </p>
          <div className={styles.guideSteps}>
            <article>
              <strong>1. 定声音</strong>
              <span>
                生成三组对白，选最像的入库。请切换多个场景（被误解、别扭关心、面对权威等），
                单场景语料会片面。也可用长场次 / 采访加厚。
              </span>
            </article>
            <article>
              <strong>2. 出思维包</strong>
              <span>
                门槛任选其一：短正例≥6、不同场景≥5、长场次≥2、或角色台词约≥800字。
                够了再合成；也可导出给女娲加深后导入。
              </span>
            </article>
            <article>
              <strong>3. 试聊排练</strong>
              <span>有思维包后，与角色对话，或让两个角色互聊验收口吻。</span>
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
              开始塑形
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
