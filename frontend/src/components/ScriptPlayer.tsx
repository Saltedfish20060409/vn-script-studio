import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Character, GameVariable, SceneChapter, ScriptBlock } from "../types/vn";
import {
  advance,
  choose,
  INSTANT,
  MAX_PLAY_STEPS,
  PLAY_START,
  scopeOf,
  visibleChoices,
  type PlayState,
} from "../lib/playState";
import styles from "./ScriptPlayer.module.css";

type Props = {
  chapter: SceneChapter;
  characters: Character[];
  projectTitle: string;
  /** 项目「变量」表的初始值（好感度/旗标等），试玩中的 set 只改副本 */
  variables?: GameVariable[];
  onExit: () => void;
};

/** 试玩时的演出状态（由途中经过的瞬时指令驱动） */
type StageState = {
  bgm: string;
  sound: string;
  voice: string;
  camera: string;
  variables: Record<string, unknown>;
};

function initialVariables(vars?: GameVariable[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const v of vars ?? []) {
    if (v?.key) out[v.key] = v.value;
  }
  return out;
}

/**
 * VN-style script player: walks a chapter's blocks as a playable sequence.
 *
 * 支持：label / scene / show / hide / 旁白 / 对白 / 选项（可带条件）/
 * jump（线性跳转会被跟随）/ return / if 条件分支 / 音频（music/sound/voice）/
 * wait 等待 / camera 镜头 / effect 特效 / set 变量。
 *
 * 演出效果（音乐、镜头、变量）由途中经过的瞬时指令驱动，见 lib/playState.ts。
 */
export function ScriptPlayer({ chapter, characters, projectTitle, variables, onExit }: Props) {
  const charMap = useMemo(
    () => new Map(characters.map((c) => [c.id, c])),
    [characters]
  );
  const labelIndex = useMemo(() => {
    const m = new Map<string, number>();
    (chapter.blocks ?? []).forEach((b, i) => {
      if (b.type === "label") m.set(b.name, i);
    });
    return m;
  }, [chapter.blocks]);

  const [cursor, setCursor] = useState<PlayState>(PLAY_START);
  const [history, setHistory] = useState<PlayState[]>([]);
  const [phase, setPhase] = useState<"intro" | "playing" | "ended">("intro");
  const [loopStop, setLoopStop] = useState(false);
  const stepRef = useRef(0);

  // 演出状态：由途中经过的瞬时指令（音乐/音效/语音/镜头/特效/变量）驱动
  const [stage, setStage] = useState<StageState>(() => ({
    bgm: "",
    sound: "",
    voice: "",
    camera: "",
    variables: initialVariables(variables),
  }));

  /** 初始变量值：来自项目「变量」表；试玩中的 set 指令只改这份副本，不写回项目。 */
  const runtimeVars = useRef<Record<string, unknown>>(initialVariables(variables));

  const applyExecuted = useCallback((executed: ScriptBlock[]) => {
    if (!executed.length) return;
    setStage((prev) => {
      let next = prev;
      const vars = { ...runtimeVars.current };
      for (const b of executed) {
        if (b.type === "music") {
          next = { ...next, bgm: b.action === "stop" ? "" : b.file || "(未命名)" };
        } else if (b.type === "sound") {
          next = { ...next, sound: b.action === "stop" ? "" : b.file || "(未命名)" };
        } else if (b.type === "voice") {
          next = { ...next, voice: b.action === "stop" ? "" : b.file || "(未命名)" };
        } else if (b.type === "camera") {
          next = {
            ...next,
            camera: b.at
              ? b.at
              : `zoom ${b.zoom ?? 1}${b.x !== undefined ? ` x${b.x}` : ""}${
                  b.y !== undefined ? ` y${b.y}` : ""
                }`,
          };
        } else if (b.type === "set") {
          const cur = vars[b.key];
          const numeric = typeof b.value === "number" ? b.value : Number(b.value);
          if (b.op === "+=") vars[b.key] = Number(cur ?? 0) + (Number.isFinite(numeric) ? numeric : 0);
          else if (b.op === "-=") vars[b.key] = Number(cur ?? 0) - (Number.isFinite(numeric) ? numeric : 0);
          else vars[b.key] = b.value ?? 0;
        }
      }
      runtimeVars.current = vars;
      return { ...next, variables: vars };
    });
  }, []);

  const current = useMemo(() => {
    const scope = scopeOf(cursor, chapter.blocks ?? []);
    return scope[cursor.index] ?? null;
  }, [cursor, chapter.blocks]);

  const bumpStep = useCallback(() => {
    stepRef.current += 1;
    if (stepRef.current > MAX_PLAY_STEPS) {
      setLoopStop(true);
      setPhase("ended");
      return true;
    }
    return false;
  }, []);

  const move = useCallback((next: PlayState, ended: boolean) => {
    setCursor(next);
    if (ended) setPhase("ended");
  }, []);

  // 开演：PLAY_START.index = -1，advance 会从第 0 块开始扫，
  // 于是开头的音乐/镜头等瞬时指令也能执行（旧版会漏掉）。
  useEffect(() => {
    if (phase !== "playing") return;
    stepRef.current = 0;
    const out = advance(PLAY_START, chapter.blocks ?? [], {
      variables: runtimeVars.current,
    }, labelIndex);
    applyExecuted(out.executed);
    if (out.looped) setLoopStop(true);
    move(out.state, out.ended);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // return 结束本章（jump 现在由 advance 直接跟随，不再需要单独的 effect）
  useEffect(() => {
    if (phase !== "playing" || !current) return;
    if (current.type === "return") setPhase("ended");
  }, [current, phase]);

  const advanceStep = useCallback(() => {
    if (bumpStep()) return;
    setHistory((h) => [...h.slice(-300), cursor]);
    const { state, ended, executed, looped } = advance(
      cursor,
      chapter.blocks ?? [],
      { variables: runtimeVars.current },
      labelIndex
    );
    applyExecuted(executed);
    if (looped) setLoopStop(true);
    move(state, ended);
  }, [cursor, chapter.blocks, move, bumpStep, applyExecuted, labelIndex]);

  // 「等待 N 秒」自动继续（点一下也能立刻跳过）
  useEffect(() => {
    if (phase !== "playing") return;
    if (current?.type !== "wait") return;
    const seconds = typeof current.seconds === "number" ? current.seconds : 1;
    const timer = window.setTimeout(() => advanceStep(), Math.max(0.1, seconds) * 1000);
    return () => window.clearTimeout(timer);
  }, [current, phase, advanceStep]);

  const goBack = useCallback(() => {
    setHistory((h) => {
      const prev = h[h.length - 1];
      if (prev) {
        setCursor(prev);
        return h.slice(0, -1);
      }
      return h;
    });
  }, []);

  const reset = useCallback(() => {
    stepRef.current = 0;
    setLoopStop(false);
    const fresh = initialVariables(variables);
    runtimeVars.current = fresh;
    setStage({ bgm: "", sound: "", voice: "", camera: "", variables: fresh });
    setCursor(PLAY_START);
    setHistory([]);
    setPhase("playing");
  }, [variables]);

  const onChoose = (c: { text: string; jump?: string; blocks?: ScriptBlock[] }) => {
    if (bumpStep()) return;
    setHistory((h) => [...h.slice(-300), cursor]);
    const { state, ended } = choose(cursor, chapter.blocks ?? [], c, labelIndex);
    move(state, ended);
    if (!ended) {
      // 选项正文开场可能又是瞬时指令 → 立刻应用一次
      const scope = scopeOf(state, chapter.blocks ?? []);
      const executed: ScriptBlock[] = [];
      for (let i = 0; i < state.index; i++) {
        const b = scope[i];
        if (b && INSTANT.has(b.type)) executed.push(b);
      }
      applyExecuted(executed);
    }
  };
  // Skip scene/show/hide cues in one go (keyboard "skip").
  const skipCues = useCallback(() => {
    setHistory((h) => [...h.slice(-300), cursor]);
    let s = cursor;
    let ended = false;
    const collected: ScriptBlock[] = [];
    for (let i = 0; i < 60; i++) {
      const b = scopeOf(s, chapter.blocks ?? [])[s.index];
      if (!b) {
        ended = true;
        break;
      }
      if (b.type === "scene" || b.type === "show" || b.type === "hide") {
        const r = advance(s, chapter.blocks ?? [], {
          variables: runtimeVars.current,
        }, labelIndex);
        s = r.state;
        ended = r.ended;
        collected.push(...r.executed);
      } else {
        break;
      }
    }
    applyExecuted(collected);
    move(s, ended);
  }, [cursor, chapter.blocks, move, applyExecuted, labelIndex]);

  // VN-style keyboard shortcuts while playing.
  useEffect(() => {
    if (phase !== "playing") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onExit();
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        skipCues();
        return;
      }
      const b = scopeOf(cursor, chapter.blocks ?? [])[cursor.index] ?? null;
      if (b?.type === "menu") {
        if (/^[1-9]$/.test(e.key)) {
          const idx = Number(e.key) - 1;
          const choice = b.choices[idx];
          if (choice) {
            e.preventDefault();
            onChoose(choice);
          }
        }
        return;
      }
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        advanceStep();
      } else if (e.key === "Backspace" || e.key === "ArrowLeft") {
        e.preventDefault();
        goBack();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, cursor, chapter.blocks, skipCues]);

  if (phase === "intro") {
    return (
      <div className={styles.wrap}>
        <div className={styles.titleCard}>
          <p className={styles.projectTitle}>{projectTitle}</p>
          <h1 className={styles.chapterTitle}>{chapter.title}</h1>
          {chapter.synopsis ? <p className={styles.synopsis}>{chapter.synopsis}</p> : null}
          <button type="button" className={styles.start} onClick={reset}>
            开始试玩
          </button>
          <button type="button" className={styles.ghost} onClick={onExit}>
            返回编辑
          </button>
        </div>
      </div>
    );
  }

  if (phase === "ended") {
    return (
      <div className={styles.wrap}>
        <div className={styles.endCard}>
          <p className={styles.projectTitle}>
            {loopStop ? "—— 检测到疑似死循环 ——" : "—— 本章完 ——"}
          </p>
          {loopStop ? (
            <p className={styles.endNote}>
              脚本结构可能导致无限跳转（常见于 AI 生成的 RPY：选项跳回开头）。
              已自动停止。可返回编辑检查脚本，或重新生成。
            </p>
          ) : null}
          <button type="button" className={styles.start} onClick={reset}>
            重新播放
          </button>
          <button type="button" className={styles.ghost} onClick={onExit}>
            返回编辑
          </button>
        </div>
      </div>
    );
  }

  const block = current;
  const speaker =
    block?.type === "dialogue" ? charMap.get(block.characterId) : undefined;
  const speakerColor = speaker?.color ?? "#e8b64c";

  return (
    <div className={styles.wrap}>
      <div className={styles.controls}>
        <button type="button" className={styles.exit} onClick={onExit} title="返回编辑">
          ✕
        </button>
        <button
          type="button"
          className={styles.ghost}
          onClick={goBack}
          disabled={history.length === 0}
        >
          ← 后退
        </button>
        <button type="button" className={styles.ghost} onClick={reset}>
          重置
        </button>
      </div>

      <div
        className={styles.stage}
        onClick={(e) => {
          // 仅当点的是舞台空白处（非对白/旁白/菜单/按钮）才前进，
          // 避免与子元素 onClick 冒泡造成一步变两步
          const b = current;
          if (b?.type === "menu") return;
          if (e.target !== e.currentTarget) return;
          advanceStep();
        }}
      >
        {block?.type === "scene" && (
          <div className={styles.sceneCue}>
            <p>[ 场景：{block.image} ]</p>
            {block.transition ? <p className={styles.sub}>{block.transition}</p> : null}
            <button type="button" className={styles.continue} onClick={advanceStep}>
              继续 ▶
            </button>
          </div>
        )}
        {block?.type === "show" && (
          <div className={styles.sceneCue}>
            <p>[ 出场：{block.image} ]</p>
            <button type="button" className={styles.continue} onClick={advanceStep}>
              继续 ▶
            </button>
          </div>
        )}
        {block?.type === "hide" && (
          <div className={styles.sceneCue}>
            <p>[ 退场：{block.image} ]</p>
            <button type="button" className={styles.continue} onClick={advanceStep}>
              继续 ▶
            </button>
          </div>
        )}
        {block?.type === "narration" && (
          <div className={styles.narrationBox} onClick={advanceStep}>
            <p>{block.text}</p>
          </div>
        )}
        {block?.type === "dialogue" && (
          <div className={styles.dialogueBox} onClick={advanceStep}>
            <p
              className={styles.speaker}
              style={{ color: speakerColor, borderColor: speakerColor }}
            >
              {speaker?.displayName ?? block.characterId}
            </p>
            <p className={styles.line}>{block.text}</p>
            <p className={styles.advanceHint}>点击继续 ▾</p>
          </div>
        )}
        {block?.type === "wait" && (
          <div className={styles.sceneCue}>
            <p>[ 等待 {typeof block.seconds === "number" ? block.seconds : 1} 秒 ]</p>
            <button type="button" className={styles.continue} onClick={advanceStep}>
              立即继续 ▶
            </button>
          </div>
        )}
        {block?.type === "menu" &&
          (() => {
            const shown = visibleChoices(block.choices ?? [], stage.variables);
            return (
              <div className={styles.menuBox}>
                {block.prompt ? <p className={styles.menuPrompt}>{block.prompt}</p> : null}
                <div className={styles.choices}>
                  {shown.map((c, i) => (
                    <button
                      key={`${c.text}-${i}`}
                      type="button"
                      className={styles.choice}
                      onClick={() => onChoose(c)}
                    >
                      {c.text}
                    </button>
                  ))}
                </div>
                {shown.length === 0 ? (
                  <p className={styles.advanceHint}>
                    所有选项的条件都不成立（检查变量初始值与选项条件），已按"没有可选项"处理。
                  </p>
                ) : null}
              </div>
            );
          })()}
      </div>

      {/* 演出状态：让作者一眼看出音乐/镜头/变量当前是什么 */}
      <div className={styles.progress}>
        <span>
          第 {cursor.index + 1} / {chapter.blocks?.length ?? 0} 步
          {stage.bgm ? ` · ♪ ${stage.bgm}` : ""}
          {stage.sound ? ` · 🔔 ${stage.sound}` : ""}
          {stage.voice ? ` · 🎙 ${stage.voice}` : ""}
          {stage.camera ? ` · 🎥 ${stage.camera}` : ""}
        </span>
        <span className={styles.keys}>
          Enter/空格 继续 · ←/Backspace 后退 · Tab 跳过提示 · Esc 退出 · 菜单按数字选择
        </span>
      </div>
      {Object.keys(stage.variables).length > 0 ? (
        <div className={styles.progress}>
          <span>
            变量：
            {Object.entries(stage.variables)
              .map(([k, v]) => `${k}=${String(v)}`)
              .join(" · ")}
          </span>
        </div>
      ) : null}
    </div>
  );
}
