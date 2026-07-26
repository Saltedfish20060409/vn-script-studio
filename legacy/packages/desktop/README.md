# Desktop shell (planned)

后续用 **Tauri** 包装 `packages/web`：

- 优势：安装包、本地文件系统权限、不依赖浏览器书签
- 现状：逻辑已在 Web + core，桌面端只需薄壳，避免三套业务代码

建议时机：Web MVP 用顺手后，再执行：

```bash
npm create tauri-app
```

并把 `beforeDevCommand` 指到 `npm run dev -w @vnss/web`。
