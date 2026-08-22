import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "../api/http";
import { activeLrcIndex, parseLrc } from "../lib/lrc";
import styles from "./MusicPlayerBar.module.css";

export interface MusicTrack {
  id: string;
  title: string;
  artist: string;
  /** 播放地址：后端代理（/music/stream?url=...）或直链 */
  audioUrl: string;
  cover?: string;
  /** LRC 原文（可选） */
  lrc?: string;
}

export interface SearchItem {
  id: string;
  title: string;
  artist: string;
  album?: string;
  cover?: string | null;
}

type Props = {
  /** 可选：当前写作章节标题，显示在迷你条 */
  contextLabel?: string;
};

const STORE_KEY = "vnss-music-v1";
const COOKIE_KEY = "vnss-music-netease-cookie";
type Platform = "netease" | "qq" | "kugou";
const PLATFORM_LABEL: Record<Platform, string> = {
  netease: "网易云",
  qq: "QQ音乐",
  kugou: "酷狗",
};

function loadCookie(): string {
  try {
    return localStorage.getItem(COOKIE_KEY) ?? "";
  } catch {
    return "";
  }
}

interface StoredState {
  list: MusicTrack[];
  index: number;
}

function loadState(): StoredState {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return { list: [], index: -1 };
    const p = JSON.parse(raw) as Partial<StoredState>;
    return {
      list: Array.isArray(p.list) ? p.list : [],
      index: typeof p.index === "number" ? p.index : -1,
    };
  } catch {
    return { list: [], index: -1 };
  }
}

function fmt(t: number): string {
  if (!Number.isFinite(t) || t < 0) return "0:00";
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** 可选的网易云 Cookie：只在请求时带上，不落服务器库。 */
function cookieHeaders(cookie: string): Record<string, string> {
  return cookie.trim() ? { "X-Netease-Cookie": cookie.trim() } : {};
}

/** 写作页底部迷你播放条：播放/上下首/进度/音量 + 歌词面板 + 播放列表。 */
export function MusicPlayerBar({ contextLabel }: Props) {
  const initial = useRef(loadState());
  const [list, setList] = useState<MusicTrack[]>(initial.current.list);
  const [index, setIndex] = useState(initial.current.index);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [volume, setVolume] = useState(0.7);
  const [lrcOpen, setLrcOpen] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [addText, setAddText] = useState("");
  const [resolving, setResolving] = useState(false);
  const [lrcInput, setLrcInput] = useState("");
  const [searchText, setSearchText] = useState("");
  const [searchPlatform, setSearchPlatform] = useState<Platform>("netease");
  const [searching, setSearching] = useState(false);
  const [searchHits, setSearchHits] = useState<SearchItem[]>([]);
  const [searchMsg, setSearchMsg] = useState("");
  const [addingId, setAddingId] = useState<string | null>(null);
  const [cookieText, setCookieText] = useState(loadCookie);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  const track = list[index] ?? null;
  const lrc = useMemo(
    () => (track?.lrc ? parseLrc(track.lrc) : { lines: [], meta: {} }),
    [track?.lrc]
  );

  // 持久化
  useEffect(() => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ list, index }));
    } catch {
      /* ignore quota */
    }
  }, [list, index]);

  // 换歌：重设 audio
  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    if (!track) {
      a.pause();
      a.removeAttribute("src");
      setPlaying(false);
      setCur(0);
      setDur(0);
      return;
    }
    a.src = track.audioUrl;
    setCur(0);
    setDur(0);
    if (playing) void a.play().catch(() => setPlaying(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track?.id]);

  const toggle = useCallback(() => {
    const a = audioRef.current;
    if (!a || !track) return;
    if (a.paused) {
      void a.play().catch(() => setPlaying(false));
    } else {
      a.pause();
    }
  }, [track]);

  const playAt = useCallback(
    (i: number) => {
      if (i < 0 || i >= list.length) return;
      setIndex(i);
      setPlaying(true);
    },
    [list.length]
  );

  const next = useCallback(() => {
    if (list.length === 0) return;
    setIndex((prev) => (prev + 1) % list.length);
    setPlaying(true);
  }, [list.length]);

  const prev = useCallback(() => {
    if (list.length === 0) return;
    setIndex((prev) => (prev <= 0 ? list.length - 1 : prev - 1));
    setPlaying(true);
  }, [list.length]);

  const removeAt = useCallback((i: number) => {
    setList((prev) => {
      const nextL = prev.filter((_, k) => k !== i);
      setIndex((idx) => {
        if (i === idx) return -1;
        if (i < idx) return idx - 1;
        return idx;
      });
      return nextL;
    });
  }, []);

  const addTrack = useCallback(
    (t: MusicTrack) => {
      setList((prev) => {
        const dup = prev.findIndex((x) => x.id === t.id);
        if (dup >= 0) {
          setIndex(dup);
          setPlaying(true);
          return prev;
        }
        const next = [...prev, t];
        setIndex(next.length - 1);
        setPlaying(true);
        return next;
      });
    },
    []
  );

  const resolveAndAdd = async () => {
    const text = addText.trim();
    if (!text || resolving) return;
    setResolving(true);
    try {
      const data = await apiFetch<MusicTrack>("/music/resolve", {
        method: "POST",
        body: JSON.stringify({ url: text }),
        headers: cookieHeaders(cookieText),
      });
      addTrack(data);
      setAddText("");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "解析失败";
      setAddText(msg.startsWith("解析失败") ? msg : `解析失败：${msg}`);
    } finally {
      setResolving(false);
    }
  };

  const runSearch = async () => {
    const q = searchText.trim();
    if (!q || searching) return;
    setSearching(true);
    setSearchMsg("");
    setSearchHits([]);
    try {
      const hits = await apiFetch<SearchItem[]>("/music/search", {
        method: "POST",
        body: JSON.stringify({ q, platform: searchPlatform }),
        headers: cookieHeaders(cookieText),
      });
      setSearchHits(hits);
      if (hits.length === 0) setSearchMsg("没有搜到，换个关键词试试");
    } catch (e) {
      setSearchMsg(e instanceof Error ? e.message : "搜索失败");
    } finally {
      setSearching(false);
    }
  };

  const addSearchHit = async (hit: SearchItem) => {
    if (addingId) return;
    setAddingId(hit.id);
    try {
      const data = await apiFetch<MusicTrack>("/music/resolve", {
        method: "POST",
        body: JSON.stringify({ platform: searchPlatform, songId: hit.id }),
        headers: cookieHeaders(cookieText),
      });
      addTrack(data);
    } catch (e) {
      setSearchMsg(e instanceof Error ? e.message : "添加失败");
    } finally {
      setAddingId(null);
    }
  };

  const saveCookie = (v: string) => {
    setCookieText(v);
    try {
      if (v.trim()) localStorage.setItem(COOKIE_KEY, v.trim());
      else localStorage.removeItem(COOKIE_KEY);
    } catch {
      /* ignore */
    }
  };

  const applyLrc = () => {
    if (!track || !lrcInput.trim()) return;
    setList((prev) =>
      prev.map((t, i) => (i === index ? { ...t, lrc: lrcInput } : t))
    );
    setLrcInput("");
  };

  const activeIdx = activeLrcIndex(lrc.lines, cur);

  return (
    <div className={styles.bar} data-testid="music-bar">
      <audio
        ref={audioRef}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
        onEnded={next}
        onError={() => setPlaying(false)}
      />
      {/* 迷你条 */}
      <div className={styles.mini}>
        <button
          type="button"
          className={styles.keyBtn}
          onClick={prev}
          disabled={list.length === 0}
          title="上一首"
        >
          ⏮
        </button>
        <button
          type="button"
          className={`${styles.keyBtn} ${styles.playBtn}`}
          onClick={toggle}
          disabled={!track}
          title={playing ? "暂停" : "播放"}
        >
          {playing ? "⏸" : "▶"}
        </button>
        <button
          type="button"
          className={styles.keyBtn}
          onClick={next}
          disabled={list.length === 0}
          title="下一首"
        >
          ⏭
        </button>
        <div className={styles.info}>
          <span className={styles.title}>{track?.title ?? "未选择歌曲"}</span>
          <span className={styles.artist}>
            {track?.artist ??
              (contextLabel
                ? `写作中 · ${contextLabel}`
                : "点「＋ 添加」搜索网易云 / QQ / 酷狗歌曲")}
          </span>
        </div>
        <input
          className={styles.seek}
          type="range"
          min={0}
          max={dur || 0}
          step={0.5}
          value={cur}
          disabled={!track}
          onChange={(e) => {
            const v = Number(e.target.value);
            setCur(v);
            if (audioRef.current) audioRef.current.currentTime = v;
          }}
          aria-label="进度"
        />
        <span className={styles.time}>
          {fmt(cur)} / {fmt(dur)}
        </span>
        <input
          className={styles.vol}
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={volume}
          onChange={(e) => {
            const v = Number(e.target.value);
            setVolume(v);
            if (audioRef.current) audioRef.current.volume = v;
          }}
          aria-label="音量"
        />
        <button
          type="button"
          className={`${styles.keyBtn} ${lrcOpen ? styles.on : ""}`}
          onClick={() => setLrcOpen((v) => !v)}
          title="歌词"
        >
          📃
        </button>
        <button
          type="button"
          className={`${styles.keyBtn} ${listOpen ? styles.on : ""}`}
          onClick={() => setListOpen((v) => !v)}
          title="播放列表"
        >
          🎵
        </button>
        <button
          type="button"
          className={styles.addSong}
          onClick={() => {
            setListOpen(true);
            requestAnimationFrame(() => searchInputRef.current?.focus());
          }}
          title="搜索并添加歌曲"
        >
          ＋ 添加
        </button>
      </div>

      {/* 展开面板：搜索 + 添加 + 列表 + 歌词 */}
      {(listOpen || lrcOpen) && (
        <div className={styles.panel}>
          {/* 搜索：三平台公开接口，无需登录 */}
          <div className={styles.searchBlock}>
            <div className={styles.searchRow}>
              <input
                ref={searchInputRef}
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void runSearch();
                }}
                placeholder="搜索歌名 / 歌手，回车搜索"
                aria-label="搜索歌曲"
              />
              <button
                type="button"
                className={styles.addBtn}
                disabled={searching || !searchText.trim()}
                onClick={() => void runSearch()}
              >
                {searching ? "搜索中…" : "搜索"}
              </button>
            </div>
            <div className={styles.platRow}>
              {(Object.keys(PLATFORM_LABEL) as Platform[]).map((p) => (
                <button
                  key={p}
                  type="button"
                  className={p === searchPlatform ? styles.platOn : styles.plat}
                  onClick={() => {
                    setSearchPlatform(p);
                    setSearchHits([]);
                    setSearchMsg("");
                  }}
                >
                  {PLATFORM_LABEL[p]}
                </button>
              ))}
            </div>
            {searchHits.length > 0 && (
              <ul className={styles.list}>
                {searchHits.map((hit) => (
                  <li
                    key={hit.id}
                    className={styles.listItem}
                    onClick={() => void addSearchHit(hit)}
                    title={`${hit.album ? `${hit.album} · ` : ""}点击添加到播放列表`}
                  >
                    <span className={styles.listNum}>
                      {addingId === hit.id ? "…" : "+"}
                    </span>
                    <span className={styles.listTitle}>{hit.title}</span>
                    <span className={styles.listArtist}>{hit.artist}</span>
                  </li>
                ))}
              </ul>
            )}
            {searchMsg && <p className={styles.searchMsg}>{searchMsg}</p>}
            <details className={styles.cookieBox}>
              <summary>网易云 Cookie（可选 · 提升 VIP 曲目播放质量）</summary>
              <input
                value={cookieText}
                onChange={(e) => saveCookie(e.target.value)}
                placeholder="粘贴 Cookie 中的 MUSIC_U=… 整段"
                className={styles.cookieInput}
              />
              <p className={styles.cookieHint}>
                仅存于本浏览器，搜索/解析时随请求发送给本站、不落服务器库；不放心可随时清空。
              </p>
            </details>
          </div>
          <div className={styles.addRow}>
            <input
              value={addText}
              onChange={(e) => setAddText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void resolveAndAdd();
              }}
              placeholder="或粘贴网易云 / QQ音乐 / 酷狗分享链接，回车添加"
            />
            <button
              type="button"
              className={styles.addBtn}
              disabled={resolving || !addText.trim()}
              onClick={() => void resolveAndAdd()}
            >
              {resolving ? "解析中…" : "添加"}
            </button>
          </div>
          <div className={styles.columns}>
            {listOpen && (
              <ul className={styles.list}>
                {list.length === 0 && <li className={styles.empty}>列表为空</li>}
                {list.map((t, i) => (
                  <li
                    key={t.id}
                    className={i === index ? styles.listItemOn : styles.listItem}
                    onClick={() => playAt(i)}
                  >
                    <span className={styles.listNum}>{i + 1}</span>
                    <span className={styles.listTitle}>{t.title}</span>
                    <span className={styles.listArtist}>{t.artist}</span>
                    <button
                      type="button"
                      className={styles.delBtn}
                      onClick={(e) => {
                        e.stopPropagation();
                        removeAt(i);
                      }}
                      title="移除"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {lrcOpen && (
              <div className={styles.lrcPane}>
                {!track?.lrc ? (
                  <div className={styles.lrcEmpty}>
                    <p>暂无歌词。粘贴 LRC 文本导入：</p>
                    <textarea
                      value={lrcInput}
                      onChange={(e) => setLrcInput(e.target.value)}
                      rows={4}
                      placeholder={'[00:12.00]第一句歌词\n[00:20.00]第二句歌词'}
                    />
                    <button
                      type="button"
                      className={styles.addBtn}
                      disabled={!lrcInput.trim()}
                      onClick={applyLrc}
                    >
                      导入歌词
                    </button>
                  </div>
                ) : (
                  <div className={styles.lrcScroll}>
                    {lrc.lines.map((ln, i) => (
                      <p
                        key={`${ln.time}-${i}`}
                        className={i === activeIdx ? styles.lrcOn : styles.lrcLine}
                      >
                        {ln.text || "♪"}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
