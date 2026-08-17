import { useEffect, useRef, useState } from "react";
import {
  createSpeechRecognition,
  joinTranscripts,
  speechSupported,
  type SpeechRecognitionLike,
} from "../lib/speechInput";
import styles from "./SpeechInputButton.module.css";

type Props = {
  /** Called with the final transcript when dictation stops (or is cancelled). */
  onInsert: (text: string) => void;
  /** Auto start on mount (e.g. after the user explicitly chose to). */
  autoStart?: boolean;
};

/**
 * 语音输入按钮：点击开始听写，再次点击停止并把转写交给 onInsert。
 * 浏览器不支持时整个按钮不渲染。
 */
export function SpeechInputButton({ onInsert, autoStart = false }: Props) {
  const supported = speechSupported();
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const finalsRef = useRef<string[]>([]);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");

  useEffect(() => {
    if (!supported) return;
    if (autoStart) start();
    return () => {
      const rec = recRef.current;
      if (rec) {
        rec.onresult = null;
        rec.onend = null;
        rec.onerror = null;
        try {
          rec.abort();
        } catch {
          /* already stopped */
        }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supported]);

  function stopAndDeliver() {
    const rec = recRef.current;
    if (!rec) return;
    rec.onresult = null;
    rec.onend = null;
    rec.onerror = null;
    try {
      rec.stop();
    } catch {
      /* ignore */
    }
    const text = joinTranscripts(finalsRef.current, interim);
    finalsRef.current = [];
    setInterim("");
    setListening(false);
    if (text) onInsert(text);
  }

  function start() {
    if (listening) return;
    const rec = createSpeechRecognition("zh-CN");
    if (!rec) return;
    recRef.current = rec;
    finalsRef.current = [];
    setInterim("");
    setListening(true);
    rec.onresult = (e) => {
      let interimText = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        const transcript = res?.[0]?.transcript ?? "";
        if (res?.isFinal) {
          finalsRef.current.push(transcript);
        } else {
          interimText += transcript;
        }
      }
      setInterim(interimText);
    };
    rec.onend = () => {
      // Stop() already delivered; a spontaneous end (silence) delivers too.
      if (listening) {
        const text = joinTranscripts(finalsRef.current, interim);
        finalsRef.current = [];
        setInterim("");
        setListening(false);
        if (text) onInsert(text);
      }
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        setListening(false);
      }
    };
    try {
      rec.start();
    } catch {
      setListening(false);
    }
  }

  if (!supported) return null;

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={`${styles.mic} ${listening ? styles.listening : ""}`}
        onClick={() => (listening ? stopAndDeliver() : start())}
        title={listening ? "停止听写并插入" : "语音输入（中文听写）"}
        aria-pressed={listening}
        data-testid="speech-input-button"
      >
        {listening ? "⏹" : "🎤"}
      </button>
      {listening && (
        <span className={styles.live} role="status" aria-live="polite">
          {interim || "正在聆听…"}
        </span>
      )}
    </div>
  );
}
