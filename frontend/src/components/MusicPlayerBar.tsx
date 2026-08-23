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
  /** 手动歌词偏移（秒）：音源与歌词不同步时的微调 */
  lrcOffset?: number;
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
const MODE_KEY = "vnss-music-mode-v1";
const COOKIE_KEY = "vnss-music-netease-cookie";
type Platform = "netease" | "kugou" | "bili";
type PlayMode = "order" | "shuffle" | "loop-one";
const PLATFORM_LABEL: Record<Platform, string> = {
  netease: "网易云",
  kugou: "酷狗",
  bili: "B站",
};
const MODE_ICON: Record<PlayMode, string> = {
  order: "🔁",
  shuffle: "🔀",
  "loop-one": "🔂",
};
const MODE_LABEL: Record<PlayMode, string> = {
  order: "顺序播放",
  shuffle: "随机播放",
  "loop-one": "单曲循环",
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

function loadMode(): PlayMode {
  try {
    const m = localStorage.getItem(MODE_KEY);
    if (m === "shuffle" || m === "loop-one") return m;
  } catch {
    /* ignore */
  }
  return "order";
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

/** 从 track id（如 bili-BV1xx… / netease-123 / kugou-hash）反推平台+源 id。 */
function parseTrackSource(id: string): { platform: string; songId: string } | null {
  const idx = id.indexOf("-");
  if (idx <= 0) return null;
  const platform = id.slice(0, idx);
  const songId = id.slice(idx + 1);
  if (!platform || !songId) return null;
  if (!["netease", "kugou", "bili"].includes(platform)) return null;
  return { platform, songId };
}

type Panel = "list" | "lrc" | "search" | null;

/** 全局底部播放条：播放模式 / 列表弹出 / 歌词居中滚动 / 搜索添加。 */
export function MusicPlayerBar({ contextLabel }: Props) {
  const initial = useRef(loadState());
  const [list, setList] = useState<MusicTrack[]>(initial.current.list);
  const [index, setIndex] = useState(initial.current.index);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [volume, setVolume] = useState(0.7);
  const [mode, setMode] = useState<PlayMode>(loadMode);
  const [panel, setPanel] = useState<Panel>(null);
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
  const lrcScrollRef = useRef<HTMLDivElement | null>(null);

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

  useEffect(() => {
    try {
      localStorage.setItem(MODE_KEY, mode);
    } catch {
      /* ignore */
    }
  }, [mode]);

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

  /** 播放失败（URL 过期）→ 重新解析一次刷新地址。B站等平台 URL 有时效。 */
  const refreshAttempts = useRef<Record<string, number>>({});
  const handleAudioError = useCallback(async () => {
    const t = track;
    if (!t) {
      setPlaying(false);
      return;
    }
    const src = parseTrackSource(t.id);
    if (!src) {
      setPlaying(false);
      return;
    }
    const attempts = refreshAttempts.current[t.id] ?? 0;
    if (attempts >= 1) {
      setPlaying(false);
      return;
    }
    refreshAttempts.current[t.id] = attempts + 1;
    try {
      const fresh = await apiFetch<MusicTrack>("/music/resolve", {
        method: "POST",
        body: JSON.stringify({
          platform: src.platform,
          songId: src.songId,
          title: t.title,
          artist: t.artist,
        }),
        headers: cookieHeaders(cookieText),
      });
      setList((prev) => prev.map((x) => (x.id === t.id ? { ...x, audioUrl: fresh.audioUrl } : x)));
    } catch {
      setPlaying(false);
    }
  }, [track, cookieText]);

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

  /** 按播放模式推进：order 下一首 / shuffle 随机 / loop-one 重播当前 */
  const advance = useCallback(() => {
    if (list.length === 0) return;
    if (mode === "loop-one") {
      const a = audioRef.current;
      if (a) {
        a.currentTime = 0;
        void a.play().catch(() => setPlaying(false));
      }
      return;
    }
    if (mode === "shuffle" && list.length > 1) {
      const next = index;
      let pick = Math.floor(Math.random() * list.length);
      while (pick === next) pick = Math.floor(Math.random() * list.length);
      setIndex(pick);
      setPlaying(true);
      return;
    }
    setIndex((prev) => (prev + 1) % list.length);
    setPlaying(true);
  }, [list.length, mode, index]);

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

  const cycleMode = () => {
    setMode((m) => (m === "order" ? "shuffle" : m === "shuffle" ? "loop-one" : "order"));
  };

  const openPanel = (p: Panel) => {
    setPanel((cur) => (cur === p ? null : p));
    if (p === "search") {
      requestAnimationFrame(() => searchInputRef.current?.focus());
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
        body: JSON.stringify({
          platform: searchPlatform,
          songId: hit.id,
          // 数据中心 IP 上网易云元数据接口可能不可用：回传展示信息兜底
          title: hit.title,
          artist: hit.artist,
        }),
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

  /** 手动歌词偏移（秒）：音源与歌词不同步时 ±0.5s 微调 */
  const nudgeLrc = (delta: number) => {
    if (!track) return;
    setList((prev) =>
      prev.map((t, i) =>
        i === index
          ? { ...t, lrcOffset: Math.max(-10, Math.min(10, (t.lrcOffset ?? 0) + delta)) }
          : t
      )
    );
  };

  // 歌词偏移应用：当前播放时间加上偏移后再找行
  const activeIdx = activeLrcIndex(lrc.lines, cur + (track?.lrcOffset ?? 0));

  // 歌词居中滚动：把当前变色行放在视口正中间（不用 smooth——歌词切换快时
  // 平滑动画追不上）。用「padding-top + 索引×固定行高」显式计算，
  // 不依赖 offsetTop/offsetParent（布局变化或作词行混入时也能准确定位）。
  useEffect(() => {
    const el = lrcScrollRef.current;
    if (!el || activeIdx < 0) return;
    // 固定行高（CSS .lrcLine line-height: 1.9rem；rem 相对根字号）
    const rootFs = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const lineH = 1.9 * rootFs;
    const padTop = parseFloat(getComputedStyle(el).paddingTop) || 0;
    // 第 activeIdx 行的内容顶 = padTop + activeIdx*lineH
    const target = padTop + activeIdx * lineH - el.clientHeight / 2 + lineH / 2;
    el.scrollTop = Math.max(0, target);
  }, [activeIdx, panel, lrc.lines.length]);

  return (
    <div className={styles.bar} data-testid="music-bar">
      <audio
        ref={audioRef}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
        onEnded={advance}
        onError={() => void handleAudioError()}
      />
      {/* 迷你条 */}
      <div className={styles.mini}>
        <button
          type="button"
          className={`${styles.keyBtn} ${styles.modeBtn}`}
          onClick={cycleMode}
          title={`播放模式：${MODE_LABEL[mode]}`}
        >
          {MODE_ICON[mode]}
        </button>
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
                : "点「＋ 添加」搜索网易云 / 酷狗 / B站歌曲")}
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
          className={`${styles.keyBtn} ${panel === "lrc" ? styles.on : ""}`}
          onClick={() => openPanel("lrc")}
          title="歌词"
        >
          📃
        </button>
        <button
          type="button"
          className={`${styles.keyBtn} ${panel === "list" ? styles.on : ""}`}
          onClick={() => openPanel("list")}
          title="播放列表"
        >
          🎵
        </button>
        <button
          type="button"
          className={styles.addSong}
          onClick={() => openPanel("search")}
          title="搜索并添加歌曲"
        >
          ＋ 添加
        </button>
      </div>

      {/* 弹出面板：向上展开 —— 列表 / 歌词 / 搜索 三选一 */}
      {panel && (
        <div className={styles.panel} data-panel={panel}>
          {/* 播放列表：向上长方形列出歌曲 */}
          {panel === "list" && (
            <ul className={styles.list}>
              {list.length === 0 && <li className={styles.empty}>列表为空</li>}
              {list.map((t, i) => (
                <li
                  key={t.id}
                  className={i === index ? styles.listItemOn : styles.listItem}
                  onClick={() => playAt(i)}
                >
                  <span className={styles.listNum}>
                    {i === index && playing ? "▶" : i + 1}
                  </span>
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

          {/* 歌词：居中滚动 */}
          {panel === "lrc" && (
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
                <>
                  <div className={styles.lrcViewport}>
                    <div className={styles.lrcScroll} ref={lrcScrollRef}>
                      {lrc.lines.map((ln, i) => (
                        <p
                          key={`${ln.time}-${i}`}
                          className={
                            i === activeIdx ? styles.lrcOn : styles.lrcLine
                          }
                        >
                          {ln.text || "♪"}
                        </p>
                      ))}
                    </div>
                    {/* 上下渐变遮罩：聚焦当前行 */}
                    <div className={styles.lrcShadeTop} aria-hidden />
                    <div className={styles.lrcShadeBottom} aria-hidden />
                  </div>
                  {/* 歌词偏移微调：音源与歌词不同步时 ±0.5s 调整 */}
                  <div className={styles.lrcOffsetRow}>
                    <button
                      type="button"
                      className={styles.keyBtn}
                      onClick={() => nudgeLrc(-0.5)}
                      title="歌词提前 0.5s"
                    >
                      −0.5
                    </button>
                    <span className={styles.lrcOffsetVal}>
                      {track?.lrcOffset ? `偏移 ${track.lrcOffset > 0 ? "+" : ""}${track.lrcOffset}s` : "歌词同步"}
                    </span>
                    <button
                      type="button"
                      className={styles.keyBtn}
                      onClick={() => nudgeLrc(0.5)}
                      title="歌词延后 0.5s"
                    >
                      +0.5
                    </button>
                    {track?.lrcOffset ? (
                      <button
                        type="button"
                        className={styles.delBtn}
                        onClick={() => nudgeLrc(-track.lrcOffset!)}
                        title="重置偏移"
                      >
                        重置
                      </button>
                    ) : null}
                  </div>
                </>
              )}
            </div>
          )}

          {/* 搜索添加：平台切换 + 结果 + Cookie */}
          {panel === "search" && (
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
              <details className={styles.cookieBox} open={!cookieText.trim()}>
                <summary>🔑 网易云登录（听大部分歌需要）</summary>

                <p className={styles.cookieHint}>
                  💡 获取方法（1 分钟）：电脑浏览器登录{" "}
                  <a href="https://music.163.com" target="_blank" rel="noreferrer">
                    music.163.com
                  </a>{" "}
                  → 按 <b>F12</b> → 点顶部「<b>应用程序 / Application</b>」→ 左侧「{" "}
                  <b>Cookie</b>」→ 选择 https://music.163.com → 找到名为{" "}
                  <b>MUSIC_U</b> 的一行 → 复制它的「<b>值 / Value</b>」→ 粘贴到下面。
                </p>
                <input
                  value={cookieText}
                  onChange={(e) => saveCookie(e.target.value)}
                  placeholder="只粘贴 MUSIC_U 的值（不用带 MUSIC_U= 前缀）"
                  className={styles.cookieInput}
                />
                <p className={styles.cookieHint}>
                  只存本浏览器、随请求发送给本站、不落服务器库，可随时清空。
                </p>
                <p className={styles.cookieExpire}>
                  ⏳ Cookie 可能过期：网易云登录态通常几天到几周有效，过期后
                  播放会失败，重新按上面步骤复制一次最新值即可。
                </p>
              </details>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
