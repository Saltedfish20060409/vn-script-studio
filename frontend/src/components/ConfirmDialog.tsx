import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { mascotLine } from "../lib/mascotCopy";
import { MascotFigure } from "./MascotFigure";
import styles from "./ConfirmDialog.module.css";

export type ConfirmOptions = {
  title: string;
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Stronger emphasis: red confirm, danger mascot line */
  danger?: boolean;
  /** Override mascot caption */
  line?: string;
};

export type PromptOptions = {
  title: string;
  body?: string;
  defaultValue?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  placeholder?: string;
  /** Override mascot caption */
  line?: string;
};

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;
type PromptFn = (opts: PromptOptions) => Promise<string | null>;

const ConfirmCtx = createContext<ConfirmFn | null>(null);
const PromptCtx = createContext<PromptFn | null>(null);

export function useConfirm(): ConfirmFn {
  const fn = useContext(ConfirmCtx);
  if (!fn) {
    return async (opts) =>
      window.confirm([opts.title, opts.body].filter(Boolean).join("\n"));
  }
  return fn;
}

export function usePrompt(): PromptFn {
  const fn = useContext(PromptCtx);
  if (!fn) {
    return async (opts) =>
      window.prompt(
        [opts.title, opts.body].filter(Boolean).join("\n"),
        opts.defaultValue ?? ""
      );
  }
  return fn;
}

type ConfirmPending = ConfirmOptions & {
  resolve: (v: boolean) => void;
};

type PromptPending = PromptOptions & {
  resolve: (v: string | null) => void;
};

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [confirmPending, setConfirmPending] = useState<ConfirmPending | null>(
    null
  );
  const [promptPending, setPromptPending] = useState<PromptPending | null>(
    null
  );
  const [promptValue, setPromptValue] = useState("");
  const titleId = useId();
  const promptTitleId = useId();
  const confirmRef = useRef<HTMLButtonElement>(null);
  const promptInputRef = useRef<HTMLInputElement>(null);

  const confirm = useCallback<ConfirmFn>((opts) => {
    return new Promise<boolean>((resolve) => {
      setConfirmPending({ ...opts, resolve });
    });
  }, []);

  const prompt = useCallback<PromptFn>((opts) => {
    return new Promise<string | null>((resolve) => {
      setPromptValue(opts.defaultValue ?? "");
      setPromptPending({ ...opts, resolve });
    });
  }, []);

  const closeConfirm = useCallback((value: boolean) => {
    setConfirmPending((cur) => {
      cur?.resolve(value);
      return null;
    });
  }, []);

  const closePrompt = useCallback(
    (value: string | null) => {
      setPromptPending((cur) => {
        cur?.resolve(value);
        return null;
      });
      setPromptValue("");
    },
    []
  );

  useEffect(() => {
    if (!confirmPending) return;
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeConfirm(false);
      } else if (e.key === "Enter") {
        const t = e.target as HTMLElement | null;
        if (t && (t.tagName === "TEXTAREA" || t.isContentEditable)) return;
        e.preventDefault();
        closeConfirm(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirmPending, closeConfirm]);

  useEffect(() => {
    if (!promptPending) return;
    promptInputRef.current?.focus();
    promptInputRef.current?.select();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closePrompt(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [promptPending, closePrompt]);

  const confirmLine =
    confirmPending?.line ??
    (confirmPending
      ? mascotLine(confirmPending.danger ? "confirmDanger" : "confirmSoft")
      : "");

  const promptLine =
    promptPending?.line ??
    (promptPending ? mascotLine("confirmSoft") : "");

  return (
    <ConfirmCtx.Provider value={confirm}>
      <PromptCtx.Provider value={prompt}>
        {children}
        {confirmPending ? (
          <div
            className={styles.backdrop}
            role="presentation"
            onClick={() => closeConfirm(false)}
          >
            <div
              className={`${styles.dialog} ${confirmPending.danger ? styles.danger : ""}`}
              role="alertdialog"
              aria-modal="true"
              aria-labelledby={titleId}
              onClick={(e) => e.stopPropagation()}
            >
              <div className={styles.mascotCol}>
                <MascotFigure
                  size="lg"
                  mood={confirmPending.danger ? "angry" : "think"}
                  line={confirmLine}
                />
              </div>
              <div className={styles.body}>
                <p className={styles.idx} aria-hidden>
                  {confirmPending.danger ? "!" : "OK"}
                </p>
                <h2 id={titleId} className={styles.title}>
                  {confirmPending.title}
                </h2>
                {confirmPending.body ? (
                  <p className={styles.text}>{confirmPending.body}</p>
                ) : null}
                <div className={styles.actions}>
                  <button
                    type="button"
                    className={styles.ghost}
                    onClick={() => closeConfirm(false)}
                  >
                    {confirmPending.cancelLabel || "取消"}
                  </button>
                  <button
                    ref={confirmRef}
                    type="button"
                    className={
                      confirmPending.danger ? styles.dangerBtn : styles.primary
                    }
                    onClick={() => closeConfirm(true)}
                  >
                    {confirmPending.confirmLabel ||
                      (confirmPending.danger ? "确认删除" : "确认")}
                  </button>
                </div>
                <p className={styles.hint}>Enter 确认 · Esc 取消</p>
              </div>
            </div>
          </div>
        ) : null}
        {promptPending ? (
          <div
            className={styles.backdrop}
            role="presentation"
            onClick={() => closePrompt(null)}
          >
            <div
              className={styles.dialog}
              role="dialog"
              aria-modal="true"
              aria-labelledby={promptTitleId}
              onClick={(e) => e.stopPropagation()}
            >
              <div className={styles.mascotCol}>
                <MascotFigure size="lg" mood="think" line={promptLine} />
              </div>
              <div className={styles.body}>
                <p className={styles.idx} aria-hidden>
                  IN
                </p>
                <h2 id={promptTitleId} className={styles.title}>
                  {promptPending.title}
                </h2>
                {promptPending.body ? (
                  <p className={styles.text}>{promptPending.body}</p>
                ) : null}
                <form
                  className={styles.promptForm}
                  onSubmit={(e) => {
                    e.preventDefault();
                    closePrompt(promptValue);
                  }}
                >
                  <input
                    ref={promptInputRef}
                    className={styles.promptInput}
                    value={promptValue}
                    placeholder={promptPending.placeholder}
                    onChange={(e) => setPromptValue(e.target.value)}
                    aria-label={promptPending.title}
                  />
                  <div className={styles.actions}>
                    <button
                      type="button"
                      className={styles.ghost}
                      onClick={() => closePrompt(null)}
                    >
                      {promptPending.cancelLabel || "取消"}
                    </button>
                    <button type="submit" className={styles.primary}>
                      {promptPending.confirmLabel || "确认"}
                    </button>
                  </div>
                </form>
                <p className={styles.hint}>Enter 确认 · Esc 取消</p>
              </div>
            </div>
          </div>
        ) : null}
      </PromptCtx.Provider>
    </ConfirmCtx.Provider>
  );
}
