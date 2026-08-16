import { MAP_LINE_STYLE_LABELS } from "../types/vn";
import type { MapLineStyle } from "../types/vn";
import type { Tool } from "./mapStudioTypes";
import styles from "./MapStudio.module.css";

type Props = {
  tool: Tool;
  linkFrom: string | null;
  lineStyle: MapLineStyle;
  brushMode: "pen" | "eraser";
  brushColor: string;
  brushWidth: number;
  onSelectTool: (tool: Tool) => void;
  onSetLineStyle: (style: MapLineStyle) => void;
  onSetBrushMode: (mode: "pen" | "eraser") => void;
  onSetBrushColor: (color: string) => void;
  onSetBrushWidth: (width: number) => void;
  onUndoStroke: () => void;
  onClearStrokes: () => void;
  onFit: () => void;
  onExtractFromScript?: () => void;
  onExtractRulesOnly?: () => void;
};

/** Center toolbar: tool switch, line style, brush controls and hints. Pure presentational. */
export function MapToolbar({
  tool,
  linkFrom,
  lineStyle,
  brushMode,
  brushColor,
  brushWidth,
  onSelectTool,
  onSetLineStyle,
  onSetBrushMode,
  onSetBrushColor,
  onSetBrushWidth,
  onUndoStroke,
  onClearStrokes,
  onFit,
  onExtractFromScript,
  onExtractRulesOnly,
}: Props) {
  return (
    <>
      <div className={styles.toolbar}>
        <span className={styles.label} style={{ margin: 0, alignSelf: "center" }}>
          TOOL
        </span>
        {(
          [
            ["pan", "漫游"],
            ["select", "选择"],
            ["place", "放置"],
            ["link", "通路"],
            ["draw", "画笔"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={tool === id ? styles.toolActive : styles.toolBtn}
            onClick={() => onSelectTool(id)}
          >
            {label}
          </button>
        ))}
        {tool === "link" && (
          <select
            value={lineStyle}
            onChange={(e) => onSetLineStyle(e.target.value as MapLineStyle)}
            title="连线样式"
          >
            {(Object.keys(MAP_LINE_STYLE_LABELS) as MapLineStyle[]).map((ls) => (
              <option key={ls} value={ls}>
                {MAP_LINE_STYLE_LABELS[ls]}
              </option>
            ))}
          </select>
        )}
        {tool === "draw" && (
          <>
            <button
              type="button"
              className={brushMode === "pen" ? styles.toolActive : styles.toolBtn}
              onClick={() => onSetBrushMode("pen")}
            >
              画笔
            </button>
            <button
              type="button"
              className={brushMode === "eraser" ? styles.toolActive : styles.toolBtn}
              onClick={() => onSetBrushMode("eraser")}
            >
              橡皮
            </button>
            <input
              type="color"
              value={brushColor}
              onChange={(e) => onSetBrushColor(e.target.value)}
              title="笔色"
              disabled={brushMode === "eraser"}
            />
            <input
              type="range"
              min={2}
              max={24}
              value={brushWidth}
              onChange={(e) => onSetBrushWidth(Number(e.target.value))}
              title={brushMode === "eraser" ? "橡皮半径" : "笔粗"}
            />
            <button
              type="button"
              className={styles.toolBtn}
              onClick={onUndoStroke}
              title="Ctrl+Z"
            >
              撤回
            </button>
            <button type="button" className={styles.toolBtn} onClick={onClearStrokes}>
              清空笔迹
            </button>
          </>
        )}
        <span className={styles.hint}>
          {tool === "pan" && "拖空白平移 · 滚轮缩放"}
          {tool === "select" && "框选 / Shift+点切换 · 拖动可多移"}
          {tool === "place" && "单击放置 · 拖空白则平移"}
          {tool === "link" && (linkFrom ? "再点终点" : "先点起点 · 空白拖动画布")}
          {tool === "draw" &&
            (brushMode === "eraser"
              ? "拖过笔迹擦除 · Ctrl+Z 撤回 · E 橡皮"
              : "拖动画线 · Ctrl+Z 撤回 · E 切橡皮")}
        </span>
        <button type="button" className={styles.toolBtn} onClick={() => onFit()}>
          复位
        </button>
        {onExtractFromScript && (
          <button
            type="button"
            className={styles.toolBtn}
            onClick={onExtractFromScript}
            title="scene + 对白/设定词典 + 模型语义提取"
          >
            智能提取地图
          </button>
        )}
        {onExtractRulesOnly && (
          <button
            type="button"
            className={styles.toolBtn}
            onClick={onExtractRulesOnly}
            title="仅从 scene bg 标签提取"
          >
            仅 scene
          </button>
        )}
      </div>
      <p className={styles.shortcuts}>
        Del / Backspace 删除 · Ctrl+Z 撤回笔迹 · B画笔 E橡皮 · V选择 H漫游
      </p>
    </>
  );
}
