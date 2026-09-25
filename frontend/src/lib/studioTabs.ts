import type { StudioTab } from "./workspacePersist";

/**
 * Word 壳六个直达入口（桌面开始菜单仍用）：`[id, 序号, 完整名, 窄屏短名]`。
 * 顶栏已改为文件/开始/审阅/视图；此处供桌面启动器「打开稿纸并打开对应面板」。
 */
export const STUDIO_TABS: ReadonlyArray<readonly [StudioTab, string, string, string]> = [
  ["write", "01", "写作", "写作"],
  ["world", "02", "设定", "设定"],
  ["voice", "03", "角色工坊", "工坊"],
  ["map", "04", "地图", "地图"],
  ["system", "05", "剧情状态", "状态"],
  ["project", "06", "项目", "项目"],
];
