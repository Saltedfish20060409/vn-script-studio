import type { StudioTab } from "./workspacePersist";

/**
 * 三栏工作台的六个篇章：`[id, 序号, 完整名, 窄屏短名]`。
 *
 * 单独放这里（而不是放在 StudioTabs.tsx 里）的原因有两个：
 * 1. 桌面视图的开始菜单要拿它做"跳到这个剧本的某一页"，组件文件只该导出组件；
 * 2. 顺序同时决定标签栏的展示顺序与切换动画方向（见 StudioApp 的 tabIndex）。
 */
export const STUDIO_TABS: ReadonlyArray<readonly [StudioTab, string, string, string]> = [
  ["write", "01", "写作", "写作"],
  ["world", "02", "设定", "设定"],
  ["voice", "03", "角色工坊", "工坊"],
  ["map", "04", "地图", "地图"],
  ["system", "05", "剧情状态", "状态"],
  ["project", "06", "项目", "项目"],
];
