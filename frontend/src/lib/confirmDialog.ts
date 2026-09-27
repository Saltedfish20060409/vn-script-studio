import { createContext, useContext } from "react";

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
  /**
   * 输入框的字符上限（可选）。
   *
   * 为什么需要：新建 / 重命名作品走的都是这个弹窗，而作品标题在数据库里是
   * `varchar(255)` —— 不设上限时，粘一大段文字进去会在保存那一刻被服务端拒绝
   * （线上曾经是 500）。第一道门放在这里最省事。
   */
  maxLength?: number;
  /** Override mascot caption */
  line?: string;
};

export type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;
export type PromptFn = (opts: PromptOptions) => Promise<string | null>;

export const ConfirmCtx = createContext<ConfirmFn | null>(null);
export const PromptCtx = createContext<PromptFn | null>(null);

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
