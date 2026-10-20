import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import type { PetManifest, PetSeqAsset, PetWalkDir } from "../lib/petManifest";
import { petAssetUrl } from "../lib/petManifest";
import {
  celebrateAt,
  CELEBRATE_MS,
  createPendulum,
  idleBreathScaleY,
  peekSlideY,
  perchSwayDeg,
  sleepNodDeg,
  stepPendulum,
  swingCssDeg,
  walkBobY,
  type CelebrateBody,
} from "../lib/petMotion";
import { bodyMetrics, emoteBox, type PetVisual } from "../lib/petVisual";
import { PetEmote } from "./PetEmote";
import styles from "./PetSprite.module.css";

type Eye = "open" | "half" | "closed";
type Mouth = "closed" | "half" | "open";

/** 眨眼节奏（brief：半闭 50 → 全闭 70 → 半闭 50）；间隔 2.6～6.2s，15% 连眨 */
const BLINK_STEPS: Array<[Eye, number]> = [
  ["half", 50],
  ["closed", 70],
  ["half", 50],
];
const BLINK_GAP_MIN = 2600;
const BLINK_GAP_SPREAD = 3600;
const DOUBLE_BLINK = 0.15;
const MOUTH_MS = 110;

function variantName(v: PetVisual, eye: Eye, mouth: Mouth): string | null {
  if (v.expression) return v.expression;
  const e: Eye = v.eyesClosed ? "closed" : eye;
  if (v.face === "idle") {
    const m: Mouth = v.canTalk ? mouth : "closed";
    return e === "open" && m === "closed" ? null : `eye_${e}+mouth_${m}`;
  }
  if (v.face === "perch_top" && e === "open") return "look";
  return e === "open" ? null : `eye_${e}`;
}

function seqOf(manifest: PetManifest, visual: PetVisual, walkDir: PetWalkDir): PetSeqAsset | null {
  if (visual.body === "walk") return manifest.walk[walkDir];
  if (visual.body === "feed") return manifest.feed;
  if (visual.body === "play") return manifest.play;
  return null;
}

type Props = {
  manifest: PetManifest;
  visual: PetVisual;
  scale: number;
  walkDir: PetWalkDir;
  talking: boolean;
  /** 换值即重播情绪符号动画 */
  emoteKey: string | number;
  reducedMotion?: boolean;
  /** 拖拽中的横向速度（母版 px/s）。松开后由精灵自己归零。 */
  dragSpeedRef?: RefObject<number>;
};

/**
 * 分层：身体图 → 脸部贴片 → 情绪符号。全部按运行时像素摆放，整体按 scale 缩放。
 * 眨眼、口型、走路/喂食/玩耍换帧直接改 DOM 样式，不触发 React 提交（待机零提交）。
 */
export function PetSprite({
  manifest,
  visual,
  scale,
  walkDir,
  talking,
  emoteKey,
  reducedMotion = false,
  dragSpeedRef,
}: Props) {
  const met = bodyMetrics(manifest, visual.body, walkDir);
  const faceAtlas = visual.face ? manifest.faces[visual.face] : undefined;
  const faceRef = useRef<HTMLDivElement>(null);
  const seqRef = useRef<HTMLDivElement>(null);
  const motionRef = useRef<HTMLDivElement>(null);
  const bodyImgRef = useRef<HTMLImageElement>(null);
  const metRef = useRef(met);
  metRef.current = met;
  const manifestRef = useRef(manifest);
  manifestRef.current = manifest;
  const motionClock = useRef({ body: "", t0: 0 });
  if (motionClock.current.body !== visual.body) {
    motionClock.current = { body: visual.body, t0: performance.now() };
  }
  const eye = useRef<Eye>("open");
  const mouth = useRef<Mouth>("closed");
  const visualRef = useRef(visual);
  visualRef.current = visual;
  const faceAtlasRef = useRef(faceAtlas);
  faceAtlasRef.current = faceAtlas;

  const applyFace = () => {
    const el = faceRef.current;
    const atlas = faceAtlasRef.current;
    if (!el || !atlas) return;
    const name = variantName(visualRef.current, eye.current, mouth.current);
    const pos = name ? atlas.variants[name] : undefined;
    if (!pos) {
      el.style.visibility = "hidden";
      return;
    }
    el.style.visibility = "visible";
    el.style.backgroundPosition = `${-pos[0]}px ${-pos[1]}px`;
  };

  useEffect(applyFace);

  useEffect(() => {
    if (!visual.canBlink) {
      eye.current = "open";
      return;
    }
    let timer = 0;
    let cancelled = false;
    const blink = (steps: Array<[Eye, number]>, done: () => void) => {
      const [state, ms] = steps[0];
      eye.current = state;
      applyFace();
      timer = window.setTimeout(() => {
        if (cancelled) return;
        if (steps.length > 1) blink(steps.slice(1), done);
        else {
          eye.current = "open";
          applyFace();
          done();
        }
      }, ms);
    };
    const schedule = () => {
      timer = window.setTimeout(() => {
        if (cancelled) return;
        const twice = Math.random() < DOUBLE_BLINK;
        blink(BLINK_STEPS, () => {
          if (twice) timer = window.setTimeout(() => blink(BLINK_STEPS, schedule), 120);
          else schedule();
        });
      }, BLINK_GAP_MIN + Math.random() * BLINK_GAP_SPREAD);
    };
    schedule();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      eye.current = "open";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visual.canBlink, visual.face]);

  const mouthOn = talking && visual.canTalk;
  useEffect(() => {
    if (!mouthOn) {
      mouth.current = "closed";
      applyFace();
      return;
    }
    const shapes: Mouth[] = ["closed", "half", "open"];
    const t = window.setInterval(() => {
      const next = shapes.filter((m) => m !== mouth.current);
      mouth.current = next[Math.floor(Math.random() * next.length)];
      applyFace();
    }, MOUTH_MS);
    return () => {
      window.clearInterval(t);
      mouth.current = "closed";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mouthOn]);

  const seq = seqOf(manifest, visual, walkDir);
  useEffect(() => {
    if (!seq) return;
    let i = 0;
    const show = () => {
      const el = seqRef.current;
      const f = seq.frames[i];
      if (el && f) el.style.backgroundPosition = `${-f[0]}px ${-f[1]}px`;
    };
    show();
    const once = visual.body === "feed";
    const t = window.setInterval(() => {
      if (once) {
        if (i >= seq.frames.length - 1) {
          window.clearInterval(t);
          return;
        }
        i += 1;
      } else {
        i = (i + 1) % seq.frames.length;
      }
      show();
    }, seq.ms);
    return () => window.clearInterval(t);
  }, [seq, visual.body]);

  useEffect(() => {
    const el = motionRef.current;
    if (!el) return;
    if (reducedMotion) {
      el.style.transform = "none";
      return;
    }
    let pend = createPendulum();
    let prev = "";
    let shown: CelebrateBody | null = null;
    let last = performance.now();
    let raf = 0;
    const frame = (now: number) => {
      // 后台页不烧 RAF；回前台时重置 dt 避免大步长抖动
      if (document.hidden) {
        raf = 0;
        return;
      }
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const v = visualRef.current;
      const m = metRef.current;
      if (v.body !== prev) shown = null;
      prev = v.body;
      const since = now - motionClock.current.t0;
      let y = 0;
      let rot = 0;
      let scaleY = 1;
      let originX = m.anchor.x;
      let originY = m.anchor.y;
      if (v.body === "happy_jump") {
        const pose = celebrateAt(since);
        y = pose.y;
        scaleY = pose.scaleY;
        if (pose.body !== shown && bodyImgRef.current) {
          shown = pose.body;
          const src = manifestRef.current.bodies[pose.body].src;
          bodyImgRef.current.src = petAssetUrl(src);
        }
        if (since > CELEBRATE_MS) scaleY = 1;
      } else if (v.body === "walk" && v.walkBob) {
        y = walkBobY(now);
      } else if (v.body === "idle") {
        scaleY = idleBreathScaleY(now);
      } else if (v.body === "perch_top") {
        rot = perchSwayDeg(now);
      } else if (v.body === "sleep") {
        rot = sleepNodDeg(now);
        originX = m.w / 2;
        originY = m.h * 0.42;
      } else if (v.body === "peek_over") {
        const slide = peekSlideY(since, m.h);
        y = v.upsideDown ? -slide : slide;
      } else if (v.body === "held") {
        pend = stepPendulum(pend, dragSpeedRef?.current ?? 0, dt);
        rot = swingCssDeg(pend);
      } else {
        pend = createPendulum();
      }
      el.style.transformOrigin = `${originX}px ${originY}px`;
      el.style.transform = `translateY(${y.toFixed(2)}px) rotate(${rot.toFixed(3)}deg) scaleY(${scaleY.toFixed(4)})`;
      raf = requestAnimationFrame(frame);
    };
    const kick = () => {
      if (document.hidden || raf) return;
      last = performance.now();
      raf = requestAnimationFrame(frame);
    };
    const onVis = () => {
      if (document.hidden) {
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
      } else kick();
    };
    document.addEventListener("visibilitychange", onVis);
    kick();
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [reducedMotion, dragSpeedRef]);

  useLayoutEffect(() => {
    if (reducedMotion || visual.body !== "happy_jump" || !bodyImgRef.current) return;
    const pose = celebrateAt(performance.now() - motionClock.current.t0);
    bodyImgRef.current.src = petAssetUrl(manifest.bodies[pose.body].src);
  });

  const emote = visual.emote ? emoteBox(met, visual.emoteAnchor, scale) : null;
  const peeking = visual.body === "peek_over";
  const emoteX = emote
    ? (visual.upsideDown || visual.mirror ? met.w - emote.cx : emote.cx)
    : 0;
  const emoteY = emote ? (visual.upsideDown ? met.h - emote.cy : emote.cy) : 0;
  const artTurn = visual.upsideDown ? "rotate(180deg)" : visual.mirror ? "scaleX(-1)" : undefined;

  const staticBody =
    visual.body !== "walk" &&
    visual.body !== "feed" &&
    visual.body !== "play"
      ? (visual.body as Exclude<PetVisual["body"], "walk" | "feed" | "play">)
      : null;

  return (
    <div className={styles.sprite} style={{ width: met.w * scale, height: met.h * scale }}>
      <div
        className={styles.stage}
        style={{ width: met.w, height: met.h, transform: `scale(${scale})` }}
      >
        <div
          className={peeking ? styles.clip : styles.motion}
          style={{ width: met.w, height: met.h }}
        >
        <div ref={motionRef} className={styles.motion} style={{ width: met.w, height: met.h }}>
        <div
          style={{
            width: met.w,
            height: met.h,
            transform: artTurn,
            transformOrigin: "center center",
          }}
        >
        {seq ? (
          <div
            ref={seqRef}
            className={styles.layer}
            style={{
              width: met.w,
              height: met.h,
              backgroundImage: `url(${petAssetUrl(seq.src)})`,
            }}
          />
        ) : (
          <img
            ref={bodyImgRef}
            className={styles.layer}
            src={petAssetUrl(manifest.bodies[staticBody!].src)}
            width={met.w}
            height={met.h}
            alt=""
            draggable={false}
          />
        )}
        {faceAtlas && (
          <div
            ref={faceRef}
            className={styles.layer}
            style={{
              left: faceAtlas.rect[0],
              top: faceAtlas.rect[1],
              width: faceAtlas.rect[2],
              height: faceAtlas.rect[3],
              backgroundImage: `url(${petAssetUrl(faceAtlas.src)})`,
              visibility: "hidden",
            }}
          />
        )}
        </div>
        {visual.emote && emote && (
          <PetEmote
            key={`${visual.emote}-${emoteKey}`}
            name={visual.emote}
            className={styles.emote}
            style={{
              left: emoteX - emote.size / 2,
              top: emoteY - emote.size / 2,
              width: emote.size,
              height: emote.size,
            }}
          />
        )}
        </div>
        </div>
      </div>
    </div>
  );
}
