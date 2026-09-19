import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
  type RefObject,
  type TextareaHTMLAttributes,
} from "react";
import type { Location } from "../types/vn";
import {
  buildPlaceNeedles,
  placeTokenAtOffset,
  tokenizeScriptLine,
} from "../lib/mapOccurrences";
import { lineIndexOf, lineSegments, lineStarts, type MarkRange } from "../lib/markHighlight";
import styles from "./ScriptEditor.module.css";

type Props = Omit<
  TextareaHTMLAttributes<HTMLTextAreaElement>,
  "value" | "onChange" | "children"
> & {
  value: string;
  onChange: (value: string) => void;
  locations: Location[];
  onPlaceClick?: (locationId: string, label: string) => void;
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  frameClassName?: string;
  /** 标记区间：在正文里高亮被标记的段落（当前核对的那条用更强样式） */
  marks?: MarkRange[];
  /** 活动标记的偏移：`overlay` 会贴着这一行显示（跟着滚动一起走） */
  anchorOffset?: number | null;
  /** 贴在活动标记行下方的浮层（标记批改卡片） */
  overlay?: ReactNode;
};

export function ScriptEditor({
  value,
  onChange,
  locations,
  onPlaceClick,
  textareaRef,
  frameClassName = "",
  className = "",
  marks,
  anchorOffset = null,
  overlay,
  onScroll,
  onClick,
  ...rest
}: Props) {
  const localRef = useRef<HTMLTextAreaElement | null>(null);
  const mirrorRef = useRef<HTMLPreElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  /** 活动行在镜像内容坐标里的底边（不随滚动变化，滚动时只需减 scrollTop） */
  const anchorBottomRef = useRef<number | null>(null);
  const needles = useMemo(() => buildPlaceNeedles(locations), [locations]);
  const lines = useMemo(() => value.replace(/\r\n/g, "\n").split("\n"), [value]);
  const starts = useMemo(() => lineStarts(value), [value]);
  const markRanges = useMemo(() => marks ?? [], [marks]);
  // Tokenize once per (lines, needles): the mirror re-renders on every keystroke
  // but the token stream only changes when the text or location set changes.
  const tokenized = useMemo(
    () => lines.map((line) => tokenizeScriptLine(line, needles)),
    [lines, needles]
  );

  function setRefs(el: HTMLTextAreaElement | null) {
    localRef.current = el;
    if (textareaRef) textareaRef.current = el;
  }

  /** 把浮层贴到活动标记那一行的下方（clamp 在可见区域内，不跑出编辑器）。 */
  const placeOverlay = useCallback(() => {
    const ov = overlayRef.current;
    const ta = localRef.current;
    if (!ov || !ta) return;
    const base = anchorBottomRef.current;
    if (base === null) {
      ov.style.display = "none";
      return;
    }
    const visibleTop = base - ta.scrollTop;
    const maxTop = Math.max(6, ta.offsetHeight - Math.min(ov.offsetHeight || 0, ta.offsetHeight) - 6);
    const top = Math.min(Math.max(6, visibleTop), maxTop);
    ov.style.display = "";
    ov.style.top = `${top}px`;
  }, []);

  const syncScroll = useCallback(
    (from: HTMLTextAreaElement) => {
      const mirror = mirrorRef.current;
      if (mirror) {
        mirror.scrollTop = from.scrollTop;
        mirror.scrollLeft = from.scrollLeft;
      }
      placeOverlay();
    },
    [placeOverlay]
  );

  const syncMirrorSize = useCallback(() => {
    const ta = localRef.current;
    const mirror = mirrorRef.current;
    if (!ta || !mirror) return;
    mirror.style.height = `${ta.offsetHeight}px`;
    syncScroll(ta);
  }, [syncScroll]);

  useEffect(() => {
    const ta = localRef.current;
    if (!ta) return;
    syncMirrorSize();
    const ro = new ResizeObserver(() => syncMirrorSize());
    ro.observe(ta);
    return () => ro.disconnect();
  }, [value, syncMirrorSize]);

  // 活动标记行变成"内容坐标里的底边"：之后滚动时只减 scrollTop，不用重新量。
  useEffect(() => {
    const mirror = mirrorRef.current;
    if (anchorOffset === null || anchorOffset === undefined || !mirror) {
      anchorBottomRef.current = null;
      placeOverlay();
      return;
    }
    const span = mirror.children[lineIndexOf(value, anchorOffset)] as HTMLElement | undefined;
    anchorBottomRef.current = span ? span.offsetTop + span.offsetHeight : null;
    placeOverlay();
    // overlay 高度会随内容变（出对照稿时变高），再量一次
    const t = window.setTimeout(placeOverlay, 0);
    return () => window.clearTimeout(t);
  }, [anchorOffset, value, overlay, placeOverlay]);

  return (
    <div className={`${styles.frame} ${frameClassName}`.trim()} ref={frameRef}>
      <pre className={styles.mirror} ref={mirrorRef} aria-hidden>
        {tokenized.map((toks, li) => (
          <span key={li} className={styles.placeLine}>
            {lineSegments(toks, starts[li] ?? 0, markRanges).map((seg, si) =>
              seg.kind === "place" ? (
                <span key={`${li}-${si}`} className={styles.place}>
                  {seg.text}
                </span>
              ) : seg.kind === "mark" ? (
                <span
                  key={`${li}-${si}`}
                  className={seg.active ? styles.markActive : styles.mark}
                  data-mark-id={seg.markId}
                >
                  {seg.text}
                </span>
              ) : (
                <span key={`${li}-${si}`}>{seg.text}</span>
              )
            )}
            {li < lines.length - 1 ? "\n" : null}
          </span>
        ))}
        {value.endsWith("\n") ? "\n" : null}
      </pre>
      {overlay ? (
        <div className={styles.overlay} ref={overlayRef}>
          {overlay}
        </div>
      ) : null}
      <textarea
        {...rest}
        ref={setRefs}
        data-testid="script-editor"
        className={`${styles.input} vnss-editor-caret ${className}`.trim()}
        value={value}
        spellCheck={false}
        onChange={(e) => {
          onChange(e.target.value);
          syncScroll(e.target);
        }}
        onScroll={(e) => {
          syncScroll(e.currentTarget);
          onScroll?.(e);
        }}
        onClick={(e) => {
          onClick?.(e);
          if (!onPlaceClick || e.defaultPrevented) return;
          const ta = e.currentTarget;
          window.requestAnimationFrame(() => {
            // Drag-select / caret after the word should not jump
            if (ta.selectionStart !== ta.selectionEnd) return;
            const hit = placeTokenAtOffset(value, needles, ta.selectionStart);
            if (hit) onPlaceClick(hit.locationId, hit.value);
          });
        }}
      />
    </div>
  );
}
