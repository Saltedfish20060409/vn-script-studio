import { useEffect, useState } from "react";
import styles from "./PwaInstallPrompt.module.css";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice?: Promise<{ outcome: "accepted" | "dismissed" }>;
};

/**
 * Optional PWA install banner. Listens for `beforeinstallprompt` (browsers
 * that support the install flow, e.g. Chrome/Edge on Android & desktop) and
 * shows a dismissible chip. The native prompt is only triggered on tap.
 */
export function PwaInstallPrompt() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => setDeferred(null);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (!deferred || dismissed) return null;

  return (
    <div className={styles.banner} role="status">
      <span className={styles.icon} aria-hidden>
        ⬇️
      </span>
      <span className={styles.text}>安装为应用，离线也能写作</span>
      <button
        type="button"
        className={styles.install}
        onClick={() => {
          void deferred.prompt();
          setDeferred(null);
        }}
      >
        安装
      </button>
      <button
        type="button"
        className={styles.dismiss}
        aria-label="稍后再说"
        onClick={() => setDismissed(true)}
      >
        ×
      </button>
    </div>
  );
}
