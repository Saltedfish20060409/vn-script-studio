/**
 * 背景图自动压缩。
 *
 * 为什么必须有这一步（线上事故，2026-09-27）：
 * 背景图是以 **base64 data URL** 存进设置 JSON 的，而设置保存是 `PUT /api/v1/settings`。
 * 一张 11.8 MB 的手机照 → 请求体 15.7 MB → 被 nginx `client_max_body_size 3m` 直接
 * 413（连后端都没到，作者看到的是 nginx 那张原始 HTML）。更糟的是
 * `settings.ts::toServerSettingsPatch` **每次保存设置都会把整张 bg_image 再发一遍**，
 * 于是本地只要挂着那张巨图，之后**每次**改设置都变成一次必然失败的 15.7 MB 请求
 * （日志里就是 200/413/413/200/413 交替）。同一张图写进 localStorage 还会撞 ~5 MB
 * 配额，而那个 catch 是空的，外观缓存会静默失效。
 *
 * 所以不靠"提示用户换张小图"，而是**自动把它压到能存下的体积**：壁纸在屏幕上
 * 根本用不到原图分辨率，长边 3200 已经够 4K 全屏，压完通常只有几百 KB。
 *
 * 本文件分两层，因为 `vitest` 的 environment 是 `node`（见 vitest.config.ts，
 * 只测 `src/**` 下的纯函数）：
 * - **纯函数**（可测）：预算判断、阶梯、尺寸换算、提示文案；
 * - **`compressImageFile`（挡在 canvas 后面）**：解码 / 缩放 / 编码，靠浏览器 API。
 */
/** 压缩结果。`overBudget` 为真时表示"压到底还是塞不下"，调用方要如实提示而不是当成成功。 */
export type BgCompressResult = {
  dataUrl: string;
  width: number;
  height: number;
  /** data URL 的字节数（≈ 它会往请求体里加多少） */
  bytes: number;
  originalBytes: number;
  /** 是否真的重新编码过 */
  compressed: boolean;
  overBudget: boolean;
};

/**
 * 一条 data URL 允许占多少字符。
 *
 * nginx 是 3m = 3,145,728 字节；这里留出余量给 JSON 里其它字段与转义，
 * 取 2.5 MB。之所以用"字符数"当尺子：canvas 产出的 data URL 全是 ASCII base64，
 * 字符数就等于字节数（见 `dataUrlBytes` 的说明）。
 */
export const BUDGET_BYTES = 2_500_000;

/** 长边上限。4K 全屏（3840）略欠，但壁纸会被缩放/平移，3200 是体积与观感的折中。 */
export const MAX_EDGE = 3200;

/**
 * 压缩阶梯：**先降质量（保住分辨率），再降尺寸**。
 *
 * 顺序是有意的：壁纸最怕的是糊（降尺寸），其次才是压缩伪影（降质量）。
 * 每一档都试到"塞进预算"为止，所以不需要用户自己猜该压到多少。
 *
 * 质量与长边两项都**严格单调不增**：这样"下一档一定更小"，不会出现
 * "试了一档更差的却更大"这种白跑一趟的情况（测试钉住了这条）。
 */
export const ATTEMPTS: ReadonlyArray<{ maxEdge: number; quality: number }> = [
  { maxEdge: MAX_EDGE, quality: 0.85 },
  { maxEdge: MAX_EDGE, quality: 0.72 },
  { maxEdge: 2560, quality: 0.7 },
  { maxEdge: 2048, quality: 0.68 },
  { maxEdge: 1600, quality: 0.64 },
  { maxEdge: 1280, quality: 0.6 },
];

/** base64 之后大约膨胀 4/3，再加 `data:image/...;base64,` 前缀的几十字节。 */
export function estimateDataUrlBytes(fileBytes: number): number {
  const n = Number.isFinite(fileBytes) && fileBytes > 0 ? fileBytes : 0;
  return Math.ceil((n * 4) / 3) + 48;
}

/**
 * data URL 的字节数。
 *
 * canvas 产出的是纯 ASCII base64，所以字符数 == 字节数；这里仍然按 UTF-8 数一遍，
 * 万一上游给进来带非 ASCII 的东西也不会低估。
 */
export function dataUrlBytes(dataUrl: string): number {
  let bytes = 0;
  for (let i = 0; i < dataUrl.length; i += 1) {
    const code = dataUrl.charCodeAt(i);
    if (code < 0x80) bytes += 1;
    else if (code < 0x800) bytes += 2;
    else if (code >= 0xd800 && code <= 0xdbff) {
      bytes += 4;
      i += 1;
    } else bytes += 3;
  }
  return bytes;
}

/**
 * 这张图需不需要压。
 *
 * 只在"预计塞不下"时才压：小图（含 SVG / 动图）原样保留，不重新编码，
 * 免得为了一次没必要的转码把矢量图变成位图、把动图压成静帧。
 */
export function shouldCompress(
  fileBytes: number,
  budget: number = BUDGET_BYTES
): boolean {
  return estimateDataUrlBytes(fileBytes) > budget;
}

/** 按长边上限等比缩放；**只缩不放**（放大只会更糊又更大）。 */
export function scaledSize(
  width: number,
  height: number,
  maxEdge: number
): { width: number; height: number } {
  const w = Math.max(0, Math.round(width));
  const h = Math.max(0, Math.round(height));
  const longEdge = Math.max(w, h);
  if (longEdge === 0 || longEdge <= maxEdge) return { width: w, height: h };
  const k = maxEdge / longEdge;
  return { width: Math.max(1, Math.round(w * k)), height: Math.max(1, Math.round(h * k)) };
}

/** 人看的体积。 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** 压过之后告诉作者发生了什么——静默压缩会让人以为图被"弄糊了"。 */
export function autoCompressedNote(originalBytes: number, outBytes: number): string {
  return (
    `背景图过大，已自动压缩：${formatBytes(originalBytes)} → ${formatBytes(outBytes)}。` +
    "壁纸在屏幕上用不到原图分辨率，观感基本不变。"
  );
}

/** 压到最后一档还是塞不下：如实说，不假装成功。 */
export function stillTooLargeNote(
  outBytes: number,
  budget: number = BUDGET_BYTES
): string {
  return (
    `这张图压缩后仍有 ${formatBytes(outBytes)}，超过可保存上限 ${formatBytes(budget)}。` +
    "请换一张，或先自行裁掉不需要的部分。"
  );
}

/** 不是浏览器能解码的图片（损坏 / 不支持的格式 / 后端拒收）。 */
export function unreadableImageNote(): string {
  return "这张图无法处理：可能已损坏，或是浏览器不支持解码的格式。请换一张试试。";
}

/** 设置里存下来的背景图体积（给"当前背景"那一行显示用）。 */
export function bgImageNote(dataUrl: string): string {
  if (!dataUrl) return "";
  return `当前背景约 ${formatBytes(dataUrlBytes(dataUrl))}。`;
}

/**
 * 压缩一张图片文件；返回可直接存进设置的 data URL。
 *
 * - 不需要压的（见 `shouldCompress`）**原样返回**，不做任何转码；
 * - 需要压的按 `ATTEMPTS` 逐档试，第一档塞进预算就停；
 * - 全部档位都塞不下时返回最后一档并标 `overBudget: true`，由调用方如实提示。
 */
export async function compressImageFile(
  file: File,
  options: { budget?: number; maxEdge?: number } = {}
): Promise<BgCompressResult> {
  const budget = options.budget ?? BUDGET_BYTES;
  const originalBytes = file.size;

  const passthrough = (dataUrl: string, width: number, height: number): BgCompressResult => ({
    dataUrl,
    width,
    height,
    bytes: dataUrlBytes(dataUrl),
    originalBytes,
    compressed: false,
    overBudget: false,
  });

  if (!shouldCompress(originalBytes, budget)) {
    const raw = await readAsDataUrl(file);
    const size = await measureDataUrl(raw);
    return passthrough(raw, size.width, size.height);
  }

  const decoded = await decodeImage(file);
  try {
    const maxEdge = options.maxEdge ?? MAX_EDGE;
    let last: BgCompressResult | null = null;

    for (const attempt of ATTEMPTS) {
      const target = scaledSize(
        decoded.width,
        decoded.height,
        Math.min(attempt.maxEdge, maxEdge)
      );
      const canvas = drawToCanvas(decoded.source, target.width, target.height);
      const dataUrl = encodeCanvas(canvas, attempt.quality);
      const bytes = dataUrlBytes(dataUrl);
      const row: BgCompressResult = {
        dataUrl,
        width: target.width,
        height: target.height,
        bytes,
        originalBytes,
        compressed: true,
        overBudget: bytes > budget,
      };
      if (bytes <= budget) return row;
      last = row;
    }

    if (last) return last;
    throw new Error("没有可用的压缩档位");
  } finally {
    decoded.release();
  }
}

// ---------------------------------------------------------------- canvas 那一层

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error ?? new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

/** 量一下已有 data URL 的像素尺寸（不重新编码，只为记下宽高）。 */
function measureDataUrl(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    // 量不出来不该让整个导入失败：宽高只用于展示，给 0 即可
    img.onerror = () => resolve({ width: 0, height: 0 });
    img.src = dataUrl;
  });
}

type Decoded = {
  source: CanvasImageSource;
  width: number;
  height: number;
  release: () => void;
};

/**
 * 解码成可画进 canvas 的位图。
 *
 * 优先 `createImageBitmap(..., { imageOrientation: "from-image" })`：手机竖拍的照片
 * 方向写在 EXIF 里，不认它就会横过来。老浏览器退回 `<img>` —— 那条路径浏览器本身
 * 就会按 EXIF 摆正，所以两条路拿到的都是"正着"的像素。
 */
async function decodeImage(file: File): Promise<Decoded> {
  if (typeof createImageBitmap === "function") {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      return {
        source: bitmap,
        width: bitmap.width,
        height: bitmap.height,
        release: () => bitmap.close?.(),
      };
    } catch {
      /* 落到 <img> 那条路 */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("图片解码失败"));
      el.src = url;
    });
    return {
      source: img,
      width: img.naturalWidth,
      height: img.naturalHeight,
      release: () => URL.revokeObjectURL(url),
    };
  } catch (err) {
    URL.revokeObjectURL(url);
    throw err;
  }
}

function drawToCanvas(
  source: CanvasImageSource,
  width: number,
  height: number
): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, width);
  canvas.height = Math.max(1, height);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("浏览器不支持 canvas 2D，无法压缩图片");
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas;
}

/**
 * 编码成 data URL。
 *
 * 先试 WebP：同体积画质更好，而且**保留透明通道**（背景图可能是带透明的 PNG）。
 * 不支持 WebP 编码的浏览器会静默返回 PNG，所以这里靠前缀判断再回退到 JPEG。
 */
function encodeCanvas(canvas: HTMLCanvasElement, quality: number): string {
  const webp = canvas.toDataURL("image/webp", quality);
  if (webp.startsWith("data:image/webp")) return webp;
  return canvas.toDataURL("image/jpeg", quality);
}
