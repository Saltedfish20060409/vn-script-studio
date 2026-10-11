/**
 * Android 客户端（伴侣 App）安装包地址——登录页 / 页脚 / 使用指南 / 设置四处共用这一份。
 *
 * 为什么要抽出来：这几处过去各写了一份 GitHub Releases 链接，改链接就得改四处，
 * 漏一处的表现是"有的入口还需要网络工具才能下"，用户根本分不清哪个才是对的。
 *
 * 主链接用**自建站点的国内直链**：GitHub 在国内经常连不上或很慢，用户拿不到包
 * 等于没发布。GitHub Releases 仍是权威源（版本历史、可校验），留作备用。
 *
 * 为什么是相对路径：同一个包跟着站点走，本地 / 预览 / 自建域名都能点，
 * 不必把 `vnscriptstudio.cn` 写进代码（README 也是"不绑定特定站点"的口径）。
 * 自建部署时把 apk 放到站点根目录的 `dl/` 下、用同名文件覆盖即可；
 * `latest` 那个名字**换版本时保持不变**，所以已经发出去的链接不会失效。
 */
export const APP_APK_URL = "/dl/vn-script-studio-android-latest.apk";

/** 备用：直链打不开 / 下载中断时用；同时是版本历史与校验来源。 */
export const APP_APK_MIRROR_URL =
  "https://github.com/Saltedfish20060409/vn-script-studio/releases";
