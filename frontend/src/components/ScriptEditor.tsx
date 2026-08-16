import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type RefObject,
  type TextareaHTMLAttributes,
} from "react";
import type { Location } from "../types/vn";
import {
  buildPlaceNeedles,
  placeTokenAtOffset,
  tokenizeScriptLine,
} from "../lib/mapOccurrences";
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
};

export function ScriptEditor({
  value,
  onChange,
  locations,
  onPlaceClick,
  textareaRef,
  frameClassName = "",
  className = "",
  onScroll,
  onClick,
  ...rest
}: Props) {
  const localRef = useRef<HTMLTextAreaElement | null>(null);
  const mirrorRef = useRef<HTMLPreElement | null>(null);
  const needles = useMemo(() => buildPlaceNeedles(locations), [locations]);
  const lines = useMemo(() => value.replace(/\r\n/g, "\n").split("\n"), [value]);

  function setRefs(el: HTMLTextAreaElement | null) {
    localRef.current = el;
    if (textareaRef) textareaRef.current = el;
  }

  function syncScroll(from: HTMLTextAreaElement) {
    const mirror = mirrorRef.current;
    if (!mirror) return;
    mirror.scrollTop = from.scrollTop;
    mirror.scrollLeft = from.scrollLeft;
  }

  const syncMirrorSize = useCallback(() => {
    const ta = localRef.current;
    const mirror = mirrorRef.current;
    if (!ta || !mirror) return;
    mirror.style.height = `${ta.offsetHeight}px`;
    syncScroll(ta);
  }, []);

  useEffect(() => {
    const ta = localRef.current;
    if (!ta) return;
    syncMirrorSize();
    const ro = new ResizeObserver(() => syncMirrorSize());
    ro.observe(ta);
    return () => ro.disconnect();
  }, [value, syncMirrorSize]);

  return (
    <div className={`${styles.frame} ${frameClassName}`.trim()}>
      <pre className={styles.mirror} ref={mirrorRef} aria-hidden>
        {lines.map((line, li) => (
          <span key={li} className={styles.placeLine}>
            {tokenizeScriptLine(line, needles).map((tok, ti) =>
              tok.type === "place" ? (
                <span key={`${li}-${ti}`} className={styles.place}>
                  {tok.value}
                </span>
              ) : (
                <span key={`${li}-${ti}`}>{tok.value}</span>
              )
            )}
            {li < lines.length - 1 ? "\n" : null}
          </span>
        ))}
        {value.endsWith("\n") ? "\n" : null}
      </pre>
      <textarea
        {...rest}
        ref={setRefs}
        data-testid="script-editor"
        className={`${styles.input} ${className}`.trim()}
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
