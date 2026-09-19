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
import { lineIndexOf, lineSegments, lineStarts, locateInNodes, type MarkRange } from "../lib/markHighlight";
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
  /** 当前选区：`selectionBar` 会贴在选区末尾旁边（选中就能就地标记） */
  selectionRange?: { from: number; to: number } | null;
  /** 贴在选区旁边的浮层（「标记这段」按钮） */
  selectionBar?: ReactNode;
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
  selectionRange = null,
  selectionBar,
  onScroll,
  onClick,
  ...rest
}: Props) {
  const localRef = useRef<HTMLTextAreaElement | null>(null);
  const mirrorRef = useRef<HTMLPreElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const selectionBarRef = useRef<HTMLDivElement | null>(null);
  /** 当前选区（供 placeSelectionBar 读取，避免把它塞进 useCallback 依赖） */
  const selectionRef = useRef<{ from: number; to: number } | null>(null);
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

  /**
   * 量出某个偏移处那个字符在屏幕上的位置。
   * 用镜像里的 Range 来量：镜像的字形与 textarea 完全一致（同一套度量），所以软换行、
   * 缩进、标点都不会算错——这正是"把按钮放到选中处旁边"需要的精度。
   */
  const measureCharRect = useCallback((offset: number): DOMRect | null => {
    const mirror = mirrorRef.current;
    if (!mirror) return null;
    const walker = document.createTreeWalker(mirror, NodeFilter.SHOW_TEXT);
    const nodes: Text[] = [];
    const lengths: number[] = [];
    while (walker.nextNode()) {
      const node = walker.currentNode as Text;
      nodes.push(node);
      lengths.push(node.data.length);
    }
    const at = locateInNodes(lengths, offset);
    if (!at) return null;
    const node = nodes[at.index];
    if (!node) return null;
    const start = Math.max(0, Math.min(at.local, node.data.length));
    const end = Math.min(start + 1, node.data.length);
    const range = document.createRange();
    if (end > start) {
      range.setStart(node, start);
      range.setEnd(node, end);
    } else {
      // 文末 / 空节点：退化成该节点末端的光标位
      range.setStart(node, node.data.length);
      range.setEnd(node, node.data.length);
    }
    const rect = range.getBoundingClientRect();
    return rect.width > 0 || rect.height > 0 ? rect : null;
  }, []);

  /** 把「标记这段」按钮贴到选区末尾旁边（选中就能就地标记，不用去下面找）。 */
  const placeSelectionBar = useCallback(() => {
    const bar = selectionBarRef.current;
    const ta = localRef.current;
    const frame = frameRef.current;
    if (!bar || !ta || !frame) return;
    const sel = selectionRef.current;
    if (!sel || sel.to <= sel.from) {
      bar.style.display = "none";
      return;
    }
    const rect = measureCharRect(sel.to - 1) ?? measureCharRect(sel.from);
    if (!rect) {
      bar.style.display = "none";
      return;
    }
    const frameRect = frame.getBoundingClientRect();
    const barW = bar.offsetWidth || 120;
    const barH = bar.offsetHeight || 28;
    const left = Math.min(
      Math.max(6, rect.right - frameRect.left - 4),
      Math.max(6, frameRect.width - barW - 10)
    );
    const maxTop = Math.max(6, ta.offsetHeight - barH - 6);
    const top = Math.min(Math.max(6, rect.bottom - frameRect.top + 6), maxTop);
    bar.style.display = "";
    bar.style.left = `${Math.round(left)}px`;
    bar.style.top = `${Math.round(top)}px`;
  }, [measureCharRect]);

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
      placeSelectionBar();
    },
    [placeOverlay, placeSelectionBar]
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

  // 选区变化 / 正文变化（会挪动字形位置）→ 重新贴「标记这段」按钮
  useEffect(() => {
    selectionRef.current = selectionRange ?? null;
    placeSelectionBar();
    // 按钮宽度要等布局完成才知道，补量一次
    const t = window.setTimeout(placeSelectionBar, 0);
    return () => window.clearTimeout(t);
  }, [selectionRange, value, selectionBar, placeSelectionBar]);

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
      {selectionBar ? (
        <div className={styles.selectionBar} ref={selectionBarRef}>
          {selectionBar}
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
