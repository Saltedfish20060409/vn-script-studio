/* eslint-disable react-refresh/only-export-components --
   组件台入口文件（自己 createRoot 挂载），不是会被 HMR 复用的组件模块。 */

import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { PetSprite } from "../src/components/PetSprite";
import { QPet } from "../src/components/QPet";
import { setDeskPetEnabled } from "../src/lib/deskPet";
import { emitPetApp, emitPetSleep } from "../src/lib/petBridge";
import { createPetState, type PetState } from "../src/lib/petMachine";
import { loadPetManifest, type PetManifest } from "../src/lib/petManifest";
import { PET_DISPLAY, petScale, petVisual } from "../src/lib/petVisual";
import "../src/styles/globals.css";

/**
 * 桌宠组件台：**不挂后端**。上半是画廊（每个姿势 / 表情 / 情绪符号用真实 CSS 缩放渲染），
 * 下半是假编辑框 + 真 QPet，用来试拖拽落点（框顶 / 框后 / 屏幕边缘）和点击反应。
 * `?bg=dark` 换深色底；`?size=large` 换大号。
 */

const params = new URLSearchParams(location.search);
const dark = params.get("bg") === "dark";
const size = (params.get("size") as keyof typeof PET_DISPLAY) || "medium";

const CASES: Array<[string, Partial<PetState>]> = [
  ["待机", {}],
  ["开心脸", { body: "nod", mood: "happy" }],
  ["难过 + 汗", { body: "idle", mood: "sad", emote: "sweat" }],
  ["思考 + …", { mood: "think", emote: "dots" }],
  ["慌乱 + ?", { body: "fluster", mood: "fluster", emote: "question" }],
  ["跳起", { body: "happy", mood: "happy" }],
  ["被摸头 + 心", { body: "headpat", mood: "happy", emote: "heart" }],
  ["喂食饼干", { body: "feed", mood: "happy", emote: "heart" }],
  ["玩耍小球", { body: "play", mood: "happy", emote: "dots" }],
  ["蜷坐", { body: "hideCorner" }],
  ["坐睡 + Zzz", { body: "sleep", emote: "zzz" }],
  ["被拎起", { body: "held", mood: "fluster" }],
  ["坐框顶", { placement: "perchTop", body: "perchTop" }],
  ["坐框顶睡", { placement: "perchTop", body: "sleep", emote: "zzz" }],
  ["探头", { placement: "peekOver", body: "peekOver" }],
  ["探头开心 + 心", { placement: "peekOver", body: "nod", mood: "happy", emote: "heart" }],
  ["探头思考", { placement: "peekOver", body: "peekOver", mood: "think", emote: "dots" }],
  ["探头睡", { placement: "peekOver", body: "sleep", emote: "zzz" }],
  ["框下探头", { placement: "peekUnder", body: "peekOver" }],
  ["靠框左侧", { placement: "perchSideLeft", body: "idle" }],
  ["靠框右侧", { placement: "perchSideRight", body: "idle" }],
  ["贴左边", { placement: "edgeLeft", body: "peekSide" }],
  ["贴右边", { placement: "edgeRight", body: "peekSide" }],
  ["走路 →", { body: "walk" }],
];

function Gallery({ manifest }: { manifest: PetManifest }) {
  const scale = petScale(PET_DISPLAY[size]);
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 18, padding: 16 }}>
      {CASES.map(([name, patch]) => {
        const s = { ...createPetState(0), ...patch };
        return (
          <figure key={name} data-case={name} style={{ margin: 0, paddingTop: 30 }}>
            <PetSprite
              manifest={manifest}
              visual={petVisual(s)}
              scale={scale}
              walkDir="r"
              talking={name === "待机"}
              emoteKey={0}
            />
            <figcaption style={{ fontSize: 12, opacity: 0.7, textAlign: "center" }}>{name}</figcaption>
          </figure>
        );
      })}
    </div>
  );
}

function App() {
  const [manifest, setManifest] = useState<PetManifest | null>(null);
  const [cheer, setCheer] = useState(0);
  const [replay, setReplay] = useState(0);
  const editorRef = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    setDeskPetEnabled(true);
    loadPetManifest().then(setManifest);
  }, []);
  return (
    <div style={{ minHeight: "100vh", background: dark ? "#1b1f2a" : "#f6f8fc", color: dark ? "#ddd" : "#222" }}>
      {manifest ? <Gallery key={replay} manifest={manifest} /> : <p>清单加载中…</p>}
      <div style={{ padding: "0 16px 16px", display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="button" onClick={() => setReplay((v) => v + 1)}>
          重播补间
        </button>
        <button type="button" onClick={() => setCheer((v) => v + 1)}>
          模拟保存成功
        </button>
        <button type="button" onClick={() => emitPetApp("compile:error", 42)}>
          编译失败·行
        </button>
        <button type="button" onClick={() => emitPetApp("compile:error")}>
          编译失败·无行号
        </button>
        <button type="button" onClick={() => emitPetApp("compile:ok")}>
          编译成功
        </button>
        <button type="button" onClick={() => emitPetApp("export:ok")}>
          导出成功
        </button>
        <button type="button" onClick={() => emitPetApp("export:error")}>
          导出失败
        </button>
        <button type="button" onClick={() => emitPetApp("agent:thinking")}>
          搭档开始想
        </button>
        <button type="button" onClick={() => emitPetApp("agent:error")}>
          搭档出错
        </button>
        <button type="button" onClick={() => emitPetSleep()}>
          先睡着
        </button>
      </div>
      <textarea
        ref={editorRef}
        defaultValue="假编辑框：拖到上沿坐下，上沿下方探头，下沿框下探头，左右外沿靠框，屏幕左右边缘贴边。"
        style={{ display: "block", width: "56%", height: 260, margin: "90px auto 120px" }}
      />
      <QPet editorRef={editorRef} cheerSignal={cheer} />
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
