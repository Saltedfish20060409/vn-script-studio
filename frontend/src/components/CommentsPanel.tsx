import { useEffect, useRef, useState } from "react";
import {
  addProjectComment,
  deleteProjectComment,
  listProjectComments,
  subscribeProjectEvents,
  updateProjectComment,
  type ProjectComment,
} from "../api/collab";
import { MascotFigure } from "./MascotFigure";
import styles from "./CommentsPanel.module.css";

type Props = {
  projectId: string;
  chapterId: string;
  chapterTitle: string;
  myUserId: string;
};

/** Collapsible inline annotation panel for the active chapter. */
export function CommentsPanel({
  projectId,
  chapterId,
  chapterTitle,
  myUserId,
}: Props) {
  const [open, setOpen] = useState(false);
  const [comments, setComments] = useState<ProjectComment[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const mountRef = useRef(true);

  useEffect(() => {
    mountRef.current = true;
    return () => {
      mountRef.current = false;
    };
  }, []);

  const refresh = async () => {
    try {
      const data = await listProjectComments(projectId, chapterId);
      if (mountRef.current) setComments(data.comments);
    } catch {
      /* transient */
    }
  };

  // Load on mount and when the chapter changes.
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, chapterId]);

  // Live updates via the project SSE bus.
  useEffect(() => {
    const unsub = subscribeProjectEvents(projectId, (evt) => {
      if (evt.type !== "comment") return;
      if (evt.chapterId && evt.chapterId !== chapterId) return;
      void refresh();
    });
    return () => unsub();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, chapterId]);

  const submit = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setBusy(true);
    setError("");
    try {
      await addProjectComment(projectId, {
        chapter_id: chapterId,
        text,
      });
      setDraft("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "添加批注失败");
    } finally {
      setBusy(false);
    }
  };

  const toggleResolved = async (c: ProjectComment) => {
    try {
      await updateProjectComment(projectId, c.id, { resolved: !c.resolved });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新失败");
    }
  };

  const saveEdit = async (c: ProjectComment) => {
    const text = editDraft.trim();
    if (!text) return;
    try {
      await updateProjectComment(projectId, c.id, { text });
      setEditingId(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新失败");
    }
  };

  const remove = async (c: ProjectComment) => {
    try {
      await deleteProjectComment(projectId, c.id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  };

  const openCount = comments.filter((c) => !c.resolved).length;

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={styles.toggle}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className={styles.toggleIcon}>💬</span>
        <span>批注</span>
        {openCount > 0 && (
          <span className={styles.badge}>{openCount}</span>
        )}
      </button>
      {open && (
        <div className={styles.panel}>
          <p className={styles.hint}>
            「{chapterTitle}」上的协作批注 — 成员实时可见
          </p>
          {error && <p className={styles.error}>{error}</p>}
          <div className={styles.composer}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="给本章加一条批注…"
              rows={2}
            />
            <button
              type="button"
              className={styles.primary}
              disabled={busy || !draft.trim()}
              onClick={() => void submit()}
            >
              添加
            </button>
          </div>
          {comments.length === 0 ? (
            <div className={styles.empty}>
              <MascotFigure mood="idle" size="sm" />
              <p>还没有批注。选中文字，或直接在这里留下意见。</p>
            </div>
          ) : (
            <ul className={styles.list}>
              {comments.map((c) => (
                <li
                  key={c.id}
                  className={`${styles.item} ${c.resolved ? styles.resolved : ""}`}
                >
                  <div className={styles.itemHead}>
                    <span className={styles.author}>{c.username}</span>
                    <time className={styles.time}>
                      {new Date(c.createdAt).toLocaleString()}
                    </time>
                    <span className={styles.anchor}>{c.anchor || "本章"}</span>
                  </div>
                  {editingId === c.id ? (
                    <div className={styles.editRow}>
                      <textarea
                        value={editDraft}
                        onChange={(e) => setEditDraft(e.target.value)}
                        rows={2}
                        autoFocus
                      />
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={() => void saveEdit(c)}
                      >
                        保存
                      </button>
                      <button
                        type="button"
                        className={styles.ghost}
                        onClick={() => setEditingId(null)}
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    <p className={styles.text}>{c.text}</p>
                  )}
                  <div className={styles.actions}>
                    <button
                      type="button"
                      className={styles.ghost}
                      onClick={() => void toggleResolved(c)}
                    >
                      {c.resolved ? "重新打开" : "标记解决"}
                    </button>
                    {c.userId === myUserId && (
                      <>
                        <button
                          type="button"
                          className={styles.ghost}
                          onClick={() => {
                            setEditingId(c.id);
                            setEditDraft(c.text);
                          }}
                        >
                          编辑
                        </button>
                        <button
                          type="button"
                          className={styles.danger}
                          onClick={() => void remove(c)}
                        >
                          删除
                        </button>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
