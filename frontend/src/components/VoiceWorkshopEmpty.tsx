import { VoiceWorkshopHero } from "./VoiceWorkshopHero";
import styles from "./CharacterWorkshop.module.css";

export function VoiceWorkshopEmpty() {
  return (
    <section className={styles.page}>
      <VoiceWorkshopHero value="定声音 → 思维包 → 试聊" />
      <div className={styles.emptyStage}>
        <img className={styles.emptyArt} src="/workshop/workshop-empty.png" alt="" />
        <p>还没有角色</p>
        <span>先在「设定 → 角色卡」添加角色，再回来塑形与试聊。</span>
      </div>
    </section>
  );
}
