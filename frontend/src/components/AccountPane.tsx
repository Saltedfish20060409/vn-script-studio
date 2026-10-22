/**
 * 设置 → 账号：把「退出登录」和「删除账号」摆在同一个页签里写清楚。
 *
 * 为什么要有这一页：作者收到的留言里最常见的一句是「怎么注销账号」。而旧界面上
 * 「注销」其实是**退出登录**（桌面视图的关机菜单），中文语境里「注销」的默认含义
 * 却是注销账号 —— 一个词两个意思，用户既找不到删号入口，也怕点错把稿子弄没。
 *
 * 所以这里的设计是：
 * 1. 两个动作并排、各自写清后果（退出登录：数据全保留；删除账号：不可恢复）；
 * 2. 删号不放在主按钮上，要展开一层确认表单，并且**用户名 + 密码**都填对才能提交
 *    （后端同样校验，前端这层只是为了让人慢一秒、看清楚自己在删什么）。
 */
import { useState } from "react";

import { deleteAccount } from "../api/client";
import { useAuth } from "../lib/authContext";

import styles from "./SettingsModal.module.css";

type Props = {
  /** 退出登录：由 StudioApp 传入（会先把没保存的稿件落盘再登出）。 */
  onLogout?: () => void;
  /**
   * 删号成功后：清本地登录态并回登录页。
   * 注意**不能**复用退出登录那条路径 —— 它会 flush 未保存的稿件，而项目此刻已经没了。
   */
  onAccountDeleted?: () => void;
};

export function AccountPane({ onLogout, onAccountDeleted }: Props) {
  const { user } = useAuth();
  /** 确认表单是否展开（默认收起：删号不该是一个"顺手能看到的大按钮"）。 */
  const [armed, setArmed] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!user) {
    return (
      <div className={styles.form}>
        <p className={styles.note}>
          当前没有读到登录信息（可能是登录态刚过期），刷新页面后再试即可。
        </p>
      </div>
    );
  }

  const nameOk = confirmName.trim() === user.username;
  const canDelete = nameOk && password.length > 0 && !busy;

  async function onDelete() {
    if (!canDelete) return;
    setBusy(true);
    setError("");
    try {
      await deleteAccount(password, confirmName.trim());
      onAccountDeleted?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败，请稍后重试");
      setBusy(false);
    }
  }

  function reset() {
    setArmed(false);
    setConfirmName("");
    setPassword("");
    setError("");
  }

  return (
    <div className={styles.form}>
      <p className={styles.note}>
        当前登录：<strong>{user.username}</strong>
        {user.email ? ` · ${user.email}` : ""}
        {user.is_admin ? " · 管理员" : ""}
      </p>

      <div className={styles.divider} />

      <h4>退出登录</h4>
      <p className={styles.note}>
        只是把当前这台设备登出。<strong>账号、项目、对话全部保留</strong>，换台设备重新登录就能接着写。
        共用电脑、或者想在手机上接着写，用这个。
      </p>
      <div className={styles.llmActions}>
        <button type="button" className={styles.ghost} onClick={() => onLogout?.()}>
          退出登录
        </button>
      </div>

      <div className={styles.divider} />

      <h4>删除账号</h4>
      <p className={styles.note}>
        删除会<strong>永久清除</strong>你名下的全部项目（含章节、设定、历史快照、分享链接）、
        AI 对话记录、批注与用量记录，<strong>无法恢复</strong>。你作为协作者加入的他人项目不会被删除，
        你只会被移出该项目的成员列表。
      </p>
      <p className={styles.note}>
        想留个底的话，删除前先到项目页「导出」一份 JSON 或 Word。只是不想再登录、或想换个设备写，
        请用上面的「退出登录」。
      </p>

      {!armed ? (
        <div className={styles.llmActions}>
          <button type="button" className={styles.danger} onClick={() => setArmed(true)}>
            我要删除账号
          </button>
        </div>
      ) : (
        <div className={styles.dangerBox}>
          <h4>确认删除：不可撤销</h4>
          <label>
            输入用户名 <strong>{user.username}</strong> 确认
            <input
              type="text"
              value={confirmName}
              autoComplete="off"
              placeholder={user.username}
              onChange={(e) => setConfirmName(e.target.value)}
            />
          </label>
          <label>
            登录密码
            <input
              type="password"
              value={password}
              autoComplete="current-password"
              placeholder="用于确认是本人操作"
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error ? <p className={styles.error}>{error}</p> : null}
          <div className={styles.llmActions}>
            <button
              type="button"
              className={styles.danger}
              disabled={!canDelete}
              onClick={() => void onDelete()}
            >
              {busy ? "删除中…" : "确认永久删除"}
            </button>
            <button type="button" className={styles.ghost} disabled={busy} onClick={reset}>
              算了，保留账号
            </button>
          </div>
          {!nameOk && confirmName.length > 0 ? (
            <p className={styles.warnNote}>用户名要一字不差（大小写敏感）。</p>
          ) : null}
        </div>
      )}
    </div>
  );
}
