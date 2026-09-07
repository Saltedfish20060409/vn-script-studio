import styles from "./CharacterWorkshop.module.css";

export type ChatMode = "user" | "duo";

export type ChatMsg = {
  id: string;
  role: "user" | "assistant";
  content: string;
  speakerId?: string;
  speakerName?: string;
  /** 台词伴随的微动作（如：叹了口气） */
  action?: string;
  /** 情绪标签（如：烦躁） */
  mood?: string;
};

type Props = {
  hasMindPack: boolean;
  chatMode: ChatMode;
  partnerId: string;
  partners: Array<{ id: string; displayName: string }>;
  busy: string;
  messages: ChatMsg[];
  chatInput: string;
  canSave: boolean;
  onModeChange: (mode: ChatMode) => void;
  onPartnerChange: (id: string) => void;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onClear: () => void;
  onSaveSample: () => void;
  onGoPack: () => void;
};

export function VoiceChatZone({
  hasMindPack,
  chatMode,
  partnerId,
  partners,
  busy,
  messages,
  chatInput,
  canSave,
  onModeChange,
  onPartnerChange,
  onInputChange,
  onSend,
  onClear,
  onSaveSample,
  onGoPack,
}: Props) {
  if (!hasMindPack) {
    return (
      <div className={styles.chatLock}>
        <p>需要先合成或导入思维包</p>
        <button type="button" className={styles.primary} onClick={onGoPack}>
          前往思维包
        </button>
      </div>
    );
  }

  return (
    <div className={styles.chatPanel}>
      <div className={styles.chatModes}>
        <button
          type="button"
          className={chatMode === "user" ? styles.shapeModeOn : styles.shapeMode}
          onClick={() => onModeChange("user")}
        >
          与 TA 聊
        </button>
        <button
          type="button"
          className={chatMode === "duo" ? styles.shapeModeOn : styles.shapeMode}
          onClick={() => onModeChange("duo")}
        >
          角色互聊
        </button>
        {chatMode === "duo" && (
          <label className={styles.field} style={{ marginLeft: "auto" }}>
            搭档
            <select value={partnerId} onChange={(e) => onPartnerChange(e.target.value)}>
              {partners.length === 0 ? (
                <option value="">无可用角色</option>
              ) : (
                partners.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.displayName}
                  </option>
                ))
              )}
            </select>
          </label>
        )}
      </div>

      <div className={styles.chatLog}>
        {messages.length === 0 && (
          <p className={styles.muted}>
            {chatMode === "duo"
              ? "输入旁白或出题，看两位角色如何交锋。"
              : "输入一句话，看看角色会怎么回。"}
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`${styles.bubble} ${
              m.role === "user" ? styles.bubbleSelf : styles.bubbleOther
            }`}
          >
            {m.speakerName && m.role !== "user" && (
              <span className={styles.bubbleName}>
                {m.speakerName}
                {m.mood ? <em className={styles.bubbleMood}>{m.mood}</em> : null}
              </span>
            )}
            {m.action ? <span className={styles.bubbleAction}>（{m.action}）</span> : null}
            {m.content}
          </div>
        ))}
      </div>

      <div className={styles.chatToolbar}>
        <button type="button" disabled={!!busy} onClick={onClear}>
          清空会话
        </button>
        <button type="button" disabled={!!busy || !canSave} onClick={onSaveSample}>
          {busy === "save-chat" ? "存入中…" : "存为示例（让角色更像这段话的语气）"}
        </button>
      </div>

      <div className={styles.chatInput}>
        <textarea
          rows={2}
          value={chatInput}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder={chatMode === "duo" ? "旁白 / 出题…" : "对角色说…"}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
        />
        <button
          type="button"
          className={styles.primary}
          disabled={!!busy || !chatInput.trim()}
          onClick={onSend}
        >
          {busy === "chat" ? "…" : "发送"}
        </button>
      </div>
    </div>
  );
}
