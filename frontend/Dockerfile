# 本地 Docker 试用：构建前端产物，用 nginx 托管并反代 /api 到后端。
#
# 构建阶段必须是 node:22，与 `.nvmrc` 和 `package.json` 的 `engines: node >=22` 对齐。
# 这不是"顺手升个版"：node:20 那版 npm（10.8.2）在 alpine/musl 下会漏装 rollup 的平台
# 原生包——`npm ci` **退出码仍是 0**，装出来的 node_modules 里只有 `@rollup/rollup` 本体，
# 于是 `npm run build` 倒在 `Cannot find module @rollup/rollup-linux-x64-musl`
# （npm/cli#4828；实测同一份锁文件在 node:22 的 npm 10.9.9 下装得出来）。
# 换句话说：镜像原本用的 Node 低于项目自己声明的下限，构建失败是必然的。
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
