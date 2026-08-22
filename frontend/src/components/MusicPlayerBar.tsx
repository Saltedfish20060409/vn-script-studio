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
  const [qrLoading, setQrLoading] = useState(false);
  const [qrState, setQrState] = useState<{
    unikey: string;
    qrimg: string;
    qrurl: string;
  } | null>(null);
  const [qrMsg, setQrMsg] = useState("");
  const [qrExpiredAt, setQrExpiredAt] = useState<number | null>(null);
  const qrTimer = useRef<number | null>(null);
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

  /** 开始扫码登录：申请二维码 → 每 2s 轮询，803 成功即保存 Cookie。 */
  const startQrLogin = async () => {
    if (qrLoading) return;
    setQrLoading(true);
    setQrMsg("");
    if (qrTimer.current) window.clearInterval(qrTimer.current);
    try {
      const state = await apiFetch<{ unikey: string; qrimg: string; qrurl: string }>(
        "/music/netease-login/create",
        { method: "POST", body: JSON.stringify({}) }
      );
      setQrState(state);
      setQrExpiredAt(Date.now() + 5 * 60 * 1000);
      qrTimer.current = window.setInterval(() => {
        void (async () => {
          try {
            const res = await apiFetch<{ code: number; message: string; cookie: string }>(
              "/music/netease-login/check",
              { method: "POST", body: JSON.stringify({ unikey: state.unikey }) }
            );
            if (res.code === 803 && res.cookie) {
              if (qrTimer.current) window.clearInterval(qrTimer.current);
              saveCookie(res.cookie);
              setQrMsg("✅ 登录成功！Cookie 已保存，可以开始听歌了。");
              setQrState(null);
              return;
            }
            const tips: Record<number, string> = {
              800: "请打开手机网易云 App 扫码…",
              // 反代容器语义：801=等待扫码，802=已扫码待确认
              801: "等待扫码…（请用手机网易云 App 扫描）",
              802: "已扫码，请在手机上确认登录…",
            };
            // 优先用后端中文消息（避免语义错位）
            setQrMsg(res.message ? `${res.message}…` : (tips[res.code] ?? "等待扫码…"));
          } catch {
            setQrMsg("轮询失败，点「刷新」重试");
          }
        })();
      }, 2000);
    } catch (e) {
      setQrMsg(e instanceof Error ? e.message : "扫码登录失败");
    } finally {
      setQrLoading(false);
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

  // 歌词居中滚动：当前行滚到可视区中央（仿主流音乐软件）
  useEffect(() => {
    const el = lrcScrollRef.current;
    if (!el || activeIdx < 0) return;
    const line = el.children[activeIdx] as HTMLElement | undefined;
    if (!line) return;
    const target = line.offsetTop - el.clientHeight / 2 + line.clientHeight / 2;
    el.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
  }, [activeIdx, panel]);

  // 卸载时清理扫码轮询
  useEffect(
    () => () => {
      if (qrTimer.current) window.clearInterval(qrTimer.current);
    },
    []
  );

  return (
    <div className={styles.bar} data-testid="music-bar">
      <audio
        ref={audioRef}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
        onEnded={advance}
        onError={() => setPlaying(false)}
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

                {/* 扫码登录：反代容器生成二维码，App 扫一下自动拿 Cookie */}
                {!qrState && (
                  <>
                    <button
                      type="button"
                      className={styles.addBtn}
                      style={{ marginTop: "0.4rem" }}
                      disabled={qrLoading}
                      onClick={() => void startQrLogin()}
                    >
                      {qrLoading ? "生成二维码中…" : "📱 扫码登录（试试）"}
                    </button>
                    <p className={styles.cookieHint}>
                      扫码最省事，但服务器在云机房，网易云可能拦截登录（提示
                      "设备环境异常"）；如果拦截，请改用下方粘贴 Cookie（100% 可用）。
                    </p>
                    {qrMsg && <p className={styles.qrMsg}>{qrMsg}</p>}
                  </>
                )}
                {qrState && (
                  <div className={styles.qrBox}>
                    <img src={qrState.qrimg} alt="网易云登录二维码" />
                    <p className={styles.cookieHint}>
                      打开手机「网易云音乐」App → 扫一扫 → 确认登录。二维码
                      {qrExpiredAt ? ` ${Math.max(0, Math.round((qrExpiredAt - Date.now()) / 1000))}s 后过期` : ""}
                      ，过期点「刷新」。
                    </p>
                    <p className={styles.qrMsg}>
                      {qrMsg || "等待扫码…"}
                    </p>
                    {qrMsg.includes("设备环境异常") && (
                      <p className={styles.cookieHint}>
                        被网易云拦截了——这是云机房 IP 的限制，扫码无法绕过。
                        请直接滚动到下方粘贴 Cookie 登录。
                      </p>
                    )}
                    <div className={styles.qrActions}>
                      <button
                        type="button"
                        className={styles.addBtn}
                        onClick={() => void startQrLogin()}
                      >
                        刷新
                      </button>
                      <button
                        type="button"
                        className={styles.keyBtn}
                        onClick={() => {
                          setQrState(null);
                          setQrMsg("");
                          if (qrTimer.current) window.clearInterval(qrTimer.current);
                        }}
                      >
                        取消，改用粘贴
                      </button>
                    </div>
                  </div>
                )}

                <p className={styles.cookieHint}>
                  💡 粘贴 Cookie（可靠）：登录 music.163.com 后按 F12 → Network →
                  任意请求的请求头里复制 Cookie 整段（含 MUSIC_U=…）粘贴到下面。
                  仅存本浏览器、随请求发送给本站、不落服务器库。
                </p>
                <input
                  value={cookieText}
                  onChange={(e) => saveCookie(e.target.value)}
                  placeholder="粘贴 Cookie 整段（含 MUSIC_U=…）"
                  className={styles.cookieInput}
                />
              </details>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
