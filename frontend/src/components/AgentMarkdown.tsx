import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import styles from "./AgentMarkdown.module.css";

type Props = {
  content: string;
  /** User bubbles stay plain; assistant uses markdown */
  mode?: "plain" | "markdown";
};

export function AgentMessageBody({ content, mode = "markdown" }: Props) {
  if (mode === "plain") {
    return <p className={styles.plain}>{content}</p>;
  }
  return (
    <div className={styles.md}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
