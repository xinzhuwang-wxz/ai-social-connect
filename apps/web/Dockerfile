# 前端。跑 dev server 而不是 production build——
# 这套 compose 的用途是"一条命令把产品跑起来给人看"，不是部署。
# production build 在容器里要多花几分钟，而它换不来任何演示价值。
FROM node:22-bookworm-slim

WORKDIR /app
RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile

COPY apps/web/ apps/web/
COPY artifacts/ artifacts/

WORKDIR /app/apps/web
EXPOSE 3000
CMD ["pnpm", "dev", "--hostname", "0.0.0.0"]
