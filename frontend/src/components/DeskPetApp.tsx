import { useSyncExternalStore } from "react";
import {
  getDeskPetState,
  setDeskPetEnabled,
  subscribeDeskPet,
} from "../lib/deskPet";
import styles from "./DeskPetApp.module.css";

/**
 * 桌面上的「桌宠」小窗口：开关、姿势与位置说明。
 *
 * 桌宠本体仍是桌面上的挂件（可以拖着走），这个窗口是它的"设置面板"——
 * 对应 Windows 里"应用 + 它的设置"分开的做法：双击图标开的是应用窗口，
 * 而不是把宠物本身塞进窗口里（塞进去它就没法趴在编辑器边上了）。
 */
export function DeskPetApp() {
  const enabled = useSyncExternalStore(
    subscribeDeskPet,
    () => getDeskPetState().enabled,
    () => getDeskPetState().enabled
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
      <p className={styles.note}>
        {enabled
          ? "现在它在屏幕上。想让它安静一点：取消上面的勾选即可。"
          : "已隐藏。勾上就会重新出现。"}
      </p>
    </div>
  );
}
