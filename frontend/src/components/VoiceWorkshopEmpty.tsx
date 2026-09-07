import { VoiceWorkshopHero } from "./VoiceWorkshopHero";
import styles from "./CharacterWorkshop.module.css";

export function VoiceWorkshopEmpty() {
  return (
    <section className={styles.page}>
      <VoiceWorkshopHero value="定口吻 → 合成思维包 → 试聊" />
      <div className={styles.emptyStage}>
        <img className={styles.emptyArt} src="/workshop/workshop-empty.png" alt="" />
        <p>还没有角色</p>
        <span>请先到「设定 → 角色卡」添加一个角色，再回到这里，按「定口吻 → 合成思维包 → 试聊」一步步来。</span>
      </div>
    </section>
  );
}
