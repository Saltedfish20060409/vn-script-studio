import { useSyncExternalStore } from "react";
import {
  getDeskPetState,
  setDeskPetEnabled,
  setPetWanderInterval,
  subscribeDeskPet,
  type PetWanderInterval,
} from "../lib/deskPet";
import styles from "./DeskPetApp.module.css";

/**
 * 桌面上的「桌宠」小窗口：开关、自主间隔。
 * 桌宠本体仍是屏幕挂件；本窗口只做设置，不把宠物塞进窗里。
 */
export function DeskPetApp() {
  const { enabled, wanderInterval } = useSyncExternalStore(
    subscribeDeskPet,
    getDeskPetState,
    getDeskPetState
  );

  return (
    <div className={styles.wrap}>
      <p className={styles.lead}>
        桌宠会趴在编辑器旁（或缩到屏幕角落）。直接拖它就能换位置；点它可以互动。
      </p>
      <label className={styles.toggle}>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setDeskPetEnabled(e.target.checked)}
        />
        显示桌宠
      </label>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>自主活动</span>
        <select
          className={styles.select}
          value={wanderInterval}
          disabled={!enabled}
          onChange={(e) => setPetWanderInterval(e.target.value as PetWanderInterval)}
        >
          <option value="normal">正常（偶尔走动、闲聊）</option>
          <option value="calm">安静（较少）</option>
          <option value="off">关闭（不走动、不闲聊）</option>
        </select>
      </label>
      <p className={styles.note}>
        {!enabled
          ? "已隐藏。勾上就会重新出现。"
          : wanderInterval === "off"
            ? "她还在，只是自己不走动、不冒写作提醒。"
            : "现在它在屏幕上。右键可喂食、玩耍、换姿势。"}
      </p>
    </div>
  );
}
