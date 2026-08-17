/**
 * Web Speech API 听写封装 — 浏览器原生语音识别（Chrome/Edge 支持最佳）。
 * 纯前端：识别在浏览器本地进行，无需后端。
 */

export interface SpeechResultEvent {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    0: { transcript: string };
    length: number;
  }>;
}

export interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: SpeechResultEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

type Ctor = new () => SpeechRecognitionLike;

function recognitionCtor(): Ctor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: Ctor;
    webkitSpeechRecognition?: Ctor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** Whether the browser can do speech recognition at all. */
export function speechSupported(): boolean {
  return recognitionCtor() !== null;
}

/**
 * Create a recognition instance for the given BCP-47 lang (e.g. "zh-CN").
 * Returns null when unsupported. Callers must wire onresult/onend/onerror.
 */
export function createSpeechRecognition(lang = "zh-CN"): SpeechRecognitionLike | null {
  const Ctor = recognitionCtor();
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.lang = lang;
  rec.continuous = true;
  rec.interimResults = true;
  rec.maxAlternatives = 1;
  return rec;
}

/** Join live transcripts into a single insertable string. */
export function joinTranscripts(finalParts: string[], interim: string): string {
  const base = finalParts.join("").trim();
  const tail = interim.trim();
  if (!base && !tail) return "";
  if (!base) return tail;
  if (!tail) return base;
  return `${base}${tail}`;
}
