import { useState } from "react";
import type { Character, GameVariable, SpriteDef } from "../types/vn";
import { conditionError } from "../lib/conditions";
import styles from "./ScriptCommandBar.module.css";

type Props = {
  characters: Character[];
  sprites: SpriteDef[];
  variables: GameVariable[];
  /** 把生成的指令文本插入到编辑器光标处 */
  onInsert: (text: string) => void;
};

type Panel =
  | ""
  | "music"
  | "sound"
  | "voice"
  | "wait"
  | "camera"
  | "effect"
  | "if"
  | "set"
  | "sprite";

const EFFECTS: Array<[string, string]> = [
  ["shake", "震屏（横）"],
  ["vshake", "震屏（纵）"],
  ["flash_white", "白闪"],
  ["flash_black", "黑闪"],
  ["fade_black", "淡出到黑"],
  ["fade_white", "淡出到白"],
  ["dissolve", "溶接"],
];

/**
 * 指令工具条：让作者不用背 DSL 语法就能插入演出指令、条件与变量赋值。
 *
 * 为什么要有它：正文编辑面是文本 DSL（方便快速写、也方便 AI 改写），但**新语法没人记得住**。
 * 这里把"需要精确语法"的部分做成表单：选变量、选运算符、选表情，生成规范文本插入光标处。
 * 纯前端计算，不改任何数据。
 */
export function ScriptCommandBar({ characters, sprites, variables, onInsert }: Props) {
  const [panel, setPanel] = useState<Panel>("");

  // 各表单的临时字段
  const [file, setFile] = useState("");
  const [fade, setFade] = useState("2");
  const [volume, setVolume] = useState("0.8");
  const [seconds, setSeconds] = useState("1.5");
  const [zoom, setZoom] = useState("1.2");
  const [offsetX, setOffsetX] = useState("0");
  const [effectKind, setEffectKind] = useState("shake");
  const [effectDuration, setEffectDuration] = useState("0.5");
  const [varKey, setVarKey] = useState(variables[0]?.key ?? "affection");
  const [op, setOp] = useState(">=");
  const [value, setValue] = useState("3");
  const [assignOp, setAssignOp] = useState("+=");
  const [assignValue, setAssignValue] = useState("1");
  const [spriteId, setSpriteId] = useState(sprites[0]?.id ?? "");
  const [exprTag, setExprTag] = useState("");

  const sprite = sprites.find((s) => s.id === spriteId);
  const expressions = sprite?.expressions ?? [];

  function insert(text: string) {
    onInsert(text);
    setPanel("");
  }

  function toggle(next: Panel) {
    setPanel((cur) => (cur === next ? "" : next));
    if (next === "if") {
      setVarKey(variables[0]?.key ?? "affection");
    }
    if (next === "sprite") {
      setSpriteId(sprites[0]?.id ?? "");
      setExprTag(sprites[0]?.expressions?.[0]?.tag ?? "");
    }
  }

  const ifPreview = `if ${varKey} ${op} ${value}:`;
  const ifError = conditionError(`${varKey} ${op} ${value}`);

  return (
    <div className={styles.wrap} data-testid="script-command-bar">
      <div className={styles.row}>
        <span className={styles.label}>插入</span>
        {(
          [
            ["music", "音乐"],
            ["sound", "音效"],
            ["voice", "语音"],
            ["wait", "等待"],
            ["camera", "镜头"],
            ["effect", "特效"],
            ["if", "条件分支"],
            ["set", "变量赋值"],
            ["sprite", "立绘/表情"],
          ] as Array<[Panel, string]>
        ).map(([id, text]) => (
          <button
            key={id}
            type="button"
            className={panel === id ? styles.on : styles.btn}
            onClick={() => toggle(id)}
            title={`插入${text}指令`}
          >
            {text}
          </button>
        ))}
      </div>

      {panel === "music" ? (
        <div className={styles.panel}>
          <input
            className={styles.input}
            value={file}
            onChange={(e) => setFile(e.target.value)}
            placeholder="音频文件，如 bgm/rain.ogg"
          />
          <label className={styles.field}>
            淡入秒数
            <input
              className={styles.num}
              value={fade}
              onChange={(e) => setFade(e.target.value)}
            />
          </label>
          <button
            type="button"
            className={styles.go}
            disabled={!file.trim()}
            onClick={() =>
              insert(
                file.trim()
                  ? `play music ${file.trim()}${fade ? ` fadein ${fade}` : ""}`
                  : "stop music"
              )
            }
          >
            插入播放
          </button>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => insert(`stop music${fade ? ` fadeout ${fade}` : ""}`)}
          >
            插入停止
          </button>
        </div>
      ) : null}

      {panel === "sound" ? (
        <div className={styles.panel}>
          <input
            className={styles.input}
            value={file}
            onChange={(e) => setFile(e.target.value)}
            placeholder="音效文件，如 sfx/door.mp3"
          />
          <label className={styles.field}>
            音量
            <input
              className={styles.num}
              value={volume}
              onChange={(e) => setVolume(e.target.value)}
            />
          </label>
          <button
            type="button"
            className={styles.go}
            disabled={!file.trim()}
            onClick={() =>
              insert(
                `play sound ${file.trim()}${volume ? ` volume ${volume}` : ""}`
              )
            }
          >
            插入
          </button>
          <button type="button" className={styles.ghost} onClick={() => insert("stop sound")}>
            插入停止
          </button>
        </div>
      ) : null}

      {panel === "voice" ? (
        <div className={styles.panel}>
          <input
            className={styles.input}
            value={file}
            onChange={(e) => setFile(e.target.value)}
            placeholder="语音文件，如 voice/y01.ogg"
          />
          <button
            type="button"
            className={styles.go}
            disabled={!file.trim()}
            onClick={() => insert(`voice ${file.trim()}`)}
          >
            插入
          </button>
          <span className={styles.hint}>插在对应台词的前一行</span>
        </div>
      ) : null}

      {panel === "wait" ? (
        <div className={styles.panel}>
          <label className={styles.field}>
            等待秒数
            <input
              className={styles.num}
              value={seconds}
              onChange={(e) => setSeconds(e.target.value)}
            />
          </label>
          <button type="button" className={styles.go} onClick={() => insert(`wait ${seconds}`)}>
            插入
          </button>
          <span className={styles.hint}>试玩时会自动继续，点击可跳过</span>
        </div>
      ) : null}

      {panel === "camera" ? (
        <div className={styles.panel}>
          <label className={styles.field}>
            缩放
            <input
              className={styles.num}
              value={zoom}
              onChange={(e) => setZoom(e.target.value)}
            />
          </label>
          <label className={styles.field}>
            水平偏移
            <input
              className={styles.num}
              value={offsetX}
              onChange={(e) => setOffsetX(e.target.value)}
            />
          </label>
          <button
            type="button"
            className={styles.go}
            onClick={() => insert(`camera zoom ${zoom} x ${offsetX}`)}
          >
            插入
          </button>
        </div>
      ) : null}

      {panel === "effect" ? (
        <div className={styles.panel}>
          <select
            className={styles.input}
            value={effectKind}
            onChange={(e) => setEffectKind(e.target.value)}
            aria-label="特效类型"
          >
            {EFFECTS.map(([id, text]) => (
              <option key={id} value={id}>
                {text}
              </option>
            ))}
          </select>
          <label className={styles.field}>
            时长
            <input
              className={styles.num}
              value={effectDuration}
              onChange={(e) => setEffectDuration(e.target.value)}
            />
          </label>
          <button
            type="button"
            className={styles.go}
            onClick={() => insert(`effect ${effectKind} ${effectDuration}`)}
          >
            插入
          </button>
        </div>
      ) : null}

      {panel === "if" ? (
        <div className={styles.panel}>
          <select
            className={styles.input}
            value={varKey}
            onChange={(e) => setVarKey(e.target.value)}
            aria-label="变量"
          >
            {variables.length === 0 ? <option value="affection">affection</option> : null}
            {variables.map((v) => (
              <option key={v.id} value={v.key}>
                {v.name || v.key}（{v.key}）
              </option>
            ))}
          </select>
          <select
            className={styles.op}
            value={op}
            onChange={(e) => setOp(e.target.value)}
            aria-label="比较符"
          >
            {[">=", "<=", "==", "!=", ">", "<"].map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
          <input
            className={styles.num}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <button
            type="button"
            className={styles.go}
            disabled={Boolean(ifError)}
            onClick={() =>
              insert(`${ifPreview}\n    \nelse:\n    `)
            }
          >
            插入分支
          </button>
          <span className={styles.hint}>
            {ifError ? `条件有问题：${ifError}` : `生成 ${ifPreview} / else，正文缩进 4 空格`}
          </span>
        </div>
      ) : null}

      {panel === "set" ? (
        <div className={styles.panel}>
          <select
            className={styles.input}
            value={varKey}
            onChange={(e) => setVarKey(e.target.value)}
            aria-label="变量"
          >
            {variables.length === 0 ? <option value="affection">affection</option> : null}
            {variables.map((v) => (
              <option key={v.id} value={v.key}>
                {v.name || v.key}（{v.key}）
              </option>
            ))}
          </select>
          <select
            className={styles.op}
            value={assignOp}
            onChange={(e) => setAssignOp(e.target.value)}
            aria-label="赋值运算符"
          >
            {["+=", "-=", "="].map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
          <input
            className={styles.num}
            value={assignValue}
            onChange={(e) => setAssignValue(e.target.value)}
          />
          <button
            type="button"
            className={styles.go}
            onClick={() => insert(`set ${varKey} ${assignOp} ${assignValue}`)}
          >
            插入
          </button>
        </div>
      ) : null}

      {panel === "sprite" ? (
        <div className={styles.panel}>
          {sprites.length === 0 ? (
            <span className={styles.hint}>
              还没有立绘定义。到「设置 → 立绘」先加角色立绘与表情，这里就能直接选。
            </span>
          ) : (
            <>
              <select
                className={styles.input}
                value={spriteId}
                onChange={(e) => {
                  setSpriteId(e.target.value);
                  const s = sprites.find((x) => x.id === e.target.value);
                  setExprTag(s?.expressions?.[0]?.tag ?? "");
                }}
                aria-label="立绘"
              >
                {sprites.map((s) => {
                  const ch = characters.find((c) => c.id === s.characterId);
                  return (
                    <option key={s.id} value={s.id}>
                      {s.name || s.imageTag}
                      {ch ? ` · ${ch.displayName}` : ""}
                    </option>
                  );
                })}
              </select>
              <select
                className={styles.input}
                value={exprTag}
                onChange={(e) => setExprTag(e.target.value)}
                aria-label="表情"
              >
                <option value="">（无表情）</option>
                {expressions.map((ex) => (
                  <option key={ex.id} value={ex.tag}>
                    {ex.name || ex.tag}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className={styles.go}
                disabled={!sprite}
                onClick={() =>
                  insert(
                    `show ${sprite?.imageTag ?? ""}${exprTag ? ` ${exprTag}` : ""}`
                  )
                }
              >
                插入出场
              </button>
              <button
                type="button"
                className={styles.ghost}
                disabled={!sprite}
                onClick={() => insert(`hide ${sprite?.imageTag ?? ""}`)}
              >
                插入退场
              </button>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
