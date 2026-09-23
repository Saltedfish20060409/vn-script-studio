import { useEffect, useMemo, useRef, useState } from "react";
import {
  expandReplacement,
  findMatches,
  replaceAllMatches,
  replaceRange,
} from "../lib/editorAssist";
import styles from "./FindReplaceBar.module.css";

type Props = {
  /** 当前正文（受控：改完由父组件走和手打一样的保存路径） */
  text: string;
  /** 提交换后的正文；父组件负责标记校验与自动保存 */
  onChangeText: (next: string) => void;
  /** 把编辑器选区移到某处（父组件负责聚焦与滚动到可见） */
  onJump: (from: number, length: number) => void;
  onClose: () => void;
  /** 打开时预填的查找词（一般用编辑器里选中的文字） */
  initialQuery?: string;
};

/**
 * 查找 / 替换。
 *
 * 为什么必须自己做：正文在 `<textarea>` 里，浏览器的 Ctrl+F 找不到它——
 * 作者要改一个角色名、统一一种标点，只能靠肉眼翻。这一条条框框很小，
 * 但它是"能改稿"和"只能重打"的分界。
 *
 * 替换不直接改 DOM：一律走父组件的 onChangeText，于是标记失效校验、
 * "RPY 可能过期"、自动保存这些既有机制全都照常生效。
 */
export function FindReplaceBar({
  text,
  onChangeText,
  onJump,
  onClose,
  initialQuery = "",
}: Props) {
  const [query, setQuery] = useState(initialQuery);
  const [replacement, setReplacement] = useState("");
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [regex, setRegex] = useState(false);
  const [index, setIndex] = useState(0);
  const [note, setNote] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.focus();
    el.select();
  }, []);

  const matches = useMemo(
    () => findMatches(text, query, { caseSensitive, regex }),
    [text, query, caseSensitive, regex]
  );
  const regexError = matches === null;
  const list = matches ?? [];

  // 换了查找词/选项就从第一处重新数，否则会停在一个旧的下标上
  useEffect(() => {
    setIndex(0);
    setNote("");
  }, [query, caseSensitive, regex]);

  const clamped = list.length === 0 ? -1 : Math.min(index, list.length - 1);
  const current = clamped >= 0 ? list[clamped] : null;

  function go(delta: number) {
    if (list.length === 0) return;
    const next = (clamped + delta + list.length) % list.length;
    setIndex(next);
    onJump(list[next].from, list[next].to - list[next].from);
  }

  function replaceOne() {
    if (!current) return;
    const piece = expandReplacement(text, current, query, replacement, { caseSensitive, regex });
    onChangeText(replaceRange(text, current.from, current.to, piece));
    setNote(`已替换 1 处（第 ${clamped + 1} 处）`);
    // 替换后原位置的下一个命中会滑到同一个下标上，不用动 index
    onJump(current.from, piece.length);
  }

  function replaceEvery() {
    const res = replaceAllMatches(text, query, replacement, { caseSensitive, regex });
    if (res.count === 0) {
      setNote(regexError ? "正则写错了，没有替换任何内容" : "没有可替换的内容");
      return;
    }
    onChangeText(res.text);
    setNote(`已替换 ${res.count} 处`);
  }

  return (
    <div className={styles.bar} data-testid="find-replace-bar">
      <div className={styles.row}>
        <input
          ref={inputRef}
          className={styles.input}
          data-testid="find-input"
          placeholder="查找（Ctrl+F）"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              go(e.shiftKey ? -1 : 1);
            } else if (e.key === "Escape") {
              e.preventDefault();
              onClose();
            }
          }}
        />
        <span className={styles.count} data-testid="find-count">
          {regexError
            ? "正则写错了"
            : list.length === 0
              ? query
                ? "没有匹配"
                : "输入要查找的内容"
              : `第 ${clamped + 1} / ${list.length} 处`}
        </span>
        <button
          type="button"
          className={styles.ghost}
          disabled={list.length === 0}
          title="上一处（Shift+Enter）"
          onClick={() => go(-1)}
        >
          ↑
        </button>
        <button
          type="button"
          className={styles.ghost}
          disabled={list.length === 0}
          title="下一处（Enter）"
          onClick={() => go(1)}
        >
          ↓
        </button>
        <button
          type="button"
          className={caseSensitive ? styles.toggleOn : styles.toggleOff}
          aria-pressed={caseSensitive}
          title="区分大小写（只影响英文字母）"
          onClick={() => setCaseSensitive((v) => !v)}
        >
          Aa
        </button>
        <button
          type="button"
          className={regex ? styles.toggleOn : styles.toggleOff}
          aria-pressed={regex}
          title="正则表达式：替换时可以用 $1 引用捕获组"
          onClick={() => setRegex((v) => !v)}
        >
          .*
        </button>
        <button type="button" className={styles.ghost} onClick={onClose} title="关闭（Esc）">
          ×
        </button>
      </div>
      <div className={styles.row}>
        <input
          className={styles.input}
          data-testid="replace-input"
          placeholder="替换为"
          value={replacement}
          onChange={(e) => setReplacement(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              replaceOne();
            } else if (e.key === "Escape") {
              e.preventDefault();
              onClose();
            }
          }}
        />
        <button
          type="button"
          className={styles.ghost}
          disabled={!current}
          data-testid="replace-one"
          onClick={replaceOne}
        >
          替换这一处
        </button>
        <button
          type="button"
          className={styles.ghost}
          disabled={list.length === 0}
          data-testid="replace-all"
          onClick={replaceEvery}
        >
          全部替换{list.length > 0 ? `（${list.length}）` : ""}
        </button>
        {note ? <span className={styles.note}>{note}</span> : null}
      </div>
    </div>
  );
}
