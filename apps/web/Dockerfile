# 前端。**production build，不是 dev server。**
#
# 原来这里跑 `pnpm dev`，理由写的是"这套 compose 是给人看的，不是部署，
# production build 要多花几分钟而换不来演示价值"。那句话有一半是错的：
# dev server 会在页面左下角常驻一个 Next 的开发标记，热更新的字体闪烁、
# 未压缩的包、慢一档的首屏——**它换来的正是"这是个 demo"的第一印象**，
# 而这套 compose 的用途恰恰是把产品拿给人看。
#
# 多阶段构建：装依赖、构建、只把产物搬进运行层。
FROM node:22-bookworm-slim AS build

WORKDIR /app
RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile

COPY apps/web/ apps/web/
COPY artifacts/ artifacts/

WORKDIR /app/apps/web
# 转发目标在**运行时**才知道（compose 网络里的服务名），所以这里不烘进去。
RUN pnpm build

FROM node:22-bookworm-slim AS run
WORKDIR /app
RUN corepack enable
ENV NODE_ENV=production

COPY --from=build /app/node_modules /app/node_modules
COPY --from=build /app/package.json /app/pnpm-workspace.yaml /app/
COPY --from=build /app/apps/web /app/apps/web

WORKDIR /app/apps/web
EXPOSE 3000
CMD ["pnpm", "start", "--hostname", "0.0.0.0"]
