import { Component, type ErrorInfo, type ReactNode } from "react";
import { reportError } from "../lib/errorReporter";

type Props = {
  children: ReactNode;
  /** Short label for where the boundary sits */
  label?: string;
};

type State = {
  error: Error | null;
};

/** Prevent a child crash from blanking the whole studio. */
export class StudioErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[StudioErrorBoundary:${this.props.label || "app"}]`, error, info);
    reportError({
      message: error.message || String(error),
      stack: error.stack || "",
      component: this.props.label || "boundary",
    });
  }

  render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          style={{
            margin: "1.5rem",
            padding: "1.25rem 1.35rem",
            border: "2px solid var(--line, #1a2338)",
            background: "var(--panel-bg, #f0f3fa)",
            color: "var(--ink, #0a0e1a)",
            fontFamily: "var(--font-ui, sans-serif)",
            maxWidth: 520,
          }}
        >
          <p
            style={{
              margin: "0 0 0.35rem",
              fontFamily: "var(--font-display, sans-serif)",
              fontWeight: 700,
              letterSpacing: "0.08em",
              color: "var(--accent, #002fa7)",
              fontSize: "0.72rem",
            }}
          >
            ERROR · {this.props.label || "STUDIO"}
          </p>
          <p style={{ margin: "0 0 0.75rem", fontWeight: 600 }}>
            这块界面出错了，其它区域应仍可用。
          </p>
          <p
            style={{
              margin: "0 0 1rem",
              fontSize: "0.82rem",
              color: "var(--ink-soft, #4a5568)",
              wordBreak: "break-word",
            }}
          >
            {this.state.error.message || String(this.state.error)}
          </p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            style={{
              border: "1px solid var(--accent, #002fa7)",
              background: "var(--accent, #002fa7)",
              color: "#fff",
              padding: "0.4rem 0.85rem",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            重试这块
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              marginLeft: "0.5rem",
              border: "1px solid var(--line, #1a2338)",
              background: "transparent",
              color: "var(--ink, #0a0e1a)",
              padding: "0.4rem 0.85rem",
              cursor: "pointer",
            }}
          >
            刷新整页
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
