import { useCallback, useEffect, useMemo, useState } from "react";
import type { Character, SceneChapter, ScriptBlock } from "../types/vn";
import {
  advance,
  choose,
  nextVisible,
  PLAY_START,
  scopeOf,
  type PlayState,
} from "../lib/playState";
import styles from "./ScriptPlayer.module.css";

type Props = {
  chapter: SceneChapter;
  characters: Character[];
  projectTitle: string;
  onExit: () => void;
};

/**
 * VN-style script player: walks a chapter's blocks as a playable sequence.
 * Supports labels (jump anchors), scene/show/hide cues, narration, dialogue,
 * menu choices (jump target or inline blocks), jump and return.
 */
export function ScriptPlayer({ chapter, characters, projectTitle, onExit }: Props) {
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

  const current = useMemo(() => {
    const scope = scopeOf(cursor, chapter.blocks ?? []);
    return scope[cursor.index] ?? null;
  }, [cursor, chapter.blocks]);

  const move = useCallback((next: PlayState, ended: boolean) => {
    setCursor(next);
    if (ended) setPhase("ended");
  }, []);

  // Land on the first playable block when playback starts.
  useEffect(() => {
    if (phase !== "playing") return;
    const idx = nextVisible(chapter.blocks ?? [], 0);
    if (idx === null) setPhase("ended");
    else if (idx !== 0) setCursor({ index: idx, stack: [], resume: [] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  // Seek on jump / end on return.
  useEffect(() => {
    if (phase !== "playing" || !current) return;
    if (current.type === "jump") {
      const target = labelIndex.get(current.target);
      if (target !== undefined) {
        setHistory((h) => [...h.slice(-300), cursor]);
        setCursor({ index: target, stack: [], resume: [] });
      }
    } else if (current.type === "return") {
      setPhase("ended");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, phase, labelIndex]);

  const advanceStep = useCallback(() => {
    setHistory((h) => [...h.slice(-300), cursor]);
    const { state, ended } = advance(cursor, chapter.blocks ?? []);
    move(state, ended);
  }, [cursor, chapter.blocks, move]);

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
    setCursor(PLAY_START);
    setHistory([]);
    setPhase("playing");
  }, []);

  const onChoose = (c: { text: string; jump?: string; blocks?: ScriptBlock[] }) => {
    setHistory((h) => [...h.slice(-300), cursor]);
    const { state, ended } = choose(cursor, chapter.blocks ?? [], c, labelIndex);
    move(state, ended);
  };

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
          <p className={styles.projectTitle}>—— 本章完 ——</p>
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

      <div className={styles.stage}>
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
        {block?.type === "menu" && (
          <div className={styles.menuBox}>
            {block.prompt ? <p className={styles.menuPrompt}>{block.prompt}</p> : null}
            <div className={styles.choices}>
              {(block.choices ?? []).map((c, i) => (
                <button key={i} type="button" className={styles.choice} onClick={() => onChoose(c)}>
                  {c.text}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className={styles.progress}>
        <span>
          第 {cursor.index + 1} / {chapter.blocks?.length ?? 0} 步
        </span>
      </div>
    </div>
  );
}
